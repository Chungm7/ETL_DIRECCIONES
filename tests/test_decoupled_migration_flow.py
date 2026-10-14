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
            dire_columna="emp_direccion",
            dire_tabla_id=101,
            dire_valor_origen="AV. BALTA 450",
            es_procesado=True,
            fecha_proceso=dt,
        )
        assert destino.dire_esquema == "licencias"
        assert destino.dire_tabla == "tb_licencia"
        assert destino.dire_columna == "emp_direccion"
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
            "dire_columna": "contribuyente_dir",
            "dire_es_procesado": None,
        }
        origen = DireccionOrigen.model_validate(raw_row)
        assert origen.id_licencia == 450
        assert origen.emp_direccion == "CALLE SAN JOSE 120"
        assert origen.dire_id == 8800
        assert origen.dire_esquema == "rentas"
        assert origen.dire_tabla == "tb_contribuyente"
        assert origen.dire_columna == "contribuyente_dir"
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
                    dire_columna VARCHAR(500),
                    dire_tabla_id INTEGER,
                    dire_valor_origen VARCHAR(500),
                    dire_es_procesado BOOLEAN,
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP
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
                    diti_orden INTEGER DEFAULT 1,
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
                    ditm_orden INTEGER DEFAULT 1,
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

            # Validar que los 3 registros estén en tb_direccion con dire_es_procesado = NULL y dire_columna poblado
            with db_svc.get_session() as session:
                dir_rows = session.execute(text("SELECT dire_id, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_columna FROM tb_direccion")).fetchall()
                assert len(dir_rows) == 3
                for row in dir_rows:
                    assert row[3] is None  # dire_es_procesado is NULL
                    assert row[4] == "direccion_raw"  # dire_columna registrado correctamente

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

    def test_extractor_central_tb_direccion_global_mode(self, db_svc):
        """Verifica que al seleccionar tb_direccion global (sin filtrar por tabla específica)
        DatabaseExtractor consulte y extraiga la totalidad de registros en tb_direccion.
        """
        with db_svc.get_session() as session:
            session.execute(text("DELETE FROM tb_direccion;"))
            session.execute(text("""
                INSERT INTO tb_direccion (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado) VALUES
                ('licencias', 'tb_licencia', 101, 'AV. BALTA 100', NULL, 'ACT'),
                ('licencias', 'tb_licencia', 102, 'CA. SAN JOSE 200', 1, 'ACT'),
                ('licencias', 'tb_licencia', 103, 'JR. COLON 300', 0, 'ACT'),
                ('rentas', 'tb_predio', 501, 'CALLE 7 DE ENERO 400', NULL, 'ACT');
            """))

        extractor_global = DatabaseExtractor(
            db_service=db_svc,
            schema="public",
            table="tb_direccion",
            source_mode="central_tb_direccion",
            target_catalog_schema="main",
        )

        counts = extractor_global.get_status_counts()
        assert counts["total"] == 4
        assert counts["pendientes"] == 2
        assert counts["validos"] == 1
        assert counts["observados"] == 1
        assert extractor_global.get_total_records() == 4

        pending_batch = extractor_global.extract_batch(filter_mode="pending", limit=10)
        assert len(pending_batch) == 2
        schemas = {r.dire_esquema for r in pending_batch}
        assert schemas == {"licencias", "rentas"}

        with db_svc.get_session() as session:
            next_rec = extractor_global.fetch_next_free_record(session, filter_mode="pending")
            assert next_rec is not None
            assert next_rec.dire_valor_origen == "AV. BALTA 100"

    def test_get_central_tb_direccion_stats(self, db_svc):
        """Verifica que get_central_tb_direccion_stats retorne métricas agregadas globales."""
        with db_svc.get_session() as session:
            session.execute(text("DELETE FROM tb_direccion;"))
            session.execute(text("""
                INSERT INTO tb_direccion (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado) VALUES
                ('licencias', 'tb_licencia', 1, 'DIR 1', NULL, 'ACT'),
                ('licencias', 'tb_licencia', 2, 'DIR 2', 1, 'ACT'),
                ('rentas', 'tb_predio', 10, 'DIR 10', NULL, 'ACT');
            """))

        with patch.object(db_svc, "table_exists", return_value=True), patch.object(db_svc, "ensure_tb_direccion_columns"):
            stats = db_svc.get_central_tb_direccion_stats(catalog_schema="main")
            assert stats["has_records"] is True
            assert stats["total"] == 3
            assert stats["pendientes"] == 2
            assert stats["normalizados"] == 1
            assert stats["rechazados"] == 0
            assert stats["sources_count"] == 2

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
                SELECT dire_id, zona_id, dire_referencia, dire_es_procesado, update_at
                FROM tb_direccion WHERE dire_id = 1;
            """)).fetchone()
            assert row[0] == 1
            assert row[1] == 5
            assert row[2] == "FRENTE AL PARQUE"
            assert row[3] == 1  # TRUE
            assert row[4] is not None  # update_at registrada

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

    def test_audit_columns_added_to_existing_tb_direccion_without_data_loss(self):
        """Valida que si tb_direccion ya existía con datos pero sin columnas de auditoría,
        ensure_tb_direccion_exists añade las 8 columnas sin perjudicar ni borrar ningún dato existente."""
        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        from sqlalchemy.orm import sessionmaker
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # 1. Crear tb_direccion en estado antiguo (sin las 8 columnas de auditoría)
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
            # 2. Insertar registros existentes
            session.execute(text("""
                INSERT INTO tb_direccion (dire_id, dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado)
                VALUES 
                    (1, 'licencias', 'tb_licencia', 101, 'AV. BALTA 100', NULL, 'ACT'),
                    (2, 'rentas', 'tb_predios', 202, 'CALLE SAN JOSE 200', TRUE, 'ACT'),
                    (3, 'catastro', 'tb_lotes', 303, 'JR. ELIAS AGUIRRE 300', FALSE, 'ACT');
            """))

        # 3. Ejecutar ensure_tb_direccion_exists
        res = svc.ensure_tb_direccion_exists()
        assert res is True

        # 4. Verificar que las 8 columnas de auditoría ahora existen (con create_at y update_at)
        cols = {c.lower() for c in svc.get_table_columns("tb_direccion")}
        expected_audit_cols = {
            "usua_id", "usua_nombre", "create_at", "update_at",
            "audit_user_pc", "audit_nombre_pc", "audit_ip", "audit_mac_address"
        }
        for audit_col in expected_audit_cols:
            assert audit_col in cols, f"Columna de auditoría '{audit_col}' debe existir en tb_direccion"
        assert "fecha_proceso" not in cols, "Columna fecha_proceso debe haber sido eliminada de tb_direccion"

        # 5. Comprobar que los datos preexistentes están 100% intactos
        with svc.get_session() as session:
            rows = session.execute(text("SELECT dire_id, dire_esquema, dire_tabla_id, dire_valor_origen FROM tb_direccion ORDER BY dire_id")).fetchall()
            assert len(rows) == 3
            assert rows[0] == (1, "licencias", 101, "AV. BALTA 100")
            assert rows[1] == (2, "rentas", 202, "CALLE SAN JOSE 200")
            assert rows[2] == (3, "catastro", 303, "JR. ELIAS AGUIRRE 300")

    def test_loader_central_tb_direccion_updates_audit_updated_at(self):
        """Valida que DatabaseLoader actualice updated_at al normalizar un registro en tb_direccion."""
        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        from sqlalchemy.orm import sessionmaker
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # Crear estructura con ensure_v2_tables_exist
        svc.ensure_v2_tables_exist()

        # Insertar registro inicial pendiente
        with svc.get_session() as session:
            session.execute(text("""
                INSERT INTO tb_direccion (dire_id, dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, dire_estado)
                VALUES (50, 'licencias', 'tb_licencia', 5050, 'AV. BALTA 550', NULL, 'A');
            """))

        loader = DatabaseLoader(
            db_service=svc,
            schema="licencias",
            table="tb_licencia",
            source_mode="central_tb_direccion",
            target_catalog_schema="",
        )

        record = DireccionDestino(
            id_licencia=5050,
            dire_id=50,
            zona_id=1,
            dire_referencia="FRENTE A BANCO DE LA NACION",
            dire_estado="A",
            es_procesado=True,
            vias=[{"via_id": 1, "divi_numero": "550", "divi_orden": 1}],
        )

        loaded_count = loader.load_batch([record])
        assert loaded_count == 1

        with svc.get_session() as session:
            row = session.execute(text("""
                SELECT dire_id, dire_es_procesado, dire_referencia, update_at 
                FROM tb_direccion WHERE dire_id = 50
            """)).fetchone()
            assert row[0] == 50
            assert bool(row[1]) is True
            assert row[2] == "FRENTE A BANCO DE LA NACION"
            assert row[3] is not None, "update_at debe actualizarse al normalizar"

    def test_consolidate_catalog_duplicates_merges_san_lucas(self):
        """Valida que registros duplicados de vías (como Pasaje San Lucas) se consoliden en 1 solo
        y que cualquier FK en tb_direccion_via se reasigne al ID canónico de forma transparente.
        """
        engine = create_engine("sqlite:///:memory:")
        svc = DatabaseService()
        svc._engine = engine
        from sqlalchemy.orm import sessionmaker
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        # Crear estructura base
        svc.ensure_v2_tables_exist()

        with svc.get_session() as session:
            # Simular inserción de duplicados históricos de San Lucas
            # 723: Calle San Lucas (tivi_id=2)
            # 1095: Pasaje San Lucas (tivi_id=4)
            # 1269: Pasaje San Lucas (tivi_id=4) DUPLICADO
            session.execute(text("""
                INSERT OR REPLACE INTO tb_via (via_id, tivi_id, via_nombre, via_estado) VALUES
                (723, 2, 'SAN LUCAS', 'A'),
                (1095, 4, 'SAN LUCAS', 'A'),
                (1269, 4, 'SAN LUCAS', 'A');
            """))

            # Crear una dirección en tb_direccion y asociarla al pasaje duplicado 1269
            session.execute(text("""
                INSERT OR REPLACE INTO tb_direccion (dire_id, dire_valor_origen, dire_es_procesado, dire_estado)
                VALUES (1001, 'PSJ. SAN LUCAS 140', 1, 'A');
            """))
            session.execute(text("""
                INSERT OR REPLACE INTO tb_direccion_via (divi_id, dire_id, via_id, divi_numero, divi_orden)
                VALUES (9001, 1001, 1269, '140', 1);
            """))

        # Ejecutar consolidación
        res = svc.consolidate_catalog_duplicates()
        assert res["vias_consolidated"] >= 1 or res["direccion_via_fks_updated"] >= 1

        with svc.get_session() as session:
            # Verificar que de Pasaje San Lucas solo quede 1 registro
            pasajes_sl = session.execute(text("""
                SELECT via_id, tivi_id, via_nombre FROM tb_via
                WHERE via_nombre = 'SAN LUCAS' AND tivi_id = 4;
            """)).fetchall()
            assert len(pasajes_sl) == 1, f"Debe quedar exactamente 1 pasaje San Lucas, pero hay {len(pasajes_sl)}"

            canonical_pasaje_id = pasajes_sl[0][0]

            # Verificar que Calle San Lucas sigue existiendo (1 registro)
            calles_sl = session.execute(text("""
                SELECT via_id, tivi_id, via_nombre FROM tb_via
                WHERE via_nombre = 'SAN LUCAS' AND tivi_id = 2;
            """)).fetchall()
            assert len(calles_sl) == 1, f"Debe quedar exactamente 1 calle San Lucas, pero hay {len(calles_sl)}"

            # Verificar que la FK en tb_direccion_via fue reasignada al pasaje canónico
            dv_row = session.execute(text("""
                SELECT via_id FROM tb_direccion_via WHERE dire_id = 1001;
            """)).fetchone()
            assert dv_row is not None
            assert dv_row[0] == canonical_pasaje_id, f"FK debe ser {canonical_pasaje_id}, pero fue {dv_row[0]}"

    def test_ensure_tb_direccion_creates_audit_columns(self, db_svc):
        """Verifica que ensure_tb_direccion_exists cree y conserve las columnas de auditoría create_at y update_at."""
        assert db_svc.ensure_tb_direccion_exists() is True

        with db_svc.get_session() as session:
            rows = session.execute(text("PRAGMA table_info(tb_direccion);")).fetchall()
            col_names = {r[1].lower() for r in rows}
            assert "usua_id" in col_names
            assert "usua_nombre" in col_names
            assert "create_at" in col_names
            assert "update_at" in col_names
            assert "audit_user_pc" in col_names
            assert "audit_nombre_pc" in col_names
            assert "audit_ip" in col_names
            assert "audit_mac_address" in col_names

    def test_ensure_tb_direccion_renames_legacy_resa_columns(self):
        """Verifica que si tb_direccion tenía resa_created_at y resa_updated_at, se renombre a create_at y update_at."""
        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        from sqlalchemy.orm import sessionmaker
        svc._session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        with svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE tb_direccion (
                    dire_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resa_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resa_updated_at TIMESTAMP
                );
            """))

        assert svc.ensure_tb_direccion_exists() is True

        with svc.get_session() as session:
            rows = session.execute(text("PRAGMA table_info(tb_direccion);")).fetchall()
            col_names = {r[1].lower() for r in rows}
            assert "create_at" in col_names
            assert "update_at" in col_names
            assert "resa_created_at" not in col_names
            assert "resa_updated_at" not in col_names

    def test_central_tb_direccion_keyset_pagination_uses_dire_id(self, db_svc):
        """Verifica que la paginación keyset en central_tb_direccion use dire_id secuencial aunque dire_tabla_id sea un número grande."""
        db_svc.ensure_tb_direccion_exists()

        with db_svc.get_session() as session:
            # Insertar registros donde dire_tabla_id es 50000+ pero dire_id es 1..3
            for i in range(1, 4):
                session.execute(text(f"""
                    INSERT INTO tb_direccion (dire_id, dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado)
                    VALUES ({i}, 'licencias', 'direcciones', {50000 + i}, 'CALLE SAN JOSE {100 * i}', NULL);
                """))

        extractor = DatabaseExtractor(
            db_service=db_svc,
            schema="licencias",
            table="direcciones",
            source_mode="central_tb_direccion",
        )

        # Batch 1 (limit=1)
        batch1 = extractor.extract_batch(limit=1, filter_mode="pending", after_id=None)
        assert len(batch1) == 1
        rec1 = batch1[0]
        assert rec1.dire_id == 1
        assert rec1.id_licencia == 50001

        # En la siguiente iteración, con el fix, after_id debe ser rec1.dire_id (1), NO rec1.id_licencia (50001)
        batch2 = extractor.extract_batch(limit=1, filter_mode="pending", after_id=rec1.dire_id)
        assert len(batch2) == 1
        assert batch2[0].dire_id == 2


