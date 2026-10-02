"""Esquemas Pydantic para la respuesta estructurada de extracción e inferencia con Ollama (Versión 2.0)."""

import re
import unicodedata
from typing import Any, List, Optional
from pydantic import BaseModel, Field, model_validator, field_validator


def _remove_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


SUBLOTE_PREFIX_REGEX = re.compile(
    r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT)\s*",
    re.IGNORECASE,
)
SUBLOTE_PLACEHOLDER_REGEX = re.compile(
    r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT|SIN\s+SUBLOTE|SIN\s+SUB\s*LOTE|NO|N/A|NA|NONE|NULL|-|\.)$",
    re.IGNORECASE,
)


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
    valor: Any = Field(description="Detalle del módulo (ej. 102, B, 15, STAND 4)")

    @field_validator("valor", mode="before")
    @classmethod
    def clean_valor(cls, v: Any) -> str:
        if isinstance(v, list):
            cleaned = [str(x).strip(" '\"[]") for x in v if str(x).strip(" '\"[]")]
            return ", ".join(cleaned)
        s = str(v).strip()
        s = re.sub(r"^[\[\(]+|[\]\)]+$", "", s).strip()
        s = s.replace("'", "").replace('"', '').strip()
        return s


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
    piso: Optional[str] = Field(default=None, description="Piso o nivel del predio (componente)")
    block: Optional[str] = Field(default=None, description="Block, bloque o torre del predio (componente)")

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
                p_nom_upper = p_nom_via.strip().upper()
                from src.catalogs.catalog_manager import CatalogManager
                if (p_nom_upper in CatalogManager.CITY_DISTRICT_STOPWORDS or _remove_accents(p_nom_upper) in CatalogManager.CITY_DISTRICT_STOPWORDS) and not p_tipo_via:
                    pass
                else:
                    parsed_vias.append({
                        "nombre": p_nom_via,
                        "tipo_via": p_tipo_via,
                        "numero": p_num_via,
                        "orden": 1,
                    })

        # Filtrar vías que sean únicamente nombres de distritos/ciudades sin tipo de vía formal
        from src.catalogs.catalog_manager import CatalogManager
        filtered_vias = []
        for v in parsed_vias:
            vn = str(v.get("nombre") or "").strip().upper()
            vn_clean = _remove_accents(vn)
            if (vn in CatalogManager.CITY_DISTRICT_STOPWORDS or vn_clean in CatalogManager.CITY_DISTRICT_STOPWORDS) and not v.get("tipo_via"):
                continue
            filtered_vias.append(v)
        parsed_vias = filtered_vias

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

        # 3. Extracción de Componentes (Mz, Lote, Sublote, Piso, Block, etc.)
        parsed_comp: List[dict] = []
        raw_comp = data.get("componentes")
        if isinstance(raw_comp, list):
            for c in raw_comp:
                if isinstance(c, BaseModel):
                    c = c.model_dump()
                if isinstance(c, dict) and c.get("nombre") and c.get("valor"):
                    c_nom = str(c["nombre"]).strip().upper()
                    c_val = str(c["valor"]).strip()
                    # Si vino como SUBLOTE pero contiene módulos o pisos, o es un placeholder ("slt"), no ingresarlo como SUBLOTE
                    if c_nom in ("SUBLOTE", "SUB LOTE", "SLOTE"):
                        clean_c_val = SUBLOTE_PREFIX_REGEX.sub("", c_val).strip(" -:,.")
                        if not clean_c_val or SUBLOTE_PLACEHOLDER_REGEX.match(clean_c_val) or SUBLOTE_PLACEHOLDER_REGEX.match(c_val):
                            continue
                        has_mod = bool(re.search(
                            r"\b(INT(?:ERIOR(?:ES)?)?|DPTO|DEP(?:ARTAMENTO)?|PUERTA|PTA|STAND|STD|TIENDA|TDA|OFICINA|OF|PUESTO|PTO|LOCAL|LOC)\b",
                            c_val,
                            re.IGNORECASE,
                        ))
                        if has_mod:
                            continue
                        if "PISO" in c_val.upper():
                            p_num = re.search(r"\d+", c_val)
                            piso_clean = p_num.group(0) if p_num else c_val
                            if not any(cp["nombre"] == "PISO" for cp in parsed_comp):
                                parsed_comp.append({"nombre": "PISO", "valor": piso_clean, "es_urbano": True})
                            continue
                        if re.search(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\b", c_val, re.IGNORECASE):
                            b_m = re.search(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\s*([A-Z0-9\-]+)\b", c_val, re.IGNORECASE)
                            b_clean = b_m.group(1).strip() if b_m else c_val
                            if not any(cp["nombre"] == "BLOCK" for cp in parsed_comp):
                                parsed_comp.append({"nombre": "BLOCK", "valor": b_clean, "es_urbano": True})
                            continue
                        c_val = clean_c_val

                    # Normalizar nombres de componentes a canónicos
                    if c_nom in ("BLOCK", "BLOQUE", "BLQ", "TORRE", "PABELLON", "PABELLÓN"):
                        c_nom = "BLOCK"
                    elif c_nom in ("PISO", "PISOS", "NIVEL"):
                        c_nom = "PISO"
                        p_num = re.search(r"\d+", c_val)
                        if p_num:
                            c_val = p_num.group(0)

                    parsed_comp.append({
                        "nombre": c_nom,
                        "valor": c_val,
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

        # Manejo de piso plano
        piso_val = None
        for k in ("piso", "Piso", "PISO", "nivel", "Nivel", "NIVEL"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    p_num = re.search(r"\d+", val)
                    clean_p = p_num.group(0) if p_num else val
                    norm["piso"] = clean_p
                    if not any(c["nombre"] == "PISO" for c in parsed_comp):
                        parsed_comp.append({"nombre": "PISO", "valor": clean_p, "es_urbano": True})
                    break

        # Manejo de block plano
        block_val = None
        for k in ("block", "Block", "BLOCK", "bloque", "Bloque", "BLOQUE", "torre", "Torre", "TORRE"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    clean_b = re.sub(r"^(?:BLOCK|BLOQUE|BLQ|TORRE)\s*", "", val, flags=re.IGNORECASE).strip() or val
                    norm["block"] = clean_b
                    if not any(c["nombre"] == "BLOCK" for c in parsed_comp):
                        parsed_comp.append({"nombre": "BLOCK", "valor": clean_b, "es_urbano": True})
                    break

        # Manejo de sublote plano (solo predial genuino, NUNCA módulos ni pisos)
        slt_val = None
        raw_slt_source = None
        for k in ("slote", "Sub LT.", "sub lt.", "sub_lote", "sublote", "Sub LT"):
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    raw_slt_source = val
                    has_mod = bool(re.search(
                        r"\b(INT(?:ERIOR(?:ES)?)?|DPTO|DEP(?:ARTAMENTO)?|PUERTA|PTA|STAND|STD|TIENDA|TDA|OFICINA|OF|PUESTO|PTO|LOCAL|LOC)\b",
                        val,
                        re.IGNORECASE,
                    ))
                    is_ref_like = bool(re.search(r"\b(?:PISO|BLOCK|BLOQUE|BLQ|TORRE|ESQ|ESQUINA|FRENTE|ALTURA|CUADRA|EDIFICIO)\b", val, re.IGNORECASE))
                    if not has_mod and not is_ref_like:
                        clean_sublote = SUBLOTE_PREFIX_REGEX.sub("", val).strip(" -:,.")
                        if clean_sublote and not SUBLOTE_PLACEHOLDER_REGEX.match(clean_sublote):
                            norm["slote"] = clean_sublote
                            if not any(c["nombre"] == "SUBLOTE" for c in parsed_comp):
                                parsed_comp.append({"nombre": "SUBLOTE", "valor": clean_sublote, "es_urbano": True})
                        else:
                            norm["slote"] = None
                    elif not has_mod:
                        # Referencia urbana (ej: '2DO. PISO ESQ. LIBERTAD') preservada para reubicación en ai_parser
                        norm["slote"] = val[:100]
                    else:
                        norm["slote"] = None
                    break

        # Sincronizar piso y block en norm desde parsed_comp si aún no estaban
        for c in parsed_comp:
            if c["nombre"] == "PISO" and not norm.get("piso"):
                norm["piso"] = c["valor"]
            elif c["nombre"] == "BLOCK" and not norm.get("block"):
                norm["block"] = c["valor"]

        norm["componentes"] = parsed_comp

        # 4. Extracción de Módulos (Interior, Dpto, Puerta, Stand, Tienda, etc. - BLOCK se maneja como componente)
        def _split_modulo_range(v_str: str) -> List[str]:
            clean_v = re.sub(r"^[\[\(]+|[\]\)]+$", "", str(v_str)).strip(" '\"")
            clean_v = re.sub(r"^(?:N°\.?|NUM°?\.?|NRO\.?|N\s+)", "", clean_v, flags=re.IGNORECASE).strip()
            parts = [p.strip() for p in re.split(r",\s*|\s+Y\s+|\s*-\s*", clean_v, flags=re.IGNORECASE) if p.strip()]
            noise_tokens = {
                "N", "NRO", "NUM", "PISO", "PISOS", "NIVEL", "CHICLAYO", "LAMBAYEQUE",
                "FERRENAFE", "PIMENTEL", "LA VICTORIA", "VICTORIA", "JLO", "REQUE",
                "MONSEFU", "LIMA", "PERU", "PERÚ"
            }
            parts = [
                p for p in parts
                if p and p.upper() not in noise_tokens and not (len(p) > 5 and not p.isdigit())
            ]
            if len(parts) > 1 and all(len(p) <= 6 for p in parts):
                return parts
            return [clean_v] if clean_v else []

        parsed_mod: List[dict] = []
        raw_mod = data.get("modulos")
        if isinstance(raw_mod, list):
            for m in raw_mod:
                if isinstance(m, BaseModel):
                    m = m.model_dump()
                if isinstance(m, dict) and m.get("tipo_modulo") and m.get("valor"):
                    t_mod = str(m["tipo_modulo"]).strip().upper()
                    split_vals = _split_modulo_range(m["valor"])
                    if t_mod in ("BLOCK", "BLQ", "TORRE", "PABELLON", "PABELLÓN"):
                        for sp_val in split_vals:
                            if not any(cp["nombre"] == "BLOCK" for cp in parsed_comp):
                                parsed_comp.append({"nombre": "BLOCK", "valor": sp_val, "es_urbano": True})
                            norm["block"] = sp_val
                        continue
                    for sp_val in split_vals:
                        if not any(x["tipo_modulo"] == t_mod and x["valor"] == sp_val for x in parsed_mod):
                            parsed_mod.append({
                                "tipo_modulo": t_mod,
                                "valor": sp_val,
                            })

        # Detección y migración de módulos desde campos legados (llaves específicas)
        legacy_module_keys = [
            ("Dep.", "DEPARTAMENTO"), ("dep", "DEPARTAMENTO"), ("dpto", "DEPARTAMENTO"), ("DPTO", "DEPARTAMENTO"),
            ("INT.", "INTERIOR"), ("int", "INTERIOR"), ("INT", "INTERIOR"),
            ("STAND.", "STAND"), ("stand", "STAND"), ("STAND", "STAND"),
            ("TDA.", "TIENDA"), ("tda", "TIENDA"), ("tienda", "TIENDA"),
            ("puerta", "PUERTA"), ("PUERTA", "PUERTA"),
            ("oficina", "OFICINA"), ("OFICINA", "OFICINA"), ("of", "OFICINA"),
            ("puesto", "PUESTO"), ("PUESTO", "PUESTO"),
        ]
        for k, timo_name in legacy_module_keys:
            if k in data and data[k] is not None:
                val = str(data[k]).strip()
                if val:
                    for sp in _split_modulo_range(val):
                        if not any(m["tipo_modulo"] == timo_name and m["valor"] == sp for m in parsed_mod):
                            parsed_mod.append({"tipo_modulo": timo_name, "valor": sp})

        # Si el valor de sublote plano contenía módulos (ej. "INT B-C", "INTERIOR B, INTERIOR C", "STAND 81")
        if raw_slt_source:
            kw = r"(?:INT(?:ERIOR(?:ES)?)?|DPTO|DEP(?:ARTAMENTO)?|PUERTA|PTA|STAND|STD|TIENDA|TDA|OFICINA|OF|PUESTO|PTO|LOCAL|LOC)"
            mod_pattern = re.compile(
                rf"\b({kw})\b\.?\s*[:\-]?\s*([A-Z0-9\-]+(?:\s*(?:,|Y|-)\s*(?!{kw}\b)[A-Z0-9\-]+)*)",
                re.IGNORECASE,
            )
            for m_match in mod_pattern.finditer(raw_slt_source):
                t_raw = m_match.group(1).upper()
                canon_mod = "INTERIOR" if "INT" in t_raw else (
                    "DEPARTAMENTO" if "DEP" in t_raw else (
                        "STAND" if "ST" in t_raw else (
                            "TIENDA" if "T" in t_raw else (
                                "OFICINA" if "OF" in t_raw else (
                                    "PUERTA" if "PT" in t_raw or "PUERTA" in t_raw else (
                                        "PUESTO" if "P" in t_raw else "LOCAL"
                                    )
                                )
                            )
                        )
                    )
                )
                val_raw = m_match.group(2).strip()
                for sp in _split_modulo_range(val_raw):
                    if not any(m["tipo_modulo"] == canon_mod and m["valor"] == sp for m in parsed_mod):
                        parsed_mod.append({"tipo_modulo": canon_mod, "valor": sp})

        # Filtrar módulos con valores espurios o etiquetas de sublote
        norm["modulos"] = [
            m for m in parsed_mod
            if m.get("valor")
            and not SUBLOTE_PLACEHOLDER_REGEX.match(str(m["valor"]).strip())
            and str(m.get("tipo_modulo", "")).upper() not in ("SLT", "SLOTE", "SUBLOTE", "S/L")
        ]

        # 5. Referencia Espacial de Orientación (Estricta para hitos urbanos)
        ref_val = None
        for k in ("referencia", "Referencia", "ref"):
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    ref_val = v
                    break

        if ref_val:
            # Capturar pisos si vinieron en referencia (ej. "1 PISO", "2 PISO", "2DO PISO", "PISO 2")
            m_piso = re.search(r"\b((?:\d+(?:DO|ER|TO|VO|MO)?\.?\s*)?PISO|\d+\s*PISO|PISO\s*\d+)\b", ref_val, re.IGNORECASE)
            if m_piso:
                piso_str = m_piso.group(1).strip().upper()
                p_num = re.search(r"\d+", piso_str)
                clean_piso = p_num.group(0) if p_num else piso_str
                if not any(c["nombre"] == "PISO" for c in parsed_comp):
                    parsed_comp.append({"nombre": "PISO", "valor": clean_piso, "es_urbano": True})
                norm["piso"] = clean_piso
                ref_val = ref_val[:m_piso.start()] + " " + ref_val[m_piso.end():]

            # Capturar blocks si vinieron en referencia (ej. "BLOCK S", "TORRE A")
            m_block = re.search(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\s*([A-Z0-9\-]+)\b", ref_val, re.IGNORECASE)
            if m_block:
                b_val = m_block.group(1).strip()
                if not any(c["nombre"] == "BLOCK" for c in parsed_comp):
                    parsed_comp.append({"nombre": "BLOCK", "valor": b_val, "es_urbano": True})
                norm["block"] = b_val
                ref_val = ref_val[:m_block.start()] + " " + ref_val[m_block.end():]

            clean_ref = ref_val.strip(" -/,.")
            norm["referencia"] = clean_ref if clean_ref else None
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


class OllamaJudgeVerdict(BaseModel):
    """Estructura de respuesta de evaluación y dictamen emitida por el Modelo 2 (El Juez / Observador)."""
    es_valido: bool = Field(
        default=False,
        description="True si la dirección es físicamente válida y completa para catastro, False si debe observarse/rechazarse",
    )
    categoria_falla: str = Field(
        default="INCOMPLETA",
        description="Categoría técnica: INCOMPLETA, INEXISTENTE, INCONGRUENTE, FUERA_JURISDICCION, FORMATO_INVALIDO",
    )
    observacion_dictamen: str = Field(
        default="Dirección no cumple con los criterios mínimos de ubicación física.",
        description="Texto exacto, conciso y estandarizado del motivo del rechazo u observación catastral",
    )

