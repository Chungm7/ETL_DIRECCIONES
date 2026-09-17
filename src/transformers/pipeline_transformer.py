"""Orquestador del proceso de transformación (limpieza léxica + IA Ollama + catálogos)."""

import logging
from typing import Optional

from src.transformers.base_transformer import BaseTransformer
from src.transformers.text_cleaner import TextCleaner
from src.transformers.ai_parser import AIAddressParser
from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.pipeline_transformer")


class PipelineTransformer(BaseTransformer):
    """Ejecuta el flujo completo de transformación para cada dirección."""

    def __init__(
        self,
        ai_parser: Optional[AIAddressParser] = None,
        use_ai: Optional[bool] = None,
    ):
        settings = get_settings()
        self.use_ai = use_ai if use_ai is not None else settings.etl.use_ai_parser
        self.ai_parser = ai_parser or AIAddressParser()

    def transform_record(self, record: DireccionOrigen) -> DireccionDestino:
        """Paso a paso de la transformación de un registro individual:
        1. Saneamiento previo del texto (TextCleaner).
        2. Extracción semántica con Ollama (si está habilitado).
        3. Generación del objeto normalizado DireccionDestino.
        """
        if record.is_empty():
            return DireccionDestino(id_licencia=record.id_licencia)

        # 1. Pre-limpieza
        cleaned_address = TextCleaner.sanitize(record.emp_direccion)
        cleaned_record = DireccionOrigen(
            id_licencia=record.id_licencia,
            emp_direccion=cleaned_address,
        )

        # 2. Parseo asistido por IA (Ollama)
        if self.use_ai:
            return self.ai_parser.parse(cleaned_record)

        # 3. Modo sin IA (Estructura base lista para conectar reglas regex en desarrollo futuro)
        logger.debug(
            "Modo sin IA activo. Registrando dirección sin desglose para licencia %d",
            record.id_licencia,
        )
        return DireccionDestino(
            id_licencia=record.id_licencia,
            nom_via=cleaned_address,
            metodo_normalizacion="Directo (IA deshabilitada)",
        )
