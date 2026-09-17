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
        t_via = table_tipo_via or self.settings.table_tipo_via
        t_zona = table_tipo_zona or self.settings.table_tipo_zona
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
                # 1. Tabla vias
                vias_check = session.execute(text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": target_schema, "table": t_vias}).scalar()

                if not vias_check or vias_check == 0:
                    create_vias_sql = f"""
                    CREATE TABLE "{target_schema}"."{t_vias}" (
                        id_via              INTEGER NOT NULL,
                        codigo_via          VARCHAR(20),
                        id_tipo_via         INTEGER,
                        nom_via             VARCHAR(150) NOT NULL,
                        clasificacion_vial  VARCHAR(100),
                        jurisdiccion        VARCHAR(100),
                        CONSTRAINT pk_{target_schema}_{t_vias} PRIMARY KEY (id_via),
                        CONSTRAINT fk_{target_schema}_{t_vias}_tipo FOREIGN KEY (id_tipo_via) REFERENCES "{target_schema}"."{t_tipo_via}"(id_tipo_via) ON UPDATE CASCADE ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_vias}_nom ON "{target_schema}"."{t_vias}" (nom_via);
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_vias}_cod ON "{target_schema}"."{t_vias}" (codigo_via);
                    """
                    session.execute(text(create_vias_sql))
                    results[t_vias]["table_created"] = True

                # Verificar si tiene registros
                vias_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."{t_vias}";')).scalar() or 0
                if vias_count == 0:
                    vias_tuples = CatalogManager.get_official_physical_vias_tuples()
                    insert_vias_sql = text(f"""
                        INSERT INTO "{target_schema}"."{t_vias}" (id_via, codigo_via, id_tipo_via, nom_via, clasificacion_vial, jurisdiccion)
                        VALUES (:id_via, :codigo_via, :id_tipo_via, :nom_via, :clasif, :juris)
                        ON CONFLICT (id_via) DO NOTHING;
                    """)
                    session.execute(
                        insert_vias_sql,
                        [
                            {
                                "id_via": item[0],
                                "codigo_via": item[1],
                                "id_tipo_via": item[2],
                                "nom_via": item[3],
                                "clasif": item[4],
                                "juris": item[5],
                            }
                            for item in vias_tuples
                        ],
                    )
                    results[t_vias]["records_seeded"] = len(vias_tuples)
                    results[t_vias]["total_records"] = len(vias_tuples)
                else:
                    results[t_vias]["total_records"] = vias_count

                # 2. Tabla zonas
                zonas_check = session.execute(text("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": target_schema, "table": t_zonas}).scalar()

                if not zonas_check or zonas_check == 0:
                    create_zonas_sql = f"""
                    CREATE TABLE "{target_schema}"."{t_zonas}" (
                        id_zona             INTEGER NOT NULL,
                        codigo_zona         VARCHAR(20),
                        id_tipo_zona        INTEGER,
                        nom_zona            VARCHAR(150) NOT NULL,
                        sector_catastral    VARCHAR(50),
                        condicion           VARCHAR(20),
                        CONSTRAINT pk_{target_schema}_{t_zonas} PRIMARY KEY (id_zona),
                        CONSTRAINT fk_{target_schema}_{t_zonas}_tipo FOREIGN KEY (id_tipo_zona) REFERENCES "{target_schema}"."{t_tipo_zona}"(id_tipo_zona) ON UPDATE CASCADE ON DELETE SET NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_zonas}_nom ON "{target_schema}"."{t_zonas}" (nom_zona);
                    CREATE INDEX IF NOT EXISTS idx_{target_schema}_{t_zonas}_cod ON "{target_schema}"."{t_zonas}" (codigo_zona);
                    """
                    session.execute(text(create_zonas_sql))
                    results[t_zonas]["table_created"] = True

                zonas_count = session.execute(text(f'SELECT COUNT(*) FROM "{target_schema}"."{t_zonas}";')).scalar() or 0
                if zonas_count == 0:
                    zonas_tuples = CatalogManager.get_official_physical_zonas_tuples()
                    insert_zonas_sql = text(f"""
                        INSERT INTO "{target_schema}"."{t_zonas}" (id_zona, codigo_zona, id_tipo_zona, nom_zona, sector_catastral, condicion)
                        VALUES (:id_zona, :codigo_zona, :id_tipo_zona, :nom_zona, :sector, :cond)
                        ON CONFLICT (id_zona) DO NOTHING;
                    """)
                    session.execute(
                        insert_zonas_sql,
                        [
                            {
                                "id_zona": item[0],
                                "codigo_zona": item[1],
                                "id_tipo_zona": item[2],
                                "nom_zona": item[3],
                                "sector": item[4],
                                "cond": item[5],
                            }
                            for item in zonas_tuples
                        ],
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
            "tipo_via": self.settings.col_tipo_via,
            "nom_via": self.settings.col_nom_via,
            "num_via": self.settings.col_num_via,
            "id_zona": self.settings.col_id_zona,
            "tipo_zona": self.settings.col_tipo_zona,
            "nom_zona": self.settings.col_nom_zona,
            "manzana": self.settings.col_manzana,
            "lote": self.settings.col_lote,
            "slote": self.settings.col_slote,
            "referencia": self.settings.col_referencia,
        }

        ddl = f"""
        ALTER TABLE "{schema}"."{table}"
            ADD COLUMN IF NOT EXISTS "{cols['id_via']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['tipo_via']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['nom_via']}" VARCHAR(150),
            ADD COLUMN IF NOT EXISTS "{cols['num_via']}" VARCHAR(50),
            ADD COLUMN IF NOT EXISTS "{cols['id_zona']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['tipo_zona']}" INTEGER,
            ADD COLUMN IF NOT EXISTS "{cols['nom_zona']}" VARCHAR(150),
            ADD COLUMN IF NOT EXISTS "{cols['manzana']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['lote']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['slote']}" VARCHAR(20),
            ADD COLUMN IF NOT EXISTS "{cols['referencia']}" VARCHAR(255);
        """

        try:
            with self.get_session() as session:
                session.execute(text(ddl))

                # Agregar llaves foráneas si existen las tablas maestras
                t_via = self.settings.table_tipo_via
                t_zona = self.settings.table_tipo_zona
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
                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_tipo_via'
                    ) THEN
                        ALTER TABLE "{schema}"."{table}"
                            ADD CONSTRAINT fk_in_place_tipo_via
                            FOREIGN KEY ("{cols['tipo_via']}") REFERENCES "{schema}"."{t_via}"(id_tipo_via)
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

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_tipo_zona'
                    ) THEN
                        ALTER TABLE "{schema}"."{table}"
                            ADD CONSTRAINT fk_in_place_tipo_zona
                            FOREIGN KEY ("{cols['tipo_zona']}") REFERENCES "{schema}"."{t_zona}"(id_tipo_zona)
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
