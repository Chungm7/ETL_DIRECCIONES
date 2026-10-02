"""Representación normalizada y consolidada para la arquitectura relacional V2 de Chiclayo."""

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class DireccionDestino(BaseModel):
    """Representa el conjunto de entidades desglosadas para persistencia en las tablas relacionales V2."""

    id_licencia: int = Field(
        description="Identificador único del registro de origen (PK de tb_xxx / xxxx_id)",
    )
    dire_id: Optional[int] = Field(
        default=None,
        description="Clave primaria generada en `tb_direccion` al normalizar con éxito",
    )
    zona_id: Optional[int] = Field(
        default=None,
        description="Clave foránea hacia `tb_zona.zona_id`",
    )
    dire_referencia: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Hito espacial o comercial exclusivo de orientación urbana (ej. CERCA AL SENATI, FRENTE AL PARQUE)",
    )
    dire_estado: str = Field(
        default="A",
        max_length=3,
        description="Estado de la dirección: A (Activo), I (Inactivo), E (Eliminado)",
    )

    # Relación de Vías (soporta 1 vía o múltiples en esquina/intersección)
    # Cada elemento es un dict: {"via_id": int, "divi_numero": str, "divi_orden": int, "via_nombre": str, "tipo_via": int}
    vias: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de arterias viales asociadas en tb_direccion_via",
    )

    # Relación de Componentes Catastrales (Manzana, Lote, Sublote, Piso, etc.)
    # Cada elemento es un dict: {"codi_id": int, "codi_nombre": str, "diti_nombre": str}
    componentes: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de componentes catastrales en tb_contenido_componente_direccion",
    )

    # Relación de Módulos Inmobiliarios (Interior, Dpto, Puerta, Stand, Block, etc.)
    # Cada elemento es un dict: {"timo_id": int, "timo_nombre": str, "ditm_nombre": str}
    modulos: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Lista de dependencias y módulos en tb_direccion_tipo_modulo",
    )

    es_procesado: bool = Field(
        default=False,
        description="TRUE si la dirección fue validada y vinculada a catastro; FALSE si fue observada",
    )
    observacion: Optional[str] = Field(
        default=None,
        description="Dictamen técnico si no pudo normalizarse o notas de auditoría",
    )
    metodo_normalizacion: str = Field(
        default="IA",
        description="Indica el motor con el que se procesó: IA, Heurístico o Híbrido",
    )

    # Campos planos / de retrocompatibilidad directa
    id_via: Optional[int] = Field(default=None, description="Clave foránea hacia vias.id_via")
    num_via: Optional[str] = Field(default=None, max_length=50, description="Numeración municipal")
    nom_via: Optional[str] = Field(default=None, max_length=150, description="Nombre de vía en memoria")
    tipo_via: Optional[int] = Field(default=None, description="ID del tipo de vía en memoria")

    id_zona: Optional[int] = Field(default=None, description="Clave foránea hacia zonas.id_zona")
    nom_zona: Optional[str] = Field(default=None, max_length=150, description="Nombre oficial de la zona en memoria")
    tipo_zona: Optional[int] = Field(default=None, description="ID del tipo de zona en memoria")

    manzana: Optional[str] = Field(default=None, max_length=20, description="Identificador de Manzana (Mz)")
    lote: Optional[str] = Field(default=None, max_length=20, description="Identificador de Lote (Lt)")
    slote: Optional[str] = Field(default=None, max_length=100, description="Sublote o resumen de módulos interiores")
    piso: Optional[str] = Field(default=None, max_length=20, description="Identificador de Piso o Nivel")
    block: Optional[str] = Field(default=None, max_length=20, description="Identificador de Block, Bloque o Torre")
    referencia: Optional[str] = Field(default=None, max_length=255, description="Punto de referencia")

    @model_validator(mode="before")
    @classmethod
    def sanitize_and_align_v2(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # 1. Sanitizar slote: segregar PISO y BLOCK hacia componentes; referencias hacia referencia
        slote_val = data.get("slote")
        if slote_val and isinstance(slote_val, str):
            slote_clean = slote_val.strip()

            # Capturar PISO si vino en slote
            m_piso = re.search(r"\b(?:PISO\s*(\d+|[A-Z0-9]+)|(\d+)(?:DO|ER|TO|VO|MO)?\.?\s*PISO)\b", slote_clean, re.IGNORECASE)
            if m_piso:
                pval = (m_piso.group(1) or m_piso.group(2) or "").strip()
                if pval and not data.get("piso"):
                    data["piso"] = pval
                slote_clean = re.sub(r"\b(?:PISO\s*(\d+|[A-Z0-9]+)|(\d+)(?:DO|ER|TO|VO|MO)?\.?\s*PISO)\b", "", slote_clean, flags=re.IGNORECASE).strip(" -/,.")

            # Capturar BLOCK si vino en slote
            m_block = re.search(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\s*([A-Z0-9\-]+)\b", slote_clean, re.IGNORECASE)
            if m_block:
                bval = m_block.group(1).strip()
                if bval and not data.get("block"):
                    data["block"] = bval
                slote_clean = re.sub(r"\b(?:BLOCK|BLOQUE|BLQ|TORRE)\s*([A-Z0-9\-]+)\b", "", slote_clean, flags=re.IGNORECASE).strip(" -/,.")

            is_ref_like = bool(re.search(r"\b(?:ESQ|ESQUINA|FRENTE|ENTRE|CRUCE|ALTURA|CUADRA)\b", slote_clean, re.IGNORECASE))
            if is_ref_like:
                current_ref = data.get("referencia") or data.get("dire_referencia") or ""
                data["referencia"] = f"{current_ref} {slote_clean}".strip() if current_ref else slote_clean
                data["dire_referencia"] = data["referencia"]
                data["slote"] = None
            elif not slote_clean:
                data["slote"] = None
            elif len(slote_clean) > 100:
                data["slote"] = slote_clean[:100].strip()
            else:
                data["slote"] = slote_clean

        # 2. Límites de longitud seguros iniciales
        limits = {
            "num_via": 50,
            "manzana": 20,
            "lote": 20,
            "slote": 100,
            "piso": 20,
            "block": 20,
            "referencia": 255,
            "dire_referencia": 500,
            "nom_via": 150,
            "nom_zona": 150,
        }
        for field, max_len in limits.items():
            val = data.get(field)
            if val and isinstance(val, str) and len(val) > max_len:
                data[field] = val[:max_len].strip()

        # 3. Sincronización bidireccional Referencia
        if "referencia" in data and not data.get("dire_referencia"):
            data["dire_referencia"] = data["referencia"]
        elif "dire_referencia" in data and not data.get("referencia"):
            data["referencia"] = data["dire_referencia"]

        # 4. Sincronización bidireccional Zona ID
        if "id_zona" in data and data["id_zona"] is not None and not data.get("zona_id"):
            data["zona_id"] = data["id_zona"]
        elif "zona_id" in data and data["zona_id"] is not None and not data.get("id_zona"):
            data["id_zona"] = data["zona_id"]

        # 5. Sincronización Vías
        vias = data.get("vias") or []
        if vias:
            v0 = vias[0]
            if not data.get("id_via") and v0.get("via_id"):
                data["id_via"] = v0.get("via_id")
            if not data.get("num_via") and v0.get("divi_numero"):
                data["num_via"] = v0.get("divi_numero")
            if not data.get("nom_via") and v0.get("via_nombre"):
                data["nom_via"] = v0.get("via_nombre")
            if not data.get("tipo_via") and v0.get("tipo_via"):
                data["tipo_via"] = v0.get("tipo_via")
        elif data.get("id_via") or data.get("nom_via"):
            data["vias"] = [{
                "via_id": data.get("id_via"),
                "divi_numero": str(data.get("num_via") or "").strip() or None,
                "divi_orden": 1,
                "via_nombre": data.get("nom_via"),
                "tipo_via": data.get("tipo_via"),
            }]

        # 6. Sincronización Componentes (Manzana, Lote, Piso, Block)
        comps = data.get("componentes") or []
        if comps:
            for c in comps:
                cn = (c.get("codi_nombre") or "").upper()
                if "MANZANA" in cn and not data.get("manzana"):
                    data["manzana"] = c.get("diti_nombre")
                elif "LOTE" in cn and "SUBLOTE" not in cn and not data.get("lote"):
                    data["lote"] = c.get("diti_nombre")
                elif "PISO" in cn and not data.get("piso"):
                    data["piso"] = c.get("diti_nombre")
                elif "BLOCK" in cn and not data.get("block"):
                    data["block"] = c.get("diti_nombre")

            # Asegurar que si data tiene piso o block, estén en la lista comps
            has_piso = any((c.get("codi_nombre") or "").upper() == "PISO" for c in comps)
            if data.get("piso") and not has_piso:
                comps.append({"codi_id": 4, "codi_nombre": "PISO", "diti_nombre": str(data["piso"]).strip()})
            has_block = any((c.get("codi_nombre") or "").upper() == "BLOCK" for c in comps)
            if data.get("block") and not has_block:
                comps.append({"codi_id": 11, "codi_nombre": "BLOCK", "diti_nombre": str(data["block"]).strip()})

            # Filtrar componentes espurios de sublote (placeholders como "slt")
            sub_pat = r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT|SIN\s+SUBLOTE|SIN\s+SUB\s*LOTE|NO|N/A|NA|NONE|NULL|-|\.)$"
            cleaned_comps = []
            for c in comps:
                cn = (c.get("codi_nombre") or "").upper()
                cv = str(c.get("diti_nombre") or "").strip()
                if "SUBLOTE" in cn:
                    clean_c = re.sub(r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT)\s*", "", cv, flags=re.IGNORECASE).strip(" -:,.")
                    if not clean_c or re.match(sub_pat, cv, re.I) or re.match(sub_pat, clean_c, re.I):
                        continue
                    c["diti_nombre"] = clean_c
                cleaned_comps.append(c)
            comps = cleaned_comps
            data["componentes"] = comps
        else:
            new_comps = []
            if data.get("manzana"):
                new_comps.append({"codi_id": 1, "codi_nombre": "MANZANA", "diti_nombre": str(data["manzana"]).strip()})
            if data.get("lote"):
                new_comps.append({"codi_id": 2, "codi_nombre": "LOTE", "diti_nombre": str(data["lote"]).strip()})
            if data.get("piso"):
                new_comps.append({"codi_id": 4, "codi_nombre": "PISO", "diti_nombre": str(data["piso"]).strip()})
            if data.get("block"):
                new_comps.append({"codi_id": 11, "codi_nombre": "BLOCK", "diti_nombre": str(data["block"]).strip()})
            if new_comps:
                data["componentes"] = new_comps

        # 7. Sincronización Módulos y Slote (Aislamiento Estricto para persistencia relacional V2)
        mods = data.get("modulos") or []
        sl_val = data.get("slote")
        if sl_val:
            s_val = str(sl_val).strip()
            sub_pat = r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT|SIN\s+SUBLOTE|SIN\s+SUB\s*LOTE|NO|N/A|NA|NONE|NULL|-|\.)$"
            clean_s = re.sub(r"^(?:SUB\s*(?:LOTE|LT\.?)|SLT\.?|SLOTE|S/L|S/LT)\s*", "", s_val, flags=re.IGNORECASE).strip(" -:,.")
            if not clean_s or re.match(sub_pat, s_val, re.I) or re.match(sub_pat, clean_s, re.I):
                data["slote"] = None
                sl_val = None
            else:
                data["slote"] = clean_s
                sl_val = clean_s
        if sl_val and not mods:
            s_val = str(sl_val).strip()
            kw = r"(?:INT(?:ERIOR(?:ES)?)?|DPTO|DEP(?:ARTAMENTO)?|PUERTA|PTA|STAND|STD|TIENDA|TDA|OFICINA|OF|PUESTO|PTO|LOCAL|LOC)"
            m_match = re.search(rf"\b({kw})\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)", s_val, re.IGNORECASE)
            if m_match:
                from src.transformers.catalog_matcher import CatalogMatcher
                mm = CatalogMatcher.match_tipo_modulo(m_match.group(1).upper())
                if mm:
                    data["modulos"] = [{"timo_id": mm[0], "timo_nombre": mm[1], "ditm_nombre": m_match.group(2).strip()}]
        elif not sl_val and mods:
            # Mantener resumen plano en slote para visualización GUI / compatibilidad V1 (máx 100 caracteres)
            summary_slote = ", ".join(
                f"{m.get('timo_nombre') or 'MODULO'} {m.get('ditm_nombre')}".strip()
                for m in mods
                if m.get("ditm_nombre")
            )
            if summary_slote:
                data["slote"] = summary_slote[:100]

        # 8. Salvaguarda final defensiva contra ValidationError por longitud
        final_limits = {
            "num_via": 50,
            "manzana": 20,
            "lote": 20,
            "slote": 100,
            "piso": 20,
            "block": 20,
            "referencia": 255,
            "dire_referencia": 500,
            "nom_via": 150,
            "nom_zona": 150,
        }
        for field, max_len in final_limits.items():
            val = data.get(field)
            if val and isinstance(val, str) and len(val) > max_len:
                data[field] = val[:max_len].strip()

        return data
