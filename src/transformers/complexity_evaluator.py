"""Evaluador de complejidad y potencial de error catastral en direcciones crudas.

Analiza y mide la densidad, ambigüedad y sobrecarga de información en cadenas de texto
de direcciones para determinar si superan el umbral seguro de normalización automática.
Si una dirección es demasiado compleja o contiene patrones de alto riesgo (alias viales EX-,
múltiples módulos masivos, predios agrícolas complejos), la clasifica como OBSERVADA (FALSE)
para exigir certificación e intervención humana y garantizar 100% de certeza catastral.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple
from src.transformers.text_cleaner import TextCleaner


@dataclass
class ComplexityEvaluationResult:
    """Resultado de la evaluación de complejidad y riesgo de una dirección."""
    is_too_complex: bool
    score: float
    triggers: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


class AddressComplexityEvaluator:
    """Evalúa la sobrecarga de información y el riesgo de error en direcciones crudas."""

    # 1. Alias viales históricos (EX-...)
    HISTORICAL_VIA_REGEX = re.compile(
        r"\b(?:EX\s*[-–.]?\s*(?:CA\.?|CALLE|AV\.?|AVENIDA|JR\.?|JIRON|PJE\.?|PANAMERICANA)|EX[-–\s]+(?:CA|AV|JR|CALLE|AVENIDA|PJE|PANAMERICANA|[A-ZÁÉÍÓÚÑ]{4,}))\b",
        re.IGNORECASE,
    )

    # 2. Vías con doble denominación o barra (ej. CALLE / AV...)
    DUAL_STREET_SLASH_REGEX = re.compile(
        r"\b(?:CALLE|CA\.?|AV\.?|AVENIDA|JR\.?|JIRON|PJE\.?)\s*/\s*(?:CALLE|CA\.?|AV\.?|AVENIDA|JR\.?|JIRON|PJE\.?)\b",
        re.IGNORECASE,
    )

    # 3. Módulos masivos en lista o rango múltiple (ej. MODULOS 3, 4, 5 Y 6 / STANDS A1, A2 Y A3 / LF05-LF07-LF09 / A2017-A2019-A2021)
    MASSIVE_MODULES_LIST_REGEX = re.compile(
        r"\b(?:M[ÓO]DULOS|STANDS|LOCALES|TIENDAS|TENDAS)\s+[A-Z0-9]{1,8}(?:\s*(?:,|Y)\s*[A-Z0-9]{1,8}){2,}",
        re.IGNORECASE,
    )
    MASSIVE_MODULES_RANGE_REGEX = re.compile(
        r"\b(?:LOCAL|LOC|STAND|STD|TIENDA|TDA|TENDAS?)\s+[A-Z0-9]{2,8}(?:-[A-Z0-9]{2,8}){2,}",
        re.IGNORECASE,
    )

    # 4. Predios rústicos y agrícolas desestructurados
    COMPLEX_RURAL_REGEX = re.compile(
        r"\b(?:PARCELA\s+AGR[IÍ]COLA|TERRENO\s+R[UÚ]STICO|U\.?C\.?\s*N[°º]?\s*\d+|FUNDO\s+[A-ZÁÉÍÓÚÑ\s]+Y\s+ANEXOS)\b",
        re.IGNORECASE,
    )

    # 5. Cruces o referencias hiper-descriptivas no canónicas
    HYPER_DESCRIPTIVE_INTERSECTION_REGEX = re.compile(
        r"\b(?:ESQ(?:UINA)?\s+CON\s+CUADRA\s+\d+|CRUCE\s+CON\s+CUADRA\s+\d+|A\s+\d+\s+METROS?\s+DE)\b",
        re.IGNORECASE,
    )

    # Marcas comerciales reconocibles para detección de saturación comercial
    COMMERCIAL_BRANDS = {
        "PROMART", "CURACAO", "PLAZA VEA", "TAI LOY", "RIPLEY", "SAGA", "FALABELLA",
        "SODIMAC", "TOTTUS", "METRO", "OECHSLE", "ESTILOS", "SUPERPET", "I-RUN", "NOW", "BORETO"
    }

    @classmethod
    def evaluate(
        cls,
        raw_text: str,
        threshold: float = 65.0,
        max_length: int = 110,
    ) -> ComplexityEvaluationResult:
        """Analiza la dirección y determina si supera el umbral seguro de complejidad.
        
        Args:
            raw_text: Cadena original o saneada de la dirección.
            threshold: Umbral de score (0 a 100) para declarar alta complejidad (default: 65.0).
            max_length: Longitud de caracteres a partir de la cual se considera sobrecargada.

        Returns:
            ComplexityEvaluationResult con el dictamen técnico.
        """
        if not raw_text or not raw_text.strip():
            return ComplexityEvaluationResult(is_too_complex=False, score=0.0)

        clean = TextCleaner.sanitize(raw_text)
        triggers: List[str] = []
        reasons: List[str] = []
        score = 0.0

        # --- A. DISPARADORES CRÍTICOS (HARD TRIGGERS) ---

        # 1. Alias de vía histórica (EX-...)
        if cls.HISTORICAL_VIA_REGEX.search(clean):
            triggers.append("ALIAS_VIA_HISTORICA")
            reasons.append("Contiene referencia a vía histórica o anterior ('EX-') que genera ambigüedad arterial")
            score += 40.0

        # 2. Doble denominación vial con barra (ej. CALLE / AV...)
        if cls.DUAL_STREET_SLASH_REGEX.search(clean):
            triggers.append("DOBLE_VIA_DISYUNTIVA")
            reasons.append("Contiene denominación vial compuesta con barra ('CALLE / AV')")
            score += 35.0

        # 3. Módulos masivos en lista o rango
        if cls.MASSIVE_MODULES_LIST_REGEX.search(clean) or cls.MASSIVE_MODULES_RANGE_REGEX.search(clean):
            triggers.append("MODULOS_MASIVOS_EN_LISTA")
            reasons.append("Agrupa 3 o más módulos o locales comerciales concatenados en lista o rango")
            score += 35.0

        # 4. Estructuras rústicas/agrícolas complejas
        if cls.COMPLEX_RURAL_REGEX.search(clean):
            triggers.append("PREDIO_RUSTICO_COMPLEJO")
            reasons.append("Estructura rústica/agrícola compleja con parcelas, fundos o unidades catastrales (U.C.)")
            score += 35.0

        # 5. Cruces hiper-descriptivos
        if cls.HYPER_DESCRIPTIVE_INTERSECTION_REGEX.search(clean):
            triggers.append("CRUCE_HIPER_DESCRIPTIVO")
            reasons.append("Cruce o esquina hiper-descriptiva con numeración de cuadra no estandarizada")
            score += 30.0

        # --- B. ANÁLISIS CUANTITATIVO DE SOBRECARGA ---

        # 6. Longitud del texto
        text_len = len(clean)
        if text_len >= 135:
            score += 40.0
            reasons.append(f"Longitud de texto excesiva ({text_len} caracteres >= 135)")
        elif text_len >= max_length:
            score += 25.0
            reasons.append(f"Longitud de texto sobrecargada ({text_len} caracteres >= {max_length})")
        elif text_len >= 95:
            score += 10.0

        # 7. Saturación de componentes catastrales simultáneos
        active_components = 0

        # Tiene numeración de calle
        if re.search(r"\b(?:N°?|NUM°?|NRO\.?|N)\s*\d+\b|\bS/N\b", clean, re.IGNORECASE):
            active_components += 1
        # Tiene manzana o lote
        if re.search(r"\b(?:MZ\.?|MZA\.?|MANZANA)\b", clean, re.IGNORECASE) or re.search(r"\b(?:LT\.?|LOTE)\b", clean, re.IGNORECASE):
            active_components += 1
        # Tiene piso o nivel
        if re.search(r"\b(?:PISO|NIVEL)\b", clean, re.IGNORECASE):
            active_components += 1
        # Tiene block o torre
        if re.search(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\b", clean, re.IGNORECASE):
            active_components += 1
        # Tiene dependencias interiores (Stand, Dpto, Local, Interior, Tienda)
        if re.search(r"\b(?:INT(?:ERIOR)?|DPTO|DEP|DEPARTAMENTO|STAND|STD|LOCAL|LOC|TIENDA|TDA|OFICINA|OF)\b", clean, re.IGNORECASE):
            active_components += 1
        # Tiene referencia a centro comercial
        if re.search(r"\b(?:MALL\s+AVENTURA|REAL\s+PLAZA|OPEN\s+PLAZA|C\.?C\.?)\b", clean, re.IGNORECASE):
            active_components += 1

        if active_components >= 5:
            score += 35.0
            reasons.append(f"Sobrecarga extrema de componentes heterogéneos simultáneos ({active_components} sistemas activos)")
        elif active_components >= 4:
            score += 20.0
            reasons.append(f"Sobrecarga de componentes heterogéneos simultáneos ({active_components} sistemas activos)")

        # 8. Múltiples marcas comerciales compitiendo como hitos
        found_brands = [b for b in cls.COMMERCIAL_BRANDS if re.search(rf"\b{re.escape(b)}\b", clean, re.IGNORECASE)]
        if len(found_brands) >= 2:
            score += 25.0
            reasons.append(f"Múltiples marcas comerciales en la referencia ({', '.join(found_brands)})")

        # 9. Densidad de delimitadores (guiones, paréntesis, barras, etc.)
        delim_count = len(re.findall(r"[-–—/(),]", clean))
        if delim_count >= 5:
            score += 15.0
            reasons.append(f"Alta densidad de delimitadores ({delim_count} delimitadores)")

        # Normalizar score a máximo 100.0
        final_score = min(100.0, score)

        # Si disparó al menos un trigger crítico, o superó el umbral de complejidad
        is_too_complex = bool(triggers) or (final_score >= threshold)

        return ComplexityEvaluationResult(
            is_too_complex=is_too_complex,
            score=round(final_score, 1),
            triggers=triggers,
            reasons=reasons,
        )
