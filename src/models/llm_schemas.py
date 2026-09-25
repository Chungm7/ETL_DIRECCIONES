"""Esquemas Pydantic para la respuesta estructurada de extracción e inferencia con Ollama (Versión 2.0)."""

import re
from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator


class ExtractedVia(BaseModel):
    """Representa una arteria vial individual identificada en la dirección."""
    nombre: str = Field(description="Nombre oficial de la vía sin tipo ni número (ej. BALTA, SAN JOSE)")
    tipo_via: Optional[str] = Field(default=None, description="Tipo de arteria (CALLE, AVENIDA, JIRON, etc.)")
    numero: Optional[str] = Field(default=None, description="Numeración municipal limpia en esta arteria (ej. 102, S/N)")
    orden: int = Field(default=1, description="1 para vía principal, 2 para vía de cruce / intersección / esquina")


class ExtractedComponente(BaseModel):
    """Representa un atributo catastral individual (manzana, lote, sublote, piso, etc.)."""
    nombre: str = Field(description="Tipo de componente: MANZANA, LOTE, SUBLOTE, PISO, PREDIO, VALLE, SECTOR, etc.")
    valor: str = Field(description="Valor del componente (ej. A, 14, 2)")
    es_urbano: bool = Field(default=True, description="True si es urbano, False si es rural")


class ExtractedModulo(BaseModel):
    """Representa una dependencia o módulo inmobiliario interior (interior, dpto, puerta, stand, etc.)."""
    tipo_modulo: str = Field(description="INTERIOR, DEPARTAMENTO, PUERTA, STAND, TIENDA, OFICINA, BLOCK, etc.")
    valor: str = Field(description="Detalle del módulo (ej. 102, B, 15, STAND 4)")


