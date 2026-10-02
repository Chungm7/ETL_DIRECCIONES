"""Pruebas de regresión y verificación para el aislamiento estricto de Módulos vs Sublote,
desglose de rangos (INT B-C, INT 17-19), auto-inversión de Vía/Zona y rescate de observaciones.
"""

import pytest
from src.models.direccion_origen import DireccionOrigen
from src.models.llm_schemas import OllamaAddressExtraction
from src.transformers.ai_parser import AIAddressParser
from src.transformers.text_cleaner import TextCleaner
from src.ui.server import extract_v2_export_row, generate_json_report


@pytest.fixture
def parser():
    return AIAddressParser(ollama_service=None)


def test_text_cleaner_glued_and_ordinal():
    """Verifica que TextCleaner despegue números y módulos y normalice símbolos ordinales Nª/Nº."""
    # Números y departamentos pegados
    t1 = TextCleaner.sanitize("CHICLAYO-ELIAS AGUIRRE00305DPTO. 201")
    assert "ELIAS AGUIRRE 305 DPTO" in t1 or "ELIAS AGUIRRE 00305 DPTO" in t1

    # Tienda pegada a número
    t2 = TextCleaner.sanitize("CHICLAYO-ARICA01127TIENDA 119")
    assert "ARICA 1127 TIENDA" in t2 or "ARICA 01127 TIENDA" in t2

    # Símbolo ordinal Nª
    t3 = TextCleaner.sanitize("CRISTOBAL COLON Nª 442")
    assert "N° 442" in t3

    # Manzana y lote pegados
    t4 = TextCleaner.sanitize("MIRAFLORES II ETAPA-JUDAMZ.LLOTE 11")
    assert "MZ L LOTE 11" in t4


def test_llm_schema_modulo_bc_isolation():
    """Verifica que normalize_input_keys en OllamaAddressExtraction desglose INT B-C y NO genere SUBLOTE."""
    data = {
        "vias": [{"nombre": "ALFREDO LAPOINT", "tipo_via": "CALLE", "numero": "838"}],
        "slote": "INT. B-C",
        "componentes": [],
        "modulos": [],
    }
    extracted = OllamaAddressExtraction(**data)

    # 1. No debe existir SUBLOTE en componentes
    assert not any(c.nombre == "SUBLOTE" for c in extracted.componentes)
    # 2. El campo slote debe quedar en None
    assert extracted.slote is None
    # 3. Debe desglosar dos módulos INTERIOR: B y C
    assert len(extracted.modulos) == 2
    vals = [m.valor for m in extracted.modulos]
    assert "B" in vals
    assert "C" in vals
    assert all(m.tipo_modulo == "INTERIOR" for m in extracted.modulos)


def test_llm_schema_modulo_numeric_range_and_piso():
    """Verifica que normalize_input_keys desglose INT. 17-19 y extraiga piso de referencia."""
    data = {
        "vias": [{"nombre": "JOSE BALTA", "tipo_via": "AVENIDA", "numero": "1400"}],
        "slote": "INT. 17-19",
        "referencia": "2 PISO",
        "componentes": [],
        "modulos": [],
    }
    extracted = OllamaAddressExtraction(**data)

    assert not any(c.nombre == "SUBLOTE" for c in extracted.componentes)
    assert extracted.slote is None
    assert len(extracted.modulos) == 2
    vals = [m.valor for m in extracted.modulos]
    assert "17" in vals
    assert "19" in vals

    # Piso debe extraerse a componentes como PISO: 2
    piso_comps = [c for c in extracted.componentes if c.nombre == "PISO"]
    assert len(piso_comps) == 1
    assert piso_comps[0].valor == "2"


