"""Pruebas estructurales de los componentes del ETL, esquemas dinámicos y catálogos oficiales."""

import unittest
from unittest.mock import MagicMock, patch
from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino
from src.models.llm_schemas import OllamaAddressExtraction
from src.transformers.text_cleaner import TextCleaner
from src.transformers.catalog_matcher import CatalogMatcher
from src.transformers.ai_parser import AIAddressParser
from src.transformers.pipeline_transformer import PipelineTransformer
from src.services.db_service import DatabaseService
from src.services.ollama_service import OllamaService
from src.pipelines.etl_pipeline import ETLPipeline



class TestPipelineStructure(unittest.TestCase):
    """Pruebas unitarias de interfaces, modelos base, sincronización de catálogos y esquemas dinámicos."""

    def tearDown(self):
        """Restaura los valores por defecto del catálogo tras cada test."""
        CatalogMatcher.reset_defaults()

    def test_direccion_origen_model(self):
        """Verifica la inicialización del modelo de origen."""
        origen = DireccionOrigen(id_licencia=101, emp_direccion="CA. BALTA 123")
        self.assertEqual(origen.id_licencia, 101)
        self.assertFalse(origen.is_empty())

    def test_direccion_destino_model(self):
        """Verifica la inicialización del modelo destino normalizado."""
        destino = DireccionDestino(
            id_licencia=101,
            tipo_via=2,  # CALLE = 2
            nom_via="JOSE LEONARDO ORTIZ",
            num_via="450",
            tipo_zona=6,  # URBANIZACION = 6
            nom_zona="SANTA VICTORIA",
            manzana="A",
            lote="15",
        )
        self.assertEqual(destino.id_licencia, 101)
        self.assertEqual(destino.tipo_via, 2)
        self.assertEqual(destino.nom_via, "JOSE LEONARDO ORTIZ")

    def test_text_cleaner_sanitization(self):
        """Valida que TextCleaner limpie espacios y normalice mayúsculas."""
        raw = "   calle   balta   n°   520   \n"
        cleaned = TextCleaner.sanitize(raw)
        self.assertEqual(cleaned, "CALLE BALTA N° 520")

    def test_catalog_matcher_vias_oficiales(self):
        """Valida que CatalogMatcher mapee según el catálogo oficial por defecto:
        1: AVENIDA, 2: CALLE, 3: JIRON, 4: PASAJE, etc.
        """
        self.assertEqual(CatalogMatcher.match_tipo_via("AVENIDA"), 1)
        self.assertEqual(CatalogMatcher.match_tipo_via("AV."), 1)
        self.assertEqual(CatalogMatcher.match_tipo_via("CALLE"), 2)
        self.assertEqual(CatalogMatcher.match_tipo_via("CA."), 2)
        self.assertEqual(CatalogMatcher.match_tipo_via("JR"), 3)
        self.assertEqual(CatalogMatcher.match_tipo_via("PASAJE"), 4)
        self.assertEqual(CatalogMatcher.match_tipo_via("ALAMEDA"), 5)
        self.assertEqual(CatalogMatcher.match_tipo_via("CARRETERA"), 6)
        self.assertEqual(CatalogMatcher.match_tipo_via("PROLONGACION"), 7)
        self.assertEqual(CatalogMatcher.match_tipo_via("PASEO"), 8)
        self.assertEqual(CatalogMatcher.match_tipo_via("MALECON"), 9)
        self.assertEqual(CatalogMatcher.match_tipo_via("CAMINO"), 10)
        self.assertEqual(CatalogMatcher.match_tipo_via("PLAZA"), 11)
        self.assertEqual(CatalogMatcher.match_tipo_via("PLAZUELA"), 12)

    def test_catalog_matcher_zonas_oficiales(self):
        """Valida que CatalogMatcher mapee según el catálogo oficial de 28 zonas por defecto."""
        self.assertEqual(CatalogMatcher.match_tipo_zona("ASENTAMIENTO HUMANO"), 1)
        self.assertEqual(CatalogMatcher.match_tipo_zona("A.H."), 1)
        self.assertEqual(CatalogMatcher.match_tipo_zona("CONJUNTO RESIDENCIAL"), 4)
        self.assertEqual(CatalogMatcher.match_tipo_zona("PUEBLO JOVEN"), 5)
        self.assertEqual(CatalogMatcher.match_tipo_zona("P.J."), 5)
        self.assertEqual(CatalogMatcher.match_tipo_zona("URBANIZACION"), 6)
        self.assertEqual(CatalogMatcher.match_tipo_zona("URB."), 6)
        self.assertEqual(CatalogMatcher.match_tipo_zona("CERCADO"), 8)
        self.assertEqual(CatalogMatcher.match_tipo_zona("FUNDO"), 19)

    def test_ensure_catalogs_exist_when_not_existing(self):
        """Caso 1: Las tablas de catálogo NO existen en el esquema.
        El servicio debe crearlas y sembrar los 12 tipos de vía y 28 tipos de zona.
        """
        mock_session = MagicMock()
        # Simula que no existen las tablas (table_check.scalar() -> 0)
        # y que no hay registros iniciales (existing_rows -> [])
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.fetchall.return_value = []

        service = DatabaseService()
        service._engine = MagicMock()

        with patch.object(service, "get_session") as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            res = service.ensure_catalogs_exist(schema="schema_solo_tabla")

            self.assertIn("tipos_via", res)
            self.assertIn("tipos_zona", res)
            self.assertTrue(res["tipos_via"]["table_created"])
            self.assertEqual(res["tipos_via"]["existing_records"], 0)
            self.assertEqual(res["tipos_via"]["added_records"], 12)
            self.assertEqual(res["tipos_via"]["total_records"], 12)

            self.assertTrue(res["tipos_zona"]["table_created"])
            self.assertEqual(res["tipos_zona"]["added_records"], 28)

    def test_ensure_catalogs_column_abreviatura_added(self):
        """Caso 2: Las tablas existen pero falta la columna 'abreviatura'.
        El servicio debe ejecutar ALTER TABLE para agregarla y sembrar los datos faltantes.
        """
        mock_session = MagicMock()

        # Configurar respuestas para table_check (existe = 1) y col_check (abreviatura no existe = 0)
        def mock_execute_side_effect(sql_stmt, params=None):
            sql_str = str(sql_stmt)
            mock_res = MagicMock()
            if "information_schema.tables" in sql_str:
                mock_res.scalar.return_value = 1  # Tabla existe
            elif "column_name = 'abreviatura'" in sql_str:
                mock_res.scalar.return_value = 0  # Columna falta
            elif "SELECT" in sql_str and "FROM" in sql_str:
                mock_res.fetchall.return_value = []  # Sin filas
            else:
                mock_res.scalar.return_value = None
                mock_res.fetchall.return_value = []
            return mock_res

        mock_session.execute.side_effect = mock_execute_side_effect

        service = DatabaseService()
        service._engine = MagicMock()

        with patch.object(service, "get_session") as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            res = service.ensure_catalogs_exist(schema="schema_cat_vacios")

            self.assertFalse(res["tipos_via"]["table_created"])
            self.assertTrue(res["tipos_via"]["column_added"])
            self.assertEqual(res["tipos_via"]["existing_records"], 0)
            self.assertEqual(res["tipos_via"]["added_records"], 12)

    def test_ensure_catalogs_partial_records_non_duplication(self):
        """Caso 3: Las tablas tienen registros con IDs no canónicos (CALLE=1, AVENIDA=2).
        El servicio debe reasignar dichos registros al orden canónico del JSON (AVENIDA=1, CALLE=2)
        y completar las 9 vías restantes conservando el estándar oficial de 12 registros.
        """
        mock_session = MagicMock()

        def mock_execute_side_effect(sql_stmt, params=None):
            sql_str = str(sql_stmt)
            mock_res = MagicMock()
            if "information_schema.tables" in sql_str:
                mock_res.scalar.return_value = 1  # Existe
            elif "column_name = 'abreviatura'" in sql_str or (isinstance(params, dict) and params.get("table") in ("tipos_via", "tipos_zona")):
                mock_res.scalar.return_value = 1  # Ya tiene columna abreviatura
            elif (isinstance(params, dict) and params.get("col") in ("tipo_via", "tipo_zona")) or "column_name = :col" in sql_str:
                mock_res.scalar.return_value = 1  # Columna en direcciones existe
            elif "tipos_via" in sql_str and "SELECT" in sql_str:
                # 3 registros pre-existentes con IDs desalineados: CALLE=1, AVENIDA=2, JIRON=3
                mock_res.fetchall.return_value = [
                    (1, "CALLE"),
                    (2, "AVENIDA"),
                    (3, "JIRON"),
                ]
            elif "tipos_zona" in sql_str and "SELECT" in sql_str:
                # 3 registros pre-existentes: URBANIZACION=1, PUEBLO JOVEN=2, ASENTAMIENTO HUMANO=3
                mock_res.fetchall.return_value = [
                    (1, "URBANIZACION"),
                    (2, "PUEBLO JOVEN"),
                    (3, "ASENTAMIENTO HUMANO"),
                ]
            else:
                mock_res.scalar.return_value = 0
                mock_res.fetchall.return_value = []
                mock_res.rowcount = 5  # 5 filas reasignadas en direcciones_actual
            return mock_res

        mock_session.execute.side_effect = mock_execute_side_effect

        service = DatabaseService()
        service._engine = MagicMock()

        with patch.object(service, "get_session") as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            res = service.ensure_catalogs_exist(schema="schema_cat_parciales")

            # tipos_via: CALLE (era 1) y AVENIDA (era 2) se estandarizan a sus IDs canónicos (2 y 1)
            self.assertEqual(res["tipos_via"]["existing_records"], 3)
            self.assertEqual(res["tipos_via"]["remapped_records"], 2)
            self.assertEqual(res["tipos_via"]["added_records"], 9)
            self.assertEqual(res["tipos_via"]["total_records"], 12)
            self.assertEqual(res["tipos_via"]["fk_remapped_records"], 5)

            # tipos_zona: URBANIZACION (era 1->6), PUEBLO JOVEN (era 2->5), AH (era 3->1)
            self.assertEqual(res["tipos_zona"]["existing_records"], 3)
            self.assertEqual(res["tipos_zona"]["remapped_records"], 3)
            self.assertEqual(res["tipos_zona"]["added_records"], 25)
            self.assertEqual(res["tipos_zona"]["total_records"], 28)
            self.assertEqual(res["tipos_zona"]["fk_remapped_records"], 5)

    def test_catalog_matcher_sync_with_db_canonical_and_custom(self):
        """Verifica que CatalogMatcher.sync_with_db sincronice con los IDs canónicos estandarizados
        y registre dinámicamente tipos custom adicionales (ej. AUTOPISTA=13, SECTOR=29).
        """
        mock_session = MagicMock()

        def mock_execute_side_effect(sql_stmt, params=None):
            sql_str = str(sql_stmt)
            mock_res = MagicMock()
            if "tipos_via" in sql_str:
                # IDs canónicos (AVENIDA=1, CALLE=2) más un tipo custom nuevo (AUTOPISTA=13)
                mock_res.fetchall.return_value = [
                    (1, "AVENIDA"),
                    (2, "CALLE"),
                    (3, "JIRON"),
                    (13, "AUTOPISTA"),
                ]
            elif "tipos_zona" in sql_str:
                # IDs canónicos (AH=1, PJ=5, URB=6) más un tipo custom nuevo (SECTOR=29)
                mock_res.fetchall.return_value = [
                    (1, "ASENTAMIENTO HUMANO"),
                    (5, "PUEBLO JOVEN"),
                    (6, "URBANIZACION"),
                    (29, "SECTOR"),
                ]
            return mock_res

        mock_session.execute.side_effect = mock_execute_side_effect

        mock_db = MagicMock()
        mock_db._engine = MagicMock()
        mock_db.settings.target_table_tipo_via = "tipos_via"
        mock_db.settings.target_table_tipo_zona = "tipos_zona"
        mock_db.get_session.return_value.__enter__.return_value = mock_session

        # Sincronizamos con el esquema
        CatalogMatcher.sync_with_db(mock_db, schema="schema_cat_parciales")

        # Verifica que los IDs canónicos se mantengan en todos los esquemas
        self.assertEqual(CatalogMatcher.match_tipo_via("AVENIDA"), 1)
        self.assertEqual(CatalogMatcher.match_tipo_via("AV."), 1)
        self.assertEqual(CatalogMatcher.match_tipo_via("CALLE"), 2)
        self.assertEqual(CatalogMatcher.match_tipo_via("CA."), 2)
        self.assertEqual(CatalogMatcher.match_tipo_via("JR."), 3)
        self.assertEqual(CatalogMatcher.match_tipo_via("AUTOPISTA"), 13)

        # Zonas sincronizadas
        self.assertEqual(CatalogMatcher.match_tipo_zona("ASENTAMIENTO HUMANO"), 1)
        self.assertEqual(CatalogMatcher.match_tipo_zona("A.H."), 1)
        self.assertEqual(CatalogMatcher.match_tipo_zona("PUEBLO JOVEN"), 5)
        self.assertEqual(CatalogMatcher.match_tipo_zona("P.J."), 5)
        self.assertEqual(CatalogMatcher.match_tipo_zona("URBANIZACION"), 6)
        self.assertEqual(CatalogMatcher.match_tipo_zona("URB."), 6)
        self.assertEqual(CatalogMatcher.match_tipo_zona("SECTOR"), 29)

    def test_ensure_in_place_columns_mocked(self):
        """Valida que DatabaseService.ensure_in_place_columns altere la tabla y aplique FKs."""
        mock_session = MagicMock()
        service = DatabaseService()
        service._engine = MagicMock()

        with patch.object(service, "get_session") as mock_get_session:
            mock_get_session.return_value.__enter__.return_value = mock_session
            cols = service.ensure_in_place_columns(schema="public", table="direcciones_actual")

            self.assertIn("id_via", cols)
            self.assertIn("num_via", cols)
            self.assertIn("id_zona", cols)
            self.assertIn("slote", cols)
            self.assertIn("referencia", cols)
            self.assertIn("es_procesado", cols)
            self.assertIn("observacion", cols)
            self.assertEqual(len(cols), 9)
            self.assertEqual(mock_session.execute.call_count, 2)

    def test_etl_pipeline_in_place_execution(self):
        """Valida la ejecución del pipeline en su método único in-place."""
        mock_db = MagicMock()
        mock_db.ensure_catalogs_exist.return_value = {
            "tipos_via": {"table_created": False, "column_added": False, "existing_records": 12, "added_records": 0, "total_records": 12},
            "tipos_zona": {"table_created": False, "column_added": False, "existing_records": 28, "added_records": 0, "total_records": 28},
        }
        mock_db.ensure_in_place_columns.return_value = ["id_via", "num_via", "id_zona", "es_procesado", "observacion"]

        mock_extractor = MagicMock()
        mock_extractor.get_total_records.return_value = 1
        mock_extractor.extract_batch.return_value = [
            DireccionOrigen(id_licencia=55, emp_direccion="CA. BALTA 123")
        ]

        mock_loader = MagicMock()
        mock_loader.load_batch.return_value = 1

        pipeline = ETLPipeline(
            extractor=mock_extractor,
            loader=mock_loader,
            db_service=mock_db,
            batch_size=1,
            schema="public",
            table="direcciones_actual",
        )

        self.assertEqual(pipeline.mode, "in_place")
        summary = pipeline.run(max_records=1)

        self.assertEqual(summary.mode, "in_place")
        self.assertEqual(summary.total_records, 1)
        self.assertEqual(summary.successful_records, 1)
        self.assertEqual(summary.failed_records, 0)
        mock_db.ensure_catalogs_exist.assert_called_once()
        mock_db.ensure_in_place_columns.assert_called_once()

    def test_ai_parser_pure_ai_tagging(self):
        """Valida que AIAddressParser asigne 'IA (<modelo>)' si la inferencia fue 100% exitosa."""
        mock_ollama = MagicMock()
        mock_ollama.model_name = "patroclo-artesano-7b"
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="BALTA",
            num_via="520",
            tipo_zona_detectada="URBANIZACION",
            nom_zona="SANTA VICTORIA",
            manzana=None,
            lote=None,
            slote=None,
            confianza=0.98,
        )

        parser = AIAddressParser(ollama_service=mock_ollama)
        record = DireccionOrigen(id_licencia=1, emp_direccion="CALLE BALTA 520 URB SANTA VICTORIA")
        dest = parser.parse(record)

        self.assertEqual(dest.metodo_normalizacion, "IA (patroclo-artesano-7b)")
        self.assertIn("BALTA", dest.nom_via)
        self.assertEqual(dest.num_via, "520")
        self.assertTrue(dest.es_procesado)

    def test_ai_parser_hybrid_tagging(self):
        """Valida que AIAddressParser asigne 'Híbrido (IA + Heurística)' si la IA necesitó asistencia."""
        mock_ollama = MagicMock()
        mock_ollama.model_name = "patroclo-artesano-7b"
        # La IA no extrajo el interior/slote que estaba en el texto
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="BALTA",
            num_via="520",
            tipo_zona_detectada="URBANIZACION",
            nom_zona="SANTA VICTORIA",
            manzana=None,
            lote=None,
            slote=None,  # IA omitió el interior
            confianza=0.85,
        )

        parser = AIAddressParser(ollama_service=mock_ollama)
        # La dirección tiene un interior INT-2 que la heurística rescatará
        record = DireccionOrigen(id_licencia=2, emp_direccion="CALLE BALTA 520 INT-2 URB SANTA VICTORIA")
        dest = parser.parse(record)

        self.assertEqual(dest.metodo_normalizacion, "Híbrido (IA + Heurística)")
        self.assertEqual(dest.slote, "INT-2")
        self.assertTrue(dest.es_procesado)

    def test_ai_parser_fallback_heuristic_tagging(self):
        """Valida que AIAddressParser asigne 'Heurístico (Fallback - IA inactiva)' si Ollama falla."""
        mock_ollama = MagicMock()
        mock_ollama.model_name = "patroclo-artesano-7b"
        mock_ollama.parse_address_with_ai.return_value = None  # Simula IA apagada o caída

        parser = AIAddressParser(ollama_service=mock_ollama)
        record = DireccionOrigen(id_licencia=3, emp_direccion="AV. BALTA N° 520")
        dest = parser.parse(record)

        self.assertEqual(dest.metodo_normalizacion, "Heurístico (Fallback - IA inactiva)")
        self.assertIn("BALTA", dest.nom_via)
        self.assertEqual(dest.num_via, "520")
        self.assertTrue(dest.es_procesado)

    def test_pipeline_transformer_no_ai_tagging(self):
        """Valida que PipelineTransformer etiquete 'Directo (IA deshabilitada)' cuando use_ai=False."""
        transformer = PipelineTransformer(use_ai=False)
        record = DireccionOrigen(id_licencia=4, emp_direccion="CA. BALTA 123")
        dest = transformer.transform_record(record)

        self.assertEqual(dest.metodo_normalizacion, "Directo (IA deshabilitada)")

    def test_etl_pipeline_metrics_ai_and_heuristic(self):
        """Valida que ETLPipeline totalice correctamente los conteos de IA, Híbrido y Heurístico."""
        mock_db = MagicMock()
        mock_db.ensure_catalogs_exist.return_value = {
            "tipos_via": {"table_created": False, "column_added": False, "existing_records": 12, "added_records": 0, "total_records": 12},
            "tipos_zona": {"table_created": False, "column_added": False, "existing_records": 28, "added_records": 0, "total_records": 28},
        }
        mock_db.ensure_in_place_columns.return_value = ["tipo_via", "nom_via"]

        rec1 = DireccionOrigen(id_licencia=1, emp_direccion="CALLE BALTA 520")
        rec2 = DireccionOrigen(id_licencia=2, emp_direccion="AV. BOLOGNESI 100")

        mock_extractor = MagicMock()
        mock_extractor.get_total_records.return_value = 2
        mock_extractor.extract_batch.return_value = [rec1, rec2]

        dest1 = DireccionDestino(id_licencia=1, metodo_normalizacion="IA (patroclo-artesano-7b)")
        dest2 = DireccionDestino(id_licencia=2, metodo_normalizacion="Heurístico (Fallback - IA inactiva)")

        mock_transformer = MagicMock()
        mock_transformer.transform_record.side_effect = [dest1, dest2]

        mock_loader = MagicMock()
        mock_loader.load_batch.return_value = 1

        pipeline = ETLPipeline(
            extractor=mock_extractor,
            transformer=mock_transformer,
            loader=mock_loader,
            db_service=mock_db,
            batch_size=2,
            schema="public",
            table="direcciones_actual",
        )

        with patch("src.services.ollama_service.OllamaService.test_model_inference") as mock_test:
            mock_test.return_value = {"model_ready": True, "latency_seconds": 1.5, "error": None}
            summary = pipeline.run()

        self.assertEqual(summary.total_records, 2)
        self.assertEqual(summary.successful_records, 2)
        self.assertEqual(summary.ai_records, 1)
        self.assertEqual(summary.heuristic_records, 1)
        self.assertEqual(summary.hybrid_records, 0)

    def test_etl_pipeline_require_ai_aborts_when_offline(self):
        """Valida que ETLPipeline con require_ai=True aborte con RuntimeError si el modelo está offline."""
        mock_db = MagicMock()
        mock_db.ensure_catalogs_exist.return_value = {
            "tipos_via": {"table_created": False, "column_added": False, "existing_records": 12, "added_records": 0, "total_records": 12},
            "tipos_zona": {"table_created": False, "column_added": False, "existing_records": 28, "added_records": 0, "total_records": 28},
        }

        pipeline = ETLPipeline(
            db_service=mock_db,
            schema="public",
            table="direcciones_actual",
            require_ai=True,
        )

        with patch("src.services.ollama_service.OllamaService.test_model_inference") as mock_test:
            mock_test.return_value = {
                "connected": False,
                "model_available": False,
                "model_ready": False,
                "latency_seconds": 0.0,
                "error": "Connection refused",
                "message": "Servidor Ollama no disponible",
            }
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.prepare_environment()

            self.assertIn("Ejecución abortada (--require-ai)", str(ctx.exception))

    def test_etl_pipeline_require_ai_defaults_to_true_from_settings(self):
        """Valida que ETLPipeline tome por defecto require_ai=True desde settings y aborte si está offline."""
        mock_db = MagicMock()
        mock_db.ensure_catalogs_exist.return_value = {}

        pipeline = ETLPipeline(
            db_service=mock_db,
            schema="public",
            table="direcciones_actual",
        )
        self.assertTrue(pipeline.require_ai)

        with patch("src.services.ollama_service.OllamaService.test_model_inference") as mock_test:
            mock_test.return_value = {
                "connected": False,
                "model_available": False,
                "model_ready": False,
                "latency_seconds": 0.0,
                "error": "Connection refused",
                "message": "Servidor Ollama no disponible",
            }
            with self.assertRaises(RuntimeError) as ctx:
                pipeline.prepare_environment()

            self.assertIn("Ejecución abortada (--require-ai)", str(ctx.exception))

    def test_etl_pipeline_allows_heuristic_fallback_when_require_ai_false(self):
        """Valida que con require_ai=False continúe en fallback heurístico sin lanzar excepción."""
        mock_db = MagicMock()
        mock_db.ensure_catalogs_exist.return_value = {}

        pipeline = ETLPipeline(
            db_service=mock_db,
            schema="public",
            table="direcciones_actual",
            require_ai=False,
        )
        self.assertFalse(pipeline.require_ai)

        with patch("src.services.ollama_service.OllamaService.test_model_inference") as mock_test:
            mock_test.return_value = {
                "connected": False,
                "model_available": False,
                "model_ready": False,
                "latency_seconds": 0.0,
                "error": "Connection refused",
                "message": "Servidor Ollama no disponible",
            }
            # No debe lanzar excepción
            pipeline.prepare_environment()
            self.assertIn("NO DISPONIBLE", pipeline.ai_status_message)

    def test_lightweight_record_logging_format(self):
        """Valida que _log_record_progress emita una sola línea limpia sin paneles pesados."""
        import io
        from unittest.mock import patch
        from src.models.direccion_destino import DireccionDestino

        pipeline = ETLPipeline(
            schema="public",
            table="direcciones_actual",
            batch_size=1,
        )

        dest_ok = DireccionDestino(
            id_licencia=101,
            id_via=1,
            tipo_via=1,
            nom_via="BALTA",
            num_via="500",
            tipo_zona=1,
            nom_zona="SANTA VICTORIA",
            es_procesado=True,
            metodo_normalizacion="IA (patroclo)",
        )

        dest_obs = DireccionDestino(
            id_licencia=102,
            id_via=None,
            es_procesado=False,
            observacion="Vía no encontrada en catálogo oficial",
            metodo_normalizacion="Heurístico",
        )

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            pipeline._log_record_progress(
                index=1,
                total=50,
                raw_text="AV BALTA 500 SANTA VICTORIA",
                destino=dest_ok,
                success=True,
            )
            output_ok = fake_out.getvalue().strip()
            # Debe ser exactamente 1 línea
            self.assertEqual(len(output_ok.splitlines()), 1)
            self.assertIn("[NORMALIZADO]", output_ok)
            self.assertIn("ID 101:", output_ok)
            self.assertIn("(IA)", output_ok)

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            pipeline._log_record_progress(
                index=2,
                total=50,
                raw_text="DIRECCION SIN VIA",
                destino=dest_obs,
                success=True,
            )
            output_obs = fake_out.getvalue().strip()
            self.assertEqual(len(output_obs.splitlines()), 1)
            self.assertIn("[OBSERVADO  ]", output_obs)
            self.assertIn("ID 102:", output_obs)
            self.assertIn("Vía no encontrada en catálogo oficial", output_obs)
            self.assertIn("(Heurístico)", output_obs)

        with patch("sys.stdout", new=io.StringIO()) as fake_out:
            pipeline._log_record_progress(
                index=3,
                total=50,
                raw_text="DIRECCION ERROR",
                destino=dest_ok,
                success=False,
            )
            output_err = fake_out.getvalue().strip()
            self.assertEqual(len(output_err.splitlines()), 1)
            self.assertIn("[ERROR      ]", output_err)
            self.assertIn("ID 101:", output_err)


if __name__ == "__main__":
    unittest.main()