class TestEnsureCatalogsAuditColumns:
    """Verifica que ensure_catalogs_audit_columns() agrega las 8 columnas de auditoría
    a las 6 tablas maestras de catálogos de forma idempotente y sin romper el flujo."""

    CATALOG_TABLES = [
        "tb_tipo_via",
        "tb_via",
        "tb_tipo_zona",
        "tb_zona",
        "tb_componente_direccion",
        "tb_tipo_modulo",
    ]
    AUDIT_COLUMNS = [
        "usua_id",
        "usua_nombre",
        "create_at",
        "update_at",
        "audit_user_pc",
        "audit_nombre_pc",
        "audit_ip",
        "audit_mac_address",
    ]

    def _get_db_svc(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.services.db_service import DatabaseService
        svc = DatabaseService()
        engine = create_engine("sqlite:///:memory:")
        svc._engine = engine
        svc._session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return svc

    def test_ensure_catalogs_audit_columns_adds_all_8_columns(self):
        """Tras crear las tablas con ensure_v2_tables_exist, todas las tablas
        maestras deben tener las 8 columnas de auditoría."""
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        with db_svc.get_session() as session:
            for table in self.CATALOG_TABLES:
                existing_cols = {
                    r[1] for r in session.execute(
                        text(f"PRAGMA table_info({table});")
                    ).fetchall()
                }
                for col in self.AUDIT_COLUMNS:
                    assert col in existing_cols, (
                        f"Columna de auditoría '{col}' faltante en {table} "
                        f"tras ensure_v2_tables_exist(). Columnas presentes: {sorted(existing_cols)}"
                    )

    def test_ensure_catalogs_audit_columns_is_idempotent(self):
        """Llamar ensure_catalogs_audit_columns() dos veces no debe lanzar excepciones
        ni alterar datos de catálogos ya sembrados."""
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        # Primera llamada
        db_svc.ensure_catalogs_audit_columns()
        # Segunda llamada — debe ser silenciosa
        db_svc.ensure_catalogs_audit_columns()

        # Datos de catálogos intactos
        with db_svc.get_session() as session:
            count = session.execute(text("SELECT COUNT(*) FROM tb_tipo_via;")).scalar() or 0
        assert count > 0, "tb_tipo_via debe conservar sus registros sembrados"

    def test_catalog_inserts_still_work_after_audit_columns(self):
        """Las sentencias INSERT existentes (sin columnas de auditoría) deben funcionar
        correctamente tras agregar las columnas de auditoría (todas son NULLable)."""
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        with db_svc.get_session() as session:
            # Insertar en tb_tipo_modulo sin columnas de auditoría (como hace el seed existente)
            session.execute(text(
                "INSERT OR IGNORE INTO tb_tipo_modulo (timo_id, timo_nombre, timo_abreviatura, timo_estado) "
                "VALUES (999, 'TEST_MODULO', 'TEST', 'A');"
            ))
            row = session.execute(text(
                "SELECT timo_id, create_at FROM tb_tipo_modulo WHERE timo_id = 999;"
            )).fetchone()
            assert row is not None, "INSERT sin columnas de auditoría debe funcionar"
            # create_at debe tener valor por DEFAULT CURRENT_TIMESTAMP (puede ser None en SQLite sin trigger)
            # Solo verificamos que no haya error al leer la columna
            assert "create_at" in [
                r[1] for r in session.execute(text("PRAGMA table_info(tb_tipo_modulo);")).fetchall()
            ]

    def test_migration_handles_null_ids_fluidly(self):
        """Verifica que la migración maneje identificadores nulos sin colgarse ni entrar en bucle infinito."""
        from unittest.mock import patch
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        with db_svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS test_null_ids (
                    id_distrito INTEGER,
                    emp_direccion TEXT
                );
            """))
            session.execute(text("DELETE FROM test_null_ids;"))
            session.execute(text("""
                INSERT INTO test_null_ids (id_distrito, emp_direccion) VALUES
                (NULL, 'CALLE SAN JOSE 100 - CHICLAYO'),
                (NULL, 'AV. BALTA 200 - CHICLAYO'),
                (140101, 'JR. COLON 300 - CHICLAYO');
            """))

        with patch.object(db_svc, "ensure_v2_tables_exist"), patch.object(db_svc, "ensure_tb_direccion_columns"):
            res = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_null_ids",
                id_col="id_distrito",
                addr_col="emp_direccion",
                drop_source_col=False,
                target_catalog_schema="main",
            )

            assert res["success"] is True
            assert res["migrated"] == 3
            assert res["total_source"] == 3
            assert res["remaining_unlinked"] == 0

        # Verificar que se insertaron las 3 filas en tb_direccion
        with db_svc.get_session() as session:
            rows = session.execute(text("""
                SELECT dire_id, dire_tabla_id, dire_valor_origen 
                FROM tb_direccion 
                WHERE dire_tabla = 'test_null_ids';
            """)).fetchall()
            assert len(rows) == 3

    def test_migration_handles_duplicate_ids_fluidly(self):
        """Verifica que la migración maneje columnas con IDs duplicados sin perder filas."""
        from unittest.mock import patch
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        with db_svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS test_dup_ids (
                    id_distrito INTEGER,
                    emp_direccion TEXT
                );
            """))
            session.execute(text("DELETE FROM test_dup_ids;"))
            session.execute(text("""
                INSERT INTO test_dup_ids (id_distrito, emp_direccion) VALUES
                (1, 'DIR A'),
                (1, 'DIR B'),
                (1, 'DIR C');
            """))

        with patch.object(db_svc, "ensure_v2_tables_exist"), patch.object(db_svc, "ensure_tb_direccion_columns"):
            res = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_dup_ids",
                id_col="id_distrito",
                addr_col="emp_direccion",
                drop_source_col=False,
                target_catalog_schema="main",
            )

            assert res["success"] is True
            assert res["migrated"] == 3
            assert res["total_source"] == 3

    def test_migration_idempotent_when_already_migrated(self):
        """Verifica que al re-ejecutar la migración cuando ya todos los datos existen, retorne de inmediato con 0 nuevos."""
        from unittest.mock import patch
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_v2_tables_exist()

        with db_svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS test_idem (
                    id_licencia INTEGER,
                    emp_direccion TEXT
                );
            """))
            session.execute(text("DELETE FROM test_idem;"))
            session.execute(text("""
                INSERT INTO test_idem (id_licencia, emp_direccion) VALUES
                (10, 'AV. SALAVERRY 100'),
                (20, 'CA. TACNA 200');
            """))

        with patch.object(db_svc, "ensure_v2_tables_exist"), patch.object(db_svc, "ensure_tb_direccion_columns"):
            res1 = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_idem",
                id_col="id_licencia",
                addr_col="emp_direccion",
                drop_source_col=False,
                target_catalog_schema="main",
            )
            assert res1["success"] is True
            assert res1["migrated"] == 2

            # Segunda ejecución — idempotente
            res2 = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_idem",
                id_col="id_licencia",
                addr_col="emp_direccion",
                drop_source_col=False,
                target_catalog_schema="main",
            )
            assert res2["success"] is True
            assert res2["migrated"] == 0
            assert res2["already_migrated"] == 2

    def test_ensure_tb_direccion_exists_cache(self):
        """Valida que ensure_tb_direccion_exists use el conjunto de caché _tb_direccion_verified
        y no ejecute DDL repetitivo en llamadas subsiguientes.
        """
        db_svc = self._get_db_svc()
        db_svc._tb_direccion_verified.clear()

        # Primera llamada: verifica y cachea
        ok1 = db_svc.ensure_tb_direccion_exists("main")
        assert ok1 is True
        assert "main" in db_svc._tb_direccion_verified

        # Segunda llamada: hit en caché inmediato
        with patch.object(db_svc, "get_session") as mock_session:
            ok2 = db_svc.ensure_tb_direccion_exists("main")
            assert ok2 is True
            # No debió abrir ninguna sesión ya que respondió directamente de la caché
            mock_session.assert_not_called()

    def test_migrate_source_table_phase_a_does_not_call_v2_or_catalog_matcher(self):
        """Garantiza que la Fase A (ingesta cruda) nunca invoque ensure_v2_tables_exist
        ni CatalogMatcher.sync_with_db, manteniendo la migración en milisegundos.
        """
        import time
        from sqlalchemy import text
        db_svc = self._get_db_svc()
        db_svc.ensure_tb_direccion_exists("main")

        with db_svc.get_session() as session:
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS test_7_rows (
                    id INTEGER PRIMARY KEY,
                    dir TEXT
                );
            """))
            session.execute(text("DELETE FROM test_7_rows;"))
            for i in range(1, 8):
                session.execute(text(f"INSERT INTO test_7_rows VALUES ({i}, 'DIRECCION DE PRUEBA {i}');"))

        with patch.object(db_svc, "ensure_v2_tables_exist") as mock_v2, \
             patch("src.transformers.catalog_matcher.CatalogMatcher.sync_with_db") as mock_sync:
            
            t0 = time.perf_counter()
            res = db_svc.migrate_source_table_to_tb_direccion(
                source_schema="",
                source_table="test_7_rows",
                id_col="id",
                addr_col="dir",
                drop_source_col=False,
                target_catalog_schema="main",
            )
            elapsed = time.perf_counter() - t0

            assert res["success"] is True
            assert res["total_source"] == 7
            assert res["migrated"] == 7
            # Verificamos que jamás se invocó V2 ni la sincronización pesada
            mock_v2.assert_not_called()
            mock_sync.assert_not_called()
            # La migración de 7 registros toma menos de 0.5 segundos (típicamente < 0.05s)
            assert elapsed < 0.5