def test_ai_parser_alfredo_lapoint_bc(parser):
    """Verifica el flujo completo de AIAddressParser para CA. ALFREDO LAPOINT N 838 INT. B-C."""
    rec = DireccionOrigen(
        id_licencia=248,
        emp_direccion="CA. ALFREDO LAPOINT N 838 INT. B-C  - CHICLAYO",
    )
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.nom_via == "ALFREDO LAPOINT"
    assert res.num_via == "838"

    # Componentes no debe tener SUBLOTE (módulos aislados a tb_direccion_tipo_modulo)
    assert not any(c.get("codi_nombre") == "SUBLOTE" for c in res.componentes)

    # Módulos debe tener B y C
    mod_vals = [m.get("ditm_nombre") for m in res.modulos]
    assert "B" in mod_vals
    assert "C" in mod_vals
    assert all(m.get("timo_id") == 1 for m in res.modulos)


def test_ai_parser_stand_not_in_sublote(parser):
    """Verifica que un stand nunca sea tratado como SUBLOTE en componentes."""
    rec = DireccionOrigen(
        id_licencia=205,
        emp_direccion="CA. 7 DE ENERO N 1659 STAND 81 - CHICLAYO",
    )
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.nom_via in ("SIETE DE ENERO", "7 DE ENERO")
    assert res.num_via == "1659"
    assert not any(c.get("codi_nombre") == "SUBLOTE" for c in res.componentes)

    # Módulo STAND 81
    assert any(m.get("timo_nombre") == "STAND" and m.get("ditm_nombre") == "81" for m in res.modulos)


def test_ai_parser_inverted_via_zona_cruz_esperanza(parser):
    """Verifica la auto-inversión de Vía y Zona en CRUZ DE LA ESPERANZA - SAN FRANCISCO DE ASIS."""
    rec = DireccionOrigen(
        id_licencia=1056,
        emp_direccion="CRUZ DE LA ESPERANZA-SAN FRANCISCO DE ASIS00229",
    )
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.nom_via == "SAN FRANCISCO DE ASIS"
    assert res.num_via == "229"
    assert res.nom_zona == "CRUZ DE LA ESPERANZA"
    assert res.observacion is None


def test_ai_parser_glued_elias_aguirre(parser):
    """Verifica la normalización de texto pegado: ELIAS AGUIRRE00305DPTO. 201."""
    rec = DireccionOrigen(
        id_licencia=767,
        emp_direccion="CHICLAYO-ELIAS AGUIRRE00305DPTO. 201",
    )
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.nom_via == "ELIAS AGUIRRE"
    assert res.num_via == "305"
    assert not any(c.get("codi_nombre") == "SUBLOTE" for c in res.componentes)
    assert any(m.get("timo_nombre") == "DEPARTAMENTO" and m.get("ditm_nombre") == "201" for m in res.modulos)


def test_ai_parser_noisy_zone_balta_not_observed(parser):
    """Verifica que números secundarios pegados como falsa zona (01440) no observen una vía oficial confirmada."""
    rec = DireccionOrigen(
        id_licencia=1267,
        emp_direccion="CHICLAYO-JOSE BALTA01420 01440",
    )
    res = parser.parse(rec)

    assert res.es_procesado is True
    assert res.nom_via == "JOSE BALTA"
    assert res.num_via in ("1420", "1420-1440")
    assert res.observacion is None


def test_export_row_clean_sublote():
    """Verifica que extract_v2_export_row y generate_json_report no filtren módulos hacia Sublote."""
    dummy_rec = {
        "id": 248,
        "id_licencia": 248,
        "dire_id": 50,
        "estado": "NORMALIZADO",
        "raw_text": "CA. ALFREDO LAPOINT N 838 INT. B-C  - CHICLAYO",
        "vias": [{"via_id": 260, "via_nombre": "ALFREDO LAPOINT", "divi_numero": "838", "tipo_via": 2}],
        "componentes": [],
        "modulos": [
            {"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": "B"},
            {"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": "C"},
        ],
        "slote": "INTERIOR B, INTERIOR C",  # Simula residuo legado
        "es_procesado": True,
    }

    row = extract_v2_export_row(dummy_rec)
    assert row["Sublote"] == ""
    assert row["Modulo_1_Valor"] == "B"
    assert row["Modulo_2_Valor"] == "C"

    # Verificación en JSON generado
    buf = generate_json_report([dummy_rec])
    import json
    data = json.loads(buf.getvalue().decode("utf-8"))
    reg = data["direcciones"][0]
    assert reg["slote"] is None
    assert reg["catastro"]["sublote"] is None
    assert not any(c.get("tipo_componente") == "SUBLOTE" for c in reg["componentes"])
    assert len(reg["modulos"]) == 2


