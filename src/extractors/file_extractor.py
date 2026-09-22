"""Extractor alternativo para datos fuentes en archivos locales (.xls, .xlsx, .csv)."""

import logging
from pathlib import Path
from typing import List, Optional

from src.extractors.base_extractor import BaseExtractor
from src.models.direccion_origen import DireccionOrigen
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.file_extractor")

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


class FileExtractor(BaseExtractor):
    """Extrae registros desde archivos de hojas de cálculo o CSV (ej. docs/data/Direcciones_.xls)."""

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = Path(file_path or get_settings().etl.path_data_legacy_xls)
        self._cached_df: Optional[pd.DataFrame] = None

    def _load_dataframe(self) -> None:
        """Carga el archivo en memoria usando pandas."""
        if not PANDAS_AVAILABLE:
            raise RuntimeError("Pandas no está instalado para procesar archivos locales.")

        if not self.file_path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de datos en: {self.file_path}")

        logger.info("Cargando dataset desde: %s", self.file_path)
        if self.file_path.suffix.lower() in [".xls", ".xlsx"]:
            self._cached_df = pd.read_excel(self.file_path)
        else:
            self._cached_df = pd.read_csv(self.file_path)

    def get_total_records(self) -> int:
        """Obtiene la cantidad total de filas del archivo."""
        if self._cached_df is None:
            try:
                self._load_dataframe()
            except Exception as e:
                logger.error("Error al cargar archivo para conteo: %s", e)
                return 0
        return len(self._cached_df) if self._cached_df is not None else 0

    def extract_batch(
        self,
        offset: int = 0,
        limit: int = 100,
        filter_mode: str = "pending",
        after_id: Optional[int] = None,
    ) -> List[DireccionOrigen]:
        """Extrae un corte de registros del DataFrame."""
        if self._cached_df is None:
            self._load_dataframe()

        if self._cached_df is None:
            return []

        chunk = self._cached_df.iloc[offset : offset + limit]
        results: List[DireccionOrigen] = []

        for _, row in chunk.iterrows():
            # Asumimos nombres de columna comunes en la data histórica
            id_licencia = int(row.get("id_licencia") or row.get("ID_LICENCIA") or row.iloc[0])
            emp_direccion = str(row.get("emp_direccion") or row.get("EMP_DIRECCION") or row.iloc[1])
            results.append(
                DireccionOrigen(
                    id_licencia=id_licencia,
                    emp_direccion=None if pd.isna(emp_direccion) else emp_direccion.strip(),
                )
            )

        return results
