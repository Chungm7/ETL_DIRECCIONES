"""Módulo de extractores de datos para el pipeline ETL."""

from src.extractors.base_extractor import BaseExtractor
from src.extractors.db_extractor import DatabaseExtractor

__all__ = ["BaseExtractor", "DatabaseExtractor"]