def test_record_206_no_slt_in_export():
    """Verifica que el registro 206 (sin lote ni sublote ni modulo) no exporte 'slt' en modulos ni sublote."""
    rec = {
        "id": 206,
        "id_licencia": 206,
        "dire_id": 7,
        "estado": "NORMALIZADO",
        "raw_text": "CA. NICOLAS CUGLIEVAN N 110 - CHICLAYO",
        "vias": [{"via_id": 104, "via_nombre": "JUAN CUGLIEVAN", "divi_numero": "110", "tipo_via": 2}],
        "componentes": [],
        "modulos": [],
        "slote": "slt",  # Simula placeholder residual
        "es_procesado": True,
    }
    row = extract_v2_export_row(rec)
    assert row["Sublote"] == ""
    assert row["Tipo_Modulo"] == ""
    assert row["Numero_Modulo"] == ""
    assert row["Todos_Los_Modulos"] == ""


def test_llm_schema_sublote_placeholders_cleaned():
    """Verifica que OllamaAddressExtraction descarte placeholders comunes de sublote."""
    placeholders = ["slt", "SLT", "Sub LT.", "sub lt", "SLOTE", "SUB LOTE", "-", "N/A", "NO"]
    for ph in placeholders:
        data = {
            "vias": [{"nombre": "JUAN CUGLIEVAN", "tipo_via": "CALLE", "numero": "110"}],
            "slote": ph,
            "componentes": [{"nombre": "SUBLOTE", "valor": ph, "es_urbano": True}],
            "modulos": [],
        }
        ext = OllamaAddressExtraction(**data)
        assert ext.slote is None, f"Fallo para placeholder {ph}: se esperaba None pero fue {ext.slote}"
        assert not any(c.nombre == "SUBLOTE" for c in ext.componentes), f"Fallo para componente con {ph}"
        assert not any("SLT" in m.tipo_modulo.upper() for m in ext.modulos)

    # Sublote genuino si debe preservarse
    valid_data = {
        "vias": [{"nombre": "JUAN CUGLIEVAN", "tipo_via": "CALLE", "numero": "110"}],
        "slote": "Sub LT. 14",
        "componentes": [],
        "modulos": [],
    }
    valid_ext = OllamaAddressExtraction(**valid_data)
    assert valid_ext.slote == "14"
    assert any(c.nombre == "SUBLOTE" and c.valor == "14" for c in valid_ext.componentes)


def test_ai_parser_record_206_with_mock_ollama_slt():
    """Verifica el flujo integral de AIAddressParser para el registro 206 evitando falsos positivos de módulo por 'slt'."""
    from unittest.mock import MagicMock
    from src.services.ollama_service import OllamaService

    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.model_name = "qwen2.5:7b"
    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(**{
        "vias": [{"nombre": "JUAN CUGLIEVAN", "tipo_via": "CALLE", "numero": "110"}],
        "slote": "slt",
        "componentes": [],
        "modulos": [],
    })

    parser = AIAddressParser(ollama_service=mock_ollama)
    rec = DireccionOrigen(id_licencia=206, emp_direccion="CA. NICOLAS CUGLIEVAN N 110 - CHICLAYO")
    destino = parser.parse(rec)

    assert destino.modulos == []
    assert destino.slote is None
    assert not any(c.get("codi_nombre") == "SUBLOTE" for c in destino.componentes)

    row = extract_v2_export_row(destino.model_dump())
    assert row["Sublote"] == ""
    assert row["Tipo_Modulo"] == ""
    assert row["Numero_Modulo"] == ""
    assert row["Todos_Los_Modulos"] == ""

