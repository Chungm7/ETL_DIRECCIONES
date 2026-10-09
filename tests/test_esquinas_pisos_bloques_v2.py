"""Pruebas unitarias para esquinas con numeración, pisos y bloques en componentes,
supresión de IDs en exportación Excel/CSV y erradicación de vías falsas (V2).
"""

import pytest
from unittest.mock import MagicMock
from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher
from src.transformers.ai_parser import AIAddressParser
from src.models.direccion_origen import DireccionOrigen
from src.ui.server import (
    build_dynamic_export_headers,
    extract_v2_export_row,
    generate_excel_report,
    generate_csv_report,
    generate_json_report,
    V2_EXPORT_HEADERS,
)


@pytest.fixture(autouse=True)
def setup_catalogs():
    """Recarga los catálogos en memoria antes de cada prueba para asegurar estado limpio."""
    CatalogManager.reload()
    CatalogMatcher.reset_defaults()


def test_city_stopwords_do_not_match_as_physical_via():
    """Topónimos de ciudad o distrito sin prefijo vial jamás deben homologarse como calles."""
    assert CatalogMatcher.match_physical_via("CHICLAYO") is None
    assert CatalogMatcher.match_physical_via("PIMENTEL") is None
    assert CatalogMatcher.match_physical_via("LAMBAYEQUE") is None
    assert CatalogMatcher.match_physical_via("FERRENAFE") is None
    assert CatalogMatcher.match_physical_via("JLO") is None

    # Con prefijo formal sí deben identificarse las avenidas o calles homónimas
    match_av_chiclayo = CatalogMatcher.match_physical_via("AV. CHICLAYO")
    assert match_av_chiclayo is not None
    assert "CHICLAYO" in match_av_chiclayo["nom_via"]

    match_ca_pimentel = CatalogMatcher.match_physical_via("CA. PIMENTEL")
    assert match_ca_pimentel is not None
    assert "PIMENTEL" in match_ca_pimentel["nom_via"]


def test_block_component_catalog_mapping():
    """BLOCK y sus variantes deben mapearse a tb_componente_direccion (codi_id=11) y no a tb_tipo_modulo."""
    comp_block = CatalogMatcher.match_componente("BLOCK")
    assert comp_block is not None
    assert comp_block[0] == 11
    assert comp_block[1] == "BLOCK"

    comp_torre = CatalogMatcher.match_componente("TORRE")
    assert comp_torre is not None
    assert comp_torre[0] == 11
    assert comp_torre[1] == "BLOCK"

    # En módulos ya no debe existir BLOCK ni TORRE
    assert CatalogMatcher.match_tipo_modulo("BLOCK") is None
    assert CatalogMatcher.match_tipo_modulo("TORRE") is None
    assert CatalogMatcher.match_tipo_modulo("BLQ") is None


def test_record_577_corner_numbers_capture():
    """Caso ID 577: 'AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905 - CHICLAYO'
    Debe capturar la primera vía con número 106 y la segunda vía en esquina con número 905 (NO S/N).
    """
    raw_text = "AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905 - CHICLAYO"
    record = DireccionOrigen(id_licencia=577, emp_direccion=raw_text)
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = None
    parser = AIAddressParser(ollama_service=mock_ollama)

    dest = parser.parse(record)

    assert dest.es_procesado is True
    assert len(dest.vias) == 2

    # Vía 1: SAENZ PEÑA 106
    v1 = dest.vias[0]
    assert "SAENZ PEÑA" in v1["via_nombre"]
    assert v1["divi_numero"] == "106"
    assert v1["divi_orden"] == 1

    # Vía 2: GARCILAZO DE LA VEGA 905
    v2 = dest.vias[1]
    assert "GARCILAZO DE LA VEGA" in v2["via_nombre"]
    assert v2["divi_numero"] == "905"
    assert v2["divi_orden"] == 2


def test_record_606_piso_as_component_not_reference():
    """Caso ID 606: 'AV. JOSÉ BALTA N 259 - 3 PISO - CHICLAYO'
    '3 PISO' debe guardarse como componente catastral PISO (codi_id=4) y NO en referencia.
    """
    raw_text = "AV. JOSÉ BALTA N 259 - 3 PISO - CHICLAYO"
    record = DireccionOrigen(id_licencia=606, emp_direccion=raw_text)
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = None
    parser = AIAddressParser(ollama_service=mock_ollama)

    dest = parser.parse(record)

    assert dest.es_procesado is True
    assert len(dest.vias) >= 1
    assert "BALTA" in dest.vias[0]["via_nombre"]
    assert dest.vias[0]["divi_numero"] == "259"

    # Componente PISO presente
    pisos = [c for c in dest.componentes if c.get("codi_nombre") == "PISO"]
    assert len(pisos) == 1
    assert pisos[0]["diti_nombre"] == "3"
    assert pisos[0]["codi_id"] == 4
    assert dest.piso == "3"

    # Referencia limpia (NO contiene '3 PISO')
    assert dest.referencia is None or "PISO" not in dest.referencia.upper()


