"""Esquemas de validación y salida estructurada para el modelo de lenguaje (Ollama)."""

from typing import Optional
from pydantic import BaseModel, Field


class OllamaAddressExtraction(BaseModel):
    """Estructura JSON esperada generada por Ollama al descomponer una dirección."""

    tipo_via_detectado: Optional[str] = Field(
        default=None,
        description="Tipo de vía detectado (ej. CALLE, AVENIDA, JIRON, PASAJE, CA, AV, JR)",
    )
    nom_via: Optional[str] = Field(
        default=None,
        description="Nombre de la vía sin prefijos de tipo ni número (ej. MOISES R. VALIENTE, BALTA)",
    )
    num_via: Optional[str] = Field(
        default=None,
        description="Número exterior, piso o indicación (ej. 349, S/N, 1673 - DPTO 2)",
    )
    tipo_zona_detectada: Optional[str] = Field(
        default=None,
        description="Tipo de habilitación o zona detectada (ej. URB, P.J., A.H., CONJ.RES.)",
    )
    nom_zona: Optional[str] = Field(
        default=None,
        description="Nombre de la urbanización, pueblo joven o sector (ej. LOS PRECURSORES)",
    )
    manzana: Optional[str] = Field(
        default=None,
        description="Manzana identificada (ej. A, 14, MZ D)",
    )
    lote: Optional[str] = Field(
        default=None,
        description="Lote identificado (ej. 12, LT 5, 43)",
    )
    slote: Optional[str] = Field(
        default=None,
        description="Sublote si se especifica",
    )
    referencia: Optional[str] = Field(
        default=None,
        description="Punto de referencia, hito urbano o indicación de ubicación (ej. CERCA AL SENATI, FRENTE AL PARQUE)",
    )
    confianza: Optional[float] = Field(

        default=1.0,
        description="Puntuación de certeza de la extracción semántica entre 0.0 y 1.0",
    )
    observaciones: Optional[str] = Field(
        default=None,
        description="Notas o anomalías encontradas durante la interpretación del texto",
    )


class OllamaBatchExtractionResponse(BaseModel):
    """Estructura de respuesta para procesamiento por lotes con Ollama."""
    id_licencia: int
    resultado: OllamaAddressExtraction
