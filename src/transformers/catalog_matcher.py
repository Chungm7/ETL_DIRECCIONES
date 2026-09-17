"""Mapeador y homologador contra los catálogos maestros de Chiclayo (tipos_via y tipos_zona).

Basado exactamente en los catálogos oficiales:
- 12 Tipos de Vía (1: AVENIDA, 2: CALLE, 3: JIRON, etc.)
- 28 Tipos de Zona (1: ASENTAMIENTO HUMANO, 2: AGRUPACION, ..., 6: URBANIZACION, etc.)
"""

from difflib import SequenceMatcher
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
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
    # -------------------------------------------------------------------------
    # Homologación con Catálogos de Vías y Zonas Físicas de Chiclayo
    # -------------------------------------------------------------------------

    ZONA_STOPWORDS: Set[str] = {
        "URB", "URBANIZACION", "PJ", "PUEBLO", "JOVEN", "AH", "ASENTAMIENTO",
        "HUMANO", "CONJ", "HAB", "RES", "COOP", "ASOC", "VIV", "DE", "DEL",
        "LA", "LAS", "LOS", "EL"
    }

    VIA_STOPWORDS: Set[str] = {
        "AV", "AVENIDA", "CA", "CALLE", "JR", "JIRON", "PJE", "PASAJE",
        "PRLG", "PROLONGACION", "CTRA", "CARRETERA", "AL", "ALAMEDA",
        "PSO", "PASEO", "DE", "DEL", "LA", "LAS", "LOS", "EL"
    }

    @staticmethod
    def normalize_variants_text(text: str) -> str:
        """Normaliza variantes comunes como etapas en números romanos/arábigos y subprogramas."""
        if not text:
            return ""
        t = TextCleaner.sanitize(text)
        t = TextCleaner.remove_accents(t)
        # Etapas
        t = re.sub(r"\b(?:1RA|1ERA|1\s*RA|I|1)\s+ETAPA\b|\bETAPA\s+(?:1RA|1ERA|I|1)\b", "PRIMERA ETAPA", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:2DA|2DO|2\s*DA|II|2)\s+ETAPA\b|\bETAPA\s+(?:2DA|2DO|II|2)\b", "SEGUNDA ETAPA", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:3RA|3ERA|3\s*RA|III|3)\s+ETAPA\b|\bETAPA\s+(?:3RA|3ERA|III|3)\b", "TERCERA ETAPA", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:4TA|4TO|4\s*TA|IV|4)\s+ETAPA\b|\bETAPA\s+(?:4TA|4TO|IV|4)\b", "CUARTA ETAPA", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:5TA|5TO|5\s*TA|V|5)\s+ETAPA\b|\bETAPA\s+(?:5TA|5TO|V|5)\b", "QUINTA ETAPA", t, flags=re.IGNORECASE)
        # Subprogramas y sectores
        t = re.sub(r"\bSUBPROGRAMA\s+(?:1|I)\b", "SUBPROGRAMA I", t, flags=re.IGNORECASE)
        t = re.sub(r"\bSUBPROGRAMA\s+(?:2|II)\b", "SUBPROGRAMA II", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:1ER|1RO|1|I)\s+SECTOR\b|\bSECTOR\s+(?:1|I)\b", "SECTOR I", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(?:2DO|2|II)\s+SECTOR\b|\bSECTOR\s+(?:2|II)\b", "SECTOR II", t, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", t).strip()

    @classmethod
    def _extract_sig_tokens(cls, text: str, is_via: bool = False) -> Set[str]:
        stopwords = cls.VIA_STOPWORDS if is_via else cls.ZONA_STOPWORDS
        words = re.findall(r"[A-Z0-9]+", text.upper())
        return {w for w in words if len(w) > 1 and w not in stopwords}

    @classmethod
    def find_zona_candidates(
        cls,
        text: str,
        tipo_zona_hint: Optional[int] = None,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Encuentra los top_k candidatos oficiales de zonas de Chiclayo ordenados por similitud."""
        if not text:
            return []
        q_norm = cls.normalize_variants_text(text)
        q_tokens = cls._extract_sig_tokens(q_norm, is_via=False)
        if not q_tokens:
            return []

        zonas = CatalogManager.get_zonas_chiclayo_catalog()
        scored: List[Tuple[Dict[str, Any], float]] = []

        for item in zonas:
            nom = item.get("nom_zona", "")
            n_norm = cls.normalize_variants_text(nom)
            n_tokens = cls._extract_sig_tokens(n_norm, is_via=False)
            if not n_tokens:
                continue

            coverage = len(q_tokens & n_tokens) / len(q_tokens)
            seq_ratio = SequenceMatcher(None, q_norm, n_norm).ratio()

            if coverage >= 1.0:
                # Penalización leve si el candidato tiene palabras extra y la consulta no mencionó etapa
                extra_words = len(n_tokens) - len(q_tokens)
                penalty = 0.05 * extra_words if (extra_words > 0 and "ETAPA" not in q_norm) else 0.0
                score = 0.82 + (seq_ratio * 0.18) - penalty
            elif coverage >= 0.5:
                score = (0.5 * coverage) + (0.5 * seq_ratio)
            else:
                score = seq_ratio * 0.55

            if tipo_zona_hint and item.get("id_tipo_zona") == tipo_zona_hint and score >= 0.6:
                score += 0.03

            if score >= min_score:
                scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @classmethod
    def find_via_candidates(
        cls,
        text: str,
        tipo_via_hint: Optional[int] = None,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Encuentra los top_k candidatos oficiales de vías de Chiclayo ordenados por similitud."""
        if not text:
            return []
        q_norm = cls.normalize_variants_text(text)
        q_tokens = cls._extract_sig_tokens(q_norm, is_via=True)
        if not q_tokens:
            return []

        vias = CatalogManager.get_vias_chiclayo_catalog()
        scored: List[Tuple[Dict[str, Any], float]] = []

        for item in vias:
            nom = item.get("nom_via", "")
            n_norm = cls.normalize_variants_text(nom)
            n_tokens = cls._extract_sig_tokens(n_norm, is_via=True)
            if not n_tokens:
                continue

            coverage = len(q_tokens & n_tokens) / len(q_tokens)
            seq_ratio = SequenceMatcher(None, q_norm, n_norm).ratio()

            if coverage >= 1.0:
                score = 0.82 + (seq_ratio * 0.18)
            elif coverage >= 0.5:
                score = (0.5 * coverage) + (0.5 * seq_ratio)
            else:
                score = seq_ratio * 0.55

            if tipo_via_hint and item.get("id_tipo_via") == tipo_via_hint and score >= 0.6:
                score += 0.03

            if score >= min_score:
                scored.append((item, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @classmethod
    def match_physical_via(
        cls,
        text: Optional[str],
        tipo_via_hint: Optional[int] = None,
        raw_text: Optional[str] = None,
        ollama_service: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Homologa el nombre de una vía contra el catálogo oficial de vías físicas de Chiclayo,
        apoyándose en coincidencia exacta, sinónimos y desambiguación con IA.
        """
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        if not clean:
            return None
        no_acc = TextCleaner.remove_accents(clean)

        lookup = CatalogManager.get_physical_vias_lookup()
        # 1. Búsqueda directa por nombre o sinónimo exacto (0ms)
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

        # 3. Normalización léxica de variantes
        norm_text = cls.normalize_variants_text(clean_noprefix)
        if norm_text in lookup:
            return lookup[norm_text]

        # 4. Búsqueda de candidatos difusos
        candidates = cls.find_via_candidates(clean_noprefix, tipo_via_hint, top_k=8, min_score=0.50)
        if not candidates:
            return None

        top_candidate, top_score = candidates[0]

        # Si hay certeza muy alta de coincidencia (> 0.93)
        if top_score >= 0.93:
            if len(candidates) == 1 or (top_score - candidates[1][1]) >= 0.08 or not ollama_service:
                return top_candidate

        # 5. Desambiguación semántica asistida por IA (Ollama)
        if ollama_service and hasattr(ollama_service, "disambiguate_candidate"):
            try:
                cands_dict_list = [c for c, _ in candidates]
                disambig = ollama_service.disambiguate_candidate(
                    raw_text=raw_text or clean,
                    entity_type="VÍA PÚBLICA / CALLE",
                    search_term=clean,
                    candidates=cands_dict_list,
                )
                if disambig and disambig.id_seleccionado is not None:
                    for cand, _ in candidates:
                        if cand["id"] == disambig.id_seleccionado:
                            logger.info(
                                "IA desambiguó vía '%s' -> ID %s (%s): %s",
                                clean, cand["id"], cand["nom_via"], disambig.motivo
                            )
                            return cand
            except Exception as ex_ai:
                logger.debug("Error en desambiguación con IA de vía: %s", ex_ai)

        # 6. Fallback algorítmico si el top candidate es suficientemente confiable (> 0.88)
        if top_score >= 0.88:
            return top_candidate

        return None

    @classmethod
    def match_physical_zona(
        cls,
        text: Optional[str],
        tipo_zona_hint: Optional[int] = None,
        raw_text: Optional[str] = None,
        ollama_service: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """Homologa el nombre de una zona contra el catálogo oficial de habilitaciones urbanas de Chiclayo,
        apoyándose en coincidencia exacta, normalización de etapas y desambiguación con IA.
        """
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        if not clean:
            return None
        no_acc = TextCleaner.remove_accents(clean)

        lookup = CatalogManager.get_physical_zonas_lookup()
        # 1. Búsqueda directa por nombre o sinónimo exacto (0ms)
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

        # 3. Normalización léxica de variantes de etapas
        norm_text = cls.normalize_variants_text(clean_noprefix)
        if norm_text in lookup:
            return lookup[norm_text]

        # 4. Búsqueda de candidatos difusos
        candidates = cls.find_zona_candidates(clean_noprefix, tipo_zona_hint, top_k=8, min_score=0.50)
        if not candidates:
            return None

        top_candidate, top_score = candidates[0]

        # Si hay certeza muy alta (> 0.93)
        if top_score >= 0.93:
            if len(candidates) == 1 or (top_score - candidates[1][1]) >= 0.08 or not ollama_service:
                return top_candidate

        # 5. Desambiguación semántica asistida por IA (Ollama)
        if ollama_service and hasattr(ollama_service, "disambiguate_candidate"):
            try:
                cands_dict_list = [c for c, _ in candidates]
                disambig = ollama_service.disambiguate_candidate(
                    raw_text=raw_text or clean,
                    entity_type="ZONA / HABILITACIÓN URBANA",
                    search_term=clean,
                    candidates=cands_dict_list,
                )
                if disambig and disambig.id_seleccionado is not None:
                    for cand, _ in candidates:
                        if cand["id"] == disambig.id_seleccionado:
                            logger.info(
                                "IA desambiguó zona '%s' -> ID %s (%s): %s",
                                clean, cand["id"], cand["nom_zona"], disambig.motivo
                            )
                            return cand
            except Exception as ex_ai:
                logger.debug("Error en desambiguación con IA de zona: %s", ex_ai)

        # 6. Fallback algorítmico si el top candidate es suficientemente confiable (> 0.88)
        if top_score >= 0.88:
            return top_candidate

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
