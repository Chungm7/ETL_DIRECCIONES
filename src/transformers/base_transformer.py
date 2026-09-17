"""Clase base abstracta para los transformadores de datos."""

from abc import ABC, abstractmethod
from typing import List

from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino


class BaseTransformer(ABC):
    """Interfaz estándar para los componentes de transformación del ETL."""

    @abstractmethod
    def transform_record(self, record: DireccionOrigen) -> DireccionDestino:
        """Transforma un registro individual de origen a la estructura normalizada.

        Args:
            record: Registro original (id_licencia, emp_direccion).

        Returns:
            DireccionDestino normalizada para la base de datos de destino.
        """
        pass

    def transform_batch(self, records: List[DireccionOrigen]) -> List[DireccionDestino]:
        """Aplica la transformación a una lista completa de registros."""
        return [self.transform_record(rec) for rec in records]
