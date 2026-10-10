"""Servicio de conexión, inspección de esquemas y ejecución DDL/DML con PostgreSQL."""

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
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
        self._v2_verified_schemas: Set[str] = set()
        self._tb_direccion_verified: Set[str] = set()

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
            logger.debug("Aviso al consultar esquemas en PostgreSQL: %s", e)
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
            logger.debug(result["message"])

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

            # Asegurar columnas de auditoría en tablas maestras (idempotente)
            try:
                self.ensure_catalogs_audit_columns(target_schema)
            except Exception as e_audit:
                logger.debug("Aviso al verificar columnas de auditoría en %s: %s", target_schema, e_audit)


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
            ADD COLUMN IF NOT EXISTS "{cols['slote']}" VARCHAR(100),
            ADD COLUMN IF NOT EXISTS "{cols['referencia']}" VARCHAR(255),
            ADD COLUMN IF NOT EXISTS "{cols['es_procesado']}" BOOLEAN DEFAULT NULL,
            ADD COLUMN IF NOT EXISTS "{cols['observacion']}" TEXT;

        -- Ampliar slote a VARCHAR(100) si existía previamente como VARCHAR(20)
        ALTER TABLE "{schema}"."{table}"
            ALTER COLUMN "{cols['slote']}" TYPE VARCHAR(100);

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
            dialect_name = getattr(self._engine.dialect, "name", "")
            with self.get_session() as session:
                if dialect_name == "sqlite":
                    count = session.execute(text("""
                        SELECT COUNT(*) FROM sqlite_master 
                        WHERE type='table' AND LOWER(name) = LOWER(:table);
                    """), {"table": table}).scalar()
                    return bool(count and count > 0)
                else:
                    count = session.execute(text("""
                        SELECT COUNT(*) FROM information_schema.tables
                        WHERE table_schema = :schema AND LOWER(table_name) = LOWER(:table);
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
            dialect_name = getattr(self._engine.dialect, "name", "")
            with self.get_session() as session:
                if dialect_name == "sqlite":
                    rows = session.execute(text(f"PRAGMA table_info({table});")).fetchall()
                    return [r[1] for r in rows]
                else:
                    rows = session.execute(text("""
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = :schema AND LOWER(table_name) = LOWER(:table)
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
        """
        try:
            with self.get_session() as session:
                session.execute(text(ddl))

                # Si la tabla origen posee columna slote/sublote, asegurar que soporte hasta 100 caracteres
                col_slt = next((c for c in existing_cols if c in ("slote", "sublote", "xxxx_slote")), None)
                if col_slt:
                    try:
                        session.execute(text(f"""
                            ALTER TABLE "{schema}"."{table}"
                            ALTER COLUMN "{col_slt}" TYPE VARCHAR(100);
                        """))
                    except Exception as ex_slt:
                        logger.debug("Aviso al ampliar columna %s en %s.%s: %s", col_slt, schema, table, ex_slt)

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
                        dv2.divi_numero AS num_via_secundaria,
                        v3.via_id AS via_3_id,
                        v3.via_nombre AS via_3_nombre,
                        tv3.tivi_nombre AS tipo_via_3,
                        dv3.divi_numero AS num_via_3
                    FROM "{schema}"."{table}" orig
                    LEFT JOIN "{schema}"."tb_direccion" d ON orig."dire_id" = d.dire_id
                    LEFT JOIN "{schema}"."tb_zona" z ON d.zona_id = z.zona_id
                    LEFT JOIN "{schema}"."tb_tipo_zona" tz ON z.tizo_id = tz.tizo_id
                    LEFT JOIN "{schema}"."tb_direccion_via" dv1 ON d.dire_id = dv1.dire_id AND dv1.divi_orden = 1
                    LEFT JOIN "{schema}"."tb_via" v1 ON dv1.via_id = v1.via_id
                    LEFT JOIN "{schema}"."tb_tipo_via" tv1 ON v1.tivi_id = tv1.tivi_id
                    LEFT JOIN "{schema}"."tb_direccion_via" dv2 ON d.dire_id = dv2.dire_id AND dv2.divi_orden = 2
                    LEFT JOIN "{schema}"."tb_via" v2 ON dv2.via_id = v2.via_id
                    LEFT JOIN "{schema}"."tb_tipo_via" tv2 ON v2.tivi_id = tv2.tivi_id
                    LEFT JOIN "{schema}"."tb_direccion_via" dv3 ON d.dire_id = dv3.dire_id AND dv3.divi_orden = 3
                    LEFT JOIN "{schema}"."tb_via" v3 ON dv3.via_id = v3.via_id
                    LEFT JOIN "{schema}"."tb_tipo_via" tv3 ON v3.tivi_id = tv3.tivi_id;

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

    def ensure_modulo_pk_constraint(self, schema: Optional[str] = None) -> bool:
        """Verifica y migra la clave primaria de tb_direccion_tipo_modulo a (dire_id, timo_id, ditm_nombre).
        Garantiza compatibilidad con inserciones múltiples de interiores y cláusulas ON CONFLICT en PostgreSQL.
        """
        target_schema = schema or self.settings.schema
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return False

        try:
            with self.get_session() as session:
                # 1. Comprobar si la tabla existe en el esquema
                table_check = session.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = :schema AND table_name = 'tb_direccion_tipo_modulo';
                """), {"schema": target_schema}).scalar()
                if not table_check or table_check == 0:
                    return False

                # 2. Consultar columnas que conforman la clave primaria actual
                pk_rows = session.execute(text("""
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_schema = :schema
                      AND tc.table_name = 'tb_direccion_tipo_modulo'
                      AND tc.constraint_type = 'PRIMARY KEY';
                """), {"schema": target_schema}).fetchall()
                current_pk_cols = {r[0].lower() for r in pk_rows}

                # Si ya incluye las 3 columnas de la PK compuesta, está al día
                if {"dire_id", "timo_id", "ditm_nombre"}.issubset(current_pk_cols):
                    return True

                logger.info(
                    "Migrando clave primaria en %s.tb_direccion_tipo_modulo de %s a (dire_id, timo_id, ditm_nombre)...",
                    target_schema,
                    current_pk_cols,
                )

                # 3. Deduplicar filas si existiesen antes de crear la PK compuesta
                session.execute(text(f"""
                    DELETE FROM "{target_schema}"."tb_direccion_tipo_modulo" a
                    USING "{target_schema}"."tb_direccion_tipo_modulo" b
                    WHERE a.ctid < b.ctid
                      AND a.dire_id = b.dire_id
                      AND a.timo_id = b.timo_id
                      AND a.ditm_nombre = b.ditm_nombre;
                """))

                # 4. Obtener nombres de restricciones PK existentes para eliminarlas
                con_names = session.execute(text("""
                    SELECT tc.constraint_name
                    FROM information_schema.table_constraints tc
                    WHERE tc.table_schema = :schema
                      AND tc.table_name = 'tb_direccion_tipo_modulo'
                      AND tc.constraint_type = 'PRIMARY KEY';
                """), {"schema": target_schema}).fetchall()

                for c_row in con_names:
                    c_name = c_row[0]
                    session.execute(text(f"""
                        ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo"
                        DROP CONSTRAINT IF EXISTS "{c_name}" CASCADE;
                    """))

                # 5. Agregar la clave primaria compuesta definitiva
                session.execute(text(f"""
                    ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo"
                    ADD CONSTRAINT pk_tb_direccion_tipo_modulo PRIMARY KEY (dire_id, timo_id, ditm_nombre);
                """))

                # 6. Asegurar que ditm_estado sea VARCHAR(3)
                try:
                    session.execute(text(f"""
                        ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo"
                        ALTER COLUMN ditm_estado TYPE VARCHAR(3);
                    """))
                except Exception as ex_col:
                    logger.debug("Aviso al asegurar VARCHAR(3) en ditm_estado: %s", ex_col)

                # 7. Crear índice único de respaldo para ON CONFLICT
                session.execute(text(f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_tipo_modulo
                    ON "{target_schema}"."tb_direccion_tipo_modulo" (dire_id, timo_id, ditm_nombre);
                """))

                logger.info("Migración de PK en %s.tb_direccion_tipo_modulo completada exitosamente.", target_schema)
                return True
        except Exception as e:
            logger.error("Error al asegurar restricción PK en %s.tb_direccion_tipo_modulo: %s", target_schema, e)
            return False


    def ensure_estado_columns_varchar3(self, schema: Optional[str] = None) -> bool:
        """Asegura que todas las columnas de estado (*_estado) de las 10 tablas relacionales V2
        tengan tipo VARCHAR(3) y admitan los estados A, I, E, ACT, INA, ELI sin errores de truncamiento.
        """
        target_schema = schema or self.settings.schema
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return False

        tables_and_cols = [
            ("tb_tipo_via", "tivi_estado"),
            ("tb_via", "via_estado"),
            ("tb_tipo_zona", "tizo_estado"),
            ("tb_zona", "zona_estado"),
            ("tb_direccion", "dire_estado"),
            ("tb_direccion_via", "divi_estado"),
            ("tb_componente_direccion", "codi_estado"),
            ("tb_contenido_componente_direccion", "diti_estado"),
            ("tb_tipo_modulo", "timo_estado"),
            ("tb_direccion_tipo_modulo", "ditm_estado"),
        ]

        try:
            with self.get_session() as session:
                for tbl, col in tables_and_cols:
                    if not self.table_exists(tbl, target_schema):
                        continue
                    try:
                        col_len = session.execute(text("""
                            SELECT character_maximum_length
                            FROM information_schema.columns
                            WHERE table_schema = :schema AND table_name = :tbl AND column_name = :col;
                        """), {"schema": target_schema, "tbl": tbl, "col": col}).scalar()

                        if col_len is not None and col_len < 3:
                            logger.info(
                                "Ampliando columna %s.%s.%s de VARCHAR(%s) a VARCHAR(3)...",
                                target_schema, tbl, col, col_len
                            )
                            # Eliminar constraints CHECK antiguos sobre la columna si existieran
                            old_cons = session.execute(text("""
                                SELECT c.conname
                                FROM pg_constraint c
                                JOIN pg_namespace n ON n.oid = c.connamespace
                                JOIN pg_class cl ON cl.oid = c.conrelid
                                WHERE n.nspname = :schema
                                  AND cl.relname = :tbl
                                  AND c.contype = 'c'
                                  AND pg_get_constraintdef(c.oid) ILIKE :col_pattern;
                            """), {"schema": target_schema, "tbl": tbl, "col_pattern": f"%{col}%"}).fetchall()

                            for c_row in old_cons:
                                session.execute(text(f"""
                                    ALTER TABLE "{target_schema}"."{tbl}"
                                    DROP CONSTRAINT IF EXISTS "{c_row[0]}";
                                """))

                            session.execute(text(f"""
                                ALTER TABLE "{target_schema}"."{tbl}"
                                ALTER COLUMN "{col}" TYPE VARCHAR(3);
                            """))

                            session.execute(text(f"""
                                ALTER TABLE "{target_schema}"."{tbl}"
                                ADD CONSTRAINT "{tbl}_{col}_check"
                                CHECK ("{col}" IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI'));
                            """))
                    except Exception as ex_col:
                        logger.debug("Aviso al asegurar VARCHAR(3) en %s.%s: %s", tbl, col, ex_col)
            return True
        except Exception as e:
            logger.debug("Aviso al verificar columnas de estado en %s: %s", target_schema, e)
            return False

    def adapt_legacy_catalog_columns(self, schema: Optional[str] = None) -> bool:
        """Adapta tablas existentes que posean nomenclatura legacy (nombre_tipo_via, nom_via, etc.)
        para hacerlas compatibles con la arquitectura V2 y evitar fallas de UndefinedColumn."""
        target_schema = schema or self.settings.schema
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return False
        try:
            is_postgres = (self._engine.dialect.name == "postgresql")
        except Exception:
            is_postgres = False

        if not is_postgres:
            return True

        ddl = f"""
        DO $$
        BEGIN
            -- tb_tipo_via
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'nombre_tipo_via') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'tivi_nombre') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_via" RENAME COLUMN nombre_tipo_via TO tivi_nombre;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'id_tipo_via') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'tivi_id') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_via" RENAME COLUMN id_tipo_via TO tivi_id;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'abreviatura') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_via' AND column_name = 'tivi_abreviatura') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_via" RENAME COLUMN abreviatura TO tivi_abreviatura;
                END IF;
                ALTER TABLE "{target_schema}"."tb_tipo_via" ADD COLUMN IF NOT EXISTS tivi_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_tipo_via" ADD COLUMN IF NOT EXISTS tivi_nombre VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_tipo_via" ADD COLUMN IF NOT EXISTS tivi_abreviatura VARCHAR(20);
                ALTER TABLE "{target_schema}"."tb_tipo_via" ADD COLUMN IF NOT EXISTS tivi_estado VARCHAR(3) DEFAULT 'A';
                
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_tipo_via_nombre ON "{target_schema}"."tb_tipo_via" (tivi_nombre);
            END IF;

            -- tb_tipo_zona
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'nombre_tipo_zona') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'tizo_nombre') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_zona" RENAME COLUMN nombre_tipo_zona TO tizo_nombre;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'id_tipo_zona') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'tizo_id') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_zona" RENAME COLUMN id_tipo_zona TO tizo_id;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'abreviatura') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_zona' AND column_name = 'tizo_abreviatura') THEN
                    ALTER TABLE "{target_schema}"."tb_tipo_zona" RENAME COLUMN abreviatura TO tizo_abreviatura;
                END IF;
                ALTER TABLE "{target_schema}"."tb_tipo_zona" ADD COLUMN IF NOT EXISTS tizo_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_tipo_zona" ADD COLUMN IF NOT EXISTS tizo_nombre VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_tipo_zona" ADD COLUMN IF NOT EXISTS tizo_abreviatura VARCHAR(20);
                ALTER TABLE "{target_schema}"."tb_tipo_zona" ADD COLUMN IF NOT EXISTS tizo_estado VARCHAR(3) DEFAULT 'A';

                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_tipo_zona_nombre ON "{target_schema}"."tb_tipo_zona" (tizo_nombre);
            END IF;

            -- tb_via
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_via') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_via' AND column_name = 'nom_via') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_via' AND column_name = 'via_nombre') THEN
                    ALTER TABLE "{target_schema}"."tb_via" RENAME COLUMN nom_via TO via_nombre;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_via' AND column_name = 'id_tipo_via') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_via' AND column_name = 'tivi_id') THEN
                    ALTER TABLE "{target_schema}"."tb_via" RENAME COLUMN id_tipo_via TO tivi_id;
                END IF;
                ALTER TABLE "{target_schema}"."tb_via" ADD COLUMN IF NOT EXISTS via_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_via" ADD COLUMN IF NOT EXISTS tivi_id BIGINT;
                ALTER TABLE "{target_schema}"."tb_via" ADD COLUMN IF NOT EXISTS via_nombre VARCHAR(250);
                ALTER TABLE "{target_schema}"."tb_via" ADD COLUMN IF NOT EXISTS via_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_via" ALTER COLUMN via_nombre TYPE VARCHAR(250);
                ALTER TABLE "{target_schema}"."tb_via" ALTER COLUMN via_estado TYPE VARCHAR(3);
            END IF;

            -- tb_zona
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_zona') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_zona' AND column_name = 'nom_zona') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_zona' AND column_name = 'zona_nombre') THEN
                    ALTER TABLE "{target_schema}"."tb_zona" RENAME COLUMN nom_zona TO zona_nombre;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_zona' AND column_name = 'id_tipo_zona') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_zona' AND column_name = 'tizo_id') THEN
                    ALTER TABLE "{target_schema}"."tb_zona" RENAME COLUMN id_tipo_zona TO tizo_id;
                END IF;
                ALTER TABLE "{target_schema}"."tb_zona" ADD COLUMN IF NOT EXISTS zona_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_zona" ADD COLUMN IF NOT EXISTS tizo_id BIGINT;
                ALTER TABLE "{target_schema}"."tb_zona" ADD COLUMN IF NOT EXISTS zona_nombre VARCHAR(250);
                ALTER TABLE "{target_schema}"."tb_zona" ADD COLUMN IF NOT EXISTS zona_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_zona" ALTER COLUMN zona_nombre TYPE VARCHAR(250);
                ALTER TABLE "{target_schema}"."tb_zona" ALTER COLUMN zona_estado TYPE VARCHAR(3);
            END IF;

            -- tb_direccion
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion') THEN
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_referencia TEXT;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_esquema VARCHAR(500);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_tabla VARCHAR(500);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_tabla_id BIGINT;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_valor_origen VARCHAR(500);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS dire_es_procesado BOOLEAN;
                ALTER TABLE "{target_schema}"."tb_direccion" DROP COLUMN IF EXISTS fecha_proceso;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'resa_created_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'create_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN resa_created_at TO create_at;
                ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'resa_create_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'create_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN resa_create_at TO create_at;
                ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'created_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'create_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN created_at TO create_at;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'resa_updated_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'update_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN resa_updated_at TO update_at;
                ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'resa_update_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'update_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN resa_update_at TO update_at;
                ELSIF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'updated_at') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion' AND column_name = 'update_at') THEN
                    ALTER TABLE "{target_schema}"."tb_direccion" RENAME COLUMN updated_at TO update_at;
                END IF;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS usua_id BIGINT;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS usua_nombre VARCHAR(200);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS create_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS update_at TIMESTAMP WITHOUT TIME ZONE;
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS audit_user_pc VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS audit_nombre_pc VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS audit_ip VARCHAR(50);
                ALTER TABLE "{target_schema}"."tb_direccion" ADD COLUMN IF NOT EXISTS audit_mac_address VARCHAR(50);
                ALTER TABLE "{target_schema}"."tb_direccion" ALTER COLUMN dire_referencia TYPE TEXT;
                ALTER TABLE "{target_schema}"."tb_direccion" ALTER COLUMN dire_estado TYPE VARCHAR(3);
            END IF;

            -- tb_direccion_via
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion_via') THEN
                ALTER TABLE "{target_schema}"."tb_direccion_via" ADD COLUMN IF NOT EXISTS divi_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_direccion_via" ADD COLUMN IF NOT EXISTS divi_cuadra VARCHAR(20);
                ALTER TABLE "{target_schema}"."tb_direccion_via" ADD COLUMN IF NOT EXISTS divi_orden INTEGER DEFAULT 1;
                ALTER TABLE "{target_schema}"."tb_direccion_via" ADD COLUMN IF NOT EXISTS divi_es_principal BOOLEAN DEFAULT TRUE;
                ALTER TABLE "{target_schema}"."tb_direccion_via" ADD COLUMN IF NOT EXISTS divi_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_direccion_via" ALTER COLUMN divi_numero TYPE VARCHAR(50);
                ALTER TABLE "{target_schema}"."tb_direccion_via" ALTER COLUMN divi_estado TYPE VARCHAR(3);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_via_lookup ON "{target_schema}"."tb_direccion_via" (dire_id, via_id);
            END IF;

            -- tb_componente_direccion
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_componente_direccion') THEN
                ALTER TABLE "{target_schema}"."tb_componente_direccion" ADD COLUMN IF NOT EXISTS codi_abreviatura VARCHAR(20);
                ALTER TABLE "{target_schema}"."tb_componente_direccion" ADD COLUMN IF NOT EXISTS codi_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_componente_direccion" ALTER COLUMN codi_nombre TYPE VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_componente_direccion" ALTER COLUMN codi_estado TYPE VARCHAR(3);
            END IF;

            -- tb_contenido_componente_direccion
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_contenido_componente_direccion') THEN
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_contenido_componente_direccion' AND column_name = 'diti_nombre') 
                   AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = '{target_schema}' AND table_name = 'tb_contenido_componente_direccion' AND column_name = 'diti_valor') THEN
                    ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" RENAME COLUMN diti_nombre TO diti_valor;
                END IF;
                ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" ADD COLUMN IF NOT EXISTS diti_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" ADD COLUMN IF NOT EXISTS diti_valor VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" ADD COLUMN IF NOT EXISTS diti_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" ALTER COLUMN diti_valor TYPE VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_contenido_componente_direccion" ALTER COLUMN diti_estado TYPE VARCHAR(3);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_contenido_comp_lookup ON "{target_schema}"."tb_contenido_componente_direccion" (dire_id, codi_id);
            END IF;

            -- tb_tipo_modulo
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_tipo_modulo') THEN
                ALTER TABLE "{target_schema}"."tb_tipo_modulo" ADD COLUMN IF NOT EXISTS timo_abreviatura VARCHAR(20);
                ALTER TABLE "{target_schema}"."tb_tipo_modulo" ADD COLUMN IF NOT EXISTS timo_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_tipo_modulo" ALTER COLUMN timo_nombre TYPE VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_tipo_modulo" ALTER COLUMN timo_estado TYPE VARCHAR(3);
            END IF;

            -- tb_direccion_tipo_modulo
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = '{target_schema}' AND table_name = 'tb_direccion_tipo_modulo') THEN
                ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo" ADD COLUMN IF NOT EXISTS ditm_id BIGSERIAL;
                ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo" ADD COLUMN IF NOT EXISTS ditm_estado VARCHAR(3) DEFAULT 'ACT';
                ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo" ALTER COLUMN ditm_nombre TYPE VARCHAR(100);
                ALTER TABLE "{target_schema}"."tb_direccion_tipo_modulo" ALTER COLUMN ditm_estado TYPE VARCHAR(3);
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_modulo_lookup ON "{target_schema}"."tb_direccion_tipo_modulo" (dire_id, timo_id, ditm_nombre);
            END IF;
        END $$;
        """
        try:
            with self.get_session() as session:
                session.execute(text(ddl))
            return True
        except Exception as e:
            logger.debug("Aviso al adaptar columnas legacy en %s: %s", target_schema, e)
            return False

    def ensure_v2_tables_exist(self, schema: Optional[str] = None) -> Dict[str, Any]:
        """Asegura que la arquitectura relacional V2 completa exista en el esquema objetivo:
        - tb_tipo_via, tb_via
        - tb_tipo_zona (los 28 tipos de zona oficiales), tb_zona
        - tb_direccion, tb_direccion_via
        - tb_componente_direccion, tb_contenido_componente_direccion
        - tb_tipo_modulo, tb_direccion_tipo_modulo
        - Vista v_direcciones_v2

        Garantiza idempotencia absoluta y rapidez:
        - Si las 10 tablas ya existen y están sembradas, retorna de inmediato (< 5ms).
        - Si falta alguna tabla o columna, la crea de forma atómica e infalible,
          sin depender de scripts SQL monolíticos frágiles.
        """
        from src.catalogs.catalog_manager import CatalogManager

        target_schema = schema or self.settings.schema or "public"
        results: Dict[str, Any] = {
            "schema": target_schema,
            "created_tables": [],
            "seeded_tables": {},
            "status": "OK",
        }

        if not SQLALCHEMY_AVAILABLE or not self._engine:
            results["status"] = "NO_ENGINE"
            return results

        is_postgres = False
        is_sqlite = False
        try:
            dialect_name = getattr(self._engine.dialect, "name", "")
            is_postgres = (dialect_name == "postgresql")
            is_sqlite = (dialect_name == "sqlite")
        except Exception:
            pass

        tables_to_check = [
            "tb_tipo_via", "tb_via", "tb_tipo_zona", "tb_zona",
            "tb_direccion", "tb_direccion_via", "tb_componente_direccion",
            "tb_contenido_componente_direccion", "tb_tipo_modulo",
            "tb_direccion_tipo_modulo"
        ]

        if target_schema in self._v2_verified_schemas:
            results["status"] = "ALL_TABLES_READY"
            return results

        # 1. Comprobar qué tablas existen actualmente en el esquema objetivo
        existing_tables = set()
        try:
            with self.get_session() as session:
                if is_sqlite:
                    rows = session.execute(text("SELECT LOWER(name) FROM sqlite_master WHERE type='table';")).fetchall()
                    existing_tables = {r[0] for r in rows}
                else:
                    rows = session.execute(text("""
                        SELECT LOWER(table_name) FROM information_schema.tables
                        WHERE table_schema = :schema;
                    """), {"schema": target_schema}).fetchall()
                    existing_tables = {r[0] for r in rows}
        except Exception as ex_list:
            logger.debug("Aviso al consultar tablas existentes en %s: %s", target_schema, ex_list)

        # 2. Fast-Path: Si ya existen las 10 tablas y los catálogos consolidados están al día, retornar rápido
        missing = [t for t in tables_to_check if t.lower() not in existing_tables]
        if not missing:
            try:
                with self.get_session() as session:
                    t_via = f'"{target_schema}"."tb_tipo_via"' if is_postgres else '"tb_tipo_via"'
                    v_via = f'"{target_schema}"."tb_via"' if is_postgres else '"tb_via"'
                    tv_c = session.execute(text(f"SELECT COUNT(*) FROM {t_via};")).scalar() or 0
                    v_c = session.execute(text(f"SELECT COUNT(*) FROM {v_via};")).scalar() or 0

                    phys_vias_count = len(CatalogManager.get_official_physical_vias_tuples())
                    if tv_c >= 12 and v_c == phys_vias_count:
                        self.ensure_tb_direccion_exists(target_schema)
                        if is_postgres:
                            self.adapt_legacy_catalog_columns(target_schema)
                        self._v2_verified_schemas.add(target_schema)
                        results["status"] = "ALL_TABLES_READY"
                        return results
            except Exception:
                pass

        # 3. Definición DDL atómica e individual para cada tabla faltante
        ddl_postgres = {
            "tb_tipo_via": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_tipo_via" (
                    tivi_id             BIGSERIAL NOT NULL,
                    tivi_nombre         VARCHAR(100) NOT NULL,
                    tivi_abreviatura    VARCHAR(20),
                    tivi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (tivi_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_tipo_via PRIMARY KEY (tivi_id),
                    CONSTRAINT uq_tb_tipo_via_nombre UNIQUE (tivi_nombre)
                );
            """,
            "tb_tipo_zona": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_tipo_zona" (
                    tizo_id             BIGSERIAL NOT NULL,
                    tizo_nombre         VARCHAR(100) NOT NULL,
                    tizo_abreviatura    VARCHAR(20),
                    tizo_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (tizo_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_tipo_zona PRIMARY KEY (tizo_id),
                    CONSTRAINT uq_tb_tipo_zona_nombre UNIQUE (tizo_nombre)
                );
            """,
            "tb_via": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_via" (
                    via_id              BIGSERIAL NOT NULL,
                    tivi_id             BIGINT NOT NULL,
                    via_nombre          VARCHAR(250) NOT NULL,
                    via_estado          VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (via_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_via PRIMARY KEY (via_id),
                    CONSTRAINT fk_tb_via_tipo_via FOREIGN KEY (tivi_id) REFERENCES "{target_schema}"."tb_tipo_via"(tivi_id) ON UPDATE CASCADE ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_tb_via_nombre ON "{target_schema}"."tb_via" (via_nombre);
                CREATE INDEX IF NOT EXISTS idx_tb_via_tipo_nombre ON "{target_schema}"."tb_via" (tivi_id, via_nombre);
            """,
            "tb_zona": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_zona" (
                    zona_id             BIGSERIAL NOT NULL,
                    tizo_id             BIGINT NOT NULL,
                    zona_nombre         VARCHAR(250) NOT NULL,
                    zona_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (zona_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_zona PRIMARY KEY (zona_id),
                    CONSTRAINT fk_tb_zona_tipo_zona FOREIGN KEY (tizo_id) REFERENCES "{target_schema}"."tb_tipo_zona"(tizo_id) ON UPDATE CASCADE ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_tb_zona_nombre ON "{target_schema}"."tb_zona" (zona_nombre);
                CREATE INDEX IF NOT EXISTS idx_tb_zona_tipo_nombre ON "{target_schema}"."tb_zona" (tizo_id, zona_nombre);
            """,
            "tb_direccion": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_direccion" (
                    dire_id             BIGSERIAL NOT NULL,
                    zona_id             BIGINT,
                    dire_referencia     TEXT,
                    dire_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (dire_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    dire_esquema        VARCHAR(500),
                    dire_tabla          VARCHAR(500),
                    dire_tabla_id       BIGINT,
                    dire_valor_origen   VARCHAR(500),
                    dire_es_procesado   BOOLEAN,
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_direccion PRIMARY KEY (dire_id),
                    CONSTRAINT fk_tb_direccion_zona FOREIGN KEY (zona_id) REFERENCES "{target_schema}"."tb_zona"(zona_id) ON UPDATE CASCADE ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tb_direccion_zona ON "{target_schema}"."tb_direccion" (zona_id);
                CREATE INDEX IF NOT EXISTS idx_tb_direccion_proc ON "{target_schema}"."tb_direccion" (dire_esquema, dire_tabla, dire_es_procesado);
                CREATE INDEX IF NOT EXISTS idx_tb_direccion_origen_lookup ON "{target_schema}"."tb_direccion" (dire_esquema, dire_tabla, dire_tabla_id);
            """,
            "tb_direccion_via": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_direccion_via" (
                    divi_id             BIGSERIAL NOT NULL,
                    dire_id             BIGINT NOT NULL,
                    via_id              BIGINT NOT NULL,
                    divi_numero         VARCHAR(50),
                    divi_cuadra         VARCHAR(20),
                    divi_orden          INTEGER NOT NULL DEFAULT 1,
                    divi_es_principal   BOOLEAN NOT NULL DEFAULT TRUE,
                    divi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (divi_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    CONSTRAINT pk_tb_direccion_via PRIMARY KEY (divi_id),
                    CONSTRAINT fk_tb_direccion_via_dir FOREIGN KEY (dire_id) REFERENCES "{target_schema}"."tb_direccion"(dire_id) ON UPDATE CASCADE ON DELETE CASCADE,
                    CONSTRAINT fk_tb_direccion_via_via FOREIGN KEY (via_id) REFERENCES "{target_schema}"."tb_via"(via_id) ON UPDATE CASCADE ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_via_lookup ON "{target_schema}"."tb_direccion_via" (dire_id, via_id);
                CREATE INDEX IF NOT EXISTS idx_tb_direccion_via_lookup ON "{target_schema}"."tb_direccion_via" (dire_id, via_id);
                CREATE INDEX IF NOT EXISTS idx_tb_direccion_via_principal ON "{target_schema}"."tb_direccion_via" (divi_es_principal);
            """,
            "tb_componente_direccion": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_componente_direccion" (
                    codi_id             BIGSERIAL NOT NULL,
                    codi_nombre         VARCHAR(100) NOT NULL,
                    codi_abreviatura    VARCHAR(20),
                    codi_es_urbano      BOOLEAN DEFAULT TRUE,
                    codi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (codi_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_componente_direccion PRIMARY KEY (codi_id),
                    CONSTRAINT uq_tb_componente_direccion_nombre UNIQUE (codi_nombre)
                );
            """,
            "tb_contenido_componente_direccion": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_contenido_componente_direccion" (
                    diti_id             BIGSERIAL NOT NULL,
                    dire_id             BIGINT NOT NULL,
                    codi_id             BIGINT NOT NULL,
                    diti_valor          VARCHAR(100) NOT NULL,
                    diti_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (diti_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    CONSTRAINT pk_tb_contenido_componente_direccion PRIMARY KEY (diti_id),
                    CONSTRAINT fk_tb_contenido_componente_dir FOREIGN KEY (dire_id) REFERENCES "{target_schema}"."tb_direccion"(dire_id) ON UPDATE CASCADE ON DELETE CASCADE,
                    CONSTRAINT fk_tb_contenido_componente_codi FOREIGN KEY (codi_id) REFERENCES "{target_schema}"."tb_componente_direccion"(codi_id) ON UPDATE CASCADE ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_contenido_comp_lookup ON "{target_schema}"."tb_contenido_componente_direccion" (dire_id, codi_id);
                CREATE INDEX IF NOT EXISTS idx_tb_contenido_comp_lookup ON "{target_schema}"."tb_contenido_componente_direccion" (dire_id, codi_id);
            """,
            "tb_tipo_modulo": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_tipo_modulo" (
                    timo_id             BIGSERIAL NOT NULL,
                    timo_nombre         VARCHAR(100) NOT NULL,
                    timo_abreviatura    VARCHAR(20),
                    timo_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (timo_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    usua_id             BIGINT,
                    usua_nombre         VARCHAR(200),
                    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    update_at           TIMESTAMP WITHOUT TIME ZONE,
                    audit_user_pc       VARCHAR(100),
                    audit_nombre_pc     VARCHAR(100),
                    audit_ip            VARCHAR(50),
                    audit_mac_address   VARCHAR(50),
                    CONSTRAINT pk_tb_tipo_modulo PRIMARY KEY (timo_id),
                    CONSTRAINT uq_tb_tipo_modulo_nombre UNIQUE (timo_nombre)
                );
            """,
            "tb_direccion_tipo_modulo": f"""
                CREATE TABLE IF NOT EXISTS "{target_schema}"."tb_direccion_tipo_modulo" (
                    ditm_id             BIGSERIAL NOT NULL,
                    dire_id             BIGINT NOT NULL,
                    timo_id             BIGINT NOT NULL,
                    ditm_nombre         VARCHAR(100) NOT NULL,
                    ditm_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT' CHECK (ditm_estado IN ('A', 'I', 'E', 'ACT', 'INA', 'ELI')),
                    CONSTRAINT pk_tb_direccion_tipo_modulo PRIMARY KEY (dire_id, timo_id, ditm_nombre),
                    CONSTRAINT fk_tb_direccion_modulo_dir FOREIGN KEY (dire_id) REFERENCES "{target_schema}"."tb_direccion"(dire_id) ON UPDATE CASCADE ON DELETE CASCADE,
                    CONSTRAINT fk_tb_direccion_modulo_timo FOREIGN KEY (timo_id) REFERENCES "{target_schema}"."tb_tipo_modulo"(timo_id) ON UPDATE CASCADE ON DELETE CASCADE
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_modulo_lookup ON "{target_schema}"."tb_direccion_tipo_modulo" (dire_id, timo_id, ditm_nombre);
            """
        }

        ddl_sqlite = {
            "tb_tipo_via": """
                CREATE TABLE IF NOT EXISTS "tb_tipo_via" (
                    tivi_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tivi_nombre VARCHAR(100) NOT NULL UNIQUE,
                    tivi_abreviatura VARCHAR(20),
                    tivi_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_tipo_zona": """
                CREATE TABLE IF NOT EXISTS "tb_tipo_zona" (
                    tizo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tizo_nombre VARCHAR(100) NOT NULL UNIQUE,
                    tizo_abreviatura VARCHAR(20),
                    tizo_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_via": """
                CREATE TABLE IF NOT EXISTS "tb_via" (
                    via_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tivi_id INTEGER NOT NULL,
                    via_nombre VARCHAR(250) NOT NULL,
                    via_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_zona": """
                CREATE TABLE IF NOT EXISTS "tb_zona" (
                    zona_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tizo_id INTEGER NOT NULL,
                    zona_nombre VARCHAR(250) NOT NULL,
                    zona_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_direccion": """
                CREATE TABLE IF NOT EXISTS "tb_direccion" (
                    dire_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    zona_id INTEGER,
                    dire_referencia TEXT,
                    dire_estado VARCHAR(3) DEFAULT 'ACT',
                    dire_esquema VARCHAR(500),
                    dire_tabla VARCHAR(500),
                    dire_tabla_id INTEGER,
                    dire_valor_origen VARCHAR(500),
                    dire_es_procesado BOOLEAN,
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_direccion_via": """
                CREATE TABLE IF NOT EXISTS "tb_direccion_via" (
                    divi_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    via_id INTEGER NOT NULL,
                    divi_numero VARCHAR(50),
                    divi_cuadra VARCHAR(20),
                    divi_orden INTEGER DEFAULT 1,
                    divi_es_principal BOOLEAN DEFAULT 1,
                    divi_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, via_id)
                );
            """,
            "tb_componente_direccion": """
                CREATE TABLE IF NOT EXISTS "tb_componente_direccion" (
                    codi_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codi_nombre VARCHAR(100) NOT NULL UNIQUE,
                    codi_abreviatura VARCHAR(20),
                    codi_es_urbano BOOLEAN DEFAULT 1,
                    codi_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_contenido_componente_direccion": """
                CREATE TABLE IF NOT EXISTS "tb_contenido_componente_direccion" (
                    diti_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    codi_id INTEGER NOT NULL,
                    diti_valor VARCHAR(100) NOT NULL,
                    diti_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, codi_id)
                );
            """,
            "tb_tipo_modulo": """
                CREATE TABLE IF NOT EXISTS "tb_tipo_modulo" (
                    timo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timo_nombre VARCHAR(100) NOT NULL UNIQUE,
                    timo_abreviatura VARCHAR(20),
                    timo_estado VARCHAR(3) DEFAULT 'ACT',
                    usua_id INTEGER,
                    usua_nombre VARCHAR(200),
                    create_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    update_at TIMESTAMP,
                    audit_user_pc VARCHAR(100),
                    audit_nombre_pc VARCHAR(100),
                    audit_ip VARCHAR(50),
                    audit_mac_address VARCHAR(50)
                );
            """,
            "tb_direccion_tipo_modulo": """
                CREATE TABLE IF NOT EXISTS "tb_direccion_tipo_modulo" (
                    ditm_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dire_id INTEGER NOT NULL,
                    timo_id INTEGER NOT NULL,
                    ditm_nombre VARCHAR(100) NOT NULL,
                    ditm_estado VARCHAR(3) DEFAULT 'ACT',
                    UNIQUE (dire_id, timo_id, ditm_nombre)
                );
            """
        }

        ddl_map = ddl_postgres if is_postgres else ddl_sqlite
        with self.get_session() as session:
            for tbl_name, ddl_stmt in ddl_map.items():
                if tbl_name.lower() in missing or not self.table_exists(tbl_name, target_schema):
                    try:
                        session.execute(text(ddl_stmt))
                        results["created_tables"].append(tbl_name)
                        logger.info("Estructura relacional V2: Creada/verificada tabla '%s' en '%s'", tbl_name, target_schema)
                    except Exception as ex_tbl:
                        logger.warning("Aviso al crear tabla V2 '%s' en '%s': %s", tbl_name, target_schema, ex_tbl)

        if is_postgres:
            # 4. Adaptar columnas legacy si existiesen previamente (divi_orden, diti_valor, etc.)
            self.adapt_legacy_catalog_columns(target_schema)

            # 5. Asegurar restricción PK compuesta en tb_direccion_tipo_modulo
            self.ensure_modulo_pk_constraint(target_schema)

            # 6. Asegurar que todas las columnas *_estado sean VARCHAR(3)
            self.ensure_estado_columns_varchar3(target_schema)

        # 7. Asegurar existencia y columnas de tb_direccion
        self.ensure_tb_direccion_exists(target_schema)

        # 8. Sembrar catálogos oficiales desde CatalogManager
        try:
            with self.get_session() as session:
                # 8.1. tb_tipo_via (12 tipos oficiales)
                vias_tipos = CatalogManager.get_official_vias_tuples()
                tv_tbl = f'"{target_schema}"."tb_tipo_via"' if is_postgres else '"tb_tipo_via"'
                tv_count = session.execute(text(f"SELECT COUNT(*) FROM {tv_tbl};")).scalar() or 0
                if tv_count < len(vias_tipos):
                    if is_postgres:
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_tipo_via" (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                            VALUES (:id, :nombre, :abrev, 'A')
                            ON CONFLICT (tivi_id) DO UPDATE
                            SET tivi_nombre = EXCLUDED.tivi_nombre, tivi_abreviatura = EXCLUDED.tivi_abreviatura;
                        """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])
                    else:
                        session.execute(text("""
                            INSERT OR IGNORE INTO tb_tipo_via (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                            VALUES (:id, :nombre, :abrev, 'A');
                        """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])
                    results["seeded_tables"]["tb_tipo_via"] = len(vias_tipos)

                # 8.2. tb_tipo_zona (28 tipos oficiales)
                zonas_tipos = CatalogManager.get_official_zonas_tuples()
                tz_tbl = f'"{target_schema}"."tb_tipo_zona"' if is_postgres else '"tb_tipo_zona"'
                tz_count = session.execute(text(f"SELECT COUNT(*) FROM {tz_tbl};")).scalar() or 0
                if tz_count < len(zonas_tipos):
                    if is_postgres:
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_tipo_zona" (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                            VALUES (:id, :nombre, :abrev, 'A')
                            ON CONFLICT (tizo_id) DO UPDATE
                            SET tizo_nombre = EXCLUDED.tizo_nombre, tizo_abreviatura = EXCLUDED.tizo_abreviatura;
                        """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])
                    else:
                        session.execute(text("""
                            INSERT OR IGNORE INTO tb_tipo_zona (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                            VALUES (:id, :nombre, :abrev, 'A');
                        """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])
                    results["seeded_tables"]["tb_tipo_zona"] = len(zonas_tipos)

                # 8.3. tb_via (2,211 vías oficiales de Chiclayo consolidadas)
                phys_vias = CatalogManager.get_official_physical_vias_tuples()
                v_tbl = f'"{target_schema}"."tb_via"' if is_postgres else '"tb_via"'
                via_count = session.execute(text(f"SELECT COUNT(*) FROM {v_tbl};")).scalar() or 0
                if via_count != len(phys_vias):
                    chunk_size = 400
                    for i in range(0, len(phys_vias), chunk_size):
                        chunk = phys_vias[i:i + chunk_size]
                        if is_postgres:
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."tb_via" (via_id, tivi_id, via_nombre, via_estado)
                                VALUES (:via_id, :tivi_id, :via_nombre, 'A')
                                ON CONFLICT (via_id) DO UPDATE
                                SET via_nombre = EXCLUDED.via_nombre, tivi_id = EXCLUDED.tivi_id, via_estado = 'A';
                            """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])
                        else:
                            session.execute(text("""
                                INSERT OR REPLACE INTO tb_via (via_id, tivi_id, via_nombre, via_estado)
                                VALUES (:via_id, :tivi_id, :via_nombre, 'A');
                            """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])
                    results["seeded_tables"]["tb_via"] = len(phys_vias)
                    logger.info("Catálogo maestro sembrado en %s: %d vías oficiales de Chiclayo", target_schema, len(phys_vias))

                # 8.4. tb_zona (452 zonas oficiales de Chiclayo consolidadas)
                phys_zonas = CatalogManager.get_official_physical_zonas_tuples()
                z_tbl = f'"{target_schema}"."tb_zona"' if is_postgres else '"tb_zona"'
                zona_count = session.execute(text(f"SELECT COUNT(*) FROM {z_tbl};")).scalar() or 0
                if zona_count != len(phys_zonas):
                    chunk_size = 200
                    for i in range(0, len(phys_zonas), chunk_size):
                        chunk = phys_zonas[i:i + chunk_size]
                        if is_postgres:
                            session.execute(text(f"""
                                INSERT INTO "{target_schema}"."tb_zona" (zona_id, tizo_id, zona_nombre, zona_estado)
                                VALUES (:zona_id, :tizo_id, :zona_nombre, 'A')
                                ON CONFLICT (zona_id) DO UPDATE
                                SET zona_nombre = EXCLUDED.zona_nombre, tizo_id = EXCLUDED.tizo_id, zona_estado = 'A';
                            """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])
                        else:
                            session.execute(text("""
                                INSERT OR REPLACE INTO tb_zona (zona_id, tizo_id, zona_nombre, zona_estado)
                                VALUES (:zona_id, :tizo_id, :zona_nombre, 'A');
                            """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])
                    results["seeded_tables"]["tb_zona"] = len(phys_zonas)
                    logger.info("Catálogo maestro sembrado en %s: %d zonas oficiales de Chiclayo", target_schema, len(phys_zonas))

                # 8.5. tb_componente_direccion (12 componentes oficiales)
                comps = CatalogManager.get_default_componentes_tuples()
                c_tbl = f'"{target_schema}"."tb_componente_direccion"' if is_postgres else '"tb_componente_direccion"'
                comp_count = session.execute(text(f"SELECT COUNT(*) FROM {c_tbl};")).scalar() or 0
                if comp_count < len(comps):
                    if is_postgres:
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_componente_direccion" (codi_id, codi_nombre, codi_abreviatura, codi_estado)
                            VALUES (:codi_id, :codi_nombre, :codi_abreviatura, :codi_estado)
                            ON CONFLICT (codi_id) DO UPDATE
                            SET codi_nombre = EXCLUDED.codi_nombre, codi_abreviatura = EXCLUDED.codi_abreviatura, codi_estado = EXCLUDED.codi_estado;
                        """), [{"codi_id": c[0], "codi_nombre": c[1], "codi_abreviatura": c[2], "codi_estado": c[3]} for c in comps])
                    else:
                        session.execute(text("""
                            INSERT OR IGNORE INTO tb_componente_direccion (codi_id, codi_nombre, codi_abreviatura, codi_estado)
                            VALUES (:codi_id, :codi_nombre, :codi_abreviatura, :codi_estado);
                        """), [{"codi_id": c[0], "codi_nombre": c[1], "codi_abreviatura": c[2], "codi_estado": c[3]} for c in comps])
                    results["seeded_tables"]["tb_componente_direccion"] = len(comps)

                # 8.6. tb_tipo_modulo (13 módulos oficiales)
                mods = CatalogManager.get_default_tipo_modulo_tuples()
                m_tbl = f'"{target_schema}"."tb_tipo_modulo"' if is_postgres else '"tb_tipo_modulo"'
                mod_count = session.execute(text(f"SELECT COUNT(*) FROM {m_tbl};")).scalar() or 0
                if mod_count < len(mods):
                    if is_postgres:
                        session.execute(text(f"""
                            INSERT INTO "{target_schema}"."tb_tipo_modulo" (timo_id, timo_nombre, timo_abreviatura, timo_estado)
                            VALUES (:timo_id, :timo_nombre, :timo_abreviatura, :timo_estado)
                            ON CONFLICT (timo_id) DO UPDATE
                            SET timo_nombre = EXCLUDED.timo_nombre, timo_abreviatura = EXCLUDED.timo_abreviatura, timo_estado = EXCLUDED.timo_estado;
                        """), [{"timo_id": m[0], "timo_nombre": m[1], "timo_abreviatura": m[2], "timo_estado": m[3]} for m in mods])
                    else:
                        session.execute(text("""
                            INSERT OR IGNORE INTO tb_tipo_modulo (timo_id, timo_nombre, timo_abreviatura, timo_estado)
                            VALUES (:timo_id, :timo_nombre, :timo_abreviatura, :timo_estado);
                        """), [{"timo_id": m[0], "timo_nombre": m[1], "timo_abreviatura": m[2], "timo_estado": m[3]} for m in mods])
                    results["seeded_tables"]["tb_tipo_modulo"] = len(mods)

                # 8.7. Ajustar secuencias en PostgreSQL
                if is_postgres:
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

                # 8.8. Vista relacional consolidada v_direcciones_v2 en PostgreSQL
                if is_postgres:
                    try:
                        session.execute(text(f"""
                            CREATE OR REPLACE VIEW "{target_schema}"."v_direcciones_v2" AS
                            SELECT 
                                d.dire_id,
                                d.zona_id,
                                d.dire_referencia,
                                d.dire_estado,
                                d.dire_esquema,
                                d.dire_tabla,
                                d.dire_tabla_id,
                                d.dire_valor_origen,
                                d.dire_es_procesado,
                                d.usua_id,
                                d.usua_nombre,
                                d.create_at,
                                d.update_at,
                                d.audit_user_pc,
                                d.audit_nombre_pc,
                                d.audit_ip,
                                d.audit_mac_address,
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
                                dv2.divi_numero AS num_via_secundaria,
                                v3.via_id AS via_3_id,
                                v3.via_nombre AS via_3_nombre,
                                tv3.tivi_nombre AS tipo_via_3,
                                dv3.divi_numero AS num_via_3
                            FROM "{target_schema}"."tb_direccion" d
                            LEFT JOIN "{target_schema}"."tb_zona" z ON d.zona_id = z.zona_id
                            LEFT JOIN "{target_schema}"."tb_tipo_zona" tz ON z.tizo_id = tz.tizo_id
                            LEFT JOIN "{target_schema}"."tb_direccion_via" dv1 ON d.dire_id = dv1.dire_id AND dv1.divi_orden = 1
                            LEFT JOIN "{target_schema}"."tb_via" v1 ON dv1.via_id = v1.via_id
                            LEFT JOIN "{target_schema}"."tb_tipo_via" tv1 ON v1.tivi_id = tv1.tivi_id
                            LEFT JOIN "{target_schema}"."tb_direccion_via" dv2 ON d.dire_id = dv2.dire_id AND dv2.divi_orden = 2
                            LEFT JOIN "{target_schema}"."tb_via" v2 ON dv2.via_id = v2.via_id
                            LEFT JOIN "{target_schema}"."tb_tipo_via" tv2 ON v2.tivi_id = tv2.tivi_id
                            LEFT JOIN "{target_schema}"."tb_direccion_via" dv3 ON d.dire_id = dv3.dire_id AND dv3.divi_orden = 3
                            LEFT JOIN "{target_schema}"."tb_via" v3 ON dv3.via_id = v3.via_id
                            LEFT JOIN "{target_schema}"."tb_tipo_via" tv3 ON v3.tivi_id = tv3.tivi_id;
                        """))
                    except Exception as view_err:
                        logger.debug("Aviso al crear vista v_direcciones_v2 en %s: %s", target_schema, view_err)

        except Exception as e:
            logger.error("Error al verificar/sembrar datos semilla V2 en %s: %s", target_schema, e)

        # Asegurar columnas de auditoría en tablas maestras de catálogos (idempotente)
        try:
            self.ensure_catalogs_audit_columns(target_schema)
        except Exception as e_audit:
            logger.debug("Aviso al verificar columnas de auditoría en catálogos de %s: %s", target_schema, e_audit)

        # Asegurar consolidación de duplicados y reasignación de FKs
        self.consolidate_catalog_duplicates(target_schema)
        self._v2_verified_schemas.add(target_schema)

        return results

    def ensure_catalogs_audit_columns(self, schema: Optional[str] = None) -> None:
        """Garantiza que las 6 tablas maestras de catálogos contengan las 8 columnas
        de auditoría estándar. Operación completamente idempotente usando ADD COLUMN IF NOT EXISTS.
        Compatible con PostgreSQL (esquema calificado) y SQLite (sin esquema).

        Tablas afectadas:
            tb_tipo_via, tb_via, tb_tipo_zona, tb_zona,
            tb_componente_direccion, tb_tipo_modulo
        """
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return

        is_postgres = (self._engine.dialect.name == "postgresql")
        target_schema = schema or self.settings.schema

        # Definición de columnas de auditoría: (nombre, tipo_postgres, tipo_sqlite, default)
        AUDIT_COLUMNS = [
            ("usua_id",           "BIGINT",                                    "INTEGER",      None),
            ("usua_nombre",       "VARCHAR(200)",                              "VARCHAR(200)", None),
            ("create_at",         "TIMESTAMP WITHOUT TIME ZONE",               "TIMESTAMP",    "CURRENT_TIMESTAMP"),
            ("update_at",         "TIMESTAMP WITHOUT TIME ZONE",               "TIMESTAMP",    None),
            ("audit_user_pc",     "VARCHAR(100)",                              "VARCHAR(100)", None),
            ("audit_nombre_pc",   "VARCHAR(100)",                              "VARCHAR(100)", None),
            ("audit_ip",          "VARCHAR(50)",                               "VARCHAR(50)",  None),
            ("audit_mac_address", "VARCHAR(50)",                               "VARCHAR(50)",  None),
        ]

        # Tablas maestras a verificar
        CATALOG_TABLES = [
            "tb_tipo_via",
            "tb_via",
            "tb_tipo_zona",
            "tb_zona",
            "tb_componente_direccion",
            "tb_tipo_modulo",
        ]

        try:
            with self.get_session() as session:
                for table in CATALOG_TABLES:
                    # Verificar que la tabla existe antes de intentar alterar
                    if is_postgres:
                        tbl_exists = session.execute(text("""
                            SELECT COUNT(*) FROM information_schema.tables
                            WHERE table_schema = :schema AND table_name = :table;
                        """), {"schema": target_schema, "table": table}).scalar() or 0
                    else:
                        tbl_exists = session.execute(text(
                            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=:table;"
                        ), {"table": table}).scalar() or 0

                    if not tbl_exists:
                        logger.debug("Tabla %s no existe en %s, se omite verificación de auditoría.", table, target_schema)
                        continue

                    # Obtener columnas existentes
                    if is_postgres:
                        existing_cols = {
                            r[0] for r in session.execute(text("""
                                SELECT column_name FROM information_schema.columns
                                WHERE table_schema = :schema AND table_name = :table;
                            """), {"schema": target_schema, "table": table}).fetchall()
                        }
                    else:
                        existing_cols = {
                            r[1] for r in session.execute(text(f"PRAGMA table_info({table});")).fetchall()
                        }

                    # Agregar únicamente las columnas de auditoría faltantes
                    for col_name, pg_type, sq_type, default in AUDIT_COLUMNS:
                        if col_name in existing_cols:
                            continue
                        col_type = pg_type if is_postgres else sq_type
                        default_clause = f" DEFAULT {default}" if default else ""
                        if is_postgres:
                            alter_sql = (
                                f'ALTER TABLE "{target_schema}"."{table}" '
                                f'ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}{default_clause};'
                            )
                        else:
                            alter_sql = (
                                f'ALTER TABLE "{table}" '
                                f'ADD COLUMN IF NOT EXISTS "{col_name}" {col_type}{default_clause};'
                            )
                        try:
                            session.execute(text(alter_sql))
                            logger.info(
                                "Columna de auditoría '%s' agregada a %s.%s.",
                                col_name, target_schema, table,
                            )
                        except Exception as e_col:
                            logger.debug(
                                "Aviso al agregar columna '%s' en %s.%s: %s",
                                col_name, target_schema, table, e_col,
                            )

        except Exception as e:
            logger.error("Error en ensure_catalogs_audit_columns para esquema %s: %s", target_schema, e)
            raise

    def consolidate_catalog_duplicates(self, target_schema: str = "public") -> Dict[str, Any]:
        """Detecta, consolida y reordena registros duplicados de vías y zonas en la base de datos,
        reasignando de forma transparente cualquier clave foránea existente en tb_direccion_via y tb_direccion.
        Garantiza que vías repetidas con el mismo tipo y nombre (ej. Pasaje 'SAN LUCAS') se consoliden en 1 solo registro canónico.
        """
        results = {
            "vias_consolidated": 0,
            "zonas_consolidated": 0,
            "direccion_via_fks_updated": 0,
            "direccion_fks_updated": 0,
        }
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return results

        from src.catalogs.catalog_manager import CatalogManager

        is_postgres = (self._engine.dialect.name == "postgresql")
        v_tbl = f'"{target_schema}"."tb_via"' if is_postgres else '"tb_via"'
        z_tbl = f'"{target_schema}"."tb_zona"' if is_postgres else '"tb_zona"'
        dv_tbl = f'"{target_schema}"."tb_direccion_via"' if is_postgres else '"tb_direccion_via"'
        d_tbl = f'"{target_schema}"."tb_direccion"' if is_postgres else '"tb_direccion"'

        has_vias = self.table_exists("tb_via", target_schema)
        has_zonas = self.table_exists("tb_zona", target_schema)
        has_dir_vias = self.table_exists("tb_direccion_via", target_schema)
        has_dirs = self.table_exists("tb_direccion", target_schema)

        if not has_vias and not has_zonas:
            return results

        vias_map = CatalogManager.get_vias_id_migration_map()
        zonas_map = CatalogManager.get_zonas_id_migration_map()

        def _clean_str(s: Optional[str]) -> str:
            if not s:
                return ""
            nfkd = unicodedata.normalize("NFKD", s)
            no_acc = "".join(c for c in nfkd if not unicodedata.combining(c))
            return re.sub(r"\s+", " ", no_acc).strip().upper()

        with self.get_session() as session:
            # 1. Consolidar VÍAS
            if has_vias:
                # 1.1 Reasignar FKs en tb_direccion_via según el mapa de migración
                if has_dir_vias and vias_map:
                    for old_id, new_id in vias_map.items():
                        if old_id != new_id:
                            try:
                                session.execute(text(f"""
                                    DELETE FROM {dv_tbl}
                                    WHERE via_id = :old_id
                                      AND dire_id IN (SELECT dire_id FROM {dv_tbl} WHERE via_id = :new_id);
                                """), {"old_id": old_id, "new_id": new_id})
                                upd_res = session.execute(text(f"""
                                    UPDATE {dv_tbl}
                                    SET via_id = :new_id
                                    WHERE via_id = :old_id;
                                """), {"old_id": old_id, "new_id": new_id})
                                results["direccion_via_fks_updated"] += (upd_res.rowcount or 0)
                            except Exception as e:
                                logger.debug("Aviso al reasignar tb_direccion_via %s -> %s: %s", old_id, new_id, e)

                # 1.2 Detectar y consolidar duplicados residuales en tb_via
                try:
                    v_rows = session.execute(text(f"SELECT via_id, tivi_id, via_nombre FROM {v_tbl} ORDER BY via_id;")).fetchall()
                    via_groups = {}
                    for row in v_rows:
                        v_id = int(row.via_id)
                        tivi = int(row.tivi_id) if row.tivi_id is not None else 0
                        v_clean = _clean_str(row.via_nombre)
                        v_key = (tivi, v_clean)
                        if v_key not in via_groups:
                            via_groups[v_key] = []
                        via_groups[v_key].append(v_id)

                    for v_key, ids in via_groups.items():
                        if len(ids) > 1:
                            canonical_id = ids[0]
                            for cid in ids:
                                if cid in vias_map.values():
                                    canonical_id = cid
                                    break
                            dup_ids = [x for x in ids if x != canonical_id]
                            if has_dir_vias and dup_ids:
                                for dup_id in dup_ids:
                                    try:
                                        session.execute(text(f"""
                                            DELETE FROM {dv_tbl}
                                            WHERE via_id = :dup_id
                                              AND dire_id IN (SELECT dire_id FROM {dv_tbl} WHERE via_id = :can_id);
                                        """), {"dup_id": dup_id, "can_id": canonical_id})
                                        session.execute(text(f"""
                                            UPDATE {dv_tbl} SET via_id = :can_id WHERE via_id = :dup_id;
                                        """), {"dup_id": dup_id, "can_id": canonical_id})
                                    except Exception as e:
                                        logger.debug("Aviso al reasignar duplicado de vía %s -> %s: %s", dup_id, canonical_id, e)

                            for dup_id in dup_ids:
                                try:
                                    session.execute(text(f"DELETE FROM {v_tbl} WHERE via_id = :dup_id;"), {"dup_id": dup_id})
                                    results["vias_consolidated"] += 1
                                except Exception as e:
                                    logger.debug("Aviso al borrar vía duplicada %s: %s", dup_id, e)
                except Exception as ex_v:
                    logger.debug("Aviso al depurar duplicados en tb_via: %s", ex_v)

                # 1.3 Eliminar IDs huérfanos que exceden el catálogo nuevo y que ya fueron migrados
                max_official_via = max((v[0] for v in CatalogManager.get_official_physical_vias_tuples()), default=2211)
                try:
                    if has_dir_vias:
                        session.execute(text(f"""
                            DELETE FROM {v_tbl}
                            WHERE via_id > :max_id
                              AND via_id NOT IN (SELECT via_id FROM {dv_tbl} WHERE via_id IS NOT NULL);
                        """), {"max_id": max_official_via})
                    else:
                        session.execute(text(f"DELETE FROM {v_tbl} WHERE via_id > :max_id;"), {"max_id": max_official_via})
                except Exception:
                    pass

            # 2. Consolidar ZONAS
            if has_zonas:
                # 2.1 Reasignar FKs en tb_direccion según mapa de migración
                if has_dirs and zonas_map:
                    for old_id, new_id in zonas_map.items():
                        if old_id != new_id:
                            try:
                                upd_res = session.execute(text(f"""
                                    UPDATE {d_tbl}
                                    SET zona_id = :new_id
                                    WHERE zona_id = :old_id;
                                """), {"old_id": old_id, "new_id": new_id})
                                results["direccion_fks_updated"] += (upd_res.rowcount or 0)
                            except Exception as e:
                                logger.debug("Aviso al reasignar tb_direccion zona %s -> %s: %s", old_id, new_id, e)

                # 2.2 Detectar y consolidar duplicados residuales en tb_zona
                try:
                    z_rows = session.execute(text(f"SELECT zona_id, tizo_id, zona_nombre FROM {z_tbl} ORDER BY zona_id;")).fetchall()
                    zona_groups = {}
                    for row in z_rows:
                        z_id = int(row.zona_id)
                        tizo = int(row.tizo_id) if row.tizo_id is not None else 0
                        z_clean = _clean_str(row.zona_nombre)
                        z_key = (tizo, z_clean)
                        if z_key not in zona_groups:
                            zona_groups[z_key] = []
                        zona_groups[z_key].append(z_id)

                    for z_key, ids in zona_groups.items():
                        if len(ids) > 1:
                            canonical_id = ids[0]
                            for cid in ids:
                                if cid in zonas_map.values():
                                    canonical_id = cid
                                    break
                            dup_ids = [x for x in ids if x != canonical_id]
                            if has_dirs and dup_ids:
                                for dup_id in dup_ids:
                                    try:
                                        session.execute(text(f"""
                                            UPDATE {d_tbl} SET zona_id = :can_id WHERE zona_id = :dup_id;
                                        """), {"dup_id": dup_id, "can_id": canonical_id})
                                    except Exception as e:
                                        logger.debug("Aviso al reasignar duplicado de zona %s -> %s: %s", dup_id, canonical_id, e)

                            for dup_id in dup_ids:
                                try:
                                    session.execute(text(f"DELETE FROM {z_tbl} WHERE zona_id = :dup_id;"), {"dup_id": dup_id})
                                    results["zonas_consolidated"] += 1
                                except Exception as e:
                                    logger.debug("Aviso al borrar zona duplicada %s: %s", dup_id, e)
                except Exception as ex_z:
                    logger.debug("Aviso al depurar duplicados en tb_zona: %s", ex_z)

                # 2.3 Eliminar IDs huérfanos que exceden el catálogo nuevo y que ya fueron migrados
                max_official_zona = max((z[0] for z in CatalogManager.get_official_physical_zonas_tuples()), default=452)
                try:
                    if has_dirs:
                        session.execute(text(f"""
                            DELETE FROM {z_tbl}
                            WHERE zona_id > :max_id
                              AND zona_id NOT IN (SELECT zona_id FROM {d_tbl} WHERE zona_id IS NOT NULL);
                        """), {"max_id": max_official_zona})
                    else:
                        session.execute(text(f"DELETE FROM {z_tbl} WHERE zona_id > :max_id;"), {"max_id": max_official_zona})
                except Exception:
                    pass

            # 3. Ajustar secuencias seriales en PostgreSQL
            if is_postgres:
                try:
                    session.execute(text(f"""
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_via"', 'via_id'), COALESCE(MAX(via_id), 1)) FROM {v_tbl};
                        SELECT setval(pg_get_serial_sequence('"{target_schema}"."tb_zona"', 'zona_id'), COALESCE(MAX(zona_id), 1)) FROM {z_tbl};
                    """))
                except Exception:
                    pass

        return results

    def seed_v2_catalogs(self, schema: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
        """Importa y siembra forzosamente la totalidad de los catálogos oficiales V2
        (2,211 vías oficiales consolidadas, 452 zonas oficiales consolidadas, 12 tipos de vía y 28 tipos de zona).
        """
        from src.catalogs.catalog_manager import CatalogManager

        target_schema = schema or self.settings.schema
        self.ensure_v2_tables_exist(target_schema)

        # Consolidar duplicados previos y reasignar FKs
        self.consolidate_catalog_duplicates(target_schema)

        is_postgres = (self._engine.dialect.name == "postgresql") if self._engine else False
        res: Dict[str, Any] = {"schema": target_schema, "status": "OK"}
        with self.get_session() as session:
            phys_vias = CatalogManager.get_official_physical_vias_tuples()
            phys_zonas = CatalogManager.get_official_physical_zonas_tuples()
            vias_tipos = CatalogManager.get_official_vias_tuples()
            zonas_tipos = CatalogManager.get_official_zonas_tuples()

            # Forzar importación completa de tb_tipo_via
            if is_postgres:
                session.execute(text(f"""
                    INSERT INTO "{target_schema}"."tb_tipo_via" (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                    VALUES (:id, :nombre, :abrev, 'A')
                    ON CONFLICT (tivi_id) DO UPDATE
                    SET tivi_nombre = EXCLUDED.tivi_nombre, tivi_abreviatura = EXCLUDED.tivi_abreviatura;
                """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])
            else:
                session.execute(text("""
                    INSERT OR REPLACE INTO tb_tipo_via (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado)
                    VALUES (:id, :nombre, :abrev, 'A');
                """), [{"id": v[0], "nombre": v[1], "abrev": v[2]} for v in vias_tipos])

            # Forzar importación completa de tb_tipo_zona
            if is_postgres:
                session.execute(text(f"""
                    INSERT INTO "{target_schema}"."tb_tipo_zona" (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                    VALUES (:id, :nombre, :abrev, 'A')
                    ON CONFLICT (tizo_id) DO UPDATE
                    SET tizo_nombre = EXCLUDED.tizo_nombre, tizo_abreviatura = EXCLUDED.tizo_abreviatura;
                """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])
            else:
                session.execute(text("""
                    INSERT OR REPLACE INTO tb_tipo_zona (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado)
                    VALUES (:id, :nombre, :abrev, 'A');
                """), [{"id": z[0], "nombre": z[1], "abrev": z[2]} for z in zonas_tipos])

            # Forzar importación completa de tb_via
            chunk_size = 400
            for i in range(0, len(phys_vias), chunk_size):
                chunk = phys_vias[i:i + chunk_size]
                if is_postgres:
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_via" (via_id, tivi_id, via_nombre, via_estado)
                        VALUES (:via_id, :tivi_id, :via_nombre, 'A')
                        ON CONFLICT (via_id) DO UPDATE
                        SET via_nombre = EXCLUDED.via_nombre, tivi_id = EXCLUDED.tivi_id, via_estado = 'A';
                    """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])
                else:
                    session.execute(text("""
                        INSERT OR REPLACE INTO tb_via (via_id, tivi_id, via_nombre, via_estado)
                        VALUES (:via_id, :tivi_id, :via_nombre, 'A');
                    """), [{"via_id": v[0], "tivi_id": v[1], "via_nombre": v[2]} for v in chunk])

            # Forzar importación completa de tb_zona
            chunk_size = 200
            for i in range(0, len(phys_zonas), chunk_size):
                chunk = phys_zonas[i:i + chunk_size]
                if is_postgres:
                    session.execute(text(f"""
                        INSERT INTO "{target_schema}"."tb_zona" (zona_id, tizo_id, zona_nombre, zona_estado)
                        VALUES (:zona_id, :tizo_id, :zona_nombre, 'A')
                        ON CONFLICT (zona_id) DO UPDATE
                        SET zona_nombre = EXCLUDED.zona_nombre, tizo_id = EXCLUDED.tizo_id, zona_estado = 'A';
                    """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])
                else:
                    session.execute(text("""
                        INSERT OR REPLACE INTO tb_zona (zona_id, tizo_id, zona_nombre, zona_estado)
                        VALUES (:zona_id, :tizo_id, :zona_nombre, 'A');
                    """), [{"zona_id": z[0], "tizo_id": z[1], "zona_nombre": z[2]} for z in chunk])

            v_tbl = f'"{target_schema}"."tb_via"' if is_postgres else '"tb_via"'
            z_tbl = f'"{target_schema}"."tb_zona"' if is_postgres else '"tb_zona"'
            tv_tbl = f'"{target_schema}"."tb_tipo_via"' if is_postgres else '"tb_tipo_via"'
            tz_tbl = f'"{target_schema}"."tb_tipo_zona"' if is_postgres else '"tb_tipo_zona"'

            res["tb_tipo_via_count"] = session.execute(text(f"SELECT COUNT(*) FROM {tv_tbl};")).scalar() or 0
            res["tb_tipo_zona_count"] = session.execute(text(f"SELECT COUNT(*) FROM {tz_tbl};")).scalar() or 0
            res["tb_via_count"] = session.execute(text(f"SELECT COUNT(*) FROM {v_tbl};")).scalar() or 0
            res["tb_zona_count"] = session.execute(text(f"SELECT COUNT(*) FROM {z_tbl};")).scalar() or 0

        # Limpiar cualquier ID residual post-inserción
        self.consolidate_catalog_duplicates(target_schema)

        return res

    def ensure_tb_direccion_exists(self, target_schema: Optional[str] = "public") -> bool:
        """Asegura de manera autónoma y aislada la existencia de tb_direccion en el esquema objetivo
        con todas sus columnas para migración desacoplada e índices de reanudación.
        NO depende ni invoca catálogos externos ni scripts DDL masivos, garantizando 100% resiliencia.
        """
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return False

        schema = target_schema or "public"
        if schema in self._tb_direccion_verified:
            return True

        is_postgres = False
        is_sqlite = False
        try:
            dialect_name = self._engine.dialect.name if self._engine else ""
            is_postgres = (dialect_name == "postgresql")
            is_sqlite = (dialect_name == "sqlite")
        except Exception:
            pass

        target_tbl = f'"{schema}"."tb_direccion"' if (is_postgres and schema and schema not in ("", "main")) else '"tb_direccion"'

        try:
            with self.get_session() as session:
                # 1. Consultar columnas que ya existen físicamente en tb_direccion para evitar DDL redundante
                existing_cols = set()
                table_already_exists = False
                if is_postgres:
                    col_rows = session.execute(text("""
                        SELECT LOWER(column_name) 
                        FROM information_schema.columns 
                        WHERE table_schema = :schema AND table_name = 'tb_direccion';
                    """), {"schema": schema}).fetchall()
                    existing_cols = {r[0] for r in col_rows}
                    table_already_exists = bool(existing_cols)
                elif is_sqlite:
                    try:
                        col_rows = session.execute(text(f"PRAGMA table_info({target_tbl});")).fetchall()
                        existing_cols = {r[1].lower() for r in col_rows}
                        table_already_exists = bool(existing_cols)
                    except Exception:
                        table_already_exists = False

                # FAST-PATH: Si la tabla ya existe y contiene las columnas requeridas de negocio y auditoría
                required_cols = {
                    "dire_id", "zona_id", "dire_referencia", "dire_estado",
                    "dire_esquema", "dire_tabla", "dire_tabla_id", "dire_valor_origen",
                    "dire_es_procesado", "create_at", "update_at", "audit_mac_address"
                }
                if table_already_exists and required_cols.issubset(existing_cols):
                    self._tb_direccion_verified.add(schema)
                    logger.info("Estructura de tb_direccion verificada exitosamente en '%s'.", schema)
                    return True

                # Si no existe la tabla, crearla de forma limpia
                if not table_already_exists:
                    if is_postgres:
                        create_table_sql = f"""
                        CREATE TABLE IF NOT EXISTS {target_tbl} (
                            dire_id             BIGSERIAL NOT NULL,
                            zona_id             BIGINT,
                            dire_referencia     TEXT,
                            dire_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',
                            dire_esquema        VARCHAR(500),
                            dire_tabla          VARCHAR(500),
                            dire_tabla_id       BIGINT,
                            dire_valor_origen   VARCHAR(500),
                            dire_es_procesado   BOOLEAN,
                            usua_id             BIGINT,
                            usua_nombre         VARCHAR(200),
                            create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                            update_at           TIMESTAMP WITHOUT TIME ZONE,
                            audit_user_pc       VARCHAR(100),
                            audit_nombre_pc     VARCHAR(100),
                            audit_ip            VARCHAR(50),
                            audit_mac_address   VARCHAR(50),
                            CONSTRAINT pk_tb_direccion PRIMARY KEY (dire_id)
                        );
                        """
                    else:
                        create_table_sql = f"""
                        CREATE TABLE IF NOT EXISTS {target_tbl} (
                            dire_id             INTEGER PRIMARY KEY AUTOINCREMENT,
                            zona_id             INTEGER,
                            dire_referencia     TEXT,
                            dire_estado         VARCHAR(3) DEFAULT 'ACT',
                            dire_esquema        VARCHAR(500),
                            dire_tabla          VARCHAR(500),
                            dire_tabla_id       INTEGER,
                            dire_valor_origen   VARCHAR(500),
                            dire_es_procesado   BOOLEAN,
                            usua_id             INTEGER,
                            usua_nombre         VARCHAR(200),
                            create_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            update_at           TIMESTAMP,
                            audit_user_pc       VARCHAR(100),
                            audit_nombre_pc     VARCHAR(100),
                            audit_ip            VARCHAR(50),
                            audit_mac_address   VARCHAR(50)
                        );
                        """
                    session.execute(text(create_table_sql))
                    # Recargar existing_cols
                    if is_postgres:
                        col_rows = session.execute(text("""
                            SELECT LOWER(column_name) 
                            FROM information_schema.columns 
                            WHERE table_schema = :schema AND table_name = 'tb_direccion';
                        """), {"schema": schema}).fetchall()
                        existing_cols = {r[0] for r in col_rows}
                    elif is_sqlite:
                        col_rows = session.execute(text(f"PRAGMA table_info({target_tbl});")).fetchall()
                        existing_cols = {r[1].lower() for r in col_rows}

                # 2.1. Renombrar columnas legacy si existían (resa_created_at/created_at -> create_at, resa_updated_at/updated_at -> update_at)
                for old_name in ("resa_created_at", "resa_create_at", "created_at"):
                    if old_name in existing_cols and "create_at" not in existing_cols:
                        try:
                            if is_postgres:
                                with session.begin_nested():
                                    session.execute(text(f'ALTER TABLE {target_tbl} RENAME COLUMN "{old_name}" TO "create_at";'))
                            else:
                                session.execute(text(f'ALTER TABLE {target_tbl} RENAME COLUMN "{old_name}" TO "create_at";'))
                            existing_cols.remove(old_name)
                            existing_cols.add("create_at")
                            break
                        except Exception as ex_ren:
                            logger.debug("Aviso al renombrar %s a create_at en %s: %s", old_name, target_tbl, ex_ren)

                for old_name in ("resa_updated_at", "resa_update_at", "updated_at"):
                    if old_name in existing_cols and "update_at" not in existing_cols:
                        try:
                            if is_postgres:
                                with session.begin_nested():
                                    session.execute(text(f'ALTER TABLE {target_tbl} RENAME COLUMN "{old_name}" TO "update_at";'))
                            else:
                                session.execute(text(f'ALTER TABLE {target_tbl} RENAME COLUMN "{old_name}" TO "update_at";'))
                            existing_cols.remove(old_name)
                            existing_cols.add("update_at")
                            break
                        except Exception as ex_ren:
                            logger.debug("Aviso al renombrar %s a update_at en %s: %s", old_name, target_tbl, ex_ren)

                # 2.2. Eliminar de manera segura la columna redundante fecha_proceso si existe
                if "fecha_proceso" in existing_cols:
                    try:
                        if is_postgres:
                            with session.begin_nested():
                                session.execute(text(f'ALTER TABLE {target_tbl} DROP COLUMN IF EXISTS "fecha_proceso";'))
                        else:
                            session.execute(text(f'ALTER TABLE {target_tbl} DROP COLUMN "fecha_proceso";'))
                        existing_cols.remove("fecha_proceso")
                    except Exception as ex_drop:
                        logger.debug("Aviso al eliminar columna redundante fecha_proceso en %s: %s", target_tbl, ex_drop)

                # 3. Definición de columnas requeridas a nivel de negocio y auditoría
                cols_to_add = [
                    ("zona_id", "BIGINT" if is_postgres else "INTEGER"),
                    ("dire_referencia", "TEXT"),
                    ("dire_estado", "VARCHAR(3) DEFAULT 'ACT'"),
                    ("dire_esquema", "VARCHAR(500)"),
                    ("dire_tabla", "VARCHAR(500)"),
                    ("dire_tabla_id", "BIGINT" if is_postgres else "INTEGER"),
                    ("dire_valor_origen", "VARCHAR(500)"),
                    ("dire_es_procesado", "BOOLEAN"),
                    ("usua_id", "BIGINT" if is_postgres else "INTEGER"),
                    ("usua_nombre", "VARCHAR(200)"),
                    ("create_at", "TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP" if is_postgres else "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                    ("update_at", "TIMESTAMP WITHOUT TIME ZONE" if is_postgres else "TIMESTAMP"),
                    ("audit_user_pc", "VARCHAR(100)"),
                    ("audit_nombre_pc", "VARCHAR(100)"),
                    ("audit_ip", "VARCHAR(50)"),
                    ("audit_mac_address", "VARCHAR(50)"),
                ]

                # Agregar ÚNICAMENTE columnas que no existan
                for col_name, col_type in cols_to_add:
                    if col_name.lower() not in existing_cols:
                        try:
                            if is_postgres:
                                with session.begin_nested():
                                    session.execute(text(f'ALTER TABLE {target_tbl} ADD COLUMN "{col_name}" {col_type};'))
                            else:
                                clean_t = col_type.split("DEFAULT")[0].strip() if "DEFAULT" in col_type else col_type
                                session.execute(text(f'ALTER TABLE {target_tbl} ADD COLUMN "{col_name}" {clean_t};'))
                            existing_cols.add(col_name.lower())
                        except Exception as ex_col:
                            logger.debug("Aviso al agregar columna %s en %s: %s", col_name, target_tbl, ex_col)

                # 4. Crear índices de manera segura sin colisionar
                if is_postgres:
                    idx_stmts = [
                        f'CREATE INDEX IF NOT EXISTS idx_tb_direccion_proc ON {target_tbl} (dire_esquema, dire_tabla, dire_es_procesado);',
                        f'CREATE INDEX IF NOT EXISTS idx_tb_direccion_origen_lookup ON {target_tbl} (dire_esquema, dire_tabla, dire_tabla_id);',
                        f'CREATE INDEX IF NOT EXISTS idx_tb_direccion_zona ON {target_tbl} (zona_id);',
                    ]
                    for idx_sql in idx_stmts:
                        try:
                            with session.begin_nested():
                                session.execute(text(idx_sql))
                        except Exception as ex_idx:
                            logger.debug("Aviso al crear índice en %s: %s", target_tbl, ex_idx)

                    # Si existe tb_zona en el mismo esquema, vincular FK condicionalmente
                    try:
                        has_zona = session.execute(text("""
                            SELECT 1 FROM information_schema.tables
                            WHERE table_schema = :schema AND table_name = 'tb_zona';
                        """), {"schema": schema}).scalar()
                        if has_zona:
                            session.execute(text(f"""
                                DO $$
                                BEGIN
                                    IF NOT EXISTS (
                                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_tb_direccion_zona'
                                    ) THEN
                                        ALTER TABLE {target_tbl}
                                        ADD CONSTRAINT fk_tb_direccion_zona
                                        FOREIGN KEY (zona_id) REFERENCES "{schema}"."tb_zona"(zona_id)
                                        ON UPDATE CASCADE ON DELETE SET NULL;
                                    END IF;
                                EXCEPTION WHEN OTHERS THEN NULL;
                                END $$;
                            """))
                    except Exception as ex_fk:
                        logger.debug("Aviso al asociar FK de zona en %s: %s", target_tbl, ex_fk)

            self._tb_direccion_verified.add(schema)
            logger.info("Estructura de tb_direccion verificada/creada exitosamente en '%s'.", schema)
            return True
        except Exception as e:
            logger.error("Error al asegurar tabla tb_direccion en %s: %s", schema, e)
            return False

    def ensure_tb_direccion_columns(self, schema: Optional[str] = None) -> bool:
        """Asegura que tb_direccion contenga las columnas de procedencia cruda y tri-state
        (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen, dire_es_procesado, fecha_proceso)
        junto con los índices para reanudación y consulta rápida.
        """
        return self.ensure_tb_direccion_exists(target_schema=schema)

    def migrate_source_table_to_tb_direccion(
        self,
        source_schema: str,
        source_table: str,
        id_col: str,
        addr_col: str,
        drop_source_col: bool = False,
        batch_size: int = 1000,
        target_catalog_schema: str = "public",
    ) -> Dict[str, Any]:
        """Fase A (Pre-migración e Ingesta):
        Migra todas las direcciones crudas desde una tabla fuente hacia public.tb_direccion
        sin alterar la tabla fuente (cero adición de columnas ni llaves en la fuente).
        Toda la correlación de procedencia queda registrada en public.tb_direccion
        (dire_esquema, dire_tabla, dire_tabla_id, dire_valor_origen).
        Opcionalmente elimina la columna de texto original de la tabla fuente si drop_source_col es True.
        """
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return {"success": False, "error": "No hay conexión a base de datos disponible."}

        is_postgres = False
        is_sqlite = False
        try:
            dialect_name = self._engine.dialect.name if self._engine else ""
            is_postgres = (dialect_name == "postgresql")
            is_sqlite = (dialect_name == "sqlite")
        except Exception:
            pass

        # Asegurar e integrar de forma definitiva la arquitectura relacional V2 completa en el esquema central
        # Asegurar exclusivamente la existencia y estructura de tb_direccion en el esquema central (Fase A).
        # La verificación de catálogos relacionales V2 (tb_via, tb_zona, etc.) y CatalogMatcher
        # pertenece exclusivamente a la Fase B (Normalización con IA) y no debe demorar la ingesta cruda.
        self.ensure_tb_direccion_exists(target_catalog_schema)

        src_table_ref = f'"{source_table}"' if is_sqlite else (f'"{source_schema}"."{source_table}"' if (source_schema and source_schema not in ("", "main")) else f'"{source_table}"')
        target_dir_ref = f'"{target_catalog_schema}"."tb_direccion"' if (not is_sqlite and target_catalog_schema and target_catalog_schema not in ("", "main")) else '"tb_direccion"'

        logger.info("Iniciando migración atómica rápida (Fase A) desde %s hacia %s...", src_table_ref, target_dir_ref)

        try:
            with self.get_session() as session:
                # 1. Conteo de registros totales en la fuente
                total_source = session.execute(text(f"""
                    SELECT COUNT(*) FROM {src_table_ref};
                """)).scalar() or 0

                # 2. Conteo de registros que ya están presentes en tb_direccion para esta tabla
                already_in_dir = session.execute(text(f"""
                    SELECT COUNT(*) FROM {target_dir_ref}
                    WHERE dire_esquema = :esq AND dire_tabla = :tab;
                """), {"esq": source_schema or "public", "tab": source_table}).scalar() or 0

                is_postgres = False
                try:
                    dialect_name = self._engine.dialect.name if self._engine else ""
                    is_postgres = (dialect_name == "postgresql")
                except Exception:
                    pass

                migrated_count = 0

                # Si no hay registros en la fuente, retornar de inmediato
                if total_source == 0:
                    return {
                        "success": True,
                        "source_schema": source_schema,
                        "source_table": source_table,
                        "total_source": 0,
                        "already_linked": already_in_dir,
                        "already_migrated": already_in_dir,
                        "migrated": 0,
                        "total_in_tb_direccion": already_in_dir,
                        "remaining_unlinked": 0,
                        "column_dropped": False,
                    }

                # Si ya todos los registros están migrados, retornar de inmediato
                if already_in_dir >= total_source:
                    return {
                        "success": True,
                        "source_schema": source_schema,
                        "source_table": source_table,
                        "total_source": total_source,
                        "already_linked": already_in_dir,
                        "already_migrated": already_in_dir,
                        "migrated": 0,
                        "total_in_tb_direccion": already_in_dir,
                        "remaining_unlinked": 0,
                        "column_dropped": False,
                    }

                # 3. Migración atómica, fluida y resiliente
                if is_postgres:
                    if already_in_dir == 0:
                        # Vía directa en una sola operación atómica (sin bucles)
                        insert_sql = text(f"""
                            INSERT INTO {target_dir_ref} (
                                dire_esquema, dire_tabla, dire_tabla_id,
                                dire_valor_origen, dire_es_procesado, dire_estado, update_at
                            )
                            SELECT
                                :esq,
                                :tab,
                                CASE 
                                    WHEN src."{id_col}" IS NULL THEN NULL
                                    WHEN CAST(src."{id_col}" AS TEXT) ~ '^-?[0-9]+$' THEN CAST(src."{id_col}" AS BIGINT)
                                    ELSE NULL
                                END,
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN NULL ELSE CAST(src."{addr_col}" AS TEXT) END,
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN FALSE ELSE NULL END,
                                'ACT',
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN CURRENT_TIMESTAMP ELSE NULL END
                            FROM {src_table_ref} src;
                        """)
                        res = session.execute(insert_sql, {
                            "esq": source_schema or "public",
                            "tab": source_table,
                        })
                        migrated_count = res.rowcount if (res.rowcount and res.rowcount > 0) else total_source
                    else:
                        # Vía incremental: insertar únicamente registros faltantes sin bucles infinitos
                        insert_sql = text(f"""
                            INSERT INTO {target_dir_ref} (
                                dire_esquema, dire_tabla, dire_tabla_id,
                                dire_valor_origen, dire_es_procesado, dire_estado, update_at
                            )
                            SELECT
                                :esq,
                                :tab,
                                CASE 
                                    WHEN src."{id_col}" IS NULL THEN NULL
                                    WHEN CAST(src."{id_col}" AS TEXT) ~ '^-?[0-9]+$' THEN CAST(src."{id_col}" AS BIGINT)
                                    ELSE NULL
                                END,
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN NULL ELSE CAST(src."{addr_col}" AS TEXT) END,
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN FALSE ELSE NULL END,
                                'ACT',
                                CASE WHEN TRIM(COALESCE(CAST(src."{addr_col}" AS TEXT), '')) = '' THEN CURRENT_TIMESTAMP ELSE NULL END
                            FROM {src_table_ref} src
                            WHERE NOT EXISTS (
                                SELECT 1 FROM {target_dir_ref} d
                                WHERE d.dire_esquema = :esq
                                  AND d.dire_tabla = :tab
                                  AND (
                                      (
                                          src."{id_col}" IS NOT NULL 
                                          AND CAST(src."{id_col}" AS TEXT) ~ '^-?[0-9]+$' 
                                          AND d.dire_tabla_id = (CASE WHEN CAST(src."{id_col}" AS TEXT) ~ '^-?[0-9]+$' THEN CAST(src."{id_col}" AS BIGINT) ELSE NULL END)
                                      )
                                      OR (
                                          (src."{id_col}" IS NULL OR NOT (CAST(src."{id_col}" AS TEXT) ~ '^-?[0-9]+$'))
                                          AND d.dire_tabla_id IS NULL 
                                          AND d.dire_valor_origen IS NOT DISTINCT FROM CAST(src."{addr_col}" AS TEXT)
                                      )
                                  )
                            );
                        """)
                        res = session.execute(insert_sql, {
                            "esq": source_schema or "public",
                            "tab": source_table,
                        })
                        migrated_count = res.rowcount if (res.rowcount and res.rowcount > 0) else max(0, total_source - already_in_dir)

                    logger.info("Migración PostgreSQL fluida: %d registros de %s.%s ingresados a %s.tb_direccion", migrated_count, source_schema, source_table, target_catalog_schema)

                else:
                    # Modo estándar / SQLite (compatible con tests unitarios y entornos de prueba)
                    if already_in_dir == 0:
                        insert_sql = text(f"""
                            INSERT INTO {target_dir_ref} (
                                dire_esquema, dire_tabla, dire_tabla_id,
                                dire_valor_origen, dire_es_procesado, dire_estado, update_at
                            )
                            SELECT
                                :esq,
                                :tab,
                                src."{id_col}",
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN NULL ELSE src."{addr_col}" END,
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN 0 ELSE NULL END,
                                'ACT',
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN CURRENT_TIMESTAMP ELSE NULL END
                            FROM {src_table_ref} src;
                        """)
                        res = session.execute(insert_sql, {
                            "esq": source_schema or "public",
                            "tab": source_table,
                        })
                        migrated_count = res.rowcount if (res.rowcount and res.rowcount > 0) else total_source
                    else:
                        insert_sql = text(f"""
                            INSERT INTO {target_dir_ref} (
                                dire_esquema, dire_tabla, dire_tabla_id,
                                dire_valor_origen, dire_es_procesado, dire_estado, update_at
                            )
                            SELECT
                                :esq,
                                :tab,
                                src."{id_col}",
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN NULL ELSE src."{addr_col}" END,
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN 0 ELSE NULL END,
                                'ACT',
                                CASE WHEN TRIM(COALESCE(src."{addr_col}", '')) = '' THEN CURRENT_TIMESTAMP ELSE NULL END
                            FROM {src_table_ref} src
                            WHERE NOT EXISTS (
                                SELECT 1 FROM {target_dir_ref} d
                                WHERE d.dire_esquema = :esq
                                  AND d.dire_tabla = :tab
                                  AND (
                                      (src."{id_col}" IS NOT NULL AND d.dire_tabla_id = src."{id_col}")
                                      OR (src."{id_col}" IS NULL AND d.dire_tabla_id IS NULL AND (d.dire_valor_origen IS src."{addr_col}" OR (d.dire_valor_origen IS NULL AND src."{addr_col}" IS NULL)))
                                  )
                            );
                        """)
                        res = session.execute(insert_sql, {
                            "esq": source_schema or "public",
                            "tab": source_table,
                        })
                        migrated_count = res.rowcount if (res.rowcount and res.rowcount > 0) else max(0, total_source - already_in_dir)

                    logger.info("Migración SQLite/estándar fluida: %d registros ingresados a %s", migrated_count, target_dir_ref)

                # 3. Conteo final en tb_direccion para esta fuente
                total_in_dir_after = session.execute(text(f"""
                    SELECT COUNT(*) FROM {target_dir_ref}
                    WHERE dire_esquema = :esq AND dire_tabla = :tab;
                """), {"esq": source_schema or "public", "tab": source_table}).scalar() or 0

                remaining_unlinked = max(0, total_source - total_in_dir_after)

                # 4. Eliminación opcional de la columna de texto original (solo si 100% de filas en tb_direccion)
                column_dropped = False
                if drop_source_col:
                    if remaining_unlinked == 0 and total_source > 0:
                        try:
                            session.execute(text(f"""
                                ALTER TABLE {src_table_ref}
                                DROP COLUMN IF EXISTS "{addr_col}";
                            """))
                            column_dropped = True
                            logger.info(
                                "Columna '%s' eliminada de %s tras migración completa hacia tb_direccion.",
                                addr_col, src_table_ref
                            )
                        except Exception as ex_drop:
                            logger.warning("No se pudo eliminar columna %s en %s: %s", addr_col, src_table_ref, ex_drop)
                    else:
                        logger.warning(
                            "No se eliminó la columna '%s' porque restan %d registros por migrar.",
                            addr_col, remaining_unlinked
                        )

                return {
                    "success": True,
                    "source_schema": source_schema,
                    "source_table": source_table,
                    "total_source": total_source,
                    "already_linked": already_in_dir,
                    "already_migrated": already_in_dir,
                    "migrated": migrated_count,
                    "total_in_tb_direccion": total_in_dir_after,
                    "remaining_unlinked": remaining_unlinked,
                    "column_dropped": column_dropped,
                }
        except Exception as e:
            logger.error("Error en migración de tabla fuente a tb_direccion: %s", e)
            return {"success": False, "error": str(e)}

    def get_ingested_sources_overview(self, catalog_schema: str = "public") -> List[Dict[str, Any]]:
        """Retorna el listado de combinaciones (esquema, tabla) ingestadas en tb_direccion
        junto con sus estadísticas de progreso catastral (total, pendientes, normalizados, rechazados).
        """
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return []

        if not self.table_exists("tb_direccion", catalog_schema):
            return []

        if catalog_schema not in self._tb_direccion_verified:
            self.ensure_tb_direccion_columns(catalog_schema)

        sql = text(f"""
            SELECT 
                COALESCE(NULLIF(dire_esquema, ''), 'public') AS dire_esquema,
                COALESCE(NULLIF(dire_tabla, ''), 'tb_direccion') AS dire_tabla,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE dire_es_procesado IS NULL) AS pendientes,
                COUNT(*) FILTER (WHERE dire_es_procesado IS TRUE) AS normalizados,
                COUNT(*) FILTER (WHERE dire_es_procesado IS FALSE) AS rechazados,
                MAX(COALESCE(update_at, create_at)) AS ultima_fecha
            FROM "{catalog_schema}"."tb_direccion"
            GROUP BY COALESCE(NULLIF(dire_esquema, ''), 'public'), COALESCE(NULLIF(dire_tabla, ''), 'tb_direccion')
            ORDER BY dire_esquema, dire_tabla;
        """)
        try:
            with self.get_session() as session:
                rows = session.execute(sql).fetchall()
                results = []
                for r in rows:
                    last_dt = r[6].isoformat() if hasattr(r[6], "isoformat") else (str(r[6]) if r[6] else None)
                    results.append({
                        "dire_esquema": r[0],
                        "dire_tabla": r[1],
                        "total": int(r[2] or 0),
                        "pendientes": int(r[3] or 0),
                        "normalizados": int(r[4] or 0),
                        "rechazados": int(r[5] or 0),
                        "ultima_fecha": last_dt,
                    })
                return results
        except Exception as e:
            logger.debug("Aviso al consultar fuentes ingestadas en %s.tb_direccion: %s", catalog_schema, e)
            return []

    def get_central_tb_direccion_stats(self, catalog_schema: str = "public") -> Dict[str, Any]:
        """Retorna los conteos globales consolidados de public.tb_direccion."""
        default_stats = {
            "total": 0,
            "pendientes": 0,
            "normalizados": 0,
            "rechazados": 0,
            "has_records": False,
            "sources_count": 0,
        }
        if not SQLALCHEMY_AVAILABLE or not self._engine:
            return default_stats

        if not self.table_exists("tb_direccion", catalog_schema):
            return default_stats

        if catalog_schema not in self._tb_direccion_verified:
            self.ensure_tb_direccion_columns(catalog_schema)

        sql = text(f"""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE dire_es_procesado IS NULL) AS pendientes,
                COUNT(*) FILTER (WHERE dire_es_procesado IS TRUE OR dire_es_procesado = 1) AS normalizados,
                COUNT(*) FILTER (WHERE dire_es_procesado IS FALSE OR dire_es_procesado = 0) AS rechazados,
                COUNT(DISTINCT (COALESCE(NULLIF(dire_esquema, ''), 'public') || '::' || COALESCE(NULLIF(dire_tabla, ''), 'tb_direccion'))) AS sources_count
            FROM "{catalog_schema}"."tb_direccion";
        """)
        try:
            with self.get_session() as session:
                row = session.execute(sql).fetchone()
                if row:
                    tot = int(row.total or 0)
                    return {
                        "total": tot,
                        "pendientes": int(row.pendientes or 0),
                        "normalizados": int(row.normalizados or 0),
                        "rechazados": int(row.rechazados or 0),
                        "has_records": (tot > 0),
                        "sources_count": int(row.sources_count or 0),
                    }
        except Exception as e:
            logger.debug("Aviso al consultar estadísticas globales de %s.tb_direccion: %s", catalog_schema, e)

        return default_stats

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
