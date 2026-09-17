"""Modelo de datos para los registros de origen (Legacy)."""

from typing import Optional
from pydantic import BaseModel, Field


class DireccionOrigen(BaseModel):
    """Representa un registro de la tabla origen `direcciones_actual`."""
    id_licencia: int = Field(
        description="Identificador único de la licencia municipal / empresa (PK)"
    )
    emp_direccion: Optional[str] = Field(
        default=None,
        description="Texto no estructurado de la dirección histórica registrada",
    )

    def is_empty(self) -> bool:
        """Indica si la dirección de texto es nula o vacía."""
        return not self.emp_direccion or not self.emp_direccion.strip()