class OllamaAddressExtraction(BaseModel):
    """Estructura JSON generada por Ollama para la arquitectura normalizada V2 de Chiclayo."""

    vias: List[ExtractedVia] = Field(
        default_factory=list,
        description="Lista de vías asociadas a la dirección (soporta esquinas / intersecciones)",
    )
    tipo_via_detectado: Optional[str] = Field(
        default=None,
        description="Tipo de la vía principal (retrocompatibilidad)",
    )
    nom_via: Optional[str] = Field(
        default=None,
        description="Nombre de la vía principal (retrocompatibilidad)",
    )
    num_via: Optional[str] = Field(
        default=None,
        description="Número de la vía principal (retrocompatibilidad)",
    )

    tipo_zona_detectada: Optional[str] = Field(
        default=None,
        description="Tipo de habilitación según catálogo oficial de 28 tipos (URBANIZACION, PUEBLO JOVEN, etc.)",
    )
    nom_zona: Optional[str] = Field(
        default=None,
        description="Nombre oficial de la zona o habilitación urbana (ej. SANTA VICTORIA, 9 DE OCTUBRE)",
    )

    componentes: List[ExtractedComponente] = Field(
        default_factory=list,
        description="Lista de atributos catastrales (manzana, lote, sublote, piso, predio, etc.)",
    )
    modulos: List[ExtractedModulo] = Field(
        default_factory=list,
        description="Lista de módulos y dependencias interiores (interior, dpto, puerta, stand, block, etc.)",
    )

    # Campos planos para retrocompatibilidad
    manzana: Optional[str] = Field(default=None, description="Manzana limpia (retrocompatibilidad)")
    lote: Optional[str] = Field(default=None, description="Lote limpio (retrocompatibilidad)")
    slote: Optional[str] = Field(default=None, description="Sublote (retrocompatibilidad)")

    referencia: Optional[str] = Field(
        default=None,
        description="Hito espacial o comercial exclusivo de orientación (ej. CERCA AL SENATI, FRENTE AL PARQUE)",
    )
    confianza: Optional[float] = Field(
        default=1.0,
        description="Puntuación de certeza de la extracción semántica entre 0.0 y 1.0",
    )
    observaciones: Optional[str] = Field(
        default=None,
        description="Notas o dictamen de inconsistencias encontradas durante la interpretación",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_input_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        norm: dict = {}

        # 1. Extracción de Vías (Estructura V2 o conversión desde campos planos V1)
        raw_vias = data.get("vias")
        parsed_vias: List[dict] = []

        if isinstance(raw_vias, list) and len(raw_vias) > 0:
            for i, v in enumerate(raw_vias):
                if isinstance(v, BaseModel):
                    v = v.model_dump()
                if isinstance(v, dict):
                    v_nom = v.get("nombre") or v.get("nom_via") or v.get("via") or ""
                    v_tipo = v.get("tipo_via") or v.get("tipo")
                    v_num = v.get("numero") or v.get("num_via") or v.get("num")
                    v_ord = v.get("orden") or (i + 1)
                    if v_nom:
                        parsed_vias.append({
                            "nombre": str(v_nom).strip(),
                            "tipo_via": str(v_tipo).strip().upper() if v_tipo else None,
                            "numero": str(v_num).strip() if v_num else None,
                            "orden": int(v_ord),
                        })
                elif isinstance(v, str) and v.strip():
                    parsed_vias.append({
                        "nombre": v.strip(),
                        "tipo_via": None,
                        "numero": None,
                        "orden": i + 1,
                    })

        # Respaldo para campos planos de vía si vias vino vacío
        if not parsed_vias:
            p_nom_via = None
            for k in ("nom_via", "nom via", "nombre via", "nombre_via", "nombre de via", "via", "calle"):
                if k in data and data[k] is not None:
                    val = str(data[k]).strip()
                    if val:
                        p_nom_via = val
                        break

            p_tipo_via = None
            for k in ("tipo_via_detectado", "tipo via detectado", "tipo_via", "tipo via", "tipovia", "tipo de via"):
                if k in data and data[k] is not None:
                    val = str(data[k]).strip()
                    if val:
                        p_tipo_via = val.upper()
                        break

            p_num_via = None
            for k in ("num_via", "num via", "número via", "numero via", "número_via", "numero_via", "numero", "número", "num", "nro"):
                if k in data and data[k] is not None:
                    val = str(data[k]).strip()
                    if val:
                        p_num_via = val
                        break

            if p_nom_via:
                parsed_vias.append({
                    "nombre": p_nom_via,
                    "tipo_via": p_tipo_via,
                    "numero": p_num_via,
                    "orden": 1,
                })

        norm["vias"] = parsed_vias
        if parsed_vias:
            norm["nom_via"] = parsed_vias[0].get("nombre")
            norm["tipo_via_detectado"] = parsed_vias[0].get("tipo_via")
            norm["num_via"] = parsed_vias[0].get("numero")
        else:
            norm["nom_via"] = None
            norm["tipo_via_detectado"] = None
            norm["num_via"] = None

        # 2. Extracción de Zona
        for k in ("tipo_zona_detectada", "tipo zona detectada", "tipo_zona", "tipo zona", "tipozona", "tipo de zona"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip().upper()
                if v:
                    # Regla HU: Mapeo hacia URBANIZACIÓN en el catálogo oficial de 28 tipos
                    if v in ("H.U.", "HU", "HABILITACION URBANA", "HABILITACIÓN URBANA"):
                        norm["tipo_zona_detectada"] = "URBANIZACION"
                    else:
                        norm["tipo_zona_detectada"] = v
                    break

        for k in ("nom_zona", "nom zona", "nombre zona", "nombre_zona", "nombre de zona", "zona_nombre", "zona", "urbanizacion"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["nom_zona"] = v
                    break

        # 3. Extracción de Componentes (Mz, Lote, Sublote, Piso, etc.)
        parsed_comp: List[dict] = []
        raw_comp = data.get("componentes")
        if isinstance(raw_comp, list):
            for c in raw_comp:
                if isinstance(c, BaseModel):
                    c = c.model_dump()
                if isinstance(c, dict) and c.get("nombre") and c.get("valor"):
                    parsed_comp.append({
                        "nombre": str(c["nombre"]).strip().upper(),
                        "valor": str(c["valor"]).strip(),
                        "es_urbano": bool(c.get("es_urbano", True)),
                    })

        # Extraer campos planos de componentes
        mz_val = None
        for k in ("manzana", "Mz", "MZ", "mz", "Mza", "mza"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    mz_val = val
                    norm["manzana"] = val
                    if not any(c["nombre"] == "MANZANA" for c in parsed_comp):
                        parsed_comp.append({"nombre": "MANZANA", "valor": val, "es_urbano": True})
                    break

        lt_val = None
        for k in ("lote", "LT.", "LT", "Lt.", "lt", "Lote"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    lt_val = val
                    norm["lote"] = val
                    if not any(c["nombre"] == "LOTE" for c in parsed_comp):
                        parsed_comp.append({"nombre": "LOTE", "valor": val, "es_urbano": True})
                    break

        slt_val = None
        for k in ("slote", "Sub LT.", "sub lt.", "sub_lote", "sublote", "Sub LT"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    slt_val = val
                    norm["slote"] = val
                    if not any(c["nombre"] == "SUBLOTE" for c in parsed_comp):
                        parsed_comp.append({"nombre": "SUBLOTE", "valor": val, "es_urbano": True})
                    break

        norm["componentes"] = parsed_comp

        # 4. Extracción de Módulos (Interior, Dpto, Puerta, Stand, Tienda, Block, etc.)
        parsed_mod: List[dict] = []
        raw_mod = data.get("modulos")
        if isinstance(raw_mod, list):
            for m in raw_mod:
                if isinstance(m, BaseModel):
                    m = m.model_dump()
                if isinstance(m, dict) and m.get("tipo_modulo") and m.get("valor"):
                    parsed_mod.append({
                        "tipo_modulo": str(m["tipo_modulo"]).strip().upper(),
                        "valor": str(m["valor"]).strip(),
                    })

        # Detección y migración de módulos desde campos legados (slote o llaves específicas)
        legacy_module_keys = [
            ("Dep.", "DEPARTAMENTO"), ("dep", "DEPARTAMENTO"), ("dpto", "DEPARTAMENTO"), ("DPTO", "DEPARTAMENTO"),
            ("INT.", "INTERIOR"), ("int", "INTERIOR"), ("INT", "INTERIOR"),
            ("STAND.", "STAND"), ("stand", "STAND"), ("STAND", "STAND"),
            ("TDA.", "TIENDA"), ("tda", "TIENDA"), ("tienda", "TIENDA"),
            ("puerta", "PUERTA"), ("PUERTA", "PUERTA"),
            ("oficina", "OFICINA"), ("OFICINA", "OFICINA"), ("of", "OFICINA"),
            ("block", "BLOCK"), ("BLOCK", "BLOCK"),
            ("puesto", "PUESTO"), ("PUESTO", "PUESTO"),
        ]
        for k, timo_name in legacy_module_keys:
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val and not any(m["tipo_modulo"] == timo_name and m["valor"] == val for m in parsed_mod):
                    parsed_mod.append({"tipo_modulo": timo_name, "valor": val})

        # Si slote contiene módulo (ej. "INT-1", "DPTO 201", "STAND 4", "BLOCK B")
        if slt_val:
            m_mod_slt = re.search(
                r"\b(INT(?:ERIOR)?|DPTO|DEP|DEPARTAMENTO|PUERTA|STAND|TIENDA|TDA|BLOCK|OFICINA|OF)\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)",
                slt_val,
                re.IGNORECASE,
            )
            if m_mod_slt:
                tipo_mod_detected = m_mod_slt.group(1).upper()
                canon_mod = "INTERIOR" if "INT" in tipo_mod_detected else (
                    "DEPARTAMENTO" if "DEP" in tipo_mod_detected else (
                        "TIENDA" if "T" in tipo_mod_detected and "STAND" not in tipo_mod_detected else (
                            "OFICINA" if "OF" in tipo_mod_detected else tipo_mod_detected
                        )
                    )
                )
                val_mod = m_mod_slt.group(2).strip()
                if not any(m["tipo_modulo"] == canon_mod for m in parsed_mod):
                    parsed_mod.append({"tipo_modulo": canon_mod, "valor": val_mod})

        norm["modulos"] = parsed_mod

        # 5. Referencia Espacial de Orientación (Estricta para hitos urbanos)
        ref_val = None
        for k in ("referencia", "Referencia", "ref"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    ref_val = v
                    break

        if ref_val:
            # Depurar módulos o dependencias si vinieron en referencia
            m_piso = re.search(r"\b((?:\d+(?:DO|ER|TO|VO|MO)?\.?\s*)?PISO)\b", ref_val, re.IGNORECASE)
            if m_piso:
                piso_str = m_piso.group(1).strip().upper()
                if not any(c["nombre"] == "PISO" for c in parsed_comp):
                    parsed_comp.append({"nombre": "PISO", "valor": piso_str, "es_urbano": True})
                ref_val = re.sub(re.escape(m_piso.group(0)), "", ref_val, flags=re.IGNORECASE).strip(" -/,.")

            norm["referencia"] = ref_val.strip(" -/,.") if ref_val else None
        else:
            norm["referencia"] = None

        # 6. Observaciones y Confianza
        for k in ("observaciones", "observacion", "observación", "comentario", "motivo"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    norm["observaciones"] = v
                    break

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
