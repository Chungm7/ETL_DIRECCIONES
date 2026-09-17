"""Transformador de direcciones asistido por Ollama con heurística de respaldo resiliente."""

import logging
import re
from typing import Optional

from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino
from src.models.llm_schemas import OllamaAddressExtraction
from src.services.ollama_service import OllamaService
from src.transformers.catalog_matcher import CatalogMatcher
from src.transformers.text_cleaner import TextCleaner
from src.catalogs.catalog_manager import CatalogManager

logger = logging.getLogger("etl_mpch.ai_parser")


class AIAddressParser:
    """Utiliza Ollama para interpretar semánticamente la dirección cruda con respaldo heurístico."""

    def __init__(self, ollama_service: Optional[OllamaService] = None):
        self.ollama = ollama_service or OllamaService()

    def parse(self, record: DireccionOrigen) -> DireccionDestino:
        """Invoca al modelo local de Ollama para desglosar la dirección y aplica correcciones."""
        if record.is_empty():
            return DireccionDestino(
                id_licencia=record.id_licencia,
                es_procesado=False,
                observacion="DIRECCIÓN VACÍA: El registro no contiene texto de dirección",
                metodo_normalizacion="N/A",
            )

        raw_text = TextCleaner.sanitize(record.emp_direccion or "")

        # 1. Inferencia semántica con Ollama
        extraction: Optional[OllamaAddressExtraction] = self.ollama.parse_address_with_ai(raw_text)

        # 2. Inicializar campos con la extracción o con valores nulos
        tipo_via_detectado = extraction.tipo_via_detectado if extraction else None
        nom_via = extraction.nom_via if extraction else None
        num_via = extraction.num_via if extraction else None
        tipo_zona_detectada = extraction.tipo_zona_detectada if extraction else None
        nom_zona = extraction.nom_zona if extraction else None
        manzana = extraction.manzana if extraction else None
        lote = extraction.lote if extraction else None
        slote = extraction.slote if extraction else None
        referencia = extraction.referencia if extraction else None

        ia_exitosa = extraction is not None
        heuristica_aplicada = False

        if not ia_exitosa:
            heuristica_aplicada = True

        # 2.5 Corrección y reconocimiento de vías emblemáticas con fechas o números (ej. '7 DE ENERO')
        known_date_streets = [
            "7 DE ENERO SUR", "SIETE DE ENERO SUR", "7 DE ENERO", "SIETE DE ENERO",
            "8 DE OCTUBRE", "9 DE OCTUBRE", "NUEVE DE OCTUBRE", "28 DE JULIO",
            "27 DE JULIO", "1 DE MAYO", "1 DE NOVIEMBRE", "15 DE ABRIL",
            "14 DE ABRIL", "12 DE FEBRERO", "6 DE JUNIO", "7 ENSAYOS"
        ]
        for kds in known_date_streets:
            if re.search(rf"\b{re.escape(kds)}\b", raw_text, re.IGNORECASE):
                if not nom_via or nom_via.upper() != kds:
                    nom_via = kds
                    after_kds = raw_text[raw_text.upper().find(kds) + len(kds):]
                    m_num_kds = re.search(r"\b(?:N°?|NUM°?|NRO\.?|N)\s*(\d+)\b", after_kds, re.IGNORECASE)
                    if m_num_kds:
                        num_via = m_num_kds.group(1)
                    else:
                        m_num_gen = re.search(r"\b(\d+)\b", after_kds)
                        if m_num_gen:
                            num_via = m_num_gen.group(1)
                    if not tipo_via_detectado:
                        before_kds = raw_text[:raw_text.upper().find(kds)]
                        via_prefixes = CatalogManager.get_via_prefix_regex_str()
                        m_pre = re.search(rf"\b({via_prefixes})\b", before_kds, re.IGNORECASE)
                        tipo_via_detectado = m_pre.group(1).upper() if m_pre else "CALLE"
                    heuristica_aplicada = True
                break

        # 3. Respaldo Heurístico Dinámico: Si Ollama no detectó el tipo de vía
        if not tipo_via_detectado:
            for via_item in CatalogManager.get_vias_catalog():
                pat = via_item.get("patron_regex")
                if pat and re.search(pat, raw_text, re.IGNORECASE):
                    tipo_via_detectado = via_item["nombre"]
                    heuristica_aplicada = True
                    break

        # 4. Respaldo Heurístico: Si nom_via quedó vacío
        if not nom_via:
            # Caso 1: Vía con prefijo común (usando prefijos dinámicos del catálogo)
            via_prefixes = CatalogManager.get_via_prefix_regex_str()
            match_via = re.search(
                rf"(?:^|\b){via_prefixes}\s+([A-ZÁÉÍÓÚÑ\s\.\-]+?)(?:\s+(?:N°|NUM°?|NRO\.?|N\s*\d+|S/N|\d+|\(|MZ|LT|,)|$)",
                raw_text,
                re.IGNORECASE,
            )
            if match_via:
                nom_via = match_via.group(1).strip(" ,.-")
                heuristica_aplicada = True

            # Caso 2: Nombre de calle precedido por la ciudad (ej. "CHICLAYO ALFREDO LAPOINT 882")
            match_city = re.search(
                r"^(?:CHICLAYO|LAMBAYEQUE|FERRENAFE)\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+(\d+|S/N)",
                raw_text,
            )
            if match_city:
                nom_via = match_city.group(1).strip()
                if not num_via:
                    num_via = match_city.group(2).strip()
                if not tipo_via_detectado:
                    tipo_via_detectado = "CALLE"
                heuristica_aplicada = True

        # 5. Respaldo Heurístico para numeración de vía
        if not num_via:
            if re.search(r"\bS/N\b", raw_text):
                num_via = "S/N"
                heuristica_aplicada = True
            else:
                match_num = re.search(r"\b(?:N°?\s*|NUM°?\s*|N\s*)?(\d+)\b", raw_text)
                if match_num:
                    num_via = match_num.group(1)
                    heuristica_aplicada = True

        # 6. Respaldo Heurístico para interiores ("INT-I", "INT- 1", "DPTO 2")
        if "INT-" in raw_text or "DPTO" in raw_text:
            match_int = re.search(r"\b(INT-[A-Z0-9]+|DPTO-[A-Z0-9]+)\b", raw_text)
            if match_int:
                interior_val = match_int.group(1)
                if not slote:
                    slote = interior_val
                    heuristica_aplicada = True
                if num_via and interior_val not in num_via:
                    num_via = f"{num_via} {interior_val}".strip()
                    heuristica_aplicada = True

        # 7. Respaldo Heurístico Dinámico para zonas y referencias
        # 7a. Extraer referencia entre paréntesis
        if "(" in raw_text and ")" in raw_text:
            match_par = re.search(r"\(([^)]+)\)", raw_text)
            if match_par:
                par_text = match_par.group(1).strip()
                if not referencia:
                    referencia = par_text.upper()
                    heuristica_aplicada = True

        # 7b. Buscar tipo de zona en el catálogo (priorizando tipos específicos sobre cercado)
        if not tipo_zona_detectada:
            for zona_item in CatalogManager.get_zonas_catalog():
                if zona_item["nombre"] == "CERCADO":
                    continue
                pat = zona_item.get("patron_regex")
                if pat and re.search(pat, raw_text, re.IGNORECASE):
                    tipo_zona_detectada = zona_item["nombre"]
                    heuristica_aplicada = True
                    break

        # 7c. Si no se detectó zona específica, evaluar CERCADO o CHICLAYO al inicio
        if not tipo_zona_detectada:
            if "CERCADO" in raw_text or raw_text.startswith("CHICLAYO "):
                tipo_zona_detectada = "CERCADO"
                if not nom_zona:
                    nom_zona = "CERCADO DE CHICLAYO"
                heuristica_aplicada = True

        # 7d. Respaldo Heurístico para nom_zona cuando no fue detectado
        if not nom_zona:
            zona_prefixes = CatalogManager.get_zona_prefix_regex_str()
            match_zona = re.search(
                rf"{zona_prefixes}\s+([^,;()\-]+?)(?:\s+(?:MZ|LT|LOTE|MANZANA|REF|\(|$)|,|-|$)",
                raw_text,
                re.IGNORECASE,
            )
            if match_zona:
                cand_zona = match_zona.group(1).strip()
                cand_zona = re.sub(r"\s+(?:CHICLAYO|LAMBAYEQUE|FERRENAFE)$", "", cand_zona, flags=re.IGNORECASE).strip(" ,.-")
                if cand_zona:
                    nom_zona = cand_zona
                    heuristica_aplicada = True

        # 7e. Respaldo Heurístico Dinámico para Referencias (hitos urbanos, guías de ubicación)
        if not referencia:
            # Caso 1: Prefijo explícito REF o REFERENCIA
            match_ref_expl = re.search(
                r"\b(?:REF(?:ERENCIA)?\.?)\s*[:\-]?\s*([^,;()]+)",
                raw_text,
                re.IGNORECASE,
            )
            if match_ref_expl:
                referencia = match_ref_expl.group(1).strip().upper()
                heuristica_aplicada = True
            else:
                # Caso 2: Locuciones espaciales (CERCA AL, FRENTE A, AL COSTADO DE, A ESPALDAS DE, etc.)
                match_ref_loc = re.search(
                    r"\b((?:CERCA\s+(?:AL?|DE)|FRENTE\s+(?:AL?|A)|(?:AL\s+)?COSTADO\s+(?:DE|DEL?)|A\s+ESPALDAS?\s+(?:DE|DEL?)|A\s+(?:LA\s+)?ALTURA\s+(?:DE|DEL?)|A\s+MEDIA\s+CUADRA\s+(?:DE|DEL?)|ENTRE\s+[A-ZÁÉÍÓÚÑ0-9\s]+\s+Y\s+|CRUCE\s+(?:CON)?)\s+[^,;()]+)",
                    raw_text,
                    re.IGNORECASE,
                )
                if match_ref_loc:
                    referencia = match_ref_loc.group(1).strip().upper()
                    heuristica_aplicada = True

        # Limpieza de referencia y prevención de fuga hacia nom_zona o nom_via
        if referencia:
            referencia = re.sub(r"\s+", " ", referencia).strip(" ,.-").upper()
            if nom_zona and referencia in nom_zona.upper():
                nom_zona = re.sub(re.escape(referencia), "", nom_zona, flags=re.IGNORECASE).strip(" ,.-")
            if nom_via and referencia in nom_via.upper():
                nom_via = re.sub(re.escape(referencia), "", nom_via, flags=re.IGNORECASE).strip(" ,.-")

        # Determinar etiqueta del método utilizado
        if ia_exitosa and not heuristica_aplicada:
            metodo = f"IA ({self.ollama.model_name})"
        elif ia_exitosa and heuristica_aplicada:
            metodo = f"Híbrido (IA + Heurística)"
        else:
            metodo = "Heurístico (Fallback - IA inactiva)"

        # 8. Homologar con catálogos oficiales de tipos y con entidades maestras de Chiclayo
        id_tipo_via = CatalogMatcher.match_tipo_via(tipo_via_detectado)
        id_tipo_zona = CatalogMatcher.match_tipo_zona(tipo_zona_detectada)

        via_detectada_en_texto = bool(nom_via and nom_via.strip())
        matched_via = CatalogMatcher.match_physical_via(nom_via, id_tipo_via) if via_detectada_en_texto else None

        zona_detectada_en_texto = bool(nom_zona and nom_zona.strip())
        matched_zona = CatalogMatcher.match_physical_zona(nom_zona, id_tipo_zona) if zona_detectada_en_texto else None

        observaciones = []

        if via_detectada_en_texto and not matched_via:
            observaciones.append(f"Vía '{nom_via}' no existe en el catálogo maestro de vías de Chiclayo")

        if zona_detectada_en_texto and not matched_zona:
            observaciones.append(f"Zona/Habilitación '{nom_zona}' no existe en el catálogo maestro de zonas de Chiclayo")

        if not via_detectada_en_texto and not zona_detectada_en_texto:
            observaciones.append("DIRECCIÓN NO RECONOCIDA: No se detectó vía ni habilitación urbana válida en el texto")

        if observaciones:
            # Caso observado: Se nullifican todas las columnas derivadas para evitar datos sin sentido
            return DireccionDestino(
                id_licencia=record.id_licencia,
                id_via=None,
                num_via=None,
                id_zona=None,
                manzana=None,
                lote=None,
                slote=None,
                referencia=None,
                es_procesado=False,
                observacion="; ".join(observaciones),
                metodo_normalizacion=metodo,
            )
        else:
            # Caso exitoso: Asociado formalmente a las tablas maestras oficiales
            return DireccionDestino(
                id_licencia=record.id_licencia,
                id_via=matched_via["id"] if matched_via else None,
                num_via=num_via,
                id_zona=matched_zona["id"] if matched_zona else None,
                manzana=manzana,
                lote=lote,
                slote=slote,
                referencia=referencia,
                es_procesado=True,
                observacion=None,
                tipo_via=matched_via.get("id_tipo_via") or id_tipo_via if matched_via else None,
                nom_via=matched_via["nom_via"] if matched_via else None,
                tipo_zona=matched_zona.get("id_tipo_zona") or id_tipo_zona if matched_zona else None,
                nom_zona=matched_zona["nom_zona"] if matched_zona else None,
                metodo_normalizacion=metodo,
            )
