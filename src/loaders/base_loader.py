"""Clase base abstracta para los cargadores (Loaders) del ETL."""

from abc import ABC, abstractmethod
from typing import List

from src.models.direccion_destino import DireccionDestino


class BaseLoader(ABC):
    """Interfaz estándar para la persistencia de datos transformados."""

    @abstractmethod
    def load_batch(self, records: List[DireccionDestino]) -> int:
        """Inserta o actualiza un lote de registros normalizados en el destino.

        Args:
            records: Lista de objetos DireccionDestino listos para insertar.

        Returns:
            Cantidad de registros cargados con éxito.
        """
        pass
