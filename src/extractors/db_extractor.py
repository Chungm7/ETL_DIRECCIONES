"""Extractor dinámico desde PostgreSQL con soporte de esquemas y columnas configurables."""

import logging
from typing import List, Optional

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
    """Extrae únicamente las dos columnas necesarias desde el esquema y tabla emisora configurados."""

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        id_col: Optional[str] = None,
        dir_col: Optional[str] = None,
    ):
        self.db = db_service or DatabaseService()
        settings = get_settings().db
        self.schema = schema or settings.schema
        self.table = table or settings.table
        self.id_col = id_col or settings.id_col
        self.dir_col = dir_col or settings.dir_col
        self.col_es_procesado = settings.col_es_procesado
        self.col_observacion: Optional[str] = None
        self.col_dire_id: Optional[str] = None
        self._columns_inspected = False

    def _inspect_columns(self) -> None:
        """Inspecciona dinámicamente las columnas de la tabla para alinear nombres y filtros."""
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

                for cand in [self.dir_col, "emp_direccion", "xxxx_direccion_original", "direccion", "dir", "raw_text"]:
                    if cand and cand.lower() in cols:
                        self.dir_col = cols[cand.lower()]
                        break

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
        """Retorna las cláusulas SQL para pendientes, válidos y observados."""
        self._inspect_columns()

        # Condición de pendientes:
        # 1. Si es_procesado es NULL -> pendiente
        # 2. Si es_procesado es FALSE pero ni dire_id ni observación están llenos -> pendiente (sin procesar aún)
        if self.col_observacion and self.col_dire_id:
            cond_pending = f'("{self.col_es_procesado}" IS NULL OR ("{self.col_es_procesado}" = FALSE AND "{self.col_dire_id}" IS NULL AND ("{self.col_observacion}" IS NULL OR TRIM("{self.col_observacion}") = \'\')))'
            cond_observed = f'("{self.col_es_procesado}" = FALSE AND "{self.col_observacion}" IS NOT NULL AND TRIM("{self.col_observacion}") != \'\')'
        elif self.col_observacion:
            cond_pending = f'("{self.col_es_procesado}" IS NULL OR ("{self.col_es_procesado}" = FALSE AND ("{self.col_observacion}" IS NULL OR TRIM("{self.col_observacion}") = \'\')))'
            cond_observed = f'("{self.col_es_procesado}" = FALSE AND "{self.col_observacion}" IS NOT NULL AND TRIM("{self.col_observacion}") != \'\')'
        else:
            cond_pending = f'"{self.col_es_procesado}" IS NULL'
            cond_observed = f'"{self.col_es_procesado}" = FALSE'

        cond_valid = f'"{self.col_es_procesado}" IS TRUE'
        return cond_pending, cond_valid, cond_observed

    def get_total_records(self) -> int:
        """Obtiene la cantidad total de registros en la tabla emisora."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            logger.warning("Base de datos no inicializada. Retornando 0 registros.")
            return 0

        query = text(f'SELECT COUNT(*) FROM "{self.schema}"."{self.table}";')
        try:
            with self.db.get_session() as session:
                count = session.execute(query).scalar()
                return int(count or 0)
        except Exception as e:
            logger.error(
                "Error al contar registros en %s.%s: %s", self.schema, self.table, e
            )
            return 0

    def get_status_counts(self) -> dict:
        """Obtiene el conteo clasificado de registros: total, pendientes, válidos y observados."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return {"total": 0, "pendientes": 0, "validos": 0, "observados": 0}

        cond_pending, cond_valid, cond_observed = self._build_status_conditions()

        query = text(f"""
            SELECT 
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE {cond_pending}) AS pendientes,
                COUNT(*) FILTER (WHERE {cond_valid}) AS validos,
                COUNT(*) FILTER (WHERE {cond_observed}) AS observados
            FROM "{self.schema}"."{self.table}";
        """)
        try:
            with self.db.get_session() as session:
                row = session.execute(query).fetchone()
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
    ) -> List[DireccionOrigen]:
        """Extrae un lote aplicando filtro de estado para reanudación automática."""
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return []

        cond_pending, cond_valid, cond_observed = self._build_status_conditions()

        conditions = []
        params: Dict[str, Any] = {"limit": limit}

        if filter_mode == "pending":
            conditions.append(cond_pending)
        elif filter_mode == "observed":
            conditions.append(cond_observed)
        elif filter_mode == "valid":
            conditions.append(cond_valid)

        if after_id is not None:
            conditions.append(f'"{self.id_col}" > :after_id')
            params["after_id"] = after_id
            offset_clause = ""
        else:
            params["offset"] = offset
            offset_clause = "OFFSET :offset"

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = text(f"""
            SELECT "{self.id_col}" AS id_val, "{self.dir_col}" AS dir_val
            FROM "{self.schema}"."{self.table}"
            {where_clause}
            ORDER BY "{self.id_col}" ASC
            LIMIT :limit {offset_clause};
        """)

        results: List[DireccionOrigen] = []
        try:
            with self.db.get_session() as session:
                rows = session.execute(query, params).fetchall()
                for row in rows:
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
