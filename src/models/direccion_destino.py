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
        default="ACT",
        description="Estado de la dirección: ACT (Activo), INA (Inactivo)",
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
    slote: Optional[str] = Field(default=None, max_length=20, description="Sublote o división interna")
    referencia: Optional[str] = Field(default=None, max_length=255, description="Punto de referencia")

    @model_validator(mode="before")
    @classmethod
    def sanitize_and_align_v2(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # 1. Sanitizar slote: si contiene 'PISO', 'ESQ', 'ESQUINA', etc. o supera 20 caracteres,
        # reasignar a referencia para evitar ValidationError y truncamiento indebido
        slote_val = data.get("slote")
        if slote_val and isinstance(slote_val, str):
            slote_clean = slote_val.strip()
            is_ref_like = bool(re.search(r"\b(?:PISO|ESQ|ESQUINA|FRENTE|ENTRE|CRUCE)\b", slote_clean, re.IGNORECASE))
            if is_ref_like or len(slote_clean) > 20:
                current_ref = data.get("referencia") or data.get("dire_referencia") or ""
                data["referencia"] = f"{current_ref} {slote_clean}".strip() if current_ref else slote_clean
                data["dire_referencia"] = data["referencia"]
                data["slote"] = None

        # 2. Límites de longitud seguros
        limits = {
            "num_via": 50,
            "manzana": 20,
            "lote": 20,
            "slote": 20,
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

        # 6. Sincronización Componentes (Manzana, Lote)
        comps = data.get("componentes") or []
        if comps:
            for c in comps:
                cn = (c.get("codi_nombre") or "").upper()
                if "MANZANA" in cn and not data.get("manzana"):
                    data["manzana"] = c.get("diti_nombre")
                elif "LOTE" in cn and "SUBLOTE" not in cn and not data.get("lote"):
                    data["lote"] = c.get("diti_nombre")
        else:
            new_comps = []
            if data.get("manzana"):
                new_comps.append({"codi_id": 1, "codi_nombre": "MANZANA", "diti_nombre": str(data["manzana"]).strip()})
            if data.get("lote"):
                new_comps.append({"codi_id": 2, "codi_nombre": "LOTE", "diti_nombre": str(data["lote"]).strip()})
            if new_comps:
                data["componentes"] = new_comps

        # 7. Sincronización Módulos y Slote
        mods = data.get("modulos") or []
        if not data.get("slote") and mods:
            data["slote"] = ", ".join(f"{m.get('timo_nombre', '')} {m.get('ditm_nombre', '')}".strip() for m in mods)
        elif data.get("slote") and not mods:
            s_val = str(data["slote"]).strip()
            m_match = re.search(r"\b(INT(?:ERIOR)?|DPTO|DEP|PUERTA|STAND|TIENDA|BLOCK|OFICINA)\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)", s_val, re.IGNORECASE)
            if m_match:
                from src.transformers.catalog_matcher import CatalogMatcher
                mm = CatalogMatcher.match_tipo_modulo(m_match.group(1).upper())
                if mm:
                    data["modulos"] = [{"timo_id": mm[0], "timo_nombre": mm[1], "ditm_nombre": m_match.group(2).strip()}]

        return data
