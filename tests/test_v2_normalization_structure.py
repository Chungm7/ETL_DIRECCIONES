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
    """Valida los modelos de catálogo institucional con nomenclatura tb_ y estados discretos A/I/E."""

    def test_tipo_via_model(self):
        tv = TipoVia(tivi_id=1, tivi_nombre="AVENIDA", tivi_abreviatura="AV.", tivi_estado="A")
        assert tv.tivi_id == 1
        assert tv.id_tipo_via == 1
        assert tv.nombre_tipo_via == "AVENIDA"
        assert tv.tivi_estado == "A"

    def test_via_model(self):
        v = Via(via_id=10, tivi_id=1, via_nombre="BALTA", via_estado="A")
        assert v.via_id == 10
        assert v.id_via == 10
        assert v.nom_via == "BALTA"
        assert v.via_estado == "A"

    def test_tipo_zona_model(self):
        tz = TipoZona(tizo_id=6, tizo_nombre="URBANIZACION", tizo_abreviatura="URB.", tizo_estado="A")
        assert tz.tizo_id == 6
        assert tz.id_tipo_zona == 6
        assert tz.nombre_tipo_zona == "URBANIZACION"
        assert tz.tizo_estado == "A"

    def test_componente_direccion_model(self):
        cd = ComponenteDireccion(codi_id=1, codi_nombre="MANZANA", codi_es_urbano=True, codi_estado="A")
        assert cd.codi_id == 1
        assert cd.codi_nombre == "MANZANA"
        assert cd.codi_es_urbano is True
        assert cd.codi_estado == "A"

    def test_tipo_modulo_model(self):
        tm = TipoModulo(timo_id=1, timo_nombre="INTERIOR", timo_estado="A")
        assert tm.timo_id == 1
        assert tm.timo_nombre == "INTERIOR"
        assert tm.timo_estado == "A"


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

    def test_custom_physical_catalog_sync_and_lookup(self):
        """Verifica que las vías y zonas físicas de la BD se sincronicen y reconozcan por nombre e ID."""
        from src.catalogs.catalog_manager import CatalogManager

        # Registrar una vía custom y zona custom
        CatalogManager.register_custom_physical_via(via_id=9999, nom_via="VIA NUEVA TEST", tivi_id=2)
        CatalogManager.register_custom_physical_zona(zona_id=8888, nom_zona="URB NUEVA TEST", tizo_id=6)

        # Verificar lookup por ID
        assert CatalogMatcher.get_physical_via_name(9999) == "VIA NUEVA TEST"
        assert CatalogMatcher.get_physical_zona_name(8888) == "URB NUEVA TEST"

        # Verificar matching
        match_via = CatalogMatcher.match_physical_via("VIA NUEVA TEST")
        assert match_via is not None
        assert match_via["id"] == 9999

        match_zona = CatalogMatcher.match_physical_zona("URB NUEVA TEST")
        assert match_zona is not None
        assert match_zona["id"] == 8888

    def test_multi_module_splitting_in_parser(self):
        """Verifica que direcciones con múltiples interiores (ej. INT. 1, 2 Y 3) se desglosen en registros independientes de modulos."""
        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = None
        parser = AIAddressParser(mock_ollama)

        orig = DireccionOrigen(
            id_licencia=888,
            emp_direccion="URB. SANTA VICTORIA CA. PACASMAYO 147 - INT. 1, 2 Y 3",
        )
        dest = parser.parse(orig)
        assert dest.es_procesado is True
        assert len(dest.modulos) == 3
        assert [m["ditm_nombre"] for m in dest.modulos] == ["1", "2", "3"]
        assert all(m["timo_nombre"] == "INTERIOR" for m in dest.modulos)

    def test_multi_via_corner_parsing(self):
        """Verifica que intersecciones de vías se asocien en la lista vias con orden 1 y 2."""
        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = None
        parser = AIAddressParser(mock_ollama)

        orig = DireccionOrigen(
            id_licencia=889,
            emp_direccion="CALLE SAN JOSE 102 CON AV. LUIS GONZALES 801",
        )
        dest = parser.parse(orig)
        assert dest.es_procesado is True
        assert len(dest.vias) == 2
        assert dest.vias[0]["via_nombre"] == "SAN JOSE"
        assert dest.vias[0]["divi_orden"] == 1
        assert dest.vias[1]["via_nombre"] == "LUIS GONZALES"
        assert dest.vias[1]["divi_orden"] == 2

    def test_db_loader_supports_multiple_interiors_same_timo_id(self):
        """Verifica que DatabaseLoader persista múltiples módulos con el mismo timo_id (ej. Interior 1 e Interior 2) gracias a la PK compuesta (dire_id, timo_id, ditm_nombre)."""
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db._engine = True
        mock_session.execute.return_value.scalar.return_value = 999

        loader = DatabaseLoader(db_service=mock_db, schema="public", table="tb_xxx")
        loader._has_tb_direccion = True
        loader._target_cols = {"xxxx_id", "dire_id", "xxxx_es_procesado", "xxxx_observacion_ia"}
        loader.col_id = "xxxx_id"
        loader.col_es_procesado = "xxxx_es_procesado"
        loader.col_observacion = "xxxx_observacion_ia"

        dest = DireccionDestino(
            id_licencia=999,
            zona_id=60,
            vias=[{"via_id": 101, "divi_numero": "200", "divi_orden": 1}],
            modulos=[
                {"timo_id": 1, "ditm_nombre": "1"},
                {"timo_id": 1, "ditm_nombre": "2"},
                {"timo_id": 1, "ditm_nombre": "3"},
            ],
            es_procesado=True,
        )
        loaded = loader._load_v2([dest])
        assert loaded == 1
        modulo_sql_calls = [
            call for call in mock_session.execute.call_args_list
            if len(call.args) > 0 and "tb_direccion_tipo_modulo" in str(call.args[0])
        ]
        assert len(modulo_sql_calls) == 3
        ditm_nombres = [call.args[1]["ditm_nombre"] for call in modulo_sql_calls]
        assert ditm_nombres == ["1", "2", "3"]
        assert all(call.args[1]["ditm_estado"] == "A" for call in modulo_sql_calls)

    def test_extracted_modulo_bracket_and_list_sanitization(self):
        """Verifica que ExtractedModulo limpie automáticamente formatos de lista serializada como ['B', 'C'] o listas reales."""
        # 1. String con formato de lista de Python
        m1 = ExtractedModulo(tipo_modulo="INTERIOR", valor="['B', 'C']")
        assert m1.valor == "B, C"

        # 2. Lista nativa de Python
        m2 = ExtractedModulo(tipo_modulo="INTERIOR", valor=["B", "C"])
        assert m2.valor == "B, C"

        # 3. String con corchetes aislados
        m3 = ExtractedModulo(tipo_modulo="INTERIOR", valor="['104']")
        assert m3.valor == "104"

    def test_ai_parser_multiple_interiors_without_brackets(self):
        """Verifica que direcciones con múltiples interiores en letras (ej. INT-B - C) se separen limpiamente sin corchetes."""
        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="ALFREDO LAPOINT",
            num_via="838",
            modulos=[ExtractedModulo(tipo_modulo="INTERIOR", valor="['B', 'C']")],
        )
        parser = AIAddressParser(mock_ollama)

        orig = DireccionOrigen(
            id_licencia=248,
            emp_direccion="CA. ALFREDO LAPOINT N 838 INT-B - C - CHICLAYO",
        )
        dest = parser.parse(orig)
        assert dest.es_procesado is True
        assert len(dest.modulos) == 2
        assert [m["ditm_nombre"] for m in dest.modulos] == ["B", "C"]
        assert all("[" not in m["ditm_nombre"] and "'" not in m["ditm_nombre"] for m in dest.modulos)

    def test_ai_parser_tienda_number_not_n(self):
        """Verifica que 'TDA. N 2' capture el número '2' y no la abreviatura 'N' como nombre de módulo."""
        mock_ollama = MagicMock()
        # Simula caso donde el LLM extrajo erróneamente 'N' como valor
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="SAN JOSE",
            num_via="100",
            modulos=[ExtractedModulo(tipo_modulo="TIENDA", valor="N")],
        )
        parser = AIAddressParser(mock_ollama)

        orig = DireccionOrigen(
            id_licencia=250,
            emp_direccion="CA. SAN JOSE N 100 TDA. N 2 - CHICLAYO",
        )
        dest = parser.parse(orig)
        assert dest.es_procesado is True
        assert len(dest.modulos) == 1
        assert dest.modulos[0]["ditm_nombre"] == "2"
        assert dest.modulos[0]["timo_nombre"] == "TIENDA"

    def test_db_service_ensure_modulo_pk_constraint_migration(self):
        """Verifica que ensure_modulo_pk_constraint ejecute la migración de PK cuando ditm_nombre no está en la PK."""
        from src.services.db_service import DatabaseService

        mock_db = DatabaseService()
        mock_session = MagicMock()
        mock_db.get_session = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db._engine = True

        # Simular que la tabla existe y su PK actual solo contiene dire_id y timo_id
        mock_session.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=1)),  # Table exists
            MagicMock(fetchall=MagicMock(return_value=[("dire_id",), ("timo_id",)])),  # Old PK columns
            MagicMock(),  # DELETE deduplicate
            MagicMock(fetchall=MagicMock(return_value=[("pk_tb_direccion_tipo_modulo",)])),  # Constraint names
            MagicMock(),  # DROP CONSTRAINT
            MagicMock(),  # ADD CONSTRAINT
            MagicMock(),  # ALTER COLUMN ditm_estado
            MagicMock(),  # CREATE UNIQUE INDEX
        ]

        migrated = mock_db.ensure_modulo_pk_constraint("sc_migracion_direcciones")
        assert migrated is True
        # Verificar que se ejecutó el DROP y ADD constraint
        executed_sqls = [str(call.args[0]) for call in mock_session.execute.call_args_list if len(call.args) > 0]
        assert any("DROP CONSTRAINT IF EXISTS \"pk_tb_direccion_tipo_modulo\"" in s for s in executed_sqls)
        assert any("ADD CONSTRAINT pk_tb_direccion_tipo_modulo PRIMARY KEY (dire_id, timo_id, ditm_nombre)" in s for s in executed_sqls)

    def test_direccion_destino_estado_varchar3(self):
        """Verifica que DireccionDestino acepte 'A' y 'ACT' sin exceder max_length=3."""
        d1 = DireccionDestino(id_licencia=1)
        assert d1.dire_estado == "A"

        d2 = DireccionDestino(id_licencia=2, dire_estado="ACT")
        assert d2.dire_estado == "ACT"

        # Validar rechazo de más de 3 caracteres
        with pytest.raises(Exception):
            DireccionDestino(id_licencia=3, dire_estado="ACTIVO")

    def test_db_service_ensure_estado_columns_varchar3(self):
        """Verifica que ensure_estado_columns_varchar3 amplíe columnas con longitud < 3."""
        from src.services.db_service import DatabaseService

        mock_db = DatabaseService()
        mock_session = MagicMock()
        mock_db.get_session = MagicMock()
        mock_db.get_session.return_value.__enter__.return_value = mock_session
        mock_db._engine = True
        mock_db.table_exists = MagicMock(return_value=True)

        # Simular que la primera tabla tiene longitud 1, las demás 3
        mock_session.execute.side_effect = [
            MagicMock(scalar=MagicMock(return_value=1)),  # length for tb_tipo_via.tivi_estado < 3
            MagicMock(fetchall=MagicMock(return_value=[("tb_tipo_via_tivi_estado_check",)])),  # old constraint
            MagicMock(),  # DROP CONSTRAINT
            MagicMock(),  # ALTER COLUMN TYPE VARCHAR(3)
            MagicMock(),  # ADD CONSTRAINT
        ] + [MagicMock(scalar=MagicMock(return_value=3)) for _ in range(9)]  # other 9 tables already 3

        result = mock_db.ensure_estado_columns_varchar3("sc_migracion_direcciones")
        assert result is True
        executed_sqls = [str(call.args[0]) for call in mock_session.execute.call_args_list if len(call.args) > 0]
        assert any("ALTER COLUMN \"tivi_estado\" TYPE VARCHAR(3)" in s for s in executed_sqls)

    def test_multiple_modules_slote_summary_exceeds_20_chars_without_validation_error(self):
        """Valida que direcciones con múltiples dependencias (como los 9 casos fallidos) no disparen ValidationError."""
        # 1. Caso ID 261: 2 Tiendas (27 caracteres)
        d_tiendas = DireccionDestino(
            id_licencia=261,
            modulos=[
                {"timo_id": 5, "timo_nombre": "TIENDA", "ditm_nombre": "METRO"},
                {"timo_id": 5, "timo_nombre": "TIENDA", "ditm_nombre": "LOCAL"},
            ],
        )
        assert d_tiendas.slote == "TIENDA METRO, TIENDA LOCAL"
        assert len(d_tiendas.slote) == 26
        assert len(d_tiendas.slote) > 20

        # 2. Caso ID 359: 2 Interiores (24 caracteres)
        d_interiores = DireccionDestino(
            id_licencia=359,
            modulos=[
                {"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": "308"},
                {"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": "A"},
            ],
        )
        assert d_interiores.slote == "INTERIOR 308, INTERIOR A"
        assert len(d_interiores.slote) == 24

        # 3. Caso ID 1013: 6 Oficinas (76 caracteres)
        d_oficinas = DireccionDestino(
            id_licencia=1013,
            modulos=[
                {"timo_id": 6, "timo_nombre": "OFICINA", "ditm_nombre": str(i)}
                for i in range(204, 210)
            ],
        )
        assert "OFICINA 204" in d_oficinas.slote
        assert "OFICINA 209" in d_oficinas.slote
        assert len(d_oficinas.slote) == 76

    def test_slote_capped_safely_at_100_chars(self):
        """Valida que módulos excesivos que superen 100 caracteres se trunquen limpiamente sin error de validación."""
        d_extremo = DireccionDestino(
            id_licencia=9999,
            modulos=[
                {"timo_id": 6, "timo_nombre": "OFICINA", "ditm_nombre": str(i)}
                for i in range(100, 120)
            ],
        )
        assert len(d_extremo.slote) <= 100
        assert d_extremo.slote.startswith("OFICINA 100")


