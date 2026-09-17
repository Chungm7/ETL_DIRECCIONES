"""Clase base abstracta para los extractores del proceso ETL."""

from abc import ABC, abstractmethod
from typing import Generator, List

from src.models.direccion_origen import DireccionOrigen


class BaseExtractor(ABC):
    """Interfaz estándar para fuentes de extracción de direcciones no estructuradas."""

    @abstractmethod
    def get_total_records(self) -> int:
        """Retorna el número total de registros disponibles en la fuente."""
        pass

    @abstractmethod
    def extract_batch(self, offset: int, limit: int, filter_mode: str = "pending") -> List[DireccionOrigen]:
        """Extrae un lote específico de registros de origen.

        Args:
            offset: Desplazamiento inicial (0-indexed).
            limit: Número máximo de registros a extraer.
            filter_mode: Modo de filtrado ('pending', 'observed', 'all').

        Returns:
            Lista de objetos DireccionOrigen.
        """
        pass

    def extract_all(self, batch_size: int = 100) -> Generator[List[DireccionOrigen], None, None]:
        """Generador que itera sobre la fuente extrayendo lotes sucesivos."""
        total = self.get_total_records()
        for offset in range(0, total, batch_size):
            yield self.extract_batch(offset=offset, limit=batch_size)
