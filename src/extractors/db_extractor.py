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

    def extract_batch(self, offset: int, limit: int) -> List[DireccionOrigen]:
        """Extrae un lote ordenado seleccionando únicamente las columnas emisoras configuradas.

        Cualquier otra columna que tenga la tabla origen se ignora por completo.
        """
        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            return []

        # Consulta parametrizada con nombres dinámicos entre comillas dobles
        query = text(f"""
            SELECT "{self.id_col}" AS id_val, "{self.dir_col}" AS dir_val
            FROM "{self.schema}"."{self.table}"
            ORDER BY "{self.id_col}" ASC
            LIMIT :limit OFFSET :offset;
        """)

        results: List[DireccionOrigen] = []
        try:
            with self.db.get_session() as session:
                rows = session.execute(query, {"limit": limit, "offset": offset}).fetchall()
                for row in rows:
                    results.append(
                        DireccionOrigen(
                            id_licencia=row.id_val,
                            emp_direccion=row.dir_val,
                        )
                    )
        except Exception as e:
            logger.error(
                "Error al extraer lote de %s.%s (offset=%d, limit=%d): %s",
                self.schema,
                self.table,
                offset,
                limit,
                e,
            )

        return results
