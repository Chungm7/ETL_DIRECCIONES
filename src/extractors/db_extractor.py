"""Extractor dinámico desde PostgreSQL con soporte de esquemas y columnas configurables."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from src.extractors.base_extractor import BaseExtractor
from src.models.direccion_origen import DireccionOrigen
from src.services.db_service import DatabaseService
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.db_extractor")

try:
    from sqlalchemy import text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class DatabaseExtractor(BaseExtractor):
    """Extrae registros desde la tabla de origen configurada o directamente desde public.tb_direccion."""

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        id_col: Optional[str] = None,
        dir_col: Optional[str] = None,
        source_mode: str = "source_table",
        target_catalog_schema: str = "public",
    ):
        self.db = db_service or DatabaseService()
        settings = get_settings().db
        self.source_mode = source_mode  # "source_table" o "central_tb_direccion"
        self.target_catalog_schema = target_catalog_schema
        self.schema = schema or settings.schema
        self.table = table or settings.table
        self.id_col = id_col or settings.id_col
        self.dir_col = dir_col or settings.dir_col
        self.col_es_procesado = settings.col_es_procesado
        self.col_observacion: Optional[str] = None
        self.col_dire_id: Optional[str] = None
        self._columns_inspected = False

    @property
    def _tb_direccion_ref(self) -> str:
        """Retorna la referencia calificada de tb_direccion segura para SQLite y PostgreSQL."""
        is_sqlite = False
        try:
            if self.db._engine and hasattr(self.db._engine, "dialect"):
                is_sqlite = (self.db._engine.dialect.name == "sqlite")
        except Exception:
            pass
        if is_sqlite or not self.target_catalog_schema or self.target_catalog_schema.lower() in ("", "main"):
            return '"tb_direccion"'
        return f'"{self.target_catalog_schema}"."tb_direccion"'

    def _inspect_columns(self) -> None:
        """Inspecciona dinámicamente las columnas de la tabla para alinear nombres y filtros."""
        if self.source_mode == "central_tb_direccion":
            self.id_col = "dire_id"
            self.dir_col = "dire_valor_origen"
            self.col_es_procesado = "dire_es_procesado"
            self._columns_inspected = True
            return

        if self._columns_inspected or not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return
        try:
            with self.db.get_session() as session:
                rows = session.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = :schema AND table_name = :table;
                """), {"schema": self.schema, "table": self.table}).fetchall()
                cols = {r[0].lower(): r[0] for r in rows}

                for cand in [self.id_col, "id_licencia", "xxxx_id", "id", "id_direccion", "codigo"]:
                    if cand and cand.lower() in cols:
                        self.id_col = cols[cand.lower()]
                        break
                if self.id_col and self.id_col.lower() not in cols and cols:
                    self.id_col = next(iter(cols.values()))

                found_dir = False
                for cand in [self.dir_col, "emp_direccion", "xxxx_direccion_original", "direccion", "dir", "raw_text"]:
                    if cand and cand.lower() in cols:
                        self.dir_col = cols[cand.lower()]
                        found_dir = True
                        break
                if not found_dir:
                    if "dire_id" in cols:
                        self.dir_col = cols["dire_id"]
                    else:
                        other_cols = [c for c in cols.values() if c != self.id_col]
                        self.dir_col = other_cols[0] if other_cols else self.id_col

                for cand in [self.col_es_procesado, "xxxx_es_procesado", "es_procesado"]:
                    if cand and cand.lower() in cols:
                        self.col_es_procesado = cols[cand.lower()]
                        break

                for cand in ["xxxx_observacion_ia", "observacion_ia", "observacion"]:
                    if cand in cols:
                        self.col_observacion = cols[cand]
                        break

                if "dire_id" in cols:
                    self.col_dire_id = cols["dire_id"]

                self._columns_inspected = True
        except Exception as e:
            logger.debug("Aviso al inspeccionar columnas en extractor %s.%s: %s", self.schema, self.table, e)

    def _build_status_conditions(self) -> tuple:
        """Retorna las cláusulas SQL para pendientes, válidos y observados/rechazados según semántica tri-state."""
        if self.source_mode == "central_tb_direccion":
            cond_pending = '"dire_es_procesado" IS NULL'
            cond_valid = '("dire_es_procesado" IS TRUE OR "dire_es_procesado" = 1)'
            cond_observed = '("dire_es_procesado" = FALSE OR "dire_es_procesado" = 0)'
            return cond_pending, cond_valid, cond_observed

        self._inspect_columns()

        cond_pending = f'"{self.col_es_procesado}" IS NULL'
        cond_valid = f'"{self.col_es_procesado}" IS TRUE'
        cond_observed = f'"{self.col_es_procesado}" = FALSE'

        return cond_pending, cond_valid, cond_observed

    def _get_central_origin_condition(self) -> Tuple[str, Dict[str, Any]]:
        """Determina la condición de procedencia (dire_esquema / dire_tabla) en public.tb_direccion.
        Si se apunta a tb_direccion globalmente o no se especifica una tabla emisora concreta,
        retorna ('', {}) para procesar todo el catastro central sin filtrar por origen.
        """
        schema_str = (self.schema or "").strip().lower()
        table_str = (self.table or "").strip().lower()
        target_cat = (self.target_catalog_schema or "public").strip().lower()

        is_schema_global = not schema_str or schema_str in ("*", "todos", "all", "public", target_cat)
        is_table_global = not table_str or table_str in ("*", "todas", "all", "tb_direccion")

        if is_schema_global and is_table_global:
            # Procesar todo tb_direccion globalmente
            return "", {}

        if not is_schema_global and is_table_global:
            # Filtrar por un esquema de procedencia completo
            return '"dire_esquema" = :schema', {"schema": self.schema}

        # Filtrar por esquema y tabla de procedencia específicos
        return '"dire_esquema" = :schema AND "dire_tabla" = :table', {
            "schema": self.schema,
            "table": self.table,
        }

    def get_total_records(self) -> int:
        """Obtiene la cantidad total de registros en la tabla emisora o en tb_direccion."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            logger.warning("Base de datos no inicialiAzada. Retornando 0 registros.")
            return 0

        if self.source_mode == "central_tb_direccion":
            origin_cond, origin_params = self._get_central_origin_condition()
            where_sql = f"WHERE {origin_cond}" if origin_cond else ""
            query = text(f"""
                SELECT COUNT(*) FROM {self._tb_direccion_ref}
                {where_sql};
            """)
            params = origin_params
        else:
            query = text(f'SELECT COUNT(*) FROM "{self.schema}"."{self.table}";')
            params = {}

        try:
            with self.db.get_session() as session:
                count = session.execute(query, params).scalar()
                return int(count or 0)
        except Exception as e:
            logger.debug(
                "Aviso al contar registros en %s.%s: %s", self.schema, self.table, e
            )
            return 0

    def get_status_counts(self) -> dict:
        """Obtiene el conteo clasificado de registros: total, pendientes, válidos y observados."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return {"total": 0, "pendientes": 0, "validos": 0, "observados": 0}

        cond_pending, cond_valid, cond_observed = self._build_status_conditions()

        if self.source_mode == "central_tb_direccion":
            origin_cond, origin_params = self._get_central_origin_condition()
            where_sql = f"WHERE {origin_cond}" if origin_cond else ""
            query = text(f"""
                SELECT 
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE {cond_pending}) AS pendientes,
                    COUNT(*) FILTER (WHERE {cond_valid}) AS validos,
                    COUNT(*) FILTER (WHERE {cond_observed}) AS observados
                FROM {self._tb_direccion_ref}
                {where_sql};
            """)
            params = origin_params
        else:
            query = text(f"""
                SELECT 
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE {cond_pending}) AS pendientes,
                    COUNT(*) FILTER (WHERE {cond_valid}) AS validos,
                    COUNT(*) FILTER (WHERE {cond_observed}) AS observados
                FROM "{self.schema}"."{self.table}";
            """)
            params = {}

        try:
            with self.db.get_session() as session:
                row = session.execute(query, params).fetchone()
                if row:
                    return {
                        "total": int(row.total or 0),
                        "pendientes": int(row.pendientes or 0),
                        "validos": int(row.validos or 0),
                        "observados": int(row.observados or 0),
                    }
        except Exception as e:
            logger.debug("Aviso al consultar conteos clasificados en %s.%s: %s", self.schema, self.table, e)
            total = self.get_total_records()
            return {"total": total, "pendientes": total, "validos": 0, "observados": 0}

        return {"total": 0, "pendientes": 0, "validos": 0, "observados": 0}

    def get_pending_records_count(self) -> int:
        """Obtiene la cantidad de registros pendientes."""
        counts = self.get_status_counts()
        return counts.get("pendientes", 0)

    def extract_batch(
        self,
        offset: int = 0,
        limit: int = 100,
        filter_mode: str = "pending",
        after_id: Optional[int] = None,
        lock_for_update: bool = False,
    ) -> List[DireccionOrigen]:
        """Extrae un lote aplicando filtro de estado para reanudación automática con soporte opcional de row locking."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return []

        cond_pending, cond_valid, cond_observed = self._build_status_conditions()

        conditions = []
        params: Dict[str, Any] = {"limit": limit}

        if self.source_mode == "central_tb_direccion":
            origin_cond, origin_params = self._get_central_origin_condition()
            if origin_cond:
                conditions.append(origin_cond)
                params.update(origin_params)
            # En modo central tb_direccion, la normalización automatizada aplica estrictamente a registros pendientes (IS NULL)
            conditions.append(cond_pending)
        else:
            if filter_mode == "pending":
                conditions.append(cond_pending)
            elif filter_mode == "observed":
                conditions.append(cond_observed)
            elif filter_mode == "valid":
                conditions.append(cond_valid)

        id_field = "dire_id" if self.source_mode == "central_tb_direccion" else self.id_col

        if after_id is not None:
            conditions.append(f'"{id_field}" > :after_id')
            params["after_id"] = after_id
            offset_clause = ""
        else:
            params["offset"] = offset
            offset_clause = "OFFSET :offset"

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        is_postgresql = False
        try:
            if self.db._engine and hasattr(self.db._engine, "dialect"):
                is_postgresql = "postgresql" in str(self.db._engine.dialect.name).lower()
        except Exception:
            is_postgresql = False

        lock_clause = "FOR UPDATE SKIP LOCKED" if (lock_for_update and is_postgresql) else ""

        if self.source_mode == "central_tb_direccion":
            query = text(f"""
                SELECT 
                    "dire_id" AS id_val,
                    "dire_valor_origen" AS dir_val,
                    "dire_tabla_id",
                    "dire_esquema",
                    "dire_tabla",
                    "dire_es_procesado"
                FROM {self._tb_direccion_ref}
                {where_clause}
                ORDER BY "dire_id" ASC
                LIMIT :limit {offset_clause}
                {lock_clause};
            """)
        else:
            query = text(f"""
                SELECT "{self.id_col}" AS id_val, "{self.dir_col}" AS dir_val
                FROM "{self.schema}"."{self.table}"
                {where_clause}
                ORDER BY "{self.id_col}" ASC
                LIMIT :limit {offset_clause}
                {lock_clause};
            """)

        results: List[DireccionOrigen] = []
        try:
            with self.db.get_session() as session:
                rows = session.execute(query, params).fetchall()
                for row in rows:
                    if self.source_mode == "central_tb_direccion":
                        results.append(
                            DireccionOrigen(
                                id_licencia=row.dire_tabla_id or row.id_val,
                                emp_direccion=row.dir_val,
                                dire_id=row.id_val,
                                dire_esquema=row.dire_esquema,
                                dire_tabla=row.dire_tabla,
                                dire_tabla_id=row.dire_tabla_id,
                                dire_valor_origen=row.dir_val,
                                es_procesado=bool(row.dire_es_procesado) if row.dire_es_procesado is not None else False,
                            )
                        )
                    else:
                        results.append(
                            DireccionOrigen(
                                id_licencia=row.id_val,
                                emp_direccion=row.dir_val,
                            )
                        )
        except Exception as e:
            logger.error(
                "Error al extraer lote de %s.%s (offset=%d, limit=%d, filter=%s, after_id=%s): %s",
                self.schema,
                self.table,
                offset,
                limit,
                filter_mode,
                after_id,
                e,
            )

        return results

    def fetch_next_free_record(
        self,
        session,
        filter_mode: str = "pending",
    ) -> Optional[DireccionOrigen]:
        """Obtiene y bloquea a nivel de fila el siguiente registro libre para una instancia concurrente."""
        cond_pending, cond_valid, cond_observed = self._build_status_conditions()
        base_condition = cond_pending if filter_mode == "pending" else (cond_observed if filter_mode == "observed" else "1=1")

        is_postgresql = False
        try:
            if self.db._engine and hasattr(self.db._engine, "dialect"):
                is_postgresql = "postgresql" in str(self.db._engine.dialect.name).lower()
        except Exception:
            is_postgresql = False

        lock_clause = "FOR UPDATE SKIP LOCKED" if is_postgresql else ""

        if self.source_mode == "central_tb_direccion":
            origin_cond, origin_params = self._get_central_origin_condition()
            conditions = [base_condition]
            params = dict(origin_params)
            if origin_cond:
                conditions.append(origin_cond)
            where_sql = f"WHERE {' AND '.join(conditions)}"
            query = text(f"""
                SELECT 
                    "dire_id" AS id_val,
                    "dire_valor_origen" AS dir_val,
                    "dire_tabla_id",
                    "dire_esquema",
                    "dire_tabla",
                    "dire_es_procesado"
                FROM {self._tb_direccion_ref}
                {where_sql}
                ORDER BY "dire_id" ASC
                LIMIT 1
                {lock_clause};
            """)
        else:
            query = text(f"""
                SELECT "{self.id_col}" AS id_val, "{self.dir_col}" AS dir_val
                FROM "{self.schema}"."{self.table}"
                WHERE {base_condition}
                ORDER BY "{self.id_col}" ASC
                LIMIT 1
                {lock_clause};
            """)
            params = {}

        try:
            row = session.execute(query, params).fetchone()
            if row:
                if self.source_mode == "central_tb_direccion":
                    return DireccionOrigen(
                        id_licencia=row.dire_tabla_id or row.id_val,
                        emp_direccion=row.dir_val,
                        dire_id=row.id_val,
                        dire_esquema=row.dire_esquema,
                        dire_tabla=row.dire_tabla,
                        dire_tabla_id=row.dire_tabla_id,
                        dire_valor_origen=row.dir_val,
                        es_procesado=bool(row.dire_es_procesado) if row.dire_es_procesado is not None else False,
                    )
                else:
                    return DireccionOrigen(
                        id_licencia=row.id_val,
                        emp_direccion=row.dir_val,
                    )
        except Exception as e:
            logger.error("Error al obtener registro libre con row-locking: %s", e)
        return None

