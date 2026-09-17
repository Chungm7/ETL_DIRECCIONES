"""Modelo de datos para el destino normalizado en PostgreSQL."""

from typing import Optional
from pydantic import BaseModel, Field


class DireccionDestino(BaseModel):
    """Representa un registro estructurado para la tabla `direcciones_generales`."""
    id_licencia: int = Field(
        description="Identificador único de la licencia municipal (PK)"
    )
    id_via: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `vias.id_via` (Vía física de Chiclayo)",
    )
    tipo_via: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `tipos_via.id_tipo_via`",
    )
    nom_via: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Nombre oficial de la vía (ej. MOISES R. VALIENTE, BALTA)",
    )
    num_via: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Numeración municipal de la vía o indicación S/N / Dpto",
    )
    id_zona: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `zonas.id_zona` (Habilitación urbana de Chiclayo)",
    )
    tipo_zona: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `tipos_zona.id_tipo_zona`",
    )
    nom_zona: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Nombre de la urbanización, sector o asentamiento",
    )
    manzana: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Identificador de Manzana (Mz)",
    )
    lote: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Identificador de Lote (Lt)",
    )
    slote: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Sublote o división interna si aplica",
    )
    referencia: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Punto de referencia, hito urbano o indicación de guía (ej. CERCA AL SENATI)",
    )
    metodo_normalizacion: str = Field(
        default="IA (patroclo)",
        description="Indica el motor con el que se normalizó: IA, Heurístico o Híbrido",
    )

