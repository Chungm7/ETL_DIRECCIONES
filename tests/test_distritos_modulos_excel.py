"""Pruebas unitarias para corrección de distritos y zonas (no alucinar Cercado de Chiclayo),
desacoplamiento estricto de módulos vs sublote, detección de jurisdicción externa y fijación
de cabeceras (freeze panes) en Excel.
"""

import io
import openpyxl
import pytest
from unittest.mock import MagicMock

from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher
from src.transformers.ai_parser import AIAddressParser
from src.models.direccion_origen import DireccionOrigen
from src.ui.server import generate_excel_report


@pytest.fixture(autouse=True)
def setup_catalogs():
    """Recarga los catálogos en memoria antes de cada prueba para asegurar estado limpio."""
    CatalogManager.reload()
    CatalogMatcher.reset_defaults()


def test_city_stopwords_do_not_match_as_physical_zona():
    """Nombres de distritos y ciudades jamás deben homologarse como zonas urbanas."""
    assert CatalogMatcher.match_physical_zona("CHICLAYO") is None
    assert CatalogMatcher.match_physical_zona("PIMENTEL") is None
    assert CatalogMatcher.match_physical_zona("LAMBAYEQUE") is None
    assert CatalogMatcher.match_physical_zona("JOSE LEONARDO ORTIZ") is None
    assert CatalogMatcher.match_physical_zona("LA VICTORIA") is None
    assert CatalogMatcher.match_physical_zona("FERRENAFE") is None
    assert CatalogMatcher.match_physical_zona("PERU") is None

    # Candidatos difusos deben retornar vacío si el texto es un stopword distrital
    assert CatalogMatcher.find_zona_candidates("CHICLAYO") == []
    assert CatalogMatcher.find_zona_candidates("PIMENTEL") == []
    assert CatalogMatcher.find_zona_candidates("LA VICTORIA") == []


def test_chiclayo_suffix_never_assigns_cercado_de_chiclayo():
    """Direcciones que terminan o contienen '- CHICLAYO' nunca deben inventar 'CERCADO DE CHICLAYO'."""
    parser = AIAddressParser(ollama_service=None)

    cases = [
        ("CA. NICOLAS CUGLIEVAN N 110 - CHICLAYO", 206),
        ("CALLE ARICA N 1364  -  CHICLAYO", 199),
        ("CA. VICENTE DE LA VEGA N 1113 - CHICLAYO", 203),
        ("AV. LUIS GONZALES N 1292 - CHICLAYO", 212),
    ]

    for raw, id_lic in cases:
        rec = DireccionOrigen(id_licencia=id_lic, emp_direccion=raw)
        dest = parser.parse(rec)

        # La zona nunca debe ser CERCADO DE CHICLAYO
        assert dest.nom_zona != "CERCADO DE CHICLAYO", f"Falso positivo en nom_zona para: {raw}"
        assert dest.zona_id != 148, f"Falso positivo en zona_id para: {raw}"
        # La dirección debe ser válida y normalizada con su vía y número
        assert dest.es_procesado is True, f"Debe normalizar vía para: {raw}"
        assert dest.nom_via is not None, f"Debe identificar vía para: {raw}"
        assert dest.num_via is not None, f"Debe identificar número para: {raw}"


def test_explicit_cercado_is_accepted():
    """Cuando la palabra 'CERCADO' sí figura explícitamente en el texto, sí debe asignarse CERCADO DE CHICLAYO."""
    parser = AIAddressParser(ollama_service=None)

    cases = [
        ("CALLE SAN JOSE N 123 CERCADO DE CHICLAYO", 901),
        ("URB. CERCADO - BALTA 400", 902),
        ("CA. 7 DE ENERO 100 CERCADO", 903),
    ]

    for raw, id_lic in cases:
        rec = DireccionOrigen(id_licencia=id_lic, emp_direccion=raw)
        dest = parser.parse(rec)

        assert dest.nom_zona == "CERCADO DE CHICLAYO", f"Debe resolver CERCADO DE CHICLAYO para: {raw}"
        assert dest.zona_id == 148, f"Debe asignar ID 148 para: {raw}"
        assert dest.es_procesado is True, f"Debe ser procesado para: {raw}"


