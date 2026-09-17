"""Mapeador y homologador contra los catálogos maestros de Chiclayo (tipos_via y tipos_zona).

Basado exactamente en los catálogos oficiales:
- 12 Tipos de Vía (1: AVENIDA, 2: CALLE, 3: JIRON, etc.)
- 28 Tipos de Zona (1: ASENTAMIENTO HUMANO, 2: AGRUPACION, ..., 6: URBANIZACION, etc.)
"""

import logging
import re
from typing import Any, Dict, Optional
from src.transformers.text_cleaner import TextCleaner

from src.catalogs.catalog_manager import CatalogManager

logger = logging.getLogger("etl_mpch.catalog_matcher")


class CatalogMatcher:
    """Homologa términos extraídos con los identificadores de tipos_via y tipos_zona."""

    CANONICAL_VIA_SYNONYMS: Dict[str, list] = CatalogManager.get_canonical_via_synonyms()
    CANONICAL_ZONA_SYNONYMS: Dict[str, list] = CatalogManager.get_canonical_zona_synonyms()
    VIAS_MAPPING: Dict[str, int] = CatalogManager.get_default_vias_mapping()
    VIAS_NAMES: Dict[int, str] = CatalogManager.get_default_vias_names()
    ZONAS_MAPPING: Dict[str, int] = CatalogManager.get_default_zonas_mapping()
    ZONAS_NAMES: Dict[int, str] = CatalogManager.get_default_zonas_names()

    @classmethod
    def reset_defaults(cls) -> None:
        """Restaura los mapeos oficiales predeterminados desde los catálogos JSON."""
        cls.CANONICAL_VIA_SYNONYMS = CatalogManager.get_canonical_via_synonyms()
        cls.CANONICAL_ZONA_SYNONYMS = CatalogManager.get_canonical_zona_synonyms()
        cls.VIAS_MAPPING = CatalogManager.get_default_vias_mapping()
        cls.VIAS_NAMES = CatalogManager.get_default_vias_names()
        cls.ZONAS_MAPPING = CatalogManager.get_default_zonas_mapping()
        cls.ZONAS_NAMES = CatalogManager.get_default_zonas_names()


    @classmethod
    def sync_with_db(cls, db_service, schema: str) -> None:
        """Sincroniza dinámicamente los mapeos de vías y zonas leyendo las tablas reales del esquema.

        Respeta los IDs asignados en la base de datos (incluso si ya estaban pre-ocupados en ese esquema).
        """
        if not db_service or not db_service._engine:
            return

        from sqlalchemy import text
        t_via = db_service.settings.target_table_tipo_via
        t_zona = db_service.settings.target_table_tipo_zona

        try:
            with db_service.get_session() as session:
                # 1. Leer tipos_via existentes en el esquema
                try:
                    vias_rows = session.execute(text(f"""
                        SELECT id_tipo_via, nombre_tipo_via 
                        FROM "{schema}"."{t_via}"
                        ORDER BY id_tipo_via ASC;
                    """)).fetchall()

                    for vid, vname in vias_rows:
                        if not vname:
                            continue
                        vname_clean = str(vname).strip().upper()
                        cls.VIAS_NAMES[vid] = vname_clean
                        norm_vname = TextCleaner.remove_accents(vname_clean)

                        # Mapear sinónimos canónicos si coincide
                        synonyms = cls.CANONICAL_VIA_SYNONYMS.get(norm_vname, [vname_clean, norm_vname])
                        for syn in synonyms:
                            cls.VIAS_MAPPING[syn] = vid
                            cls.VIAS_MAPPING[TextCleaner.remove_accents(syn)] = vid
                except Exception as ex_vias:
                    logger.debug("No se pudieron leer tipos_via en %s: %s", schema, ex_vias)

                # 2. Leer tipos_zona existentes en el esquema
                try:
                    zonas_rows = session.execute(text(f"""
                        SELECT id_tipo_zona, nombre_tipo_zona 
                        FROM "{schema}"."{t_zona}"
                        ORDER BY id_tipo_zona ASC;
                    """)).fetchall()

                    for zid, zname in zonas_rows:
                        if not zname:
                            continue
                        zname_clean = str(zname).strip().upper()
                        cls.ZONAS_NAMES[zid] = zname_clean
                        norm_zname = TextCleaner.remove_accents(zname_clean)

                        # Mapear sinónimos canónicos si coincide
                        synonyms = cls.CANONICAL_ZONA_SYNONYMS.get(norm_zname, [zname_clean, norm_zname])
                        for syn in synonyms:
                            cls.ZONAS_MAPPING[syn] = zid
                            cls.ZONAS_MAPPING[TextCleaner.remove_accents(syn)] = zid
                except Exception as ex_zonas:
                    logger.debug("No se pudieron leer tipos_zona en %s: %s", schema, ex_zonas)

            logger.info("Mapeo de catálogos sincronizado exitosamente con esquema '%s'", schema)
        except Exception as e:
            logger.warning("Aviso al sincronizar catálogos dinámicos con '%s': %s", schema, e)

    @classmethod
    def match_tipo_via(cls, text: Optional[str]) -> Optional[int]:
        """Obtiene el id_tipo_via según el mapeo activo o None."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        clean_no_accents = TextCleaner.remove_accents(clean)

        return (
            cls.VIAS_MAPPING.get(clean)
            or cls.VIAS_MAPPING.get(clean_no_accents)
            or cls.VIAS_MAPPING.get(clean.rstrip("."))
            or cls.VIAS_MAPPING.get(clean_no_accents.rstrip("."))
        )

    @classmethod
    def match_tipo_zona(cls, text: Optional[str]) -> Optional[int]:
        """Obtiene el id_tipo_zona según el mapeo activo o None."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        clean_no_accents = TextCleaner.remove_accents(clean)

        return (
            cls.ZONAS_MAPPING.get(clean)
            or cls.ZONAS_MAPPING.get(clean_no_accents)
            or cls.ZONAS_MAPPING.get(clean.rstrip("."))
            or cls.ZONAS_MAPPING.get(clean_no_accents.rstrip("."))
        )

    @classmethod
    def get_via_name(cls, id_via: Optional[int]) -> str:
        """Retorna el nombre oficial o sincronizado de la vía dado su ID."""
        if id_via is None:
            return "SIN VIA"
        return cls.VIAS_NAMES.get(id_via, f"VIA #{id_via}")

    @classmethod
    def get_zona_name(cls, id_zona: Optional[int]) -> str:
        """Retorna el nombre oficial o sincronizado del tipo de zona dado su ID."""
        if id_zona is None:
            return "SIN ZONA"
        return cls.ZONAS_NAMES.get(id_zona, f"TIPO ZONA #{id_zona}")

    # -------------------------------------------------------------------------
    # Homologación con Catálogos de Vías y Zonas Físicas de Chiclayo
    # -------------------------------------------------------------------------

    @classmethod
    def match_physical_via(cls, text: Optional[str], tipo_via_hint: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Homologa el nombre de una vía contra el catálogo oficial de vías físicas de Chiclayo."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        if not clean:
            return None
        no_acc = TextCleaner.remove_accents(clean)

        lookup = CatalogManager.get_physical_vias_lookup()
        # 1. Búsqueda directa por nombre o sinónimo exacto
        if clean in lookup:
            return lookup[clean]
        if no_acc in lookup:
            return lookup[no_acc]

        # 2. Quitar prefijos comunes de vías
        clean_noprefix = re.sub(
            r"^(?:AV\.|AVENIDA|CA\.|CALLE|JR\.|JIRON|PJE\.|PASAJE|PRLG\.|PROLONGACION|CTRA\.|CARRETERA|AL\.|ALAMEDA|PSO\.|PASEO)\s+",
            "",
            clean,
            flags=re.IGNORECASE,
        ).strip()
        no_acc_noprefix = TextCleaner.remove_accents(clean_noprefix)
        if clean_noprefix in lookup:
            return lookup[clean_noprefix]
        if no_acc_noprefix in lookup:
            return lookup[no_acc_noprefix]

        return None

    @classmethod
    def match_physical_zona(cls, text: Optional[str], tipo_zona_hint: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Homologa el nombre de una zona contra el catálogo oficial de habilitaciones urbanas de Chiclayo."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        if not clean:
            return None
        no_acc = TextCleaner.remove_accents(clean)

        lookup = CatalogManager.get_physical_zonas_lookup()
        # 1. Búsqueda directa por nombre o sinónimo exacto
        if clean in lookup:
            return lookup[clean]
        if no_acc in lookup:
            return lookup[no_acc]

        # 2. Quitar prefijos comunes de habilitaciones urbanas
        clean_noprefix = re.sub(
            r"^(?:URB\.|URBANIZACION|P\.J\.|PUEBLO JOVEN|A\.H\.|ASENTAMIENTO HUMANO|H\.U\.|CONJ\.HAB\.|CONJ\.RES\.|COOP\.VIV\.|ASOC\.VIV\.)\s+",
            "",
            clean,
            flags=re.IGNORECASE,
        ).strip()
        no_acc_noprefix = TextCleaner.remove_accents(clean_noprefix)
        if clean_noprefix in lookup:
            return lookup[clean_noprefix]
        if no_acc_noprefix in lookup:
            return lookup[no_acc_noprefix]

        return None

    @classmethod
    def get_physical_via_name(cls, id_via: Optional[int]) -> str:
        """Retorna el nombre oficial de la vía física dado su ID."""
        if id_via is None:
            return "SIN VIA MAESTRA"
        for item in CatalogManager.get_vias_chiclayo_catalog():
            if item["id"] == id_via:
                return item["nom_via"]
        return f"VIA #{id_via}"

    @classmethod
    def get_physical_zona_name(cls, id_zona: Optional[int]) -> str:
        """Retorna el nombre oficial de la zona física dado su ID."""
        if id_zona is None:
            return "SIN ZONA MAESTRA"
        for item in CatalogManager.get_zonas_chiclayo_catalog():
            if item["id"] == id_zona:
                return item["nom_zona"]
        return f"ZONA #{id_zona}"
