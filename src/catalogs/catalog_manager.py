"""Gestor y cargador centralizado de catálogos y diccionarios desde archivos JSON.

Permite desacoplar los datos maestros de vías, zonas, sinónimos y heurísticas
del código de ejecución. Facilita agregar nuevos registros (por ejemplo de 28 a 32 zonas)
sin modificar la lógica interna del ETL ni de la base de datos.
"""

import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("etl_mpch.catalog_manager")

DEFAULT_CATALOGS_DIR = Path(__file__).resolve().parent
VIAS_FILE = DEFAULT_CATALOGS_DIR / "tipos_via.json"
ZONAS_FILE = DEFAULT_CATALOGS_DIR / "tipos_zona.json"
VIAS_CHICLAYO_FILE = DEFAULT_CATALOGS_DIR / "vias_chiclayo.json"
ZONAS_CHICLAYO_FILE = DEFAULT_CATALOGS_DIR / "zonas_chiclayo.json"


def _remove_accents(text: str) -> str:
    """Elimina diacríticos para indexación y búsqueda canónica."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join([c for c in nfkd if not unicodedata.combining(c)])


def _sanitize(text: Optional[str]) -> str:
    """Limpia espacios y mayúsculas sin dependencias externas."""
    if not text:
        return ""
    clean = "".join(ch for ch in text if ch.isprintable())
    return re.sub(r"\s+", " ", clean).strip().upper()



class CatalogManager:
    """Administra la carga, persistencia y construcción de diccionarios para vías y zonas."""

    _vias_cache: Optional[List[Dict[str, Any]]] = None
    _zonas_cache: Optional[List[Dict[str, Any]]] = None
    _vias_chiclayo_cache: Optional[List[Dict[str, Any]]] = None
    _zonas_chiclayo_cache: Optional[List[Dict[str, Any]]] = None
    _physical_vias_lookup_cache: Optional[Dict[str, Dict[str, Any]]] = None
    _physical_zonas_lookup_cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def reload(cls) -> None:
        """Fuerza la recarga de los catálogos en memoria desde los archivos JSON."""
        cls._vias_cache = None
        cls._zonas_cache = None
        cls._vias_chiclayo_cache = None
        cls._zonas_chiclayo_cache = None
        cls._physical_vias_lookup_cache = None
        cls._physical_zonas_lookup_cache = None
        # Notificar a CatalogMatcher para refrescar sus mapeos
        try:
            from src.transformers.catalog_matcher import CatalogMatcher
            CatalogMatcher.reset_defaults()
        except ImportError:
            pass

    @classmethod
    def get_vias_catalog(cls) -> List[Dict[str, Any]]:
        """Retorna la lista de tipos de vía cargada desde JSON."""
        if cls._vias_cache is None:
            cls._vias_cache = cls._load_json(VIAS_FILE, default=[])
        return cls._vias_cache

    @classmethod
    def get_zonas_catalog(cls) -> List[Dict[str, Any]]:
        """Retorna la lista de tipos de zona cargada desde JSON."""
        if cls._zonas_cache is None:
            cls._zonas_cache = cls._load_json(ZONAS_FILE, default=[])
        return cls._zonas_cache

    @classmethod
    def get_vias_chiclayo_catalog(cls) -> List[Dict[str, Any]]:
        """Retorna la lista maestra de vías físicas de Chiclayo cargada desde JSON."""
        if cls._vias_chiclayo_cache is None:
            cls._vias_chiclayo_cache = cls._load_json(VIAS_CHICLAYO_FILE, default=[])
        return cls._vias_chiclayo_cache

    @classmethod
    def get_zonas_chiclayo_catalog(cls) -> List[Dict[str, Any]]:
        """Retorna la lista maestra de zonas / habilitaciones urbanas de Chiclayo cargada desde JSON."""
        if cls._zonas_chiclayo_cache is None:
            cls._zonas_chiclayo_cache = cls._load_json(ZONAS_CHICLAYO_FILE, default=[])
        return cls._zonas_chiclayo_cache

    @classmethod
    def get_official_physical_vias_tuples(cls) -> List[Tuple[int, Optional[int], str]]:
        """Retorna [(id_via, id_tipo_via, nom_via), ...] para sembrar la tabla vias."""
        catalog = cls.get_vias_chiclayo_catalog()
        return [
            (
                item["id"],
                item.get("id_tipo_via"),
                item["nom_via"],
            )
            for item in catalog
        ]

    @classmethod
    def get_official_physical_zonas_tuples(cls) -> List[Tuple[int, Optional[int], str]]:
        """Retorna [(id_zona, id_tipo_zona, nom_zona), ...] para sembrar la tabla zonas."""
        catalog = cls.get_zonas_chiclayo_catalog()
        return [
            (
                item["id"],
                item.get("id_tipo_zona"),
                item["nom_zona"],
            )
            for item in catalog
        ]

    EXTRA_VIAS_SYNONYMS: Dict[str, str] = {
        "NICOLAS CUGLIEVAN": "JUAN CUGLIEVAN",
        "GALERIAS NICOLAS CUGLIEVAN": "JUAN CUGLIEVAN",
        "GALERIAS CUGLIEVAN": "JUAN CUGLIEVAN",
        "NICOLAS DE CUGLIEVAN": "JUAN CUGLIEVAN",
        "PEDRO CIEZA DE LEON": "PEDRO CIEZA DE LEON",
        "PEDRO CIEZA": "PEDRO CIEZA DE LEON",
        "ANGEL CORNEJO": "ANGEL GUSTAVO CORNEJO",
        "BOLOGNESI": "AV. FRANCISCO BOLOGNESI",
        "SALAVERRY": "FELIPE SANTIAGO SALAVERRY",
        "ULISES ULLOA TELLO": "ULISES ULLOA TELLO",
        "MANUEL ARTEAGA": "MANUEL ARTEAGA",
        "ALFONSO UGARTE": "ALFONSO UGARTE",
        "RIO CHIRA": "RIO CHIRA",
        "BAGUA": "BAGUA",
        "IQUITOS": "IQUITOS",
        "LOS GORRIONES": "LOS GORRIONES",
    }

    EXTRA_ZONAS_SYNONYMS: Dict[str, str] = {
        "JOSE QUIÑONES GONZALES": "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA",
        "JOSE QUIÑONES": "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA",
        "JOSÉ QUIÑONES": "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA",
        "URB. QUIÑONES": "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA",
        "QUIÑONES": "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA",
        "JOSE OBRERO": "PROGRESIVA SAN JOSÉ OBRERO",
        "JOSÉ OBRERO": "PROGRESIVA SAN JOSÉ OBRERO",
        "SAN JOSE OBRERO": "PROGRESIVA SAN JOSÉ OBRERO",
        "SAN JOSÉ OBRERO": "PROGRESIVA SAN JOSÉ OBRERO",
        "MAGISTERIAL": "RESIDENCIAL DERRAMA MAGISTERIAL",
        "DERRAMA MAGISTERIAL": "RESIDENCIAL DERRAMA MAGISTERIAL",
        "CONDOMINIO LA PRIMAVERA": "LA PRIMAVERA",
        "LA PRIMAVERA III ETAPA": "LA PRIMAVERA III",
        "LA PRIMAVERA III-ETAPA": "LA PRIMAVERA III",
        "LA PRIMAVERA 3 ETAPA": "LA PRIMAVERA III",
        "LA PRIMAVERA 3RA ETAPA": "LA PRIMAVERA III",
        "3 DE OCTUBRE": "3 DE OCTUBRE - PAMPA Y MOLINO DE VIENTO",
        "SAN LORENZO": "SAN LORENZO",
        "SANTA VICTORIA": "SANTA VICTORIA",
        "LAS BRISAS": "LAS BRISAS",
        "JOSE OLAYA": "JOSÉ OLAYA",
        "JOSÉ OLAYA": "JOSÉ OLAYA",
        "CESAR VALLEJO": "CÉSAR VALLEJO",
        "CÉSAR VALLEJO": "CÉSAR VALLEJO",
        "LAS TORRES DE CHICLAYO": "CERCADO DE CHICLAYO",
    }

    @classmethod
    def get_physical_vias_lookup(cls) -> Dict[str, Dict[str, Any]]:
        """Retorna un índice rápido {nombre_o_sinonimo_limpio: via_dict} para vías físicas."""
        if cls._physical_vias_lookup_cache is None:
            lookup: Dict[str, Dict[str, Any]] = {}
            for item in cls.get_vias_chiclayo_catalog():
                nom = item["nom_via"].strip().upper()
                clean_nom = _remove_accents(nom)
                lookup[nom] = item
                lookup[clean_nom] = item

                for syn in item.get("sinonimos", []):
                    s_clean = str(syn).strip().upper()
                    s_noacc = _remove_accents(s_clean)
                    lookup[s_clean] = item
                    lookup[s_noacc] = item

            # Enriquecer con sinónimos canónicos frecuentes de Chiclayo
            for alias, target in cls.EXTRA_VIAS_SYNONYMS.items():
                target_clean = target.strip().upper()
                target_obj = lookup.get(target_clean) or lookup.get(_remove_accents(target_clean))
                if target_obj:
                    lookup[alias] = target_obj
                    lookup[_remove_accents(alias)] = target_obj

            cls._physical_vias_lookup_cache = lookup
        return cls._physical_vias_lookup_cache

    @classmethod
    def get_physical_zonas_lookup(cls) -> Dict[str, Dict[str, Any]]:
        """Retorna un índice rápido {nombre_o_sinonimo_limpio: zona_dict} para zonas físicas."""
        if cls._physical_zonas_lookup_cache is None:
            lookup: Dict[str, Dict[str, Any]] = {}
            for item in cls.get_zonas_chiclayo_catalog():
                nom = item["nom_zona"].strip().upper()
                clean_nom = _remove_accents(nom)
                lookup[nom] = item
                lookup[clean_nom] = item

                for syn in item.get("sinonimos", []):
                    s_clean = str(syn).strip().upper()
                    s_noacc = _remove_accents(s_clean)
                    lookup[s_clean] = item
                    lookup[s_noacc] = item

            # Enriquecer con sinónimos canónicos frecuentes de zonas
            for alias, target in cls.EXTRA_ZONAS_SYNONYMS.items():
                target_clean = target.strip().upper()
                target_obj = lookup.get(target_clean) or lookup.get(_remove_accents(target_clean))
                if target_obj:
                    lookup[alias] = target_obj
                    lookup[_remove_accents(alias)] = target_obj

            cls._physical_zonas_lookup_cache = lookup
        return cls._physical_zonas_lookup_cache

    @classmethod
    def _load_json(cls, file_path: Path, default: Any) -> Any:
        """Lee y deserializa un archivo JSON de forma segura."""
        if not file_path.exists():
            logger.warning("Archivo de catálogo no encontrado: %s", file_path)
            return default
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error al cargar JSON de catálogo en %s: %s", file_path, e)
            return default

    @classmethod
    def _save_json(cls, file_path: Path, data: Any) -> bool:
        """Serializa y guarda datos en un archivo JSON con formato legible."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error("Error al guardar JSON de catálogo en %s: %s", file_path, e)
            return False

    # -------------------------------------------------------------------------
    # Integración con DatabaseService (Inserción y verificación en BD)
    # -------------------------------------------------------------------------

    @classmethod
    def get_official_vias_tuples(cls) -> List[Tuple[int, str, str]]:
        """Retorna [(id, nombre, abreviatura), ...] para sincronizar con PostgreSQL."""
        catalog = cls.get_vias_catalog()
        return [(item["id"], item["nombre"], item.get("abreviatura") or "") for item in catalog]

    @classmethod
    def get_official_zonas_tuples(cls) -> List[Tuple[int, str, str]]:
        """Retorna [(id, nombre, abreviatura), ...] para sincronizar con PostgreSQL."""
        catalog = cls.get_zonas_catalog()
        return [(item["id"], item["nombre"], item.get("abreviatura") or "") for item in catalog]

    # -------------------------------------------------------------------------
    # Integración con CatalogMatcher (Sinónimos y mapeos en memoria)
    # -------------------------------------------------------------------------

    @classmethod
    def get_canonical_via_synonyms(cls) -> Dict[str, List[str]]:
        """Retorna un diccionario {nombre_canonico: [sinonimos...]} para vías."""
        res: Dict[str, List[str]] = {}
        for item in cls.get_vias_catalog():
            nombre = item["nombre"]
            syns = list(item.get("sinonimos", []))
            if nombre not in syns:
                syns.insert(0, nombre)
            abrev = item.get("abreviatura")
            if abrev and abrev not in syns:
                syns.append(abrev)
            res[nombre] = syns
        return res

    @classmethod
    def get_canonical_zona_synonyms(cls) -> Dict[str, List[str]]:
        """Retorna un diccionario {nombre_canonico: [sinonimos...]} para zonas."""
        res: Dict[str, List[str]] = {}
        for item in cls.get_zonas_catalog():
            nombre = item["nombre"]
            syns = list(item.get("sinonimos", []))
            if nombre not in syns:
                syns.insert(0, nombre)
            abrev = item.get("abreviatura")
            if abrev and abrev not in syns:
                syns.append(abrev)
            res[nombre] = syns
        return res

    @classmethod
    def get_default_vias_mapping(cls) -> Dict[str, int]:
        """Construye el mapeo completo {termino: id_tipo_via} para vías."""
        mapping: Dict[str, int] = {}
        for item in cls.get_vias_catalog():
            vid = item["id"]
            nombre = item["nombre"]
            mapping[nombre] = vid
            mapping[_remove_accents(nombre)] = vid

            for syn in item.get("sinonimos", []):
                syn_clean = str(syn).strip().upper()
                mapping[syn_clean] = vid
                mapping[_remove_accents(syn_clean)] = vid
                if syn_clean.endswith("."):
                    mapping[syn_clean.rstrip(".")] = vid
        return mapping

    @classmethod
    def get_default_zonas_mapping(cls) -> Dict[str, int]:
        """Construye el mapeo completo {termino: id_tipo_zona} para zonas."""
        mapping: Dict[str, int] = {}
        for item in cls.get_zonas_catalog():
            zid = item["id"]
            nombre = item["nombre"]
            mapping[nombre] = zid
            mapping[_remove_accents(nombre)] = zid

            for syn in item.get("sinonimos", []):
                syn_clean = str(syn).strip().upper()
                mapping[syn_clean] = zid
                mapping[_remove_accents(syn_clean)] = zid
                if syn_clean.endswith("."):
                    mapping[syn_clean.rstrip(".")] = zid
        return mapping


    @classmethod
    def get_default_vias_names(cls) -> Dict[int, str]:
        """Retorna {id_tipo_via: nombre_oficial}."""
        return {item["id"]: item["nombre"] for item in cls.get_vias_catalog()}

    @classmethod
    def get_default_zonas_names(cls) -> Dict[int, str]:
        """Retorna {id_tipo_zona: nombre_oficial}."""
        return {item["id"]: item["nombre"] for item in cls.get_zonas_catalog()}

    # -------------------------------------------------------------------------
    # Integración con Prompts del Modelo de IA (Ollama)
    # -------------------------------------------------------------------------

    @classmethod
    def format_vias_for_prompt(cls) -> str:
        """Formatea la lista de vías para incluir en el System Prompt del LLM."""
        items = []
        for v in cls.get_vias_catalog():
            abrev = f" ({v['abreviatura']})" if v.get("abreviatura") else ""
            items.append(f"{v['nombre']}{abrev}")
        return ", ".join(items)

    @classmethod
    def format_zonas_for_prompt(cls) -> str:
        """Formatea la lista de zonas para incluir en el System Prompt del LLM."""
        items = []
        for z in cls.get_zonas_catalog():
            abrev = f" ({z['abreviatura']})" if z.get("abreviatura") else ""
            items.append(f"{z['nombre']}{abrev}")
        return ", ".join(items)
    @classmethod
    def format_physical_vias_for_prompt(cls, limit: int = 150) -> str:
        """Formatea las vías metropolitanas y céntricas más representativas de Chiclayo para el LLM."""
        catalog = cls.get_vias_chiclayo_catalog()
        # 1. Vías con jerarquía vial relevante (arterial, colectora, expresa, etc.)
        prominent = set(
            v["nom_via"]
            for v in catalog
            if v.get("clasificacion") and v.get("clasificacion") != "LOCAL" and v.get("nom_via")
        )
        # 2. Vías céntricas y de alto tránsito de Chiclayo
        central_keys = (
            "BALTA", "LAPOINT", "GONZALES", "TORRES PAZ", "7 DE ENERO", "PEDRO RUIZ",
            "SAN JOSE", "ELIAS AGUIRRE", "IZAGA", "COLON", "TACNA", "ARICA",
            "LEONCIO PRADO", "MANCO CAPAC", "VICENTE DE LA VEGA", "ORIENTE",
            "AMERICAS", "SANTA VICTORIA", "BOLOGNESI", "GRAU", "SALAVERRY",
            "LEGUIA", "FITZCARRAL", "JORGE CHAVEZ", "LOS INCAS", "UNION",
            "LORA Y LORA", "FRANCISCO CABRERA", "QUIÑONES", "CHICLAYO", "PIMENTEL"
        )
        for v in catalog:
            nom = v.get("nom_via", "")
            if any(k in nom for k in central_keys):
                prominent.add(nom)

        unique_vias = sorted(list(prominent))[:limit]
        return ", ".join(unique_vias)

    @classmethod
    def format_physical_zonas_sample_for_prompt(cls, limit: int = 80) -> str:
        """Formatea las zonas y habilitaciones urbanas más representativas de Chiclayo para el LLM."""
        catalog = cls.get_zonas_chiclayo_catalog()
        unique_zonas = sorted(list(set(z["nom_zona"] for z in catalog if z.get("nom_zona") and not z["nom_zona"].startswith("SIN DENOMINACION"))))
        return ", ".join(unique_zonas[:limit])

    @classmethod
    def get_via_prefix_regex_str(cls) -> str:
        """Genera la expresión regular para prefijos comunes de vías reconocidos."""
        prefixes = set()
        for v in cls.get_vias_catalog():
            prefixes.add(re.escape(v["nombre"]))
            if v.get("abreviatura"):
                prefixes.add(re.escape(v["abreviatura"]))
            for s in v.get("sinonimos", []):
                if len(s) <= 15:
                    prefixes.add(re.escape(s))
        # Ordenar por longitud descendente para emparejar los más largos primero
        sorted_prefixes = sorted(list(prefixes), key=len, reverse=True)
        return r"(?:" + "|".join(sorted_prefixes) + r")"

    @classmethod
    def get_zona_prefix_regex_str(cls) -> str:
        """Genera la expresión regular para prefijos comunes de zonas reconocidos."""
        prefixes = set()
        for z in cls.get_zonas_catalog():
            if z["nombre"] == "CERCADO":
                continue
            prefixes.add(re.escape(z["nombre"]))
            if z.get("abreviatura"):
                prefixes.add(re.escape(z["abreviatura"]))
            for s in z.get("sinonimos", []):
                if len(s) <= 25:
                    prefixes.add(re.escape(s))
        sorted_prefixes = sorted(list(prefixes), key=len, reverse=True)
        return r"(?:" + "|".join(sorted_prefixes) + r")"

    # -------------------------------------------------------------------------
    # Métodos para Agregar Registros Dinámicamente (CLI y Scripting)
    # -------------------------------------------------------------------------

    @classmethod
    def add_tipo_via(
        cls,
        nombre: str,
        abreviatura: Optional[str] = None,
        sinonimos: Optional[List[str]] = None,
        patron_regex: Optional[str] = None,
        id_tipo: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Agrega un nuevo tipo de vía al catálogo JSON sin tocar código fuente."""
        catalog = cls.get_vias_catalog()
        clean_name = _sanitize(nombre)
        norm_name = _remove_accents(clean_name)

        # Verificar si ya existe
        for item in catalog:
            if _remove_accents(item["nombre"]) == norm_name:
                return {
                    "success": False,
                    "message": f"El tipo de vía '{clean_name}' ya existe en el catálogo con ID {item['id']}.",
                    "entry": item,
                }

        # Determinar ID
        if id_tipo is None:
            max_id = max((item["id"] for item in catalog), default=0)
            assigned_id = max_id + 1
        else:
            assigned_id = id_tipo

        clean_abrev = _sanitize(abreviatura) if abreviatura else clean_name[:4] + "."
        if clean_abrev and not clean_abrev.endswith("."):
            clean_abrev += "."

        # Consolidar sinónimos
        syn_list = [clean_name]
        if norm_name != clean_name:
            syn_list.append(norm_name)
        if clean_abrev and clean_abrev not in syn_list:
            syn_list.append(clean_abrev)
        if sinonimos:
            for s in sinonimos:
                s_clean = _sanitize(s)
                if s_clean and s_clean not in syn_list:
                    syn_list.append(s_clean)

        new_entry = {
            "id": assigned_id,
            "nombre": clean_name,
            "abreviatura": clean_abrev,
            "sinonimos": syn_list,
            "patron_regex": patron_regex or f"\\b{re.escape(clean_name)}\\b",
        }

        catalog.append(new_entry)
        saved = cls._save_json(VIAS_FILE, catalog)
        if saved:
            cls.reload()
            return {
                "success": True,
                "message": f"Tipo de vía '{clean_name}' agregado exitosamente con ID {assigned_id}.",
                "entry": new_entry,
                "total_records": len(catalog),
            }
        return {
            "success": False,
            "message": f"Error al persistir el archivo JSON {VIAS_FILE}.",
            "entry": new_entry,
        }

    @classmethod
    def add_tipo_zona(
        cls,
        nombre: str,
        abreviatura: Optional[str] = None,
        sinonimos: Optional[List[str]] = None,
        patron_regex: Optional[str] = None,
        id_tipo: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Agrega un nuevo tipo de zona al catálogo JSON sin tocar código fuente."""
        catalog = cls.get_zonas_catalog()
        clean_name = _sanitize(nombre)
        norm_name = _remove_accents(clean_name)

        # Verificar si ya existe
        for item in catalog:
            if _remove_accents(item["nombre"]) == norm_name:
                return {
                    "success": False,
                    "message": f"El tipo de zona '{clean_name}' ya existe en el catálogo con ID {item['id']}.",
                    "entry": item,
                }

        # Determinar ID
        if id_tipo is None:
            max_id = max((item["id"] for item in catalog), default=0)
            assigned_id = max_id + 1
        else:
            assigned_id = id_tipo

        clean_abrev = _sanitize(abreviatura) if abreviatura else clean_name[:4] + "."
        if clean_abrev and not clean_abrev.endswith("."):
            clean_abrev += "."

        # Consolidar sinónimos
        syn_list = [clean_name]
        if norm_name != clean_name:
            syn_list.append(norm_name)
        if clean_abrev and clean_abrev not in syn_list:
            syn_list.append(clean_abrev)
        if sinonimos:
            for s in sinonimos:
                s_clean = _sanitize(s)
                if s_clean and s_clean not in syn_list:
                    syn_list.append(s_clean)


        new_entry = {
            "id": assigned_id,
            "nombre": clean_name,
            "abreviatura": clean_abrev,
            "sinonimos": syn_list,
            "patron_regex": patron_regex or f"\\b{re.escape(clean_name)}\\b",
        }

        catalog.append(new_entry)
        saved = cls._save_json(ZONAS_FILE, catalog)
        if saved:
            cls.reload()
            return {
                "success": True,
                "message": f"Tipo de zona '{clean_name}' agregado exitosamente con ID {assigned_id}.",
                "entry": new_entry,
                "total_records": len(catalog),
            }
        return {
            "success": False,
            "message": f"Error al persistir el archivo JSON {ZONAS_FILE}.",
            "entry": new_entry,
        }

    @classmethod
    def get_summary(cls) -> Dict[str, Any]:
        """Retorna un resumen con los conteos y listas actuales."""
        vias = cls.get_vias_catalog()
        zonas = cls.get_zonas_catalog()
        return {
            "total_vias": len(vias),
            "total_zonas": len(zonas),
            "vias_file": str(VIAS_FILE),
            "zonas_file": str(ZONAS_FILE),
        }