def test_external_district_is_observed():
    """Direcciones de otros distritos (Pimentel, JLO, La Victoria) sin zona en Chiclayo deben observarse."""
    parser = AIAddressParser(ollama_service=None)

    cases = [
        ("AV. BALTA N 120 - PIMENTEL", "Pimentel"),
        ("CA. GRAU 450 - JOSE LEONARDO ORTIZ", "José Leonardo Ortiz"),
        ("CALLE REAL 100 - LA VICTORIA", "La Victoria"),
        ("AV. CHICLAYO 500 - JLO", "José Leonardo Ortiz"),
    ]

    for raw, dist_esperado in cases:
        rec = DireccionOrigen(id_licencia=888, emp_direccion=raw)
        dest = parser.parse(rec)

        assert dest.es_procesado is False, f"Debe ser observada por jurisdicción externa: {raw}"
        assert dest.observacion is not None, f"Debe contener motivo para: {raw}"
        assert "jurisdicción distrital externa" in dest.observacion.lower(), (
            f"El motivo debe señalar jurisdicción distrital externa para '{raw}'. Obtenido: '{dest.observacion}'"
        )
        assert dist_esperado.lower() in dest.observacion.lower(), (
            f"El motivo debe mencionar el distrito '{dist_esperado}'. Obtenido: '{dest.observacion}'"
        )


def test_interior_module_is_not_sublote():
    """Los módulos (interiores, tiendas, departamentos) jamás deben colocarse en slote."""
    parser = AIAddressParser(ollama_service=None)

    cases = [
        ("AV. JOSÉ BALTA N 1400 - INT. 17-19 2 PISO - CHICLAYO", "INTERIOR"),
        ("CA. AREQUIPA NORTE N 181 INT. 99 - CHICLAYO", "INTERIOR"),
        ("CA. VICENTE DE LA VEGA N 800 TIENDA N 02 - CHICLAYO", "TIENDA"),
        ("CA. SAN JOSE 123 INT. 1A", "INTERIOR"),
    ]

    for raw, expected_mod_type in cases:
        rec = DireccionOrigen(id_licencia=777, emp_direccion=raw)
        dest = parser.parse(rec)

        # slote debe ser estrictamente None (no debe contener INT ni TIENDA)
        assert dest.slote is None, f"slote debe ser None para: {raw}, pero se obtuvo '{dest.slote}'"
        # modulos debe contener la relación correspondiente
        assert len(dest.modulos) >= 1, f"Debe extraer al menos un módulo para: {raw}"
        assert any(m["timo_nombre"] == expected_mod_type for m in dest.modulos), (
            f"Debe contener un módulo de tipo '{expected_mod_type}'. Obtenido: {dest.modulos}"
        )


def test_excel_export_freezes_header_row():
    """El reporte exportado a Excel (.xlsx) debe inmovilizar la fila 1 de encabezados (freeze_panes = 'A2')."""
    records = [
        {
            "id_licencia": 101,
            "raw_text": "CA. SAN JOSE 123",
            "nom_via": "SAN JOSE",
            "num_via": "123",
            "nom_zona": None,
            "manzana": None,
            "lote": None,
            "slote": None,
            "block": None,
            "piso": None,
            "modulos": [],
            "es_procesado": True,
            "observacion": None,
            "metodo": "IA",
        },
        {
            "id_licencia": 102,
            "raw_text": "AV. BALTA N 120 - PIMENTEL",
            "nom_via": "JOSE BALTA",
            "num_via": "120",
            "nom_zona": None,
            "manzana": None,
            "lote": None,
            "slote": None,
            "block": None,
            "piso": None,
            "modulos": [],
            "es_procesado": False,
            "observacion": "Dirección con jurisdicción distrital externa (Pimentel): No corresponde al catastro urbano del distrito de Chiclayo.",
            "metodo": "Heurístico",
        },
    ]

    excel_io = generate_excel_report(records)
    assert isinstance(excel_io, io.BytesIO)
    wb = openpyxl.load_workbook(excel_io)
    ws = wb.active
    assert ws is not None
    assert ws.freeze_panes == "A2", f"freeze_panes debe ser 'A2', pero se obtuvo '{ws.freeze_panes}'"


