"""Pruebas unitarias para la arquitectura relacional V2 de normalización MPCH.

Valida:
1. Multi-vías (Esquinas e intersecciones viales)
2. Normalización de zonas con máxima coherencia (ej. 9 de Octubre -> UPIS)
3. Mapeo estricto de H.U. (Habilitación Urbana) -> Urbanización (28 tipos oficiales)
4. Módulos inmobiliarios (Interior, Dpto, Stand, Puerta)
5. Componentes catastrales urbanos y rurales (Manzana, Lote, Piso, etc.)
6. Confinamiento de referencias a hitos espaciales/comerciales
7. Exportación JSON estructurada V2
8. Persistencia y carga relacional en tb_xxx con dire_id
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.models.catalogos import (
    TipoVia,
    Via,
    TipoZona,
    Zona,
    ComponenteDireccion,
    TipoModulo,
)
from src.models.direccion_destino import DireccionDestino
from src.models.direccion_origen import DireccionOrigen
from src.models.llm_schemas import (
    OllamaAddressExtraction,
    ExtractedVia,
    ExtractedComponente,
    ExtractedModulo,
)
from src.transformers.ai_parser import AIAddressParser
from src.transformers.catalog_matcher import CatalogMatcher
from src.loaders.db_loader import DatabaseLoader
from src.ui.server import generate_json_report


class TestV2CatalogModels:
    """Valida los modelos de catálogo institucional con nomenclatura tb_."""

    def test_tipo_via_model(self):
        tv = TipoVia(tivi_id=1, tivi_nombre="AVENIDA", tivi_abreviatura="AV.", tivi_estado="ACT")
        assert tv.tivi_id == 1
        assert tv.id_tipo_via == 1
        assert tv.nombre_tipo_via == "AVENIDA"

    def test_via_model(self):
        v = Via(via_id=10, tivi_id=1, via_nombre="BALTA", via_estado="ACT")
        assert v.via_id == 10
        assert v.id_via == 10
        assert v.nom_via == "BALTA"

    def test_tipo_zona_model(self):
        tz = TipoZona(tizo_id=6, tizo_nombre="URBANIZACION", tizo_abreviatura="URB.", tizo_estado="ACT")
        assert tz.tizo_id == 6
        assert tz.id_tipo_zona == 6
        assert tz.nombre_tipo_zona == "URBANIZACION"

    def test_componente_direccion_model(self):
        cd = ComponenteDireccion(codi_id=1, codi_nombre="MANZANA", codi_es_urbano=True, codi_estado="ACT")
        assert cd.codi_id == 1
        assert cd.codi_nombre == "MANZANA"
        assert cd.codi_es_urbano is True

    def test_tipo_modulo_model(self):
        tm = TipoModulo(timo_id=1, timo_nombre="INTERIOR", timo_estado="ACT")
        assert tm.timo_id == 1
        assert tm.timo_nombre == "INTERIOR"


class TestV2CatalogMatcher:
    """Valida la resolución canónica de catálogos V2."""

    def test_hu_maps_to_urbanizacion(self):
        """Verifica que H.U. o HABILITACION URBANA mapea canónicamente al tipo 6 (URBANIZACION)."""
        id_tz = CatalogMatcher.match_tipo_zona("H.U.")
        assert id_tz == 6
        id_tz_full = CatalogMatcher.match_tipo_zona("HABILITACION URBANA")
        assert id_tz_full == 6

    def test_9_de_octubre_zone_coherence(self):
        """Verifica que 'URB. 9 DE OCTUBRE' se asocia a la zona oficial 9 DE OCTUBRE."""
        # En el catálogo oficial de Chiclayo, 9 de Octubre tiene id_zona 60
        match_res = CatalogMatcher.match_physical_zona("9 DE OCTUBRE")
        assert match_res is not None
        assert "9 DE OCTUBRE" in match_res["nom_zona"].upper()

    def test_match_componente(self):
        """Verifica la resolución de componentes catastrales."""
        assert CatalogMatcher.match_componente("MZ")[0] == 1
        assert CatalogMatcher.match_componente("MANZANA")[0] == 1
        assert CatalogMatcher.match_componente("LT")[0] == 2
        assert CatalogMatcher.match_componente("LOTE")[0] == 2
        assert CatalogMatcher.match_componente("PISO")[0] == 4
        assert CatalogMatcher.match_componente("PREDIO")[0] == 5
        assert CatalogMatcher.match_componente("VALLE")[0] == 6

    def test_match_tipo_modulo(self):
        """Verifica la resolución de módulos inmobiliarios."""
        assert CatalogMatcher.match_tipo_modulo("INT")[0] == 1
        assert CatalogMatcher.match_tipo_modulo("INTERIOR")[0] == 1
        assert CatalogMatcher.match_tipo_modulo("DPTO")[0] == 2
        assert CatalogMatcher.match_tipo_modulo("DEPARTAMENTO")[0] == 2
        assert CatalogMatcher.match_tipo_modulo("PTA")[0] == 3
        assert CatalogMatcher.match_tipo_modulo("PUERTA")[0] == 3
        assert CatalogMatcher.match_tipo_modulo("STAND")[0] == 4
        assert CatalogMatcher.match_tipo_modulo("TIENDA")[0] == 5
        assert CatalogMatcher.match_tipo_modulo("BLOCK")[0] == 7


class TestV2AIParserAndDestino:
    """Valida la extracción estructurada con IA y armado de entidades DireccionDestino."""

    def test_multi_via_corner_parsing(self):
        """Verifica que una dirección en esquina genera múltiples vías en tb_direccion_via."""
        parser = AIAddressParser()
        parser.model_inference_active = False  # Modo defensivo / fallback

        # Simular extracción de IA con esquina
        fake_llm = OllamaAddressExtraction(
            vias=[
                ExtractedVia(tipo_via="AVENIDA", nombre="JOSE BALTA", numero="102", orden=1),
                ExtractedVia(tipo_via="CALLE", nombre="LUIS GONZALES", numero="801", orden=2),
            ],
            zona_nombre="CENTRO",
            tipo_zona="URBANIZACION",
            componentes=[
                ExtractedComponente(nombre="PISO", valor="2"),
            ],
            modulos=[
                ExtractedModulo(tipo_modulo="OFICINA", valor="204"),
            ],
            referencia="FRENTE AL PARQUE PRINCIPAL",
            es_esquina=True,
        )

        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = fake_llm
        parser = AIAddressParser(ollama_service=mock_ollama)

        origen = DireccionOrigen(
            id_licencia=1001,
            emp_direccion="AV BALTA 102 CON LUIS GONZALES 801 PISO 2 OF 204 FRENTE AL PARQUE",
        )
        dest = parser.parse(origen)

        assert dest.id_licencia == 1001
        assert len(dest.vias) == 2
        assert dest.vias[0]["divi_numero"] == "102"
        assert dest.vias[1]["divi_numero"] == "801"
        assert dest.vias[0]["divi_orden"] == 1
        assert dest.vias[1]["divi_orden"] == 2

        # Módulo no debe estar en referencia
        assert len(dest.modulos) == 1
        assert dest.modulos[0]["timo_nombre"] == "OFICINA"
        assert dest.modulos[0]["ditm_nombre"] == "204"
        assert "OFICINA" not in (dest.dire_referencia or "")
        assert "PARQUE" in (dest.dire_referencia or "")

        # Componente piso
        assert len(dest.componentes) == 1
        assert dest.componentes[0]["codi_nombre"] == "PISO"
        assert dest.componentes[0]["diti_nombre"] == "2"

    def test_modules_not_in_reference(self):
        """Verifica que módulos como Stand, Interior, Dpto se confinan a tb_direccion_tipo_modulo."""
        fake_llm = OllamaAddressExtraction(
            vias=[ExtractedVia(tipo_via="CALLE", nombre="SAN JOSE", numero="550")],
            modulos=[
                ExtractedModulo(tipo_modulo="STAND", valor="12"),
                ExtractedModulo(tipo_modulo="INTERIOR", valor="B"),
            ],
            referencia="STAND 12 INT B CERCA A REAL PLAZA",
        )

        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = fake_llm
        parser = AIAddressParser(ollama_service=mock_ollama)

        origen = DireccionOrigen(id_licencia=1002, emp_direccion="CA SAN JOSE 550 STAND 12 INT B")
        dest = parser.parse(origen)

        assert len(dest.modulos) == 2
        # La referencia debe quedar limpia de los módulos
        assert "STAND" not in (dest.dire_referencia or "")
        assert "INT" not in (dest.dire_referencia or "")
        assert "REAL PLAZA" in (dest.dire_referencia or "")


class TestV2JsonExport:
    """Valida la generación de reportes JSON V2."""

    def test_generate_json_report(self):
        records = [
            {
                "id_licencia": 10,
                "raw_text": "AV BALTA 102 CON CA LUIS GONZALES 801",
                "dire_id": 501,
                "vias": [
                    {"via_id": 1, "via_nombre": "BALTA", "divi_numero": "102", "divi_orden": 1},
                    {"via_id": 2, "via_nombre": "LUIS GONZALES", "divi_numero": "801", "divi_orden": 2},
                ],
                "componentes": [
                    {"codi_id": 1, "codi_nombre": "MANZANA", "diti_nombre": "A"},
                ],
                "modulos": [
                    {"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": "4"},
                ],
                "dire_referencia": "FRENTE AL PARQUE",
                "es_procesado": True,
                "observacion": "Normalizado V2",
            }
        ]

        buf = generate_json_report(records)
        raw_str = buf.getvalue().decode("utf-8")
        parsed = json.loads(raw_str)

        assert parsed["metadata"]["version"] == "2.0"
        assert parsed["metadata"]["total_registros"] == 1
        assert len(parsed["direcciones"]) == 1
        dir_obj = parsed["direcciones"][0]
        assert dir_obj["dire_id"] == 501
        assert len(dir_obj["vias"]) == 2
        assert len(dir_obj["modulos"]) == 1
        assert len(dir_obj["componentes"]) == 1


class TestV2DatabaseLoader:
    """Valida la persistencia atómica en tablas relacionales V2."""

    def test_load_v2_success_record(self):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db._engine = True

        # Simular que tb_direccion retorna dire_id = 99
        mock_session.execute.return_value.scalar.return_value = 99

        loader = DatabaseLoader(db_service=mock_db, schema="public", table="tb_xxx")
        loader._has_tb_direccion = True
        loader._target_cols = {"xxxx_id", "dire_id", "xxxx_es_procesado", "xxxx_observacion_ia"}
        loader.col_id = "xxxx_id"
        loader.col_es_procesado = "xxxx_es_procesado"
        loader.col_observacion = "xxxx_observacion_ia"

        dest = DireccionDestino(
            id_licencia=55,
            zona_id=60,
            dire_referencia="FRENTE AL MALL",
            vias=[
                {"via_id": 101, "divi_numero": "200", "divi_orden": 1},
                {"via_id": 102, "divi_numero": "300", "divi_orden": 2},
            ],
            componentes=[
                {"codi_id": 1, "diti_nombre": "B"},
            ],
            modulos=[
                {"timo_id": 2, "ditm_nombre": "301"},
            ],
            es_procesado=True,
            observacion="Validado con éxito",
        )

        loaded = loader._load_v2([dest])
        assert loaded == 1
        assert dest.dire_id == 99

        # Verificar que se ejecutaron sentencias SQL (tb_direccion, vias, componentes, modulos, update tb_xxx)
        assert mock_session.execute.call_count >= 5

    def test_load_v2_observed_record(self):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db._engine = True

        loader = DatabaseLoader(db_service=mock_db, schema="public", table="tb_xxx")
        loader._has_tb_direccion = True
        loader._target_cols = {"xxxx_id", "dire_id", "xxxx_es_procesado", "xxxx_observacion_ia"}
        loader.col_id = "xxxx_id"
        loader.col_es_procesado = "xxxx_es_procesado"
        loader.col_observacion = "xxxx_observacion_ia"

        dest = DireccionDestino(
            id_licencia=56,
            es_procesado=False,
            observacion="Zona desconocida en Chiclayo",
        )

        loaded = loader._load_v2([dest])
        assert loaded == 1
        assert dest.dire_id is None
        assert mock_session.execute.call_count == 1
