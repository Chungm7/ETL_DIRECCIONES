"""Configuración de logging estructurado para el proceso ETL."""

import logging
import sys


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configura el logger principal de la aplicación con formato legible."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger("etl_mpch")
    logger.setLevel(level)

    # Evitar duplicación de handlers si se llama varias veces
    if not logger.handlers:
        logger.addHandler(handler)

    return logger
