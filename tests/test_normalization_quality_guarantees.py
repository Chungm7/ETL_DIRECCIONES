"""Pruebas unitarias de calidad y garantías de normalización para el motor ETL de la MPCH.

Verifica:
1. Cero falsos positivos: Bloqueo de alucinaciones y colisiones difusas (Brisas != Fresas, Colón != Vallejo).
2. Preservación de vías oficiales frente a hitos comerciales (Real Plaza, Boulevard, Open Plaza).
3. Numeración municipal limpia: Aislamiento estricto de interiores, departamentos y bloques en slote.
4. Diagnóstico preciso en observados para vías fuera de catálogo.
5. Inmutabilidad de los catálogos oficiales JSON (2,935 vías y 460 zonas).
"""

import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock

from src.models.direccion_origen import DireccionOrigen
from src.transformers.ai_parser import AIAddressParser
from src.transformers.catalog_matcher import CatalogMatcher
from src.models.llm_schemas import OllamaAddressExtraction


def test_catalogs_inmutability():
    """Garantiza que los archivos oficiales JSON no fueron alterados."""
    vias_path = Path("src/catalogs/vias_chiclayo.json")
    zonas_path = Path("src/catalogs/zonas_chiclayo.json")

    with open(vias_path, "r", encoding="utf-8") as f:
        vias = json.load(f)
    with open(zonas_path, "r", encoding="utf-8") as f:
        zonas = json.load(f)

    assert len(vias) == 2935, f"Se alteró el catálogo oficial de vías: esperadas 2935, hay {len(vias)}"
    assert len(zonas) == 460, f"Se alteró el catálogo oficial de zonas: esperadas 460, hay {len(zonas)}"


def test_brisas_never_matches_fresas():
    """Asegura que 'LAS BRISAS' nunca se homologue como pasaje 'LAS FRESAS'."""
    cand_via = CatalogMatcher.find_via_candidates("LAS BRISAS")
    matched_via = CatalogMatcher.match_physical_via("LAS BRISAS")
    assert matched_via is None, f"Error: LAS BRISAS fue emparejado con vía: {matched_via}"

    matched_zona = CatalogMatcher.match_physical_zona("LAS BRISAS")
    assert matched_zona is not None
    assert matched_zona["nom_zona"] == "LAS BRISAS"


def test_brisas_street_parsing_rescued():
    """Verifica que una dirección en Las Brisas identifique la calle real y no Las Fresas."""
    parser = AIAddressParser()
    rec = DireccionOrigen(
        id_licencia=1213,
        emp_direccion="LAS BRISAS-PEDRO CIEZA DE LEON - CDRA. 3 - LOTE 25"
    )
    result = parser.parse(rec)
    assert result.nom_via == "PEDRO CIEZA DE LEON"
    assert result.nom_zona == "LAS BRISAS"
    assert result.id_via is not None
    assert result.id_zona is not None
    assert result.es_procesado is True


def test_anti_hallucination_cristobal_colon():
    """Asegura que si un LLM alucina 'CESAR VALLEJO' ante 'CRISTOBAL COLON', el guardrail lo rechace."""
    mock_ollama = MagicMock()
    # Simular que el LLM alucinó completamente
    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
        nom_via="CESAR VALLEJO",
        tipo_via_detectado="CALLE",
        num_via="607",
        nom_zona="CÉSAR VALLEJO",
        tipo_zona_detectada="URBANIZACION POPULAR",
        confianza=0.9
    )

    parser = AIAddressParser(ollama_service=mock_ollama)
    rec = DireccionOrigen(
        id_licencia=1583,
        emp_direccion="CHICLAYO-CRISTOBAL COLON 0607"
    )
    result = parser.parse(rec)

    # El guardrail debe haber descartado la alucinación y rescatado 'CRISTOBAL COLON'
    assert result.nom_via == "CRISTOBAL COLON"
    assert result.id_via == 881
    assert result.num_via == "607"
    assert result.es_procesado is True


def test_santa_victoria_pacasmayo_inversion():
    """Verifica que URB. SANTA VICTORIA - PACASMAYO 147 no tome Sesquicentenario como vía."""
    parser = AIAddressParser()
    rec = DireccionOrigen(
        id_licencia=2469,
        emp_direccion="URB. SANTA VICTORIA-PACASMAYO 00147"
    )
    result = parser.parse(rec)
    assert "PACASMAYO" in result.nom_via
    assert result.nom_zona == "SANTA VICTORIA"
    assert result.num_via == "147"
    assert result.es_procesado is True


def test_commercial_mall_preserves_confirmed_via():
    """Verifica que C.C. REAL PLAZA pase a referencia y preserve la vía oficial confirmada."""
    parser = AIAddressParser()
    rec = DireccionOrigen(
        id_licencia=2203,
        emp_direccion="CHICLAYO MIGUEL DE CERVANTES00300 CC. REAL PLAZA"
    )
    result = parser.parse(rec)
    assert "MIGUEL DE CERVANTES" in result.nom_via
    assert result.num_via == "300"
    assert result.id_via == 224
    assert result.es_procesado is True
    assert result.nom_zona is None
    assert "REAL PLAZA" in (result.referencia or "")


