"""Esquemas de validación y salida estructurada para el modelo de lenguaje (Ollama)."""

from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


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

    @model_validator(mode="before")
    @classmethod
    def normalize_input_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        norm = {}

        # 1. tipo_via_detectado
        for k in ("tipo_via_detectado", "tipo via detectado", "tipo_via", "tipo via", "tipovia", "tipo de via"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["tipo_via_detectado"] = v
                    break

        # 2. nom_via
        for k in ("nom_via", "nom via", "nombre via", "nombre_via", "nombre de via", "via", "calle"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["nom_via"] = v
                    break

        # 3. num_via
        for k in ("num_via", "num via", "número via", "numero via", "número_via", "numero_via", "numero", "número", "num", "nro"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["num_via"] = v
                    break

        # 4. tipo_zona_detectada
        for k in ("tipo_zona_detectada", "tipo zona detectada", "tipo_zona", "tipo zona", "tipozona", "tipo de zona"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["tipo_zona_detectada"] = v
                    break

        # 5. nom_zona
        for k in ("nom_zona", "nom zona", "nombre zona", "nombre_zona", "nombre de zona", "zona", "urbanizacion"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["nom_zona"] = v
                    break

        # 6. manzana
        for k in ("manzana", "Mz", "MZ", "mz", "Mza", "mza"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["manzana"] = v
                    break

        # 7. lote
        for k in ("lote", "LT.", "LT", "Lt.", "lt", "Lote"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["lote"] = v
                    break

        # 8. slote
        for k in ("slote", "Sub LT.", "sub lt.", "sub_lote", "sublote", "Sub LT"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["slote"] = v
                    break

        # 9. Extra elements inmobiliarios (Dep., INT., STAND., TDA., Piso, Sección)
        extra_refs = []
        for k, pfx in [
            ("Dep.", "DEP"), ("dep", "DEP"),
            ("INT.", "INT"), ("int", "INT"),
            ("STAND.", "STAND"), ("stand", "STAND"),
            ("TDA.", "TIENDA"), ("tda", "TIENDA"),
            ("Piso", "PISO"), ("piso", "PISO"),
            ("Sección", "SECCION"), ("seccion", "SECCION")
        ]:
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    extra_refs.append(f"{pfx} {v}")

        # 10. referencia
        ref_val = None
        for k in ("referencia", "Referencia", "ref"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    ref_val = v
                    break

        if extra_refs:
            extras_combined = " - ".join(extra_refs)
            norm["referencia"] = f"{ref_val} - {extras_combined}".strip(" -") if ref_val else extras_combined
        elif ref_val:
            norm["referencia"] = ref_val

        # 11. observaciones
        for k in ("observaciones", "observacion", "observación", "comentario", "motivo"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["observaciones"] = v
                    break

        # 12. confianza
        if "confianza" in data and data["confianza"] is not None:
            try:
                norm["confianza"] = float(data["confianza"])
            except (ValueError, TypeError):
                norm["confianza"] = 1.0

        return norm


class OllamaBatchExtractionResponse(BaseModel):
    """Estructura de respuesta para procesamiento por lotes con Ollama."""
    id_licencia: int
    resultado: OllamaAddressExtraction


class OllamaCandidateDisambiguation(BaseModel):
    """Estructura de respuesta de Ollama al evaluar candidatos y desambiguar variantes viales o de zonas."""
    id_seleccionado: Optional[int] = Field(
        default=None,
        description="ID del candidato oficial de Chiclayo seleccionado, o null si ninguno corresponde",
    )
    nombre_oficial: Optional[str] = Field(
        default=None,
        description="Nombre oficial exacto de la entidad seleccionada en el catálogo",
    )
    motivo: Optional[str] = Field(
        default=None,
        description="Explicación breve del razonamiento semántico para la selección o descarte",
    )