def test_salvador_allende_santa_rosa_normalizes_cleanly():
    """ID 221: CA. SALVADOR ALLENDE N 321 PP.JJ. SANTA ROSA - CHICLAYO debe normalizarse con éxito.
    Nunca debe ser observada por 'jurisdicción distrital externa' ni por falta de componentes.
    """
    parser = AIAddressParser(ollama_service=None)
    rec = DireccionOrigen(
        id_licencia=221,
        emp_direccion="CA. SALVADOR ALLENDE N 321 PP.JJ. SANTA ROSA - CHICLAYO "
    )
    dest = parser.parse(rec)

    assert dest.es_procesado is True, f"ID 221 debe ser exitosa, pero fue observada: {dest.observacion}"
    assert dest.nom_via == "SALVADOR ALLENDE"
    assert dest.num_via == "321"
    assert dest.nom_zona == "SANTA ROSA DE LIMA"
    assert dest.zona_id == 44
    assert len(dest.vias) == 1
    assert dest.vias[0]["via_id"] == 353
    assert dest.observacion is None


def test_av_jose_leonardo_ortiz_chiclayo_is_not_external_district():
    """ID 366: AV. JOSE LEONARDO ORTIZ N 118 - CHICLAYO es una avenida oficial en Chiclayo (ID 2863).
    No debe confundirse con el distrito de JLO ni observarse como jurisdicción externa.
    """
    parser = AIAddressParser(ollama_service=None)
    rec = DireccionOrigen(
        id_licencia=366,
        emp_direccion="AV. JOSE LEONARDO ORTIZ N 118 - CHICLAYO "
    )
    dest = parser.parse(rec)

    assert dest.es_procesado is True, f"ID 366 debe normalizarse, pero fue observada: {dest.observacion}"
    assert dest.nom_via == "JOSÉ LEONARDO ORTIZ"
    assert dest.num_via == "118"
    assert len(dest.vias) == 1
    assert dest.vias[0]["via_id"] == 2863
    assert dest.observacion is None


def test_predio_mz_lt_without_via_normalizes():
    """ID 312 y 302: Lotes prediales urbanos con Mz/Lt y Zona confirmada deben normalizarse."""
    parser = AIAddressParser(ollama_service=None)

    # Caso 1: Miraflores II Etapa
    rec_312 = DireccionOrigen(
        id_licencia=312,
        emp_direccion="MZ. A LOTE 09 URB. MIRAFLORES II ETAPA - CHICLAYO "
    )
    dest_312 = parser.parse(rec_312)
    assert dest_312.es_procesado is True, f"ID 312 debe ser exitosa: {dest_312.observacion}"
    assert dest_312.nom_zona == "MIRAFLORES II ETAPA"
    assert dest_312.manzana == "A"
    assert dest_312.lote == "09"

    # Caso 2: Fanny Abanto Calle (el apellido Calle no debe convertirse en nom_via = 'MZ Q')
    rec_302 = DireccionOrigen(
        id_licencia=302,
        emp_direccion="PP.JJ. FANNY ABANTO CALLE MZ. Q  LT 04 - CHICLAYO"
    )
    dest_302 = parser.parse(rec_302)
    assert dest_302.es_procesado is True, f"ID 302 debe ser exitosa: {dest_302.observacion}"
    assert dest_302.nom_zona == "FANNY ABANTO CALLE"
    assert dest_302.manzana == "Q"
    assert dest_302.lote == "04"
    assert dest_302.nom_via is None


def test_confusing_records_remain_observed_with_clear_diagnosis():
    """Direcciones ininteligibles, confusas o sin datos mínimos deben mantenerse observadas con diagnóstico claro."""
    parser = AIAddressParser(ollama_service=None)

    # 1. Dirección incompleta (vía sin número y sin predio)
    rec_inc = DireccionOrigen(id_licencia=991, emp_direccion="CALLE ELIAS AGUIRRE - CHICLAYO")
    dest_inc = parser.parse(rec_inc)
    assert dest_inc.es_procesado is False
    assert "incompleta" in dest_inc.observacion.lower()
    assert "numeración" in dest_inc.observacion.lower() or "número" in dest_inc.observacion.lower()

    # 2. Vía inexistente / no identificada
    rec_inv = DireccionOrigen(id_licencia=992, emp_direccion="CA. ARTERIA INEXISTENTE N 999 - CHICLAYO")
    dest_inv = parser.parse(rec_inv)
    assert dest_inv.es_procesado is False
    assert "no figura" in dest_inv.observacion.lower() or "no identificada" in dest_inv.observacion.lower()