def test_clean_numbering_interior_decoupling():
    """Verifica que interiores y dptos se desacoplen estrictamente de num_via."""
    parser = AIAddressParser()

    # Caso DPTO
    rec1 = DireccionOrigen(id_licencia=1319, emp_direccion="CHICLAYO-TORRES PAZ00683 DPTO. 304")
    res1 = parser.parse(rec1)
    assert res1.num_via == "683"
    assert "DPTO" in (res1.slote or "")

    # Caso INT
    rec2 = DireccionOrigen(id_licencia=1533, emp_direccion="CHICLAYO-ELIAS AGUIRRE 00631-INT. 105")
    res2 = parser.parse(rec2)
    assert res2.num_via == "631"
    assert "INT" in (res2.slote or "")

    # Caso BLOCK
    rec3 = DireccionOrigen(id_licencia=1230, emp_direccion="CONDOMINIO LA PRIMAVERA-ANGEL CORNEJO BLOCK F-101")
    res3 = parser.parse(rec3)
    assert res3.num_via is None or res3.num_via == "S/N"
    assert "BLOCK" in str(res3.slote or res3.referencia)


def test_clean_numbering_letter_suffix():
    """Verifica que sufijos de letra (ej. 125-A) mantengan el número limpio."""
    parser = AIAddressParser()
    rec = DireccionOrigen(id_licencia=1263, emp_direccion="CHICLAYO-8 DE OCTUBRE00125 - A")
    res = parser.parse(rec)
    assert res.num_via == "125"
    assert "8 DE OCTUBRE" in res.nom_via
    assert res.slote == "A"


def test_uncataloged_via_is_accurately_observed():
    """Verifica que una vía que no está en el catálogo sea observada con diagnóstico exacto."""
    parser = AIAddressParser()
    rec = DireccionOrigen(
        id_licencia=99999,
        emp_direccion="CALLE VIA_INVENTADA_TOTALMENTE_999 N 123"
    )
    res = parser.parse(rec)
    assert res.es_procesado is False
    assert "catálogo maestro" in res.observacion.lower()


def test_official_synonyms_resolution():
    """Verifica que variantes ortográficas de vías existentes en el catálogo resuelvan perfectamente."""
    # HUMBOLT -> ALEXANDER VON HUMBOLDT
    match_h = CatalogMatcher.match_physical_via("HUMBOLT")
    assert match_h is not None
    assert match_h["nom_via"] == "ALEXANDER VON HUMBOLDT"

    # VIRGILIO DALLORSO -> DALL'ORSO
    match_d = CatalogMatcher.match_physical_via("VIRGILIO DALLORSO")
    assert match_d is not None
    assert match_d["nom_via"] == "DALL'ORSO"

    # ROQUE SAENZ PEÑA -> SAENZ PEÑA
    match_s = CatalogMatcher.match_physical_via("ROQUE SAENZ PEÑA")
    assert match_s is not None
    assert match_s["nom_via"] == "SAENZ PEÑA"


def test_diego_ferre_baquijano_heuristic_resolution():
    """Caso ID 1283: 'DIEGO FERRE-BAQUIJANO00675' heurístico.
    Diego Ferré es la habilitación urbana (P.J. Diego Ferré, ID 30, Sector 33).
    Baquíjano es la calle (Calle José Baquíjano, ID 206, Sector 33).
    NUNCA debe asignarse Diego Ferré como vía ni Baquíjano como esquina (ESQ.).
    """
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = None
    parser = AIAddressParser(mock_ollama)

    rec = DireccionOrigen(id_licencia=1283, emp_direccion="DIEGO FERRE-BAQUIJANO00675")
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.id_zona == 30, f"Esperado ID zona 30 (Diego Ferré), obtenido: {res.id_zona}"
    assert res.nom_zona == "DIEGO FERRE"
    assert res.id_via == 206, f"Esperado ID vía 206 (José Baquíjano), obtenido: {res.id_via}"
    assert "BAQUIJANO" in res.nom_via
    assert res.num_via == "675"
    assert res.referencia is None or "ESQ" not in res.referencia


def test_diego_ferre_baquijano_ai_inversion_protection():
    """Caso ID 1283 Híbrido: Simula que la IA extrajo DIEGO FERRE como vía y BAQUIJANO como zona.
    El guardrail de inversión semántica debe detectar que DIEGO FERRE es una zona oficial
    y BAQUIJANO es exclusivamente una vía oficial, restaurando los roles correctos.
    """
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
        nom_via="DIEGO FERRE",
        num_via="675",
        nom_zona="BAQUIJANO",
        tipo_via_detectado="CALLE",
    )
    parser = AIAddressParser(mock_ollama)

    rec = DireccionOrigen(id_licencia=1283, emp_direccion="DIEGO FERRE-BAQUIJANO00675")
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.id_zona == 30, f"Esperado ID zona 30 (Diego Ferré), obtenido: {res.id_zona}"
    assert res.nom_zona == "DIEGO FERRE"
    assert res.id_via == 206, f"Esperado ID vía 206 (José Baquíjano), obtenido: {res.id_via}"
    assert "BAQUIJANO" in res.nom_via
    assert res.num_via == "675"
    assert res.referencia is None, f"Referencia no deseada generada: {res.referencia}"


def test_diego_ferre_miguel_de_cervantes_resolution():
    """Caso ID 1943: 'DIEGO FERRE-MIGUEL DE CERVANTES 0300 - M-10'.
    Debe normalizar a Vía: Miguel de Cervantes (ID 224), Zona: Diego Ferré (ID 30),
    num_via: '300', referencia: 'M-10'.
    """
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = None
    parser = AIAddressParser(mock_ollama)

    rec = DireccionOrigen(id_licencia=1943, emp_direccion="DIEGO FERRE-MIGUEL DE CERVANTES 0300 - M-10")
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.id_zona == 30
    assert res.nom_zona == "DIEGO FERRE"
    assert res.id_via == 224
    assert "MIGUEL DE CERVANTES" in res.nom_via
    assert res.num_via == "300"
    assert res.referencia is not None
    assert "M" in res.referencia and "10" in res.referencia

