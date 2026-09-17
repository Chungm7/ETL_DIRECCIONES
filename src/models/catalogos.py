"""Modelos de datos para las tablas maestras y catálogos de Chiclayo."""

from typing import Optional
from pydantic import BaseModel, Field


class TipoVia(BaseModel):
    """Representa un tipo de vía de la tabla maestra `tipos_via`."""
    id_tipo_via: int = Field(description="Identificador único del tipo de vía")
    nombre_tipo_via: str = Field(description="Nombre completo (CALLE, AVENIDA, JIRÓN, etc.)")
    abreviatura: Optional[str] = Field(default=None, description="Abreviatura oficial (CA., AV., etc.)")


class TipoZona(BaseModel):
    """Representa un tipo de zona de la tabla maestra `tipos_zona`."""
    id_tipo_zona: int = Field(description="Identificador único del tipo de zona")
    nombre_tipo_zona: str = Field(description="Nombre completo (URBANIZACIÓN, PUEBLO JOVEN, etc.)")
    abreviatura: Optional[str] = Field(default=None, description="Abreviatura oficial (URB., P.J., etc.)")
