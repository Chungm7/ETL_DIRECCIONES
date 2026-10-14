"""Validador de certeza catastral y coherencia post-normalización.

Compara la dirección cruda original contra la dirección normalizada completa reconstruida
a partir de los campos catalogados oficiales (vía, número, manzana, lote, módulos, zona y referencia).

Calcula la cobertura de tokens informativos y la similitud de secuencia para garantizar un
100% de certeza en los registros marcados como normalizados (es_procesado = True).
Si la similitud cae por debajo del umbral de alta certeza (ej. 85%), o si la IA omitió partes
esenciales del texto crudo, la dirección se veta y se deriva a es_procesado = False (OBSERVADO)
para que un operador humano la certifique en la GUI.
"""

import difflib
import re
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

from src.models.direccion_destino import DireccionDestino
from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher
from src.transformers.text_cleaner import TextCleaner


@dataclass
class NormalizationValidationResult:
    """Resultado de la validación cruzada entre texto crudo y resultado normalizado."""
    is_valid: bool
    score: float
    token_coverage: float
    sequence_ratio: float
    unmatched_tokens: List[str] = field(default_factory=list)
    reconstructed_text: str = ""
    rejection_reason: Optional[str] = None


class AddressNormalizationValidator:
    """Evalúa la fidelidad y certeza de la normalización comparando el texto crudo con el resultado."""

    # Stopwords lingüísticas y administrativas que no aportan discriminación catastral
    STOPWORDS: Set[str] = {
        "DE", "DEL", "LA", "EL", "LOS", "LAS", "EN", "A", "AL", "Y", "E", "O", "U",
        "POR", "CON", "PARA", "SIN", "SOBRE", "ENTRE", "HACIA", "HASTA",
        "CHICLAYO", "LAMBAYEQUE", "PERU", "PERÚ",
    }

    # Descriptores y marcadores numéricos que pueden estar o no presentes sin alterar la semántica
    DESCRIPTOR_NOISE: Set[str] = {
        "N", "NO", "N°", "Nº", "NUM", "NUM°", "NUMº", "NRO", "NRO°", "NROº",
        "NUMERO", "NUMERACION",
    }

    # Mapa de normalización canónica de abreviaturas para comparación justa
    ABBREVIATION_MAP = {
        "AV": "AVENIDA",
        "AVDA": "AVENIDA",
        "CA": "CALLE",
        "CL": "CALLE",
        "JR": "JIRON",
        "JRN": "JIRON",
        "PSJ": "PASAJE",
        "PJE": "PASAJE",
        "PRL": "PROLONGACION",
        "PROL": "PROLONGACION",
        "MZ": "MANZANA",
        "MZA": "MANZANA",
        "LT": "LOTE",
        "LTE": "LOTE",
        "SLT": "SUBLOTE",
        "SL": "SUBLOTE",
        "DPTO": "DEPARTAMENTO",
        "DEP": "DEPARTAMENTO",
        "DTO": "DEPARTAMENTO",
        "INT": "INTERIOR",
        "URB": "URBANIZACION",
        "PJ": "PUEBLO JOVEN",
        "PPJJ": "PUEBLO JOVEN",
        "AH": "ASENTAMIENTO HUMANO",
        "AAHH": "ASENTAMIENTO HUMANO",
        "CP": "CENTRO POBLADO",
        "SEC": "SECTOR",
        "BLQ": "BLOCK",
        "BLOQUE": "BLOCK",
        "TORRE": "BLOCK",
        "TDA": "TIENDA",
        "STD": "STAND",
        "OF": "OFICINA",
        "PTO": "PUESTO",
        "PTA": "PUERTA",
        "CONDOMINIO": "URBANIZACION",
        "RESIDENCIAL": "URBANIZACION",
        "COOPERATIVA": "URBANIZACION",
        "ASOCIACION": "URBANIZACION",
    }

    ORDINAL_MAP = {
        "1ER": "1", "1ERO": "1", "1RO": "1", "1RA": "1", "PRIMER": "1", "PRIMERA": "1", "PRIMERO": "1", "UNO": "1",
        "2DO": "2", "2DA": "2", "SEGUNDO": "2", "SEGUNDA": "2", "DOS": "2",
        "3ER": "3", "3ERO": "3", "3RO": "3", "3RA": "3", "TERCER": "3", "TERCERA": "3", "TERCERO": "3", "TRES": "3",
        "4TO": "4", "4TA": "4", "CUARTO": "4", "CUARTA": "4", "CUATRO": "4",
        "5TO": "5", "5TA": "5", "QUINTO": "5", "QUINTA": "5", "CINCO": "5",
        "6TO": "6", "6TA": "6", "SEXTO": "6", "SEXTA": "6", "SEIS": "6",
        "7MO": "7", "7MA": "7", "SEPTIMO": "7", "SEPTIMA": "7", "SIETE": "7",
        "8VO": "8", "8VA": "8", "OCTAVO": "8", "OCTAVA": "8", "OCHO": "8",
        "9NO": "9", "9NA": "9", "NOVENO": "9", "NOVENA": "9", "NUEVE": "9",
        "10MO": "10", "10MA": "10", "DECIMO": "10", "DECIMA": "10", "DIEZ": "10",
        "ONCE": "11", "DOCE": "12", "TRECE": "13", "CATORCE": "14", "QUINCE": "15",
        "VEINTE": "20", "VEINTISIETE": "27", "VEINTIOCHO": "28",
    }

    ROMAN_MAP = {
        "I": "1", "II": "2", "III": "3", "IV": "4", "V": "5",
        "VI": "6", "VII": "7", "VIII": "8", "IX": "9", "X": "10",
    }

    VIA_TYPES: Set[str] = {
        "AVENIDA", "CALLE", "JIRON", "PASAJE", "PROLONGACION", "CARRETERA", "AUTOPISTA"
    }

    ZONA_TYPES: Set[str] = {
        "URBANIZACION", "PUEBLO JOVEN", "ASENTAMIENTO HUMANO", "CENTRO POBLADO", "SECTOR",
        "CONDOMINIO", "RESIDENCIAL"
    }

    @classmethod
    def reconstruct_canonical_address(cls, dest: DireccionDestino) -> str:
        """Reconstruye una cadena de texto canónica a partir de los campos normalizados en DireccionDestino."""
        parts: List[str] = []

        # 1. Vías (Principal y Secundarias)
        if dest.vias:
            for v in dest.vias:
                t_via = v.get("tipo_via_name")
                if not t_via and v.get("tipo_via"):
                    t_via = CatalogMatcher.get_via_name(v["tipo_via"]) if isinstance(v["tipo_via"], int) else str(v["tipo_via"])
                n_via = v.get("via_nombre") or ""
                num = v.get("divi_numero") or ""
                v_str = f"{t_via or ''} {n_via}".strip()
                if num and str(num).upper() != "S/N":
                    v_str = f"{v_str} {num}".strip()
                if v_str:
                    parts.append(v_str)
        elif dest.nom_via:
            t_via = dest.tipo_via
            if isinstance(t_via, int):
                t_via = CatalogMatcher.get_via_name(t_via)
            n_via = dest.nom_via or ""
            num = dest.num_via or ""
            v_str = f"{t_via or ''} {n_via}".strip()
            if num and str(num).upper() != "S/N":
                v_str = f"{v_str} {num}".strip()
            if v_str:
                parts.append(v_str)

        # 2. Componentes catastrales (Manzana, Lote, Sublote, Piso, Block, etc.)
        if dest.componentes:
            for c in dest.componentes:
                c_nom = c.get("codi_nombre") or c.get("tipo_componente") or ""
                c_val = c.get("diti_nombre") or c.get("diti_valor") or c.get("valor") or ""
                if c_nom and c_val:
                    parts.append(f"{c_nom} {c_val}".strip())
        else:
            if dest.manzana:
                parts.append(f"MANZANA {dest.manzana}")
            if dest.lote:
                parts.append(f"LOTE {dest.lote}")
            if dest.slote:
                parts.append(f"SUBLOTE {dest.slote}")
            if dest.piso:
                parts.append(f"PISO {dest.piso}")
            if dest.block:
                parts.append(f"BLOCK {dest.block}")

        # 3. Módulos Inmobiliarios (Dpto, Tienda, Stand, Interior, etc.)
        if dest.modulos:
            for m in dest.modulos:
                m_tipo = m.get("timo_nombre") or m.get("tipo") or ""
                m_num = m.get("ditm_nombre") or m.get("numero") or ""
                if m_tipo and m_num:
                    parts.append(f"{m_tipo} {m_num}".strip())

        # 4. Zona / Habilitación Urbana
        if dest.nom_zona:
            t_zona = dest.tipo_zona
            if isinstance(t_zona, int):
                t_zona = CatalogMatcher.get_zona_name(t_zona)
            parts.append(f"{t_zona or ''} {dest.nom_zona}".strip())

        # 5. Referencia limpia
        ref = dest.dire_referencia or dest.referencia
        if ref:
            parts.append(str(ref).strip())

        return " ".join(parts).strip()

    @classmethod
    def tokenize_and_canonicalize(cls, text: str) -> List[str]:
        """Limpia y tokeniza una cadena de dirección convirtiendo abreviaturas a su forma canónica."""
        if not text:
            return []

        # Remover acentos y convertir a mayúsculas
        clean = TextCleaner.remove_accents(text).upper()
        # Normalizar sufijos ordinales numéricos (ej. 2DO -> 2, 3ER -> 3)
        clean = re.sub(r"\b(\d+)(?:ER|ERO|RO|RA|DO|DA|TO|TA|VO|VA|MO|MA)\b", r"\1", clean)
        # Normalizar acrónimos compuestos con puntos frecuentes en Perú
        clean = re.sub(r"\b(?:P\.?P\.?\s*J\.?J\.?|P\.?J\.?)\b", " PUEBLO JOVEN ", clean)
        clean = re.sub(r"\b(?:A\.?A\.?\s*H\.?H\.?|A\.?H\.?)\b", " ASENTAMIENTO HUMANO ", clean)
        clean = re.sub(r"\b(?:C\.?P\.?)\b", " CENTRO POBLADO ", clean)
        clean = re.sub(r"\b(?:U\.?R\.?B\.?)\b", " URBANIZACION ", clean)
        # Normalizar separadores y puntuación
        clean = re.sub(r"[\.,;:_/\-\(\)\[\]#°ºª\\–]+", " ", clean)
        # Despegar números y letras pegadas (ej. GONZALES00839 -> GONZALES 00839, AMERICAS705 -> AMERICAS 705)
        clean = re.sub(r"([A-ZÁÉÍÓÚÑ]{2,})(\d+)", r"\1 \2", clean)
        clean = re.sub(r"(\d+)([A-ZÁÉÍÓÚÑ]{2,})", r"\1 \2", clean)

        raw_tokens = clean.split()
        canonical_tokens: List[str] = []

        for token in raw_tokens:
            token = token.strip()
            if not token:
                continue

            # Descartar ruido descriptor de número (N, NRO, NUM)
            if token in cls.DESCRIPTOR_NOISE:
                continue

            # Descartar stopwords
            if token in cls.STOPWORDS:
                continue

            # Normalizar ceros iniciales en números
            if token.isdigit():
                token = str(int(token))
            else:
                token = cls.ORDINAL_MAP.get(token, token)
                token = cls.ROMAN_MAP.get(token, token)

            # Mapear abreviatura a forma canónica si existe
            canonical = cls.ABBREVIATION_MAP.get(token, token)
            canonical_tokens.append(canonical)

        return canonical_tokens

    @classmethod
    def validate(
        cls,
        raw_text: str,
        destino: DireccionDestino,
        threshold: float = 0.85,
    ) -> NormalizationValidationResult:
        """Valida que la dirección normalizada tenga un umbral de certeza y similitud muy alto.
        
        Args:
            raw_text: Dirección cruda original.
            destino: Objeto DireccionDestino resultante de la normalización.
            threshold: Umbral mínimo de score compuesto (0.0 a 1.0) para confirmar éxito.

        Returns:
            NormalizationValidationResult con veredicto, scores y diagnóstico.
        """
        reconstructed = cls.reconstruct_canonical_address(destino)

        raw_tokens = cls.tokenize_and_canonicalize(raw_text)
        norm_tokens = cls.tokenize_and_canonicalize(reconstructed)

        if not raw_tokens:
            # Texto crudo vacío o compuesto solo de stopwords
            return NormalizationValidationResult(
                is_valid=False,
                score=0.0,
                token_coverage=0.0,
                sequence_ratio=0.0,
                reconstructed_text=reconstructed,
                rejection_reason="DIRECCION_ORIGINAL_VACIA_O_TRIVIAL",
            )

        norm_token_set = set(norm_tokens)
        norm_token_list = list(norm_tokens)

        # Si se confirmó una vía válida, cualquier descriptor de tipo de vía en el texto crudo queda explicado
        if destino.nom_via or destino.vias:
            norm_token_set.update(cls.VIA_TYPES)
            v_names = [destino.nom_via] if destino.nom_via else []
            if destino.vias:
                v_names.extend(v.get("via_nombre") for v in destino.vias if v.get("via_nombre"))
            for vn in v_names:
                if vn:
                    vn_up = vn.upper().strip()
                    for syn, target in getattr(CatalogManager, "EXTRA_VIAS_SYNONYMS", {}).items():
                        if target.upper() == vn_up or target.upper() in vn_up or vn_up in target.upper():
                            for st in cls.tokenize_and_canonicalize(syn):
                                norm_token_set.add(st)
                                if st not in norm_token_list:
                                    norm_token_list.append(st)

        # Si se confirmó una zona válida, cualquier descriptor de zona en el texto crudo queda explicado
        if destino.nom_zona or destino.zona_id:
            norm_token_set.update(cls.ZONA_TYPES)
            if destino.nom_zona:
                zn_up = destino.nom_zona.upper().strip()
                for syn, target in getattr(CatalogManager, "EXTRA_ZONAS_SYNONYMS", {}).items():
                    if target.upper() == zn_up or target.upper() in zn_up or zn_up in target.upper():
                        for st in cls.tokenize_and_canonicalize(syn):
                            norm_token_set.add(st)
                            if st not in norm_token_list:
                                norm_token_list.append(st)

        # Si se resolvieron múltiples vías (esquina/intersección), los conectores típicos quedan implícitamente explicados
        if (destino.vias and len(destino.vias) > 1):
            norm_token_set.update({"ESQ", "ESQUINA", "CRUCE", "CON", "INTERSECCION"})

        # 1. Cobertura de Tokens (Token Recall): ¿Qué porcentaje de tokens crudos se explicaron?
        matched_tokens_count = 0
        unmatched_tokens: List[str] = []

        for token in raw_tokens:
            if token in norm_token_set:
                matched_tokens_count += 1
            else:
                # Comprobación de coincidencia difusa individual para tolerar pequeñas variaciones ortográficas
                fuzzy_match = any(
                    difflib.SequenceMatcher(None, token, nt).ratio() >= 0.88
                    for nt in norm_token_list
                    if abs(len(token) - len(nt)) <= 2
                )
                if fuzzy_match:
                    matched_tokens_count += 1
                else:
                    unmatched_tokens.append(token)

        token_coverage = matched_tokens_count / len(raw_tokens)

        # 2. Similitud de Contenido y Secuencia (Permutation-Safe Sequence Ratio)
        common_tokens = [t for t in raw_tokens if t not in unmatched_tokens]
        sequence_ratio = (
            difflib.SequenceMatcher(
                None, " ".join(sorted(raw_tokens)), " ".join(sorted(common_tokens))
            ).ratio()
            if raw_tokens
            else 0.0
        )

        # 3. Score Compuesto Ponderado (60% Cobertura de tokens + 40% Similitud de contenido común)
        score = round((0.60 * token_coverage) + (0.40 * sequence_ratio), 3)

        # 4. Decisión Estricta de Certeza:
        # Se exige que el score compuesto supere el umbral Y que la cobertura de tokens sea de al menos 75%
        # para evitar que una normalización que omitió palabras clave sea aprobada.
        is_valid = bool(score >= threshold and token_coverage >= 0.75)

        rejection_reason: Optional[str] = None
        if not is_valid:
            pct_score = round(score * 100, 1)
            pct_cov = round(token_coverage * 100, 1)
            unmatched_sample = ", ".join(unmatched_tokens[:5])
            if len(unmatched_tokens) > 5:
                unmatched_sample += f" (+{len(unmatched_tokens) - 5} más)"
            rejection_reason = (
                f"SIMILITUD_INSUFICIENTE (Score {pct_score}%, Cobertura {pct_cov}% < Umbral {round(threshold*100, 1)}%). "
                f"Tokens no explicados: [{unmatched_sample}]"
            )

        return NormalizationValidationResult(
            is_valid=is_valid,
            score=score,
            token_coverage=round(token_coverage, 3),
            sequence_ratio=round(sequence_ratio, 3),
            unmatched_tokens=unmatched_tokens,
            reconstructed_text=reconstructed,
            rejection_reason=rejection_reason,
        )