def test_record_618_condominio_sin_calle_block_dpto():
    """Caso ID 618: 'CONDOMINIO LOS PINOS DE LA PLATA BLOCK S DPTO. 102 - CHICLAYO'
    - NO debe inventar vía 'U. DE CHICLAYO' (vias debe ser []).
    - Debe asociar la zona oficial ('MULTIFAMILIAR LOS PINOS DE LA PLATA').
    - BLOCK S debe ser componente (codi_id=11).
    - DPTO 102 debe ser módulo (timo_id=2).
    - es_procesado debe ser True.
    """
    raw_text = "CONDOMINIO LOS PINOS DE LA PLATA BLOCK S DPTO. 102 - CHICLAYO"
    record = DireccionOrigen(id_licencia=618, emp_direccion=raw_text)
    mock_ollama = MagicMock()
    mock_ollama.parse_address_with_ai.return_value = None
    parser = AIAddressParser(ollama_service=mock_ollama)

    dest = parser.parse(record)

    assert dest.es_procesado is True
    # Sin vías inventadas
    assert len(dest.vias) == 0
    assert dest.nom_via is None

    # Zona oficial identificada
    assert dest.zona_id is not None
    assert "PINOS DE LA PLATA" in dest.nom_zona

    # Componente BLOCK
    blocks = [c for c in dest.componentes if c.get("codi_nombre") == "BLOCK"]
    assert len(blocks) == 1
    assert blocks[0]["diti_nombre"] == "S"
    assert blocks[0]["codi_id"] == 11
    assert dest.block == "S"

    # Módulo DEPARTAMENTO
    dptos = [m for m in dest.modulos if m.get("timo_nombre") == "DEPARTAMENTO"]
    assert len(dptos) == 1
    assert dptos[0]["ditm_nombre"] == "102"
    assert dptos[0]["timo_id"] == 2

    # Referencia limpia
    assert dest.referencia is None


def test_excel_export_headers_do_not_contain_technical_ids():
    """Las cabeceras de Excel/CSV no deben contener Via_Principal_ID, Via_Secundaria_ID, ni ID_Zona,
    y deben incluir la columna 'Block'.
    """
    sample_records = [
        {
            "id_licencia": 577,
            "raw_text": "AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905",
            "vias": [
                {"via_id": 1, "via_nombre": "SAENZ PEÑA", "divi_numero": "106", "divi_orden": 1},
                {"via_id": 2, "via_nombre": "GARCILAZO DE LA VEGA", "divi_numero": "905", "divi_orden": 2},
            ],
            "componentes": [
                {"codi_id": 11, "codi_nombre": "BLOCK", "diti_nombre": "S"},
                {"codi_id": 4, "codi_nombre": "PISO", "diti_nombre": "3"},
            ],
            "modulos": [
                {"timo_id": 2, "timo_nombre": "DEPARTAMENTO", "ditm_nombre": "102"},
            ],
            "zona_id": 115,
            "nom_zona": "LOS PINOS DE LA PLATA",
            "tipo_zona_name": "URBANIZACION",
            "es_procesado": True,
        }
    ]

    headers, meta = build_dynamic_export_headers(sample_records)

    # Validar ausencia de IDs técnicos de vías y zonas
    assert "Via_Principal_ID" not in headers
    assert "Via_Secundaria_ID" not in headers
    assert "ID_Zona" not in headers

    # Validar presencia de componentes estándar
    assert "Manzana" in headers
    assert "Lote" in headers
    assert "Sublote" in headers
    assert "Block" in headers
    assert "Piso" in headers

    # Validar exportación de fila
    row = extract_v2_export_row(sample_records[0], max_vias=meta["max_vias"], max_modulos=meta["max_modulos"])
    assert row["Block"] == "S"
    assert row["Piso"] == "3"
    assert row["Via_Principal_Nombre"] == "SAENZ PEÑA"
    assert row["Via_Principal_Numero"] == "106"
    assert row["Via_Secundaria_Nombre"] == "GARCILAZO DE LA VEGA"
    assert row["Via_Secundaria_Numero"] == "905"

    # Probar generación de buffers Excel y CSV
    excel_buf = generate_excel_report(sample_records)
    assert excel_buf is not None and excel_buf.getbuffer().nbytes > 0

    csv_buf = generate_csv_report(sample_records)
    csv_text = csv_buf.getvalue().decode("utf-8-sig")
    assert "Via_Principal_ID" not in csv_text
    assert "ID_Zona" not in csv_text
    assert "Block" in csv_text
    assert "Piso" in csv_text


def test_json_report_includes_block_and_piso():
    """El reporte JSON debe exponer block y piso tanto planos como dentro de catastro."""
    sample_records = [
        {
            "id_licencia": 618,
            "raw_text": "CONDOMINIO LOS PINOS DE LA PLATA BLOCK S DPTO. 102",
            "nom_zona": "LOS PINOS DE LA PLATA",
            "componentes": [
                {"codi_id": 11, "codi_nombre": "BLOCK", "diti_nombre": "S"},
                {"codi_id": 4, "codi_nombre": "PISO", "diti_nombre": "2"},
            ],
            "modulos": [
                {"timo_id": 2, "timo_nombre": "DEPARTAMENTO", "ditm_nombre": "102"},
            ],
            "es_procesado": True,
        }
    ]

    import json
    buf = generate_json_report(sample_records)
    data = json.loads(buf.getvalue().decode("utf-8"))
    assert len(data["direcciones"]) == 1
    rec = data["direcciones"][0]

    assert rec["block"] == "S"
    assert rec["piso"] == "2"
    assert rec["catastro"]["block"] == "S"
    assert rec["catastro"]["piso"] == "2"
