"""Módulo de modelos de datos para el proyecto ETL."""

from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino
from src.models.catalogos import TipoVia, TipoZona
from src.models.llm_schemas import OllamaAddressExtraction, OllamaBatchExtractionResponse

__all__ = [
    "DireccionOrigen",
    "DireccionDestino",
    "TipoVia",
    "TipoZona",
    "OllamaAddressExtraction",
    "OllamaBatchExtractionResponse",
]
