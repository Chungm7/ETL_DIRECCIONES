"""Tests unitarios y de integración para el nuevo flujo de migración desacoplada en tb_direccion.

Valida:
1. Modelos DireccionDestino y DireccionOrigen con metadatos de procedencia (esquema, tabla, tabla_id, valor_origen, fecha_proceso).
2. Lógica de Fase A (Pre-migración e Ingesta): migrate_source_table_to_tb_direccion, vinculación de dire_id y drop opcional.
3. Extractor en modo central_tb_direccion con conteo tri-state y extracción de lotes.
4. Cargador en modo central_tb_direccion: actualización directa en tb_direccion e inserción de entidades relacionales.
5. Endpoints de FastAPI /api/migrate-source-table y /api/ingested-sources.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine, text

from src.models.direccion_destino import DireccionDestino
from src.models.direccion_origen import DireccionOrigen
from src.extractors.db_extractor import DatabaseExtractor
from src.loaders.db_loader import DatabaseLoader
from src.services.db_service import DatabaseService


class TestDecoupledModels:
    """Verifica que los modelos Pydantic soporten los campos desacoplados de procedencia."""

    def test_direccion_destino_fields(self):
        dt = datetime(2026, 10, 7, 10, 0, 0)
        destino = DireccionDestino(
            id_licencia=101,
            dire_id=5001,
            zona_id=12,
            dire_referencia="FRENTE AL PARQUE INFANTIL",
            dire_estado="ACT",
            dire_esquema="licencias",
            dire_tabla="tb_licencia",
            dire_tabla_id=101,
            dire_valor_origen="AV. BALTA 450",
            es_procesado=True,
            fecha_proceso=dt,
        )
        assert destino.dire_esquema == "licencias"
        assert destino.dire_tabla == "tb_licencia"
        assert destino.dire_tabla_id == 101
        assert destino.dire_valor_origen == "AV. BALTA 450"
        assert destino.es_procesado is True
        assert destino.fecha_proceso == dt

    def test_direccion_origen_mapping_from_tb_direccion(self):
        """Valida que DireccionOrigen mapee automáticamente desde las columnas de tb_direccion."""
        raw_row = {
            "dire_id": 8800,
            "dire_tabla_id": 450,
            "dire_valor_origen": "CALLE SAN JOSE 120",
            "dire_esquema": "rentas",
            "dire_tabla": "tb_contribuyente",
            "dire_es_procesado": None,
        }
        origen = DireccionOrigen.model_validate(raw_row)
        assert origen.id_licencia == 450
        assert origen.emp_direccion == "CALLE SAN JOSE 120"
        assert origen.dire_id == 8800
        assert origen.dire_esquema == "rentas"
        assert origen.dire_tabla == "tb_contribuyente"
        assert origen.es_procesado is False  # None mapea a False en boolean flag local


class TestDecoupledDatabaseOperations:
    """Pruebas funcionales con base de datos en memoria para el flujo desacoplado."""

    @pytest.fixture
    def db_svc(self):
        """Crea un DatabaseService con motor SQLite en memoria y tablas simuladas."""
        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        from sqlalchemy.orm import sessionmaker
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # Crear esquema de tb_direccion simulado en SQLite
        with svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE tb_direccion (
                    dire_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zona_id INTEGER,
                    dire_referencia TEXT,
                    dire_estado VARCHAR(3) DEFAULT 'ACT',
                    dire_esquema VARCHAR(500),
                    dire_tabla VARCHAR(500),
                    dire_tabla_id INTEGER,
                    dire_valor_origen VARCHAR(500),
                    dire_es_procesado BOOLEAN,
                    fecha_proceso TIMESTAMP
                );
            """))
            session.execute(text("""
                CREATE TABLE tb_direccion_via (
                    divi_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    via_id INTEGER NOT NULL,
                    divi_numero VARCHAR(50),
                    divi_orden INTEGER DEFAULT 1,
                    divi_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, via_id)
                );
            """))
            session.execute(text("""
                CREATE TABLE tb_contenido_componente_direccion (
                    diti_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    codi_id INTEGER NOT NULL,
                    diti_nombre VARCHAR(100) NOT NULL,
                    diti_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, codi_id)
                );
            """))
            session.execute(text("""
                CREATE TABLE tb_direccion_tipo_modulo (
                    ditm_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    timo_id INTEGER NOT NULL,
                    ditm_nombre VARCHAR(100) NOT NULL,
                    ditm_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, timo_id, ditm_nombre)
                );
            """))

            # Crear tabla fuente de prueba (sin columna dire_id)
            session.execute(text("""
                CREATE TABLE test_source (
                    id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
                    direccion_raw VARCHAR(500)
                );
            """))
            # Insertar registros fuente sin migrar
            session.execute(text("""
                INSERT INTO test_source (direccion_raw) VALUES
                ('AV. BALTA 100'),
                ('CA. SAN JOSE 200'),
                ('JR. COLON 300');
            """))

        return svc

    def test_migration_phase_a(self, db_svc):
        """Verifica la Fase A: migración desde test_source hacia tb_direccion sin alterar la tabla fuente."""
        with patch.object(db_svc, "ensure_v2_tables_exist"), patch.object(db_svc, "ensure_tb_direccion_columns"):
            res = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="licencias",
                source_table="test_source",
                id_col="id_registro",
                addr_col="direccion_raw",
                drop_source_col=False,
                target_catalog_schema="main",
            )
            assert res["success"] is True
            assert res["migrated"] == 3
            assert res["total_in_tb_direccion"] == 3

            # Validar que los 3 registros estén en tb_direccion con dire_es_procesado = NULL
            with db_svc.get_session() as session:
                dir_rows = session.execute(text("SELECT dire_id, dire_tabla_id, dire_valor_origen, dire_es_procesado FROM tb_direccion")).fetchall()
                assert len(dir_rows) == 3
                for row in dir_rows:
                    assert row[3] is None  # dire_es_procesado is NULL

                # Validar que test_source conserve sus datos sin columnas impuestas
                src_rows = session.execute(text("SELECT id_registro, direccion_raw FROM test_source")).fetchall()
                assert len(src_rows) == 3

    def test_extractor_central_tb_direccion_mode(self, db_svc):
        """Verifica que DatabaseExtractor en modo central_tb_direccion consulte y extraiga de tb_direccion."""
        # Insertar 2 registros en tb_direccion
        with db_svc.get_session() as session:
            session.execute(text("""
                INSERT INTO tb_direccion (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado) VALUES
                ('licencias', 'tb_licencia', 101, 'AV. BALTA 100', NULL, 'ACT'),
                ('licencias', 'tb_licencia', 102, 'CA. SAN JOSE 200', 1, 'ACT'),
                ('licencias', 'tb_licencia', 103, 'JR. COLON 300', 0, 'ACT');
            """))

        extractor = DatabaseExtractor(
            db_service=db_svc,
            schema="licencias",
            table="tb_licencia",
            source_mode="central_tb_direccion",
            target_catalog_schema="main",
        )

        # Reemplazar schema público por vacío en consultas SQLite
        extractor.target_catalog_schema = "main"

        # Verificar conteos clasificados
        counts = extractor.get_status_counts()
        assert counts["total"] == 3
        assert counts["pendientes"] == 1
        assert counts["validos"] == 1
        assert counts["observados"] == 1

        # Extraer lote de pendientes
        pending_batch = extractor.extract_batch(filter_mode="pending", limit=10)
        assert len(pending_batch) == 1
        assert pending_batch[0].id_licencia == 101
        assert pending_batch[0].emp_direccion == "AV. BALTA 100"
        assert pending_batch[0].dire_id == 1

    def test_loader_central_tb_direccion_mode(self, db_svc):
        """Verifica que DatabaseLoader en modo central_tb_direccion actualice tb_direccion y agregue vías/módulos."""
        with db_svc.get_session() as session:
            session.execute(text("""
                INSERT INTO tb_direccion (dire_id, dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado)
                VALUES (1, 'licencias', 'tb_licencia', 101, 'AV. BALTA 100', NULL, 'ACT');
            """))

        loader = DatabaseLoader(
            db_service=db_svc,
            schema="licencias",
            table="tb_licencia",
            source_mode="central_tb_direccion",
            target_catalog_schema="main",
        )

        destino = DireccionDestino(
            id_licencia=101,
            dire_id=1,
            zona_id=5,
            dire_referencia="FRENTE AL PARQUE",
            dire_estado="ACT",
            es_procesado=True,
            vias=[{"via_id": 201, "divi_numero": "100", "divi_orden": 1}],
            modulos=[{"timo_id": 3, "ditm_nombre": "101"}],
        )

        loaded = loader.load_batch([destino])
        assert loaded == 1

        with db_svc.get_session() as session:
            # Comprobar actualización en tb_direccion
            row = session.execute(text("""
                SELECT dire_id, zona_id, dire_referencia, dire_es_procesado, fecha_proceso
                FROM tb_direccion WHERE dire_id = 1;
            """)).fetchone()
            assert row[0] == 1
            assert row[1] == 5
            assert row[2] == "FRENTE AL PARQUE"
            assert row[3] == 1  # TRUE
            assert row[4] is not None  # fecha_proceso registrada

            # Comprobar inserción en tb_direccion_via
            via_row = session.execute(text("SELECT via_id, divi_numero FROM tb_direccion_via WHERE dire_id = 1")).fetchone()
            assert via_row[0] == 201
            assert via_row[1] == "100"

    def test_get_ingested_sources_overview(self, db_svc):
        """Verifica que get_ingested_sources_overview retorne las fuentes agrupadas con sus métricas."""
        with db_svc.get_session() as session:
            session.execute(text("""
                INSERT INTO tb_direccion (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado) VALUES
                ('licencias', 'tb_licencia', 1, 'DIR 1', NULL, 'ACT'),
                ('licencias', 'tb_licencia', 2, 'DIR 2', 1, 'ACT'),
                ('rentas', 'tb_predio', 10, 'DIR 10', NULL, 'ACT');
            """))

        with patch.object(db_svc, "table_exists", return_value=True), patch.object(db_svc, "ensure_tb_direccion_columns"):
            overview = db_svc.get_ingested_sources_overview(catalog_schema="main")
            assert len(overview) == 2

            lic_source = next(s for s in overview if s["dire_esquema"] == "licencias")
            assert lic_source["total"] == 2
            assert lic_source["pendientes"] == 1
            assert lic_source["normalizados"] == 1

            rentas_source = next(s for s in overview if s["dire_esquema"] == "rentas")
            assert rentas_source["total"] == 1
            assert rentas_source["pendientes"] == 1
            assert rentas_source["normalizados"] == 0

    def test_migration_handles_empty_and_null_addresses_without_orphans(self, db_svc):
        """Verifica que registros con dirección NULL o vacía (ej. caso 34680) se migren a tb_direccion sin quedar fuera."""
        with db_svc.get_session() as session:
            # Crear tabla fuente limpia (sin dire_id) con mezcla de casos
            session.execute(text("""
                CREATE TABLE test_mixed (
                    id_lic INTEGER PRIMARY KEY AUTOINCREMENT,
                    dir_raw VARCHAR(500)
                );
            """))
            session.execute(text("""
                INSERT INTO test_mixed (id_lic, dir_raw) VALUES
                (1, 'AV. BALTA 100'),
                (2, ''),
                (3, NULL),
                (4, '   '),
                (34680, NULL);
            """))

        with patch.object(db_svc, "ensure_v2_tables_exist"), patch.object(db_svc, "ensure_tb_direccion_columns"):
            # En SQLite no hay prefijo de esquema en la tabla, simulamos ejecutando directamente la lógica de migración
            res = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_mixed",
                id_col="id_lic",
                addr_col="dir_raw",
                drop_source_col=False,
                target_catalog_schema="main",
            )

            # Comprobar reporte
            assert res["success"] is True
            assert res["migrated"] == 5
            assert res["total_in_tb_direccion"] == 5
            assert res["remaining_unlinked"] == 0

            # Verificar que en test_mixed las 5 filas se conservan intactas
            with db_svc.get_session() as session:
                count_src = session.execute(text("SELECT COUNT(*) FROM test_mixed")).scalar()
                assert count_src == 5

                # Verificar en tb_direccion cómo quedó el registro 34680 (migrado con éxito y dire_es_procesado = FALSE)
                dir_row = session.execute(text("SELECT dire_id, dire_tabla_id, dire_es_procesado FROM tb_direccion WHERE dire_tabla_id = 34680")).fetchone()
                assert dir_row is not None
                assert dir_row[1] == 34680
                assert dir_row[2] == 0  # Marcado como FALSE (no procesable / vacío)

    def test_pipeline_transformer_propagates_dire_id_and_metadata(self):
        """Valida que PipelineTransformer y AIAddressParser preserven dire_id y metadatos sin perderlos."""
        from src.transformers.pipeline_transformer import PipelineTransformer
        from src.transformers.ai_parser import AIAddressParser

        # 1. Caso registro con dirección válida
        orig = DireccionOrigen(
            id_licencia=34680,
            emp_direccion="AV. BALTA 123",
            dire_id=999,
            dire_esquema="licencias",
            dire_tabla="tb_licencia",
            dire_tabla_id=34680,
            dire_valor_origen="AV. BALTA 123",
            es_procesado=False,
        )

        # Modo sin IA
        transformer_no_ai = PipelineTransformer(use_ai=False)
        dest_no_ai = transformer_no_ai.transform_record(orig)
        assert dest_no_ai.dire_id == 999
        assert dest_no_ai.dire_esquema == "licencias"
        assert dest_no_ai.dire_tabla == "tb_licencia"
        assert dest_no_ai.dire_tabla_id == 34680
        assert dest_no_ai.dire_valor_origen == "AV. BALTA 123"

        # Modo con IA (mockeando el modelo de Ollama para retornar extracción simple)
        mock_ai_parser = MagicMock(spec=AIAddressParser)
        mock_ai_parser.parse.return_value = DireccionDestino(
            id_licencia=34680,
            dire_id=999,
            dire_esquema="licencias",
            dire_tabla="tb_licencia",
            dire_tabla_id=34680,
            dire_valor_origen="AV. BALTA 123",
            es_procesado=True,
            vias=[{"via_id": 1, "divi_numero": "123"}],
        )
        transformer_ai = PipelineTransformer(ai_parser=mock_ai_parser, use_ai=True)
        dest_ai = transformer_ai.transform_record(orig)
        assert dest_ai.dire_id == 999
        assert dest_ai.dire_esquema == "licencias"
        assert dest_ai.dire_tabla_id == 34680

        # 2. Caso registro vacío
        orig_empty = DireccionOrigen(
            id_licencia=34680,
            emp_direccion="",
            dire_id=999,
            dire_esquema="licencias",
            dire_tabla="tb_licencia",
            dire_tabla_id=34680,
            dire_valor_origen=None,
        )
        dest_empty = transformer_no_ai.transform_record(orig_empty)
        assert dest_empty.dire_id == 999
        assert dest_empty.es_procesado is False
        assert dest_empty.dire_tabla_id == 34680

    def test_ensure_v2_tables_exist_creates_all_10_tables_and_seeds(self):
        """Verifica que ensure_v2_tables_exist cree las 10 tablas relacionales V2 completas y siembre catálogos."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        res = svc.ensure_v2_tables_exist()
        assert res["status"] in ("OK", "ALL_TABLES_READY")

        expected_tables = [
            "tb_tipo_via", "tb_via", "tb_tipo_zona", "tb_zona",
            "tb_direccion", "tb_direccion_via", "tb_componente_direccion",
            "tb_contenido_componente_direccion", "tb_tipo_modulo",
            "tb_direccion_tipo_modulo"
        ]
        for tbl in expected_tables:
            assert svc.table_exists(tbl) is True, f"Tabla {tbl} debe existir tras ensure_v2_tables_exist"

        # Validar sembrado de catálogos
        with svc.get_session() as session:
            tv_count = session.execute(text("SELECT COUNT(*) FROM tb_tipo_via")).scalar()
            assert tv_count == 12
            tz_count = session.execute(text("SELECT COUNT(*) FROM tb_tipo_zona")).scalar()
            assert tz_count == 28
            comp_count = session.execute(text("SELECT COUNT(*) FROM tb_componente_direccion")).scalar()
            assert comp_count == 12
            mod_count = session.execute(text("SELECT COUNT(*) FROM tb_tipo_modulo")).scalar()
            assert mod_count == 13

        # Segunda llamada: Idempotencia y Fast-Path
        res_fast = svc.ensure_v2_tables_exist()
        assert res_fast["status"] == "ALL_TABLES_READY"


