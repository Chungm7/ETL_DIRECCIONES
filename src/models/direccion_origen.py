"""Modelo de datos para los registros de origen de sistemas institucionales (tb_xxx / Legacy)."""

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class DireccionOrigen(BaseModel):
    """Representa un registro de la tabla origen (tb_xxx, direcciones_actual, etc.)."""
    id_licencia: int = Field(
        description="Identificador único del registro en la tabla de origen (xxxx_id / id_licencia)"
    )
    emp_direccion: Optional[str] = Field(
        default=None,
        description="Texto no estructurado de la dirección histórica registrada (xxxx_direccion_original)"
    )
    dire_id: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia tb_direccion si ya fue procesada"
    )
    es_procesado: bool = Field(
        default=False,
        description="Estado de procesamiento previo (xxxx_es_procesado)"
    )
    observacion_ia: Optional[str] = Field(
        default=None,
        description="Observación previa registrada (xxxx_observacion_ia)"
    )
    valor_1: Optional[int] = Field(default=None, description="Parámetro referencial de negocio 1 (xxxx_valor_1)")
    valor_2: Optional[int] = Field(default=None, description="Parámetro referencial de negocio 2 (xxxx_valor_2)")
    valor_3: Optional[int] = Field(default=None, description="Parámetro referencial de negocio 3 (xxxx_valor_3)")

    @model_validator(mode="before")
    @classmethod
    def map_generic_system_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Mapear xxxx_id a id_licencia si aplica
        if "id_licencia" not in data:
            for k in ("xxxx_id", "id", "id_direccion", "codigo"):
                if k in data and data[k] is not None:
                    data["id_licencia"] = int(data[k])
                    break

        # Mapear xxxx_direccion_original a emp_direccion si aplica
        if "emp_direccion" not in data or data["emp_direccion"] is None:
            for k in ("xxxx_direccion_original", "direccion", "dir", "raw_text", "texto_direccion"):
                if k in data and data[k] is not None:
                    data["emp_direccion"] = str(data[k])
                    break

        if "es_procesado" not in data:
            if "xxxx_es_procesado" in data:
                data["es_procesado"] = bool(data["xxxx_es_procesado"])

        if "observacion_ia" not in data:
            if "xxxx_observacion_ia" in data:
                data["observacion_ia"] = data["xxxx_observacion_ia"]

        return data

    @property
    def xxxx_id(self) -> int:
        return self.id_licencia

    @property
    def xxxx_direccion_original(self) -> Optional[str]:
        return self.emp_direccion

    def is_empty(self) -> bool:
        """Indica si la dirección de texto es nula o vacía."""
        return not self.emp_direccion or not self.emp_direccion.strip()
