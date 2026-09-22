import re
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class DireccionDestino(BaseModel):
    """Representa un registro consolidado para la tabla de direcciones normalizada."""

    @model_validator(mode="before")
    @classmethod
    def sanitize_field_lengths(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # 1. Tratamiento especial para slote (evitar que pisos, esquinas o textos largos rompan la validación)
        slote = data.get("slote")
        if slote and isinstance(slote, str):
            slote_clean = slote.strip()
            if len(slote_clean) > 20 or re.search(
                r"\b(?:PISO|ESQ|ESQUINA|FRENTE|ALTURA|CUADRA|BLOCK|EDIFICIO)\b",
                slote_clean,
                re.IGNORECASE,
            ):
                ref = data.get("referencia") or ""
                if slote_clean.upper() not in ref.upper():
                    data["referencia"] = f"{ref} - {slote_clean}".strip(" -") if ref else slote_clean
                data["slote"] = None
            elif len(slote_clean) > 20:
                data["slote"] = slote_clean[:20]
            else:
                data["slote"] = slote_clean

        # 2. Guardrail defensivo contra desbordamiento en columnas de BD y validación Pydantic
        limits = {
            "num_via": 50,
            "manzana": 20,
            "lote": 20,
            "slote": 20,
            "referencia": 255,
            "nom_via": 150,
            "nom_zona": 150,
        }
        for field, max_len in limits.items():
            val = data.get(field)
            if val and isinstance(val, str) and len(val) > max_len:
                data[field] = val[:max_len].strip()

        return data
    id_licencia: int = Field(
        description="Identificador único de la licencia municipal (PK)"
    )
    id_via: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `vias.id_via` (Vía física oficial de Chiclayo)",
    )
    num_via: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Numeración municipal de la vía o indicación S/N / Dpto",
    )
    id_zona: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `zonas.id_zona` (Habilitación urbana oficial de Chiclayo)",
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
    es_procesado: bool = Field(
        default=False,
        description="True si la dirección se validó y asoció formalmente a los catálogos maestros oficiales; False si fue observada",
    )
    observacion: Optional[str] = Field(
        default=None,
        description="Detalle o diagnóstico si la vía o zona no existen en las tablas maestras oficiales",
    )

    # Campos opcionales en memoria para auditoría/visualización
    tipo_via: Optional[int] = Field(
        default=None,
        description="ID del tipo de vía en memoria",
    )
    nom_via: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Nombre oficial en memoria de la vía",
    )
    tipo_zona: Optional[int] = Field(
        default=None,
        description="ID del tipo de zona en memoria",
    )
    nom_zona: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Nombre oficial en memoria de la zona",
    )
    metodo_normalizacion: str = Field(
        default="IA",
        description="Indica el motor con el que se normalizó: IA, Heurístico o Híbrido",
    )
