"""Cargador de datos hacia PostgreSQL para el método In-Place conservando IDs originales."""

import logging
from typing import List, Optional

from src.loaders.base_loader import BaseLoader
from src.models.direccion_destino import DireccionDestino
from src.services.db_service import DatabaseService
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.db_loader")

try:
    from sqlalchemy import text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False


class DatabaseLoader(BaseLoader):
    """Carga y actualiza registros normalizados in-place en la tabla existente conservando IDs."""

    def __init__(
        self,
        db_service: Optional[DatabaseService] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        mode: str = "in_place",
    ):
        self.db = db_service or DatabaseService()
        self.settings = get_settings().db
        self.mode = "in_place"
        self.schema = schema or self.settings.schema
        self.table = table or self.settings.table

        # Mapeo de nombres dinámicos de columnas normalizadas
        self.col_id = self.settings.id_col
        self.col_id_via = self.settings.col_id_via
        self.col_tipo_via = self.settings.col_tipo_via
        self.col_nom_via = self.settings.col_nom_via
        self.col_num_via = self.settings.col_num_via
        self.col_id_zona = self.settings.col_id_zona
        self.col_tipo_zona = self.settings.col_tipo_zona
        self.col_nom_zona = self.settings.col_nom_zona
        self.col_mz = self.settings.col_manzana
        self.col_lt = self.settings.col_lote
        self.col_slt = self.settings.col_slote
        self.col_referencia = self.settings.col_referencia

    def load_batch(self, records: List[DireccionDestino]) -> int:
        """Actualiza in-place las columnas normalizadas en la tabla existente conservando IDs."""
        if not records:
            return 0

        if not SQLALCHEMY_AVAILABLE or not self.db._engine:
            logger.warning("Base de datos no disponible. Omitiendo persistencia.")
            return 0

        return self._load_in_place(records)

    def _load_in_place(self, records: List[DireccionDestino]) -> int:
        """Actualiza in-place las columnas normalizadas en la tabla existente conservando IDs."""
        query = text(f"""
            UPDATE "{self.schema}"."{self.table}" SET
                "{self.col_id_via}"      = :id_via,
                "{self.col_tipo_via}"    = :tipo_via,
                "{self.col_nom_via}"     = :nom_via,
                "{self.col_num_via}"     = :num_via,
                "{self.col_id_zona}"     = :id_zona,
                "{self.col_tipo_zona}"   = :tipo_zona,
                "{self.col_nom_zona}"    = :nom_zona,
                "{self.col_mz}"          = :manzana,
                "{self.col_lt}"          = :lote,
                "{self.col_slt}"         = :slote,
                "{self.col_referencia}"  = :referencia
            WHERE "{self.col_id}" = :id_licencia;
        """)

        payload = [
            {
                "id_licencia": rec.id_licencia,
                "id_via": rec.id_via,
                "tipo_via": rec.tipo_via,
                "nom_via": rec.nom_via,
                "num_via": rec.num_via,
                "id_zona": rec.id_zona,
                "tipo_zona": rec.tipo_zona,
                "nom_zona": rec.nom_zona,
                "manzana": rec.manzana,
                "lote": rec.lote,
                "slote": rec.slote,
                "referencia": rec.referencia,
            }
            for rec in records
        ]
        try:
            with self.db.get_session() as session:
                session.execute(query, payload)
            logger.debug(
                "Lote de %d registros actualizado in-place en %s.%s",
                len(records),
                self.schema,
                self.table,
            )
            return len(records)
        except Exception as e:
            logger.error(
                "Error en actualización in-place en %s.%s: %s", self.schema, self.table, e
            )
            return 0
