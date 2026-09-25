"""Servicio de conexión, inspección de esquemas y ejecución DDL/DML con PostgreSQL."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

from src.config.settings import DatabaseSettings, get_settings

logger = logging.getLogger("etl_mpch.db_service")

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker, Session
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class DatabaseService:
    """Administra conexiones, esquemas dinámicos y operaciones DDL/DML en PostgreSQL."""

    def __init__(self, settings: Optional[DatabaseSettings] = None):
        self.settings = settings or get_settings().db
        self.url = self.settings.url
        self._engine = None
        self._session_factory = None

        if SQLALCHEMY_AVAILABLE:
            self._init_engine()
        else:
            logger.warning("SQLAlchemy no está instalado en el entorno actual.")

    def _init_engine(self) -> None:
        """Inicializa el Engine y la factoría de sesiones de SQLAlchemy."""
        try:
            self._engine = create_engine(
                self.url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
            )
            self._session_factory = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self._engine,
            )
        except Exception as e:
            logger.error("Error al configurar el engine de base de datos: %s", e)

    def get_available_schemas(self) -> List[str]:
        """Retorna la lista de esquemas de aplicación disponibles en la base de datos."""
        if not self._engine:
            return []
        sql = text("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY schema_name;
        """)
        try:
            with self.get_session() as session:
                rows = session.execute(sql).fetchall()
                return [r[0] for r in rows]
        except Exception as e:
            logger.error("Error al consultar esquemas en PostgreSQL: %s", e)
            return []

    def check_connection(self, schema: Optional[str] = None) -> Dict[str, Any]:
        """Comprueba la conexión con PostgreSQL y verifica el esquema activo y sus tablas."""
        active_schema = schema or self.settings.schema
        result: Dict[str, Any] = {
            "connected": False,
            "host": self.settings.host,
            "database": self.settings.name,
            "schema": active_schema,
            "table": self.settings.table,
            "source_schema": active_schema,
            "source_table": self.settings.table,
            "table_exists": False,
            "source_table_exists": False,
            "catalogs_exist": False,
            "catalogs_found": [],
            "available_schemas": [],
            "message": "",
        }

        if not SQLALCHEMY_AVAILABLE or self._engine is None:
            result["message"] = "SQLAlchemy no está disponible o el motor no se inicializó."
            return result

        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1;"))
                result["connected"] = True

                # Listar esquemas de aplicación disponibles
                result["available_schemas"] = self.get_available_schemas()

                # Verificar tabla de direcciones en el esquema activo
                check_src_sql = text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema AND table_name = :table;
                """)
                src_count = conn.execute(
                    check_src_sql,
                    {"schema": active_schema, "table": self.settings.table},
                ).scalar()
                result["table_exists"] = bool(src_count and src_count > 0)
                result["source_table_exists"] = result["table_exists"]

                # Verificar catálogos en el esquema activo
                check_catalogs_sql = text("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema 
                      AND table_name IN (:t_via, :t_zona, :t_vias, :t_zonas);
                """)
                cat_rows = conn.execute(
                    check_catalogs_sql,
                    {
                        "schema": active_schema,
                        "t_via": self.settings.table_tipo_via,
                        "t_zona": self.settings.table_tipo_zona,
                        "t_vias": self.settings.table_vias,
                        "t_zonas": self.settings.table_zonas,
                    },
                ).fetchall()
                found_cats = [r[0] for r in cat_rows]
                result["catalogs_found"] = found_cats
                result["catalogs_exist"] = len(found_cats) >= 2

                result["message"] = f"Conexión a PostgreSQL exitosa en esquema '{active_schema}'."

        except Exception as e:
            result["message"] = f"Error al conectar con PostgreSQL: {str(e)}"
            logger.error(result["message"])

        return result

    def ensure_catalogs_exist(
        self,
        schema: Optional[str] = None,
        table_tipo_via: Optional[str] = None,
        table_tipo_zona: Optional[str] = None,
        directions_table: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Examina las tablas de catálogos en el esquema destino, estandariza sus IDs según
        el catálogo canónico propuesto en JSON, reasigna relaciones previas en la tabla de direcciones
        y completa los registros oficiales faltantes.

        Args:
            schema: Esquema a verificar (default: self.settings.schema).
            table_tipo_via: Nombre de la tabla de tipos de vía.
            table_tipo_zona: Nombre de la tabla de tipos de zona.
            directions_table: Nombre de la tabla de direcciones para reasignar FKs si existen.

        Returns:
            Diccionario detallado con el estado de cada tabla:
            {
                "tipos_via": {"table_created": bool, "column_added": bool, "existing_records": int, "remapped_records": int, "added_records": int, "total_records": int, "fk_remapped_records": int},
                "tipos_zona": ...
            }
        """
        from src.transformers.text_cleaner import TextCleaner
        from src.catalogs.catalog_manager import CatalogManager

        official_vias = CatalogManager.get_official_vias_tuples()
        official_zonas = CatalogManager.get_official_zonas_tuples()

        target_schema = schema or self.settings.schema
        t_via = table_tipo_via or "tipos_via"
        t_zona = table_tipo_zona or "tipos_zona"
        dir_table = directions_table or self.settings.table
        col_via = self.settings.col_tipo_via
        col_zona = self.settings.col_tipo_zona

        results = {}

        if not SQLALCHEMY_AVAILABLE or not self._engine:
            logger.warning("SQLAlchemy o engine no disponible para verificar catálogos.")
            return {
                t_via: {"table_created": False, "column_added": False, "existing_records": 0, "remapped_records": 0, "added_records": 0, "total_records": 0, "fk_remapped_records": 0},
                t_zona: {"table_created": False, "column_added": False, "existing_records": 0, "remapped_records": 0, "added_records": 0, "total_records": 0, "fk_remapped_records": 0},
            }

        try:
            with self.get_session() as session:
                def _sync_single_catalog(table_name: str, pk_col: str, name_col: str, dir_col: str, official_list: list):
                    status = {
                        "table_created": False,
                        "column_added": False,
                        "existing_records": 0,
                        "remapped_records": 0,
                        "added_records": 0,
                        "total_records": 0,
                        "fk_remapped_records": 0,
                    }

                    # 1. Verificar si existe la tabla
                    table_check = session.execute(text("""
                        SELECT COUNT(*) 
                        FROM information_schema.tables 
                        WHERE table_schema = :schema AND table_name = :table;
                    """), {"schema": target_schema, "table": table_name}).scalar()

                    if not table_check or table_check == 0:
                        # Crear la tabla desde cero
                        create_sql = f"""
                        CREATE TABLE "{target_schema}"."{table_name}" (
                            "{pk_col}"     INTEGER NOT NULL,
                            "{name_col}"   VARCHAR(100) NOT NULL,
                            abreviatura    VARCHAR(20),
                            CONSTRAINT pk_{target_schema}_{table_name} PRIMARY KEY ("{pk_col}")
                        );
                        """
                        session.execute(text(create_sql))
                        status["table_created"] = True

                        for def_id, def_name, def_abrev in official_list:
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."{table_name}" ("{pk_col}", "{name_col}", abreviatura)
                                VALUES (:id, :name, :abrev);
                            """), {"id": def_id, "name": def_name, "abrev": def_abrev})

                        status["added_records"] = len(official_list)
                        status["total_records"] = len(official_list)
                        return status

                    # 2. La tabla existe: comprobar si falta la columna 'abreviatura'
                    col_check = session.execute(text("""
                        SELECT COUNT(*) 
                        FROM information_schema.columns 
                        WHERE table_schema = :schema AND table_name = :table AND column_name = 'abreviatura';
                    """), {"schema": target_schema, "table": table_name}).scalar()

                    if not col_check or col_check == 0:
                        alter_col_sql = f"""
                        ALTER TABLE "{target_schema}"."{table_name}" 
                            ADD COLUMN IF NOT EXISTS abreviatura VARCHAR(20);
                        """
                        session.execute(text(alter_col_sql))
                        status["column_added"] = True

                    # 3. Consultar registros existentes en la tabla
                    existing_rows = session.execute(text(f"""
                        SELECT "{pk_col}", "{name_col}" 
                        FROM "{target_schema}"."{table_name}"
                        ORDER BY "{pk_col}" ASC;
                    """)).fetchall()

                    status["existing_records"] = len(existing_rows)

                    if not existing_rows:
                        for def_id, def_name, def_abrev in official_list:
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."{table_name}" ("{pk_col}", "{name_col}", abreviatura)
                                VALUES (:id, :name, :abrev);
                            """), {"id": def_id, "name": def_name, "abrev": def_abrev})
                        status["added_records"] = len(official_list)
                        status["total_records"] = len(official_list)
                        return status

                    # 4. Comparar registros existentes contra la estructura oficial canónica del JSON
                    canonical_by_name = {}
                    canonical_ids = set()
                    for def_id, def_name, def_abrev in official_list:
                        clean_k = TextCleaner.remove_accents(def_name.strip().upper())
                        canonical_by_name[clean_k] = (def_id, def_name, def_abrev)
                        canonical_ids.add(def_id)

                    id_remap = {}  # {old_id: new_canonical_id}
                    matched_names = set()
                    custom_rows = []

                    for r in existing_rows:
                        old_id = r[0]
                        raw_name = str(r[1]).strip() if r[1] is not None else ""
                        clean_name = TextCleaner.remove_accents(raw_name.upper())

                        if clean_name in canonical_by_name:
                            can_id, can_name, can_abrev = canonical_by_name[clean_name]
                            matched_names.add(clean_name)
                            if old_id != can_id:
                                id_remap[old_id] = can_id
                        else:
                            custom_rows.append((old_id, raw_name))

                    # Reasignar IDs para filas custom que colisionen con los IDs canónicos
                    next_custom_id = (max(canonical_ids) + 1) if canonical_ids else 1
                    for old_id, raw_name in custom_rows:
                        if old_id in canonical_ids:
                            while next_custom_id in canonical_ids or next_custom_id in id_remap.values():
                                next_custom_id += 1
                            id_remap[old_id] = next_custom_id
                            next_custom_id += 1

                    # 5. Si hay discrepancias de IDs, estandarizar tabla y reasignar relaciones en direcciones
                    if id_remap:
                        # Verificar si existe la tabla de direcciones y contiene la columna foránea
                        dir_col_check = session.execute(text("""
                            SELECT COUNT(*) 
                            FROM information_schema.columns 
                            WHERE table_schema = :schema AND table_name = :table AND column_name = :col;
                        """), {"schema": target_schema, "table": dir_table, "col": dir_col}).scalar()

                        if dir_col_check and dir_col_check > 0:
                            # Remover temporalmente foreign keys de dir_table hacia table_name
                            try:
                                session.execute(text(f"""
                                DO $$
                                DECLARE
                                    r RECORD;
                                BEGIN
                                    FOR r IN (
                                        SELECT tc.constraint_name
                                        FROM information_schema.table_constraints tc
                                        JOIN information_schema.key_column_usage kcu
                                          ON tc.constraint_name = kcu.constraint_name
                                          AND tc.table_schema = kcu.table_schema
                                        WHERE tc.table_schema = '{target_schema}'
                                          AND tc.table_name = '{dir_table}'
                                          AND kcu.column_name = '{dir_col}'
                                          AND tc.constraint_type = 'FOREIGN KEY'
                                    ) LOOP
                                        EXECUTE 'ALTER TABLE "{target_schema}"."{dir_table}" DROP CONSTRAINT IF EXISTS ' || quote_ident(r.constraint_name);
                                    END LOOP;
                                END $$;
                                """))
                            except Exception as e_fk:
                                logger.debug("Aviso al remover FK temporal en %s.%s: %s", target_schema, dir_table, e_fk)

                            # Actualizar atómicamente la columna en direcciones con CASE
                            when_clauses = " ".join([f"WHEN {old} THEN {new}" for old, new in id_remap.items()])
                            in_clause = ", ".join(str(old) for old in id_remap.keys())

                            update_dir_sql = text(f"""
                                UPDATE "{target_schema}"."{dir_table}"
                                SET "{dir_col}" = CASE "{dir_col}"
                                    {when_clauses}
                                    ELSE "{dir_col}"
                                END
                                WHERE "{dir_col}" IN ({in_clause});
                            """)
                            res_dir = session.execute(update_dir_sql)
                            status["fk_remapped_records"] = res_dir.rowcount if hasattr(res_dir, "rowcount") and res_dir.rowcount is not None and res_dir.rowcount >= 0 else 0

                        # Vaciar y reconstruir la tabla categorizable con los IDs canónicos estándar
                        session.execute(text(f'DELETE FROM "{target_schema}"."{table_name}";'))

                        for def_id, def_name, def_abrev in official_list:
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."{table_name}" ("{pk_col}", "{name_col}", abreviatura)
                                VALUES (:id, :name, :abrev);
                            """), {"id": def_id, "name": def_name, "abrev": def_abrev})

                        for old_id, raw_name in custom_rows:
                            new_id = id_remap.get(old_id, old_id)
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."{table_name}" ("{pk_col}", "{name_col}", abreviatura)
                                VALUES (:id, :name, NULL);
                            """), {"id": new_id, "name": raw_name})

                        if dir_col_check and dir_col_check > 0:
                            session.execute(text(f"""
                            DO $$
                            BEGIN
                                IF NOT EXISTS (
                                    SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_{table_name}'
                                ) THEN
                                    ALTER TABLE "{target_schema}"."{dir_table}"
                                        ADD CONSTRAINT fk_in_place_{table_name}
                                        FOREIGN KEY ("{dir_col}") REFERENCES "{target_schema}"."{table_name}"("{pk_col}")
                                        ON UPDATE CASCADE ON DELETE SET NULL;
                                END IF;
                            EXCEPTION
                                WHEN duplicate_object THEN NULL;
                                WHEN undefined_table THEN NULL;
                                WHEN others THEN NULL;
                            END $$;
                            """))

                        status["remapped_records"] = len(id_remap)
                        status["added_records"] = len(official_list) - len(matched_names)
                        status["total_records"] = len(official_list) + len(custom_rows)
                    else:
                        # No hay remapeo necesario: solo insertar los oficiales faltantes
                        added_count = 0
                        for def_id, def_name, def_abrev in official_list:
                            clean_def = TextCleaner.remove_accents(def_name.strip().upper())
                            if clean_def in matched_names:
                                continue
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."{table_name}" ("{pk_col}", "{name_col}", abreviatura)
                                VALUES (:id, :name, :abrev);
                            """), {"id": def_id, "name": def_name, "abrev": def_abrev})
                            added_count += 1

                        status["added_records"] = added_count
                        status["total_records"] = len(existing_rows) + added_count

                    return status

                # Procesar tipos_via y tipos_zona
                results[t_via] = _sync_single_catalog(t_via, "id_tipo_via", "nombre_tipo_via", col_via, official_vias)
                results[t_zona] = _sync_single_catalog(t_zona, "id_tipo_zona", "nombre_tipo_zona", col_zona, official_zonas)

            # Sincronizar tablas maestras terciarias vias y zonas
            physical_results = self.ensure_vias_and_zonas_tables_exist(schema=target_schema)
            results.update(physical_results)

            logger.info(
                "Sincronización estándar de catálogos en '%s': %s (existían %d, remapeados %d, agregados %d, total %d), %s (existían %d, remapeados %d, agregados %d, total %d)",
                target_schema,
                t_via, results[t_via]["existing_records"], results[t_via]["remapped_records"], results[t_via]["added_records"], results[t_via]["total_records"],
                t_zona, results[t_zona]["existing_records"], results[t_zona]["remapped_records"], results[t_zona]["added_records"], results[t_zona]["total_records"],
            )
        except Exception as e:
            logger.error("Error al examinar/sincronizar catálogos en %s: %s", target_schema, e)
            raise

        return results

    def ensure_vias_and_zonas_tables_exist(
        self,
        schema: Optional[str] = None,
        table_vias: Optional[str] = None,
        table_zonas: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Asegura la creación y carga completa de las tablas terciarias maestras de vías y zonas físicas de Chiclayo."""
        from src.catalogs.catalog_manager import CatalogManager

        target_schema = schema or self.settings.schema
        t_vias = table_vias or self.settings.table_vias
        t_zonas = table_zonas or self.settings.table_zonas
        t_tipo_via = self.settings.table_tipo_via
        t_tipo_zona = self.settings.table_tipo_zona

        results = {
            t_vias: {"table_created": False, "records_seeded": 0, "total_records": 0},
            t_zonas: {"table_created": False, "records_seeded": 0, "total_records": 0},
        }

        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return results

        try:
            with self.get_session() as session:
                # 1. Tabla vias (id_via, id_tipo_via -> tipos_via, nom_via)
                vias_check = session.execute(text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": target_schema, "table": t_vias}).scalar()

                if not vias_check or vias_check == 0:
                    create_vias_sql = f"""
                    CREATE TABLE "{target_schema}"."{t_vias}" (
                        id_via              INTEGER NOT NULL,
                        id_tipo_via         INTEGER,
                        nom_via             VARCHAR(150) NOT NULL,
                        CONSTRAINT pk_{target_schema}_{t_vias} PRIMARY KEY (id_via),
                        CONSTRAINT fk_{target_schema}_{t_vias}_tipo FOREIGN KEY (id_tipo_via) REFERENCES "{target_schema}"."{t_tipo_via}"(id_tipo_via) ON UPDATE CASCADE ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_vias}_nom ON "{target_schema}"."{t_vias}" (nom_via);
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_vias}_tipo ON "{target_schema}"."{t_vias}" (id_tipo_via);
                    """
                    session.execute(text(create_vias_sql))
                    results[t_vias]["table_created"] = True
                else:
                    # Depurar columnas obsoletas y asegurar relación con tipos_via
                    session.execute(text(f"""
                        ALTER TABLE "{target_schema}"."{t_vias}"
                            ADD COLUMN IF NOT EXISTS id_tipo_via INTEGER,
                            DROP COLUMN IF EXISTS codigo_via,
                            DROP COLUMN IF EXISTS clasificacion_vial,
                            DROP COLUMN IF EXISTS jurisdiccion;

                        DO $$
                        BEGIN
                            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_{target_schema}_{t_vias}_tipo') THEN
                                ALTER TABLE "{target_schema}"."{t_vias}"
                                    ADD CONSTRAINT fk_{target_schema}_{t_vias}_tipo
                                    FOREIGN KEY (id_tipo_via) REFERENCES "{target_schema}"."{t_tipo_via}"(id_tipo_via)
                                    ON UPDATE CASCADE ON DELETE SET NULL;
                            END IF;
                        EXCEPTION WHEN OTHERS THEN NULL;
                        END $$;
                    """))

                # Verificar si tiene registros
                vias_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."{t_vias}";')).scalar() or 0
                if vias_count == 0:
                    vias_tuples = CatalogManager.get_official_physical_vias_tuples()
                    insert_vias_sql = text(f"""
                        INSERT INTO "{target_schema}"."{t_vias}" (id_via, id_tipo_via, nom_via)
                        VALUES (:id_via, :id_tipo_via, :nom_via)
                        ON CONFLICT (id_via) DO NOTHING;
                    """)
                    session.execute(
                        insert_vias_sql,
                        [{"id_via": item[0], "id_tipo_via": item[1], "nom_via": item[2]} for item in vias_tuples],
                    )
                    results[t_vias]["records_seeded"] = len(vias_tuples)
                    results[t_vias]["total_records"] = len(vias_tuples)
                else:
                    results[t_vias]["total_records"] = vias_count

                # 2. Tabla zonas (id_zona, id_tipo_zona -> tipos_zona, nom_zona)
                zonas_check = session.execute(text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": target_schema, "table": t_zonas}).scalar()

                if not zonas_check or zonas_check == 0:
                    create_zonas_sql = f"""
                    CREATE TABLE "{target_schema}"."{t_zonas}" (
                        id_zona             INTEGER NOT NULL,
                        id_tipo_zona        INTEGER,
                        nom_zona            VARCHAR(150) NOT NULL,
                        CONSTRAINT pk_{target_schema}_{t_zonas} PRIMARY KEY (id_zona),
                        CONSTRAINT fk_{target_schema}_{t_zonas}_tipo FOREIGN KEY (id_tipo_zona) REFERENCES "{target_schema}"."{t_tipo_zona}"(id_tipo_zona) ON UPDATE CASCADE ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_zonas}_nom ON "{target_schema}"."{t_zonas}" (nom_zona);
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_zonas}_tipo ON "{target_schema}"."{t_zonas}" (id_tipo_zona);
                    """
                    session.execute(text(create_zonas_sql))
                    results[t_zonas]["table_created"] = True
                else:
                    # Depurar columnas obsoletas y asegurar relación con tipos_zona
                    session.execute(text(f"""
                        ALTER TABLE "{target_schema}"."{t_zonas}"
                            ADD COLUMN IF NOT EXISTS id_tipo_zona INTEGER,
                            DROP COLUMN IF EXISTS codigo_zona,
                            DROP COLUMN IF EXISTS sector_catastral,
                            DROP COLUMN IF EXISTS condicion;

                        DO $$
                        BEGIN
                            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_{target_schema}_{t_zonas}_tipo') THEN
                                ALTER TABLE "{target_schema}"."{t_zonas}"
                                    ADD CONSTRAINT fk_{target_schema}_{t_zonas}_tipo
                                    FOREIGN KEY (id_tipo_zona) REFERENCES "{target_schema}"."{t_tipo_zona}"(id_tipo_zona)
                                    ON UPDATE CASCADE ON DELETE SET NULL;
                            END IF;
                        EXCEPTION WHEN OTHERS THEN NULL;
                        END $$;
                    """))

                zonas_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."{t_zonas}";')).scalar() or 0
                if zonas_count == 0:
                    zonas_tuples = CatalogManager.get_official_physical_zonas_tuples()
                    insert_zonas_sql = text(f"""
                        INSERT INTO "{target_schema}"."{t_zonas}" (id_zona, id_tipo_zona, nom_zona)
                        VALUES (:id_zona, :id_tipo_zona, :nom_zona)
                        ON CONFLICT (id_zona) DO NOTHING;
                    """)
                    session.execute(
                        insert_zonas_sql,
                        [{"id_zona": item[0], "id_tipo_zona": item[1], "nom_zona": item[2]} for item in zonas_tuples],
                    )
                    results[t_zonas]["records_seeded"] = len(zonas_tuples)
                    results[t_zonas]["total_records"] = len(zonas_tuples)
                else:
                    results[t_zonas]["total_records"] = zonas_count

            logger.info(
                "Tablas terciarias maestras sincronizadas en '%s': %s (%d registros), %s (%d registros)",
                target_schema,
                t_vias,
                results[t_vias]["total_records"],
                t_zonas,
                results[t_zonas]["total_records"],
            )
        except Exception as e:
            logger.error("Error al sincronizar tablas terciarias maestras en %s: %s", target_schema, e)
            raise

        return results

    def ensure_in_place_columns(
        self,
        schema: str,
        table: str,
        column_names: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Agrega dinámicamente las columnas normalizadas a la tabla existente si aún no están creadas
        y asegura las referencias foráneas hacia los catálogos.

        Args:
            schema: Esquema de la tabla.
            table: Nombre de la tabla receptora en sitio.
            column_names: Diccionario con los nombres de columnas a crear.

        Returns:
            Lista de columnas que fueron agregadas o que ya existen.
        """
        cols = column_names or {
            "id_via": self.settings.col_id_via,
            "num_via": self.settings.col_num_via,
            "id_zona": self.settings.col_id_zona,
            "manzana": self.settings.col_manzana,
            "lote": self.settings.col_lote,
            "slote": self.settings.col_slote,
            "referencia": self.settings.col_referencia,
            "es_procesado": self.settings.col_es_procesado,
            "observacion": self.settings.col_observacion,
        }

        # 1. Crear las columnas consolidadas si no existen
        col_id = self.settings.id_col
        ddl = f"""
        ALTER TABLE "{schema}"."{table}"
            ADD COLUMN IF NOT EXISTS "{cols['id_via']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['num_via']}" VARCHAR(50),
            ADD COLUMN IF NOT EXISTS "{cols['id_zona']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['manzana']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['lote']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['slote']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['referencia']}" VARCHAR(255),
            ADD COLUMN IF NOT EXISTS "{cols['es_procesado']}" BOOLEAN DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS "{cols['observacion']}" TEXT;

        -- Asegurar que es_procesado arranque como NULL (Pendiente) para registros no evaluados
        ALTER TABLE "{schema}"."{table}"
            ALTER COLUMN "{cols['es_procesado']}" DROP DEFAULT;

        -- Partial Index para consultas ultrarrápidas de registros pendientes en tablas de 42,000+ filas
        CREATE INDEX IF NOT EXISTS "idx_{table}_pendientes"
            ON "{schema}"."{table}" ("{col_id}")
            WHERE "{cols['es_procesado']}" IS NULL;

        -- Depurar columnas de texto redundantes para consolidar a 3NF
        ALTER TABLE "{schema}"."{table}"
            DROP COLUMN IF EXISTS tipo_via,
            DROP COLUMN IF EXISTS nom_via,
            DROP COLUMN IF EXISTS tipo_zona,
            DROP COLUMN IF EXISTS nom_zona;
        """

        try:
            with self.get_session() as session:
                session.execute(text(ddl))

                # Agregar llaves foráneas hacia las tablas maestras físicas
                t_vias = self.settings.table_vias
                t_zonas = self.settings.table_zonas
                fk_ddl = f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_id_via'
                    ) THEN
                        ALTER TABLE "{schema}"."{table}"
                            ADD CONSTRAINT fk_in_place_id_via
                            FOREIGN KEY ("{cols['id_via']}") REFERENCES "{schema}"."{t_vias}"(id_via)
                            ON UPDATE CASCADE ON DELETE SET NULL;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_id_zona'
                    ) THEN
                        ALTER TABLE "{schema}"."{table}"
                            ADD CONSTRAINT fk_in_place_id_zona
                            FOREIGN KEY ("{cols['id_zona']}") REFERENCES "{schema}"."{t_zonas}"(id_zona)
                            ON UPDATE CASCADE ON DELETE SET NULL;
                    END IF;
                EXCEPTION
                    WHEN duplicate_object THEN NULL;
                    WHEN undefined_table THEN NULL;
                    WHEN others THEN NULL;
                END $$;
                """
                session.execute(text(fk_ddl))

            logger.info(
                "Columnas normalizadas verificadas/agregadas in-place en %s.%s: %s",
                schema,
                table,
                list(cols.values()),
            )
            return list(cols.values())
        except Exception as e:
            logger.error("Error al alterar tabla in-place %s.%s: %s", schema, table, e)
            raise

    def table_exists(self, table: str, schema: Optional[str] = None) -> bool:
        """Comprueba si una tabla existe en el esquema especificado."""
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return False
        target_schema = schema or self.settings.schema
        try:
            with self.get_session() as session:
                count = session.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": target_schema, "table": table}).scalar()
                return bool(count and count > 0)
        except Exception as e:
            logger.debug("Error comprobando existencia de tabla %s.%s: %s", target_schema, table, e)
            return False

    def get_table_columns(self, table: str, schema: Optional[str] = None) -> List[str]:
        """Retorna la lista de columnas existentes en una tabla."""
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return []
        target_schema = schema or self.settings.schema
        try:
            with self.get_session() as session:
                rows = session.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table
                    ORDER BY ordinal_position ASC;
                """), {"schema": target_schema, "table": table}).fetchall()
                return [r[0] for r in rows]
        except Exception as e:
            logger.debug("Error obteniendo columnas de %s.%s: %s", target_schema, table, e)
            return []

    def ensure_v2_source_columns(self, schema: str, table: str) -> List[str]:
        """Asegura que la tabla fuente (ej. tb_xxx) cuente con las columnas requeridas para vincular
        a la arquitectura V2: dire_id (FK a tb_direccion), es_procesado y observacion."""
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return []

        existing_cols = {c.lower() for c in self.get_table_columns(table, schema)}
        
        has_xxxx = any(c.startswith("xxxx_") for c in existing_cols)
        col_proc = "xxxx_es_procesado" if has_xxxx or "xxxx_es_procesado" in existing_cols else "es_procesado"
        col_obs = "xxxx_observacion_ia" if has_xxxx or "xxxx_observacion_ia" in existing_cols else "observacion"

        ddl = f"""
        ALTER TABLE "{schema}"."{table}"
            ADD COLUMN IF NOT EXISTS "dire_id" BIGINT,
            ADD COLUMN IF NOT EXISTS "{col_proc}" BOOLEAN DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS "{col_obs}" TEXT;

        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_{table}_tb_direccion'
            ) THEN
                BEGIN
                    ALTER TABLE "{schema}"."{table}"
                        ADD CONSTRAINT fk_{table}_tb_direccion
                        FOREIGN KEY ("dire_id") REFERENCES "{schema}"."tb_direccion"("dire_id")
                        ON UPDATE CASCADE ON DELETE SET NULL;
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
            END IF;
        END $$;
        """
        try:
            with self.get_session() as session:
                session.execute(text(ddl))

                # Crear vista relacional dinámica para la tabla seleccionada por el usuario
                try:
                    view_ddl = f"""
                    CREATE OR REPLACE VIEW "{schema}"."v_{table}_normalizada" AS
                    SELECT 
                        orig.*,
                        d.dire_referencia,
                        d.dire_estado,
                        z.zona_id,
                        z.zona_nombre AS zona_oficial,
                        tz.tizo_nombre AS tipo_zona_oficial,
                        tz.tizo_abreviatura AS abrev_tipo_zona,
                        v1.via_id AS via_principal_id,
                        v1.via_nombre AS via_principal_nombre,
                        tv1.tivi_nombre AS tipo_via_principal,
                        dv1.divi_numero AS num_via_principal,
                        v2.via_id AS via_secundaria_id,
                        v2.via_nombre AS via_secundaria_nombre,
                        tv2.tivi_nombre AS tipo_via_secundaria,
                        dv2.divi_numero AS num_via_secundaria
                    FROM "{schema}"."{table}" orig
                    LEFT JOIN "{schema}"."tb_direccion" d ON orig."dire_id" = d.dire_id
                    LEFT JOIN "{schema}"."tb_zona" z ON d.zona_id = z.zona_id
                    LEFT JOIN "{schema}"."tb_tipo_zona" tz ON z.tizo_id = tz.tizo_id
                    LEFT JOIN "{schema}"."tb_direccion_via" dv1 ON d.dire_id = dv1.dire_id AND dv1.divi_orden = 1
                    LEFT JOIN "{schema}"."tb_via" v1 ON dv1.via_id = v1.via_id
                    LEFT JOIN "{schema}"."tb_tipo_via" tv1 ON v1.tivi_id = tv1.tivi_id
                    LEFT JOIN "{schema}"."tb_direccion_via" dv2 ON d.dire_id = dv2.dire_id AND dv2.divi_orden = 2
                    LEFT JOIN "{schema}"."tb_via" v2 ON dv2.via_id = v2.via_id
                    LEFT JOIN "{schema}"."tb_tipo_via" tv2 ON v2.tivi_id = tv2.tivi_id;

                    CREATE OR REPLACE VIEW "{schema}"."v_direcciones_normalizadas" AS
                    SELECT * FROM "{schema}"."v_{table}_normalizada";
                    """
                    session.execute(text(view_ddl))
                except Exception as ex_view:
                    logger.debug("Aviso al crear vista dinámica de normalización en %s.%s: %s", schema, table, ex_view)

            return ["dire_id", col_proc, col_obs]
        except Exception as e:
            logger.debug("Aviso al asegurar columnas fuente V2 en %s.%s: %s", schema, table, e)
            return []

    def ensure_v2_tables_exist(self, schema: Optional[str] = None) -> Dict[str, Any]:
        """Asegura que la arquitectura relacional V2 completa exista en el esquema objetivo:
        - tb_tipo_via, tb_via
        - tb_tipo_zona (los 28 tipos de zona oficiales), tb_zona
        - tb_direccion, tb_direccion_via
        - tb_componente_direccion, tb_contenido_componente_direccion
        - tb_tipo_modulo, tb_direccion_tipo_modulo
        - tb_xxx (tabla de prueba representativa)
        - Vista v_direcciones_v2
        """
        from src.catalogs.catalog_manager import CatalogManager

        target_schema = schema or self.settings.schema
        results: Dict[str, Any] = {
            "schema": target_schema,
            "created_tables": [],
            "seeded_tables": {},
            "status": "OK",
        }

        if not SQLALCHEMY_AVAILABLE or not self._engine:
            results["status"] = "NO_ENGINE"
            return results

        tables_to_check = [
            "tb_tipo_via", "tb_via", "tb_tipo_zona", "tb_zona",
            "tb_direccion", "tb_direccion_via", "tb_componente_direccion",
            "tb_contenido_componente_direccion", "tb_tipo_modulo",
            "tb_direccion_tipo_modulo"
        ]

        missing = []
        for t in tables_to_check:
            if not self.table_exists(t, target_schema):
                missing.append(t)

        if missing:
            sql_file = Path("scripts_data_base/06_crear_estructura_v2_normalizada.sql")
            if sql_file.exists():
                logger.info("Ejecutando script de estructura relacional V2 en %s...", target_schema)
                self.execute_sql_file(str(sql_file), target_schema=target_schema)
                results["created_tables"] = missing

        try:
            with self.get_session() as session:
                # 1. tb_tipo_via
                # 1. tb_tipo_via (12 tipos oficiales)
                vias_tipos = CatalogManager.get_official_vias_tuples()
                tv_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_tipo_via";')).scalar() or 0
                if tv_count < len(vias_tipos):
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_tipo_via" (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                        VALUES (:id, :nombre, :abrev, 'ACT')
                        ON CONFLICT (tivi_id) DO UPDATE
                        SET tivi_nombre = EXCLUDED.tivi_nombre, tivi_abreviatura = EXCLUDED.tivi_abreviatura;
                    """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])
                    results["seeded_tables"]["tb_tipo_via"] = len(vias_tipos)

                # 2. tb_tipo_zona (Exactamente los 28 tipos oficiales)
                zonas_tipos = CatalogManager.get_official_zonas_tuples()
                tz_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_tipo_zona";')).scalar() or 0
                if tz_count < len(zonas_tipos):
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_tipo_zona" (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                        VALUES (:id, :nombre, :abrev, 'ACT')
                        ON CONFLICT (tizo_id) DO UPDATE
                        SET tizo_nombre = EXCLUDED.tizo_nombre, tizo_abreviatura = EXCLUDED.tizo_abreviatura;
                    """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])
                    results["seeded_tables"]["tb_tipo_zona"] = len(zonas_tipos)

                # 3. tb_via (Catálogo completo de 2,935 vías oficiales de Chiclayo)
                phys_vias = CatalogManager.get_official_physical_vias_tuples()
                via_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_via";')).scalar() or 0
                if via_count < len(phys_vias):
                    chunk_size = 400
                    for i in range(0, len(phys_vias), chunk_size):
                        chunk = phys_vias[i:i + chunk_size]
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_via" (via_id, tivi_id, via_nombre, via_estado)
                            VALUES (:via_id, :tivi_id, :via_nombre, 'ACT')
                            ON CONFLICT (via_id) DO UPDATE
                            SET via_nombre = EXCLUDED.via_nombre, tivi_id = EXCLUDED.tivi_id, via_estado = 'ACT';
                        """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])
                    results["seeded_tables"]["tb_via"] = len(phys_vias)
                    logger.info("Catálogo maestro sembrado en %s: %d vías oficiales de Chiclayo", target_schema, len(phys_vias))

                # 4. tb_zona (Catálogo completo de 460 zonas oficiales de Chiclayo)
                phys_zonas = CatalogManager.get_official_physical_zonas_tuples()
                zona_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_zona";')).scalar() or 0
                if zona_count < len(phys_zonas):
                    chunk_size = 200
                    for i in range(0, len(phys_zonas), chunk_size):
                        chunk = phys_zonas[i:i + chunk_size]
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_zona" (zona_id, tizo_id, zona_nombre, zona_estado)
                            VALUES (:zona_id, :tizo_id, :zona_nombre, 'ACT')
                            ON CONFLICT (zona_id) DO UPDATE
                            SET zona_nombre = EXCLUDED.zona_nombre, tizo_id = EXCLUDED.tizo_id, zona_estado = 'ACT';
                        """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])
                    results["seeded_tables"]["tb_zona"] = len(phys_zonas)
                    logger.info("Catálogo maestro sembrado en %s: %d zonas oficiales de Chiclayo", target_schema, len(phys_zonas))

                # 5. tb_componente_direccion
                comps = CatalogManager.get_default_componentes_tuples()
                comp_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_componente_direccion";')).scalar() or 0
                if comp_count < len(comps):
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_componente_direccion" (codi_id, codi_nombre, codi_es_urbano, codi_estado)
                        VALUES (:codi_id, :codi_nombre, :codi_es_urbano, :codi_estado)
                        ON CONFLICT (codi_id) DO UPDATE
                        SET codi_nombre = EXCLUDED.codi_nombre, codi_es_urbano = EXCLUDED.codi_es_urbano;
                    """), [{"codi_id": c[0], "codi_nombre": c[1], "codi_es_urbano": c[2], "codi_estado": c[3]} for c in comps])
                    results["seeded_tables"]["tb_componente_direccion"] = len(comps)

                # 6. tb_tipo_modulo
                mods = CatalogManager.get_default_tipo_modulo_tuples()
                mod_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_tipo_modulo";')).scalar() or 0
                if mod_count < len(mods):
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_tipo_modulo" (timo_id, timo_nombre, timo_estado)
                        VALUES (:timo_id, :timo_nombre, :timo_estado)
                        ON CONFLICT (timo_id) DO UPDATE
                        SET timo_nombre = EXCLUDED.timo_nombre;
                    """), [{"timo_id": m[0], "timo_nombre": m[1], "timo_estado": m[2]} for m in mods])
                    results["seeded_tables"]["tb_tipo_modulo"] = len(mods)

                # 7. Ajustar secuencias de PKs
                try:
                    session.execute(text(f"""
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_tipo_via"', 'tivi_id'), COALESCE(MAX(tivi_id), 1)) FROM "{target_schema}"."tb_tipo_via";
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_tipo_zona"', 'tizo_id'), COALESCE(MAX(tizo_id), 1)) FROM "{target_schema}"."tb_tipo_zona";
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_via"', 'via_id'), COALESCE(MAX(via_id), 1)) FROM "{target_schema}"."tb_via";
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_zona"', 'zona_id'), COALESCE(MAX(zona_id), 1)) FROM "{target_schema}"."tb_zona";
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_componente_direccion"', 'codi_id'), COALESCE(MAX(codi_id), 1)) FROM "{target_schema}"."tb_componente_direccion";
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_tipo_modulo"', 'timo_id'), COALESCE(MAX(timo_id), 1)) FROM "{target_schema}"."tb_tipo_modulo";
                    """))
                except Exception as seq_err:
                    logger.debug("Aviso al sincronizar secuencias en %s: %s", target_schema, seq_err)

        except Exception as e:
            logger.error("Error al verificar/sembrar datos semilla V2 en %s: %s", target_schema, e)

        return results

    def seed_v2_catalogs(self, schema: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Importa y siembra forzosamente la totalidad de los catálogos oficiales V2
        (2,935 vías oficiales, 460 zonas oficiales, 12 tipos de vía y 28 tipos de zona).
        """
        from src.catalogs.catalog_manager import CatalogManager

        target_schema = schema or self.settings.schema
        self.ensure_v2_tables_exist(target_schema)

        res: Dict[str, Any] = {"schema": target_schema, "status": "OK"}
        with self.get_session() as session:
            phys_vias = CatalogManager.get_official_physical_vias_tuples()
            phys_zonas = CatalogManager.get_official_physical_zonas_tuples()
            vias_tipos = CatalogManager.get_official_vias_tuples()
            zonas_tipos = CatalogManager.get_official_zonas_tuples()

            # Forzar importación completa de tb_tipo_via
            session.execute(text(f"""
                INSERT INTO "{target_schema}"."tb_tipo_via" (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                VALUES (:id, :nombre, :abrev, 'ACT')
                ON CONFLICT (tivi_id) DO UPDATE
                SET tivi_nombre = EXCLUDED.tivi_nombre, tivi_abreviatura = EXCLUDED.tivi_abreviatura;
            """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])

            # Forzar importación completa de tb_tipo_zona
            session.execute(text(f"""
                INSERT INTO "{target_schema}"."tb_tipo_zona" (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                VALUES (:id, :nombre, :abrev, 'ACT')
                ON CONFLICT (tizo_id) DO UPDATE
                SET tizo_nombre = EXCLUDED.tizo_nombre, tizo_abreviatura = EXCLUDED.tizo_abreviatura;
            """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])

            # Forzar importación completa de tb_via
            chunk_size = 400
            for i in range(0, len(phys_vias), chunk_size):
                chunk = phys_vias[i:i + chunk_size]
                session.execute(text(f"""
                    INSERT INTO "{target_schema}"."tb_via" (via_id, tivi_id, via_nombre, via_estado)
                    VALUES (:via_id, :tivi_id, :via_nombre, 'ACT')
                    ON CONFLICT (via_id) DO UPDATE
                    SET via_nombre = EXCLUDED.via_nombre, tivi_id = EXCLUDED.tivi_id, via_estado = 'ACT';
                """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])

            # Forzar importación completa de tb_zona
            chunk_size = 200
            for i in range(0, len(phys_zonas), chunk_size):
                chunk = phys_zonas[i:i + chunk_size]
                session.execute(text(f"""
                    INSERT INTO "{target_schema}"."tb_zona" (zona_id, tizo_id, zona_nombre, zona_estado)
                    VALUES (:zona_id, :tizo_id, :zona_nombre, 'ACT')
                    ON CONFLICT (zona_id) DO UPDATE
                    SET zona_nombre = EXCLUDED.zona_nombre, tizo_id = EXCLUDED.tizo_id, zona_estado = 'ACT';
                """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])

            res["tb_tipo_via_count"] = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_tipo_via";')).scalar() or 0
            res["tb_tipo_zona_count"] = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_tipo_zona";')).scalar() or 0
            res["tb_via_count"] = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_via";')).scalar() or 0
            res["tb_zona_count"] = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."tb_zona";')).scalar() or 0

        return res

    def execute_sql_file(self, file_path: str, target_schema: Optional[str] = None) -> bool:
        """Ejecuta un script SQL en la base de datos, configurando el search_path si se provee."""
        path = Path(file_path)
        if not path.exists():
            logger.error("No existe el archivo SQL en %s", file_path)
            return False

        schema = target_schema or self.settings.target_schema

        try:
            sql_content = path.read_text(encoding="utf-8")
            with self.get_session() as session:
                # Establecer schema de trabajo para el script
                session.execute(text(f'SET search_path TO "{schema}", public;'))
                session.execute(text(sql_content))
            logger.info("Script SQL ejecutado con éxito: %s en esquema %s", path.name, schema)
            return True
        except Exception as e:
            logger.error("Error al ejecutar script SQL %s: %s", file_path, e)
            return False

    @contextmanager
    def get_session(self):
        """Generador de contexto para sesiones transaccionales seguras."""
        if not self._session_factory:
            raise RuntimeError("SessionFactory no inicializada. Verifica la conexión a PostgreSQL.")

        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
