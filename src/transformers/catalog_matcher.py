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
        target_t_via = getattr(db_service.settings, "target_table_tipo_via", None) or getattr(db_service.settings, "table_tipo_via", None)
        target_t_zona = getattr(db_service.settings, "target_table_tipo_zona", None) or getattr(db_service.settings, "table_tipo_zona", None)
        candidates_via = [c for c in [target_t_via, "tb_tipo_via", "tipos_via"] if c]
        candidates_zona = [c for c in [target_t_zona, "tb_tipo_zona", "tipos_zona"] if c]

        try:
            with db_service.get_session() as session:
                # 1. Leer tipos_via existentes en el esquema
                for t_via in candidates_via:
                    try:
                        res = session.execute(text(f'SELECT * FROM "{schema}"."{t_via}"'))
                        keys = [str(k).lower() for k in res.keys()] if hasattr(res, "keys") and callable(res.keys) else []
                        rows = res.fetchall()
                        if not rows:
                            continue

                        pk_idx = 0
                        name_idx = 1
                        if "tivi_id" in keys and "tivi_nombre" in keys:
                            pk_idx = keys.index("tivi_id")
                            name_idx = keys.index("tivi_nombre")
                        elif "id_tipo_via" in keys and "nombre_tipo_via" in keys:
                            pk_idx = keys.index("id_tipo_via")
                            name_idx = keys.index("nombre_tipo_via")

                        for row in rows:
                            vid = row[pk_idx]
                            vname = row[name_idx]
                            if not vname:
                                continue
                            vname_clean = str(vname).strip().upper()
                            cls.VIAS_NAMES[vid] = vname_clean
                            norm_vname = TextCleaner.remove_accents(vname_clean)

                            synonyms = cls.CANONICAL_VIA_SYNONYMS.get(norm_vname, [vname_clean, norm_vname])
                            for syn in synonyms:
                                cls.VIAS_MAPPING[syn] = vid
                                cls.VIAS_MAPPING[TextCleaner.remove_accents(syn)] = vid
                        break
                    except Exception as ex_vias:
                        logger.debug("Aviso leyendo tipos_via en %s.%s: %s", schema, t_via, ex_vias)

                # 2. Leer tipos_zona existentes en el esquema
                for t_zona in candidates_zona:
                    try:
                        res = session.execute(text(f'SELECT * FROM "{schema}"."{t_zona}"'))
                        keys = [str(k).lower() for k in res.keys()] if hasattr(res, "keys") and callable(res.keys) else []
                        rows = res.fetchall()
                        if not rows:
                            continue

                        pk_idx = 0
                        name_idx = 1
                        if "tizo_id" in keys and "tizo_nombre" in keys:
                            pk_idx = keys.index("tizo_id")
                            name_idx = keys.index("tizo_nombre")
                        elif "id_tipo_zona" in keys and "nombre_tipo_zona" in keys:
                            pk_idx = keys.index("id_tipo_zona")
                            name_idx = keys.index("nombre_tipo_zona")

                        for row in rows:
                            zid = row[pk_idx]
                            zname = row[name_idx]
                            if not zname:
                                continue
                            zname_clean = str(zname).strip().upper()
                            cls.ZONAS_NAMES[zid] = zname_clean
                            norm_zname = TextCleaner.remove_accents(zname_clean)

                            synonyms = cls.CANONICAL_ZONA_SYNONYMS.get(norm_zname, [zname_clean, norm_zname])
                            for syn in synonyms:
                                cls.ZONAS_MAPPING[syn] = zid
                                cls.ZONAS_MAPPING[TextCleaner.remove_accents(syn)] = zid
                        break
                    except Exception as ex_zonas:
                        logger.debug("Aviso leyendo tipos_zona en %s.%s: %s", schema, t_zona, ex_zonas)

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
    # Homologación de Componentes y Módulos V2
    # -------------------------------------------------------------------------
    COMPONENTES_DICT: Dict[str, Tuple[int, str, bool]] = {
        "MANZANA": (1, "MANZANA", True),
        "MZ": (1, "MANZANA", True),
        "MZA": (1, "MANZANA", True),
        "MZA.": (1, "MANZANA", True),
        "MZ.": (1, "MANZANA", True),
        "LOTE": (2, "LOTE", True),
        "LT": (2, "LOTE", True),
        "LT.": (2, "LOTE", True),
        "SUBLOTE": (3, "SUBLOTE", True),
        "SLOTE": (3, "SUBLOTE", True),
        "SLT": (3, "SUBLOTE", True),
        "SLT.": (3, "SUBLOTE", True),
        "SUB-LOTE": (3, "SUBLOTE", True),
        "SUB LOTE": (3, "SUBLOTE", True),
        "PISO": (4, "PISO", True),
        "PISOS": (4, "PISO", True),
        "NIVEL": (4, "PISO", True),
        "PREDIO": (5, "PREDIO", False),
        "FUNDO": (5, "PREDIO", False),
        "VALLE": (6, "VALLE", False),
        "SECTOR": (7, "SECTOR", False),
        "UNIDAD CATASTRAL": (8, "UNIDAD CATASTRAL", False),
        "UC": (8, "UNIDAD CATASTRAL", False),
        "U.C.": (8, "UNIDAD CATASTRAL", False),
        "COORDENADA NORTE": (9, "COORDENADA NORTE", False),
        "NORTE": (9, "COORDENADA NORTE", False),
        "COORDENADA ESTE": (10, "COORDENADA ESTE", False),
        "ESTE": (10, "COORDENADA ESTE", False),
    }

    MODULOS_DICT: Dict[str, Tuple[int, str]] = {
        "INTERIOR": (1, "INTERIOR"),
        "INT": (1, "INTERIOR"),
        "INT.": (1, "INTERIOR"),
        "DEPARTAMENTO": (2, "DEPARTAMENTO"),
        "DPTO": (2, "DEPARTAMENTO"),
        "DPTO.": (2, "DEPARTAMENTO"),
        "DEP": (2, "DEPARTAMENTO"),
        "DEP.": (2, "DEPARTAMENTO"),
        "PUERTA": (3, "PUERTA"),
        "PTA": (3, "PUERTA"),
        "PTA.": (3, "PUERTA"),
        "STAND": (4, "STAND"),
        "STAND.": (4, "STAND"),
        "STD": (4, "STAND"),
        "TIENDA": (5, "TIENDA"),
        "TDA": (5, "TIENDA"),
        "TDA.": (5, "TIENDA"),
        "OFICINA": (6, "OFICINA"),
        "OF": (6, "OFICINA"),
        "OF.": (6, "OFICINA"),
        "BLOCK": (7, "BLOCK"),
        "BLQ": (7, "BLOCK"),
        "TORRE": (7, "BLOCK"),
        "PABELLON": (7, "BLOCK"),
        "PABELLÓN": (7, "BLOCK"),
        "PUESTO": (8, "PUESTO"),
        "PTO": (8, "PUESTO"),
        "LOCAL": (9, "LOCAL"),
        "LC": (9, "LOCAL"),
        "COCHERA": (10, "COCHERA"),
        "ESTACIONAMIENTO": (10, "COCHERA"),
    }

    @classmethod
    def match_componente(cls, text: Optional[str]) -> Optional[Tuple[int, str, bool]]:
        """Homologa el nombre del componente catastral hacia (codi_id, codi_nombre, codi_es_urbano)."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text).upper()
        clean_no_accents = TextCleaner.remove_accents(clean)
        return cls.COMPONENTES_DICT.get(clean) or cls.COMPONENTES_DICT.get(clean_no_accents)

    @classmethod
    def match_tipo_modulo(cls, text: Optional[str]) -> Optional[Tuple[int, str]]:
        """Homologa el tipo de módulo hacia (timo_id, timo_nombre)."""
        if not text:
            return None
        clean = TextCleaner.sanitize(text).upper()
        clean_no_accents = TextCleaner.remove_accents(clean)
        return cls.MODULOS_DICT.get(clean) or cls.MODULOS_DICT.get(clean_no_accents)

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
        # Limpieza de ceros iniciales en números aislados (ej. '09 DE OCTUBRE' -> '9 DE OCTUBRE')
        t = re.sub(r"\b0+(\d+)\b", r"\1", t)
        # Normalización de números escritos en letras para fechas/calles/zonas
        t = re.sub(r"\bNUEVE\b", "9", t, flags=re.IGNORECASE)
        t = re.sub(r"\bOCHO\b", "8", t, flags=re.IGNORECASE)
        t = re.sub(r"\bSIETE\b", "7", t, flags=re.IGNORECASE)
        t = re.sub(r"\bSEIS\b", "6", t, flags=re.IGNORECASE)
        t = re.sub(r"\bTRES\b", "3", t, flags=re.IGNORECASE)
        t = re.sub(r"\bDOS\b", "2", t, flags=re.IGNORECASE)
        t = re.sub(r"\bPRIMERO\b", "1", t, flags=re.IGNORECASE)
        t = re.sub(r"\bVEINTIOCHO\b", "28", t, flags=re.IGNORECASE)
        t = re.sub(r"\bVEINTISIETE\b", "27", t, flags=re.IGNORECASE)
        t = re.sub(r"\bQUINCE\b", "15", t, flags=re.IGNORECASE)
        t = re.sub(r"\bCATORCE\b", "14", t, flags=re.IGNORECASE)
        t = re.sub(r"\bDOCE\b", "12", t, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", t).strip()

    @classmethod
    def _extract_sig_tokens(cls, text: str, is_via: bool = False) -> Set[str]:
        stopwords = cls.VIA_STOPWORDS if is_via else cls.ZONA_STOPWORDS
        words = re.findall(r"[A-Z0-9]+", text.upper())
        return {w for w in words if (len(w) > 1 or w.isdigit()) and w not in stopwords}

    @staticmethod
    def _common_prefix_length(w1: str, w2: str) -> int:
        """Calcula la longitud del prefijo común consecutivo desde el inicio de ambas palabras."""
        length = 0
        for a, b in zip(w1, w2):
            if a == b:
                length += 1
            else:
                break
        return length

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

            # Bloqueo explícito de colisiones fonéticas conocidas
            if ("BRISAS" in q_norm and "FRESAS" in n_norm) or ("FRESAS" in q_norm and "BRISAS" in n_norm):
                continue

            # Si ambos tienen números identificadores y no coinciden (ej. etapa 1 vs 2, o sector 3 vs 4)
            q_digits = {t for t in q_tokens if t.isdigit()}
            n_digits = {t for t in n_tokens if t.isdigit()}
            if q_digits and n_digits and not (q_digits & n_digits):
                continue

            coverage = len(q_tokens & n_tokens) / len(q_tokens)
            seq_ratio = SequenceMatcher(None, q_norm, n_norm).ratio()

            # Boost para variantes ortográficas de una sola palabra (ej. PORCUYA ≈ PORCULLA)
            # Requiere: prefijo común consecutivo real >= 4 chars para evitar falsos positivos
            if coverage == 0 and len(q_tokens) == 1 and len(n_tokens) == 1 and seq_ratio >= 0.75:
                q_word = next(iter(q_tokens))
                n_word = next(iter(n_tokens))
                prefix_len = cls._common_prefix_length(q_word, n_word)
                if prefix_len >= 4 and seq_ratio >= 0.80:
                    score = 0.50 + (seq_ratio * 0.50)
                else:
                    score = seq_ratio * 0.40
            elif coverage >= 1.0:
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
        sector_hint: Optional[str] = None,
        top_k: int = 5,
        min_score: float = 0.55,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Encuentra los top_k candidatos oficiales de vías de Chiclayo ordenados por similitud y sector."""
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

            # Bloqueo explícito de colisiones fonéticas conocidas
            if ("BRISAS" in q_norm and "FRESAS" in n_norm) or ("FRESAS" in q_norm and "BRISAS" in n_norm):
                continue

            # Si ambos tienen números identificadores y difieren (ej. 3 de Octubre vs 31 u 8 de Octubre)
            q_digits = {t for t in q_tokens if t.isdigit()}
            n_digits = {t for t in n_tokens if t.isdigit()}
            if q_digits and n_digits and not (q_digits & n_digits):
                continue

            coverage = len(q_tokens & n_tokens) / len(q_tokens)
            seq_ratio = SequenceMatcher(None, q_norm, n_norm).ratio()

            # Boost para variantes ortográficas de una sola palabra (ej. PORCUYA ≈ PORCULLA)
            # Requiere: prefijo común consecutivo real >= 4 chars para evitar falsos positivos
            if coverage == 0 and len(q_tokens) == 1 and len(n_tokens) == 1 and seq_ratio >= 0.75:
                q_word = next(iter(q_tokens))
                n_word = next(iter(n_tokens))
                prefix_len = cls._common_prefix_length(q_word, n_word)
                if prefix_len >= 4 and seq_ratio >= 0.80:
                    score = 0.50 + (seq_ratio * 0.50)
                else:
                    score = seq_ratio * 0.40
            elif coverage >= 1.0:
                score = 0.82 + (seq_ratio * 0.18)
            elif coverage >= 0.5:
                score = (0.5 * coverage) + (0.5 * seq_ratio)
            else:
                score = seq_ratio * 0.55

            if tipo_via_hint and item.get("id_tipo_via") == tipo_via_hint and score >= 0.6:
                score += 0.03

            # Boost sectorial si la vía pertenece al sector de la zona identificada
            if sector_hint and item.get("sector") and score >= 0.50:
                s_targets = set(str(sector_hint).replace(",", " ").split())
                v_sectors = set(str(item.get("sector") or "").replace(",", " ").split())
                if s_targets & v_sectors:
                    score += 0.08

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
        sector_hint: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Homologa el nombre de una vía contra el catálogo oficial de vías físicas de Chiclayo,
        apoyándose en coincidencia exacta, filtro sectorial para vías homónimas, sinónimos y desambiguación con IA.
        """
        if not text:
            return None
        clean = TextCleaner.sanitize(text)
        if not clean:
            return None
        no_acc = TextCleaner.remove_accents(clean)

        multi_lookup = CatalogManager.get_physical_vias_multi_lookup()
        lookup = CatalogManager.get_physical_vias_lookup()

        # Inferencia de tipo de vía a partir del texto de entrada si no fue provisto
        inferred_tipo_via = tipo_via_hint
        if not inferred_tipo_via:
            if re.match(r"^(?:AV\.|AVENIDA|AV)\s+", clean, re.IGNORECASE):
                inferred_tipo_via = 1
            elif re.match(r"^(?:CA\.|CALLE|CL\.|CL|CA)\s+", clean, re.IGNORECASE):
                inferred_tipo_via = 2
            elif re.match(r"^(?:JR\.|JIRON|JIRÓN|JR)\s+", clean, re.IGNORECASE):
                inferred_tipo_via = 3
            elif re.match(r"^(?:PJE\.|PASAJE|PSJ\.|PSJ|PJE)\s+", clean, re.IGNORECASE):
                inferred_tipo_via = 4

        def _resolve_sector(entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not entries:
                return None
            if len(entries) == 1:
                return entries[0]
            if sector_hint:
                s_targets = set(str(sector_hint).replace(",", " ").split())
                s_matches = [itm for itm in entries if s_targets & set(str(itm.get("sector") or "").replace(",", " ").split())]
                if s_matches:
                    if inferred_tipo_via:
                        t_matches = [itm for itm in s_matches if itm.get("id_tipo_via") == inferred_tipo_via]
                        if t_matches:
                            f_matches = [itm for itm in t_matches if itm.get("condicion") == "F"]
                            return f_matches[0] if f_matches else t_matches[0]
                    f_matches = [itm for itm in s_matches if itm.get("condicion") == "F"]
                    return f_matches[0] if f_matches else s_matches[0]
            if inferred_tipo_via:
                t_matches = [itm for itm in entries if itm.get("id_tipo_via") == inferred_tipo_via]
                if t_matches:
                    f_matches = [itm for itm in t_matches if itm.get("condicion") == "F"]
                    return f_matches[0] if f_matches else t_matches[0]
            f_entries = [e for e in entries if e.get("condicion") == "F"]
            return f_entries[0] if f_entries else entries[0]

        # 1. Búsqueda directa por nombre o sinónimo exacto con desambiguación sectorial (0ms)
        if clean in multi_lookup:
            return _resolve_sector(multi_lookup[clean])
        if no_acc in multi_lookup:
            return _resolve_sector(multi_lookup[no_acc])

        # 2. Quitar prefijos comunes de vías
        clean_noprefix = re.sub(
            r"^(?:AV\.|AVENIDA|CA\.|CALLE|JR\.|JIRON|PJE\.|PASAJE|PRLG\.|PROLONGACION|CTRA\.|CARRETERA|AL\.|ALAMEDA|PSO\.|PASEO)\s+",
            "",
            clean,
            flags=re.IGNORECASE,
        ).strip()
        no_acc_noprefix = TextCleaner.remove_accents(clean_noprefix)

        # Context-sensitive: Santa Victoria as Av. Sesquicentenario (ID 2926) only with Avenue hint/prefix
        is_av_santa_victoria = (
            clean_noprefix in ("SANTA VICTORIA", "STA VICTORIA", "STA. VICTORIA")
            and (
                inferred_tipo_via == 1
                or (raw_text and bool(re.search(r"\b(?:AV\.?|AVENIDA)\s+ST?A\.?\s+VICTORIA\b", raw_text, re.IGNORECASE)))
            )
        )
        if is_av_santa_victoria and "SESQUICENTENARIO" in multi_lookup:
            return _resolve_sector(multi_lookup["SESQUICENTENARIO"])

        if clean_noprefix in multi_lookup:
            return _resolve_sector(multi_lookup[clean_noprefix])
        if no_acc_noprefix in multi_lookup:
            return _resolve_sector(multi_lookup[no_acc_noprefix])

        # 3. Normalización léxica de variantes
        norm_text = cls.normalize_variants_text(clean_noprefix)
        if norm_text in multi_lookup:
            return _resolve_sector(multi_lookup[norm_text])

        # 4. Búsqueda de candidatos difusos con sector_hint
        candidates = cls.find_via_candidates(
            clean_noprefix,
            tipo_via_hint=tipo_via_hint,
            sector_hint=sector_hint,
            top_k=8,
            min_score=0.50,
        )
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
            top_tokens = cls._extract_sig_tokens(top_candidate.get("nom_via", ""), is_via=True)
            q_tokens = cls._extract_sig_tokens(clean_noprefix, is_via=True)
            if not (q_tokens & top_tokens):
                if not (len(q_tokens) == 1 and len(top_tokens) == 1 and cls._common_prefix_length(next(iter(q_tokens)), next(iter(top_tokens))) >= 4):
                    return None
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
            top_tokens = cls._extract_sig_tokens(top_candidate.get("nom_zona", ""), is_via=False)
            q_tokens = cls._extract_sig_tokens(clean_noprefix, is_via=False)
            if not (q_tokens & top_tokens):
                if not (len(q_tokens) == 1 and len(top_tokens) == 1 and cls._common_prefix_length(next(iter(q_tokens)), next(iter(top_tokens))) >= 4):
                    return None
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
