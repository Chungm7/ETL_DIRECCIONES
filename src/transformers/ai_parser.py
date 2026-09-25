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
        two_vias_conflict = None

        if not ia_exitosa:
            heuristica_aplicada = True
        else:
            # Guardrail Anti-Alucinación: Verificar que nom_via y nom_zona compartan raíz con raw_text
            if nom_via:
                v_toks = CatalogMatcher._extract_sig_tokens(nom_via, is_via=True)
                r_toks = CatalogMatcher._extract_sig_tokens(raw_text, is_via=True)
                is_syn_v = False
                for cand_syn, target_name in CatalogManager.EXTRA_VIAS_SYNONYMS.items():
                    if target_name.upper() in nom_via.upper() and cand_syn.upper() in raw_text.upper():
                        is_syn_v = True
                        break
                if not is_syn_v and not (v_toks & r_toks):
                    logger.warning("Descartando nom_via alucinado por IA: '%s' no presente en '%s'", nom_via, raw_text)
                    nom_via = None
                    heuristica_aplicada = True

            if nom_zona:
                z_toks = CatalogMatcher._extract_sig_tokens(nom_zona, is_via=False)
                r_toks = CatalogMatcher._extract_sig_tokens(raw_text, is_via=False)
                is_syn_z = False
                for cand_syn, target_name in CatalogManager.EXTRA_ZONAS_SYNONYMS.items():
                    if target_name.upper() in nom_zona.upper() and cand_syn.upper() in raw_text.upper():
                        is_syn_z = True
                        break
                if not is_syn_z and not (z_toks & r_toks):
                    logger.warning("Descartando nom_zona alucinado por IA: '%s' no presente en '%s'", nom_zona, raw_text)
                    nom_zona = None
                    heuristica_aplicada = True

        # 2.5 Respaldo para vías emblemáticas con fechas o números cuando nom_via está vacío o truncado
        if not nom_via or nom_via.upper() in ("ENERO", "OCTUBRE", "JULIO", "MAYO", "NOVIEMBRE", "ABRIL", "FEBRERO", "JUNIO", "ENSAYOS"):
            known_date_streets = [
                "7 DE ENERO SUR", "SIETE DE ENERO SUR", "7 DE ENERO", "SIETE DE ENERO",
                "8 DE OCTUBRE", "9 DE OCTUBRE", "NUEVE DE OCTUBRE", "28 DE JULIO",
                "27 DE JULIO", "1 DE MAYO", "1 DE NOVIEMBRE", "15 DE ABRIL",
                "14 DE ABRIL", "12 DE FEBRERO", "6 DE JUNIO", "7 ENSAYOS"
            ]
            for kds in known_date_streets:
                if re.search(rf"\b{re.escape(kds)}\b", raw_text, re.IGNORECASE):
                    # Verificar que la fecha no corresponda a la zona
                    if not nom_zona or kds not in nom_zona.upper():
                        nom_via = kds
                        after_kds = raw_text[raw_text.upper().find(kds) + len(kds):]
                        m_num_kds = re.search(r"\b(?:N°?|NUM°?|NRO\.?|N)\s*(\d+)\b", after_kds, re.IGNORECASE)
                        if m_num_kds:
                            num_via = m_num_kds.group(1)
                            after_kds_sub = after_kds[m_num_kds.end():]
                            m_let = re.search(r"^\s*[-/]?\s*([A-Za-z])\b", after_kds_sub)
                            if m_let and not slote:
                                slote = m_let.group(1).upper()
                        elif not num_via:
                            m_num_gen = re.search(r"\b(\d+)\b", after_kds)
                            if m_num_gen:
                                num_via = m_num_gen.group(1)
                                after_kds_sub = after_kds[m_num_gen.end():]
                                m_let = re.search(r"^\s*[-/]?\s*([A-Za-z])\b", after_kds_sub)
                                if m_let and not slote:
                                    slote = m_let.group(1).upper()
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

            # Caso 2: Nombre de calle precedido por la ciudad (ej. "CHICLAYO ALFREDO LAPOINT 882" o "CHICLAYO - LUIS GONZALES 839")
            if not nom_via:
                match_city = re.search(
                    r"^(?:CHICLAYO|LAMBAYEQUE|FERRENAFE|PIMENTEL|LA VICTORIA|JLO)\s*(?:-\s*)?([A-ZÁÉÍÓÚÑ\s\.\-]+?)\s+(\d+|S/N)\b",
                    raw_text,
                    re.IGNORECASE,
                )
                if match_city:
                    nom_via = match_city.group(1).strip(" ,.-")
                    if not num_via:
                        num_via = match_city.group(2).strip()
                    if not tipo_via_detectado:
                        tipo_via_detectado = "CALLE"
                    heuristica_aplicada = True

            # Caso 3: Formato ZONA - VIA NUMERO (ej. "SAN NICOLAS - LAS AMERICAS 705", "REMIGIO SILVA-TOMAS GUTIERREZ00370" o "LAS AMERICAS 705 - SAN NICOLAS")
            if not nom_via:
                match_zona_via = re.search(
                    r"^([A-ZÁÉÍÓÚÑ0-9\s\.]+?)\s*(?<!INT)(?<!DPTO)(?<!DEP)-\s*([A-ZÁÉÍÓÚÑ0-9\s\.]+?)(?:,\s*(\d+|S/N)\b|\s+(\d+|S/N)\b|\s+(?:BLOCK|MZ|LT)\b|\s*-\s*|$)",
                    raw_text,
                    re.IGNORECASE,
                )
                if match_zona_via:
                    posible_1 = match_zona_via.group(1).strip()
                    posible_2 = match_zona_via.group(2).strip()
                    posible_num = match_zona_via.group(3) or match_zona_via.group(4)
                    if posible_1 not in ("CHICLAYO", "LAMBAYEQUE", "FERRENAFE", "PIMENTEL", "LA VICTORIA", "JLO"):
                        # Detectar y separar número pegado al final si existe
                        m_p2_num = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', posible_2, re.IGNORECASE)
                        cand_p2_num = None
                        if m_p2_num and not CatalogMatcher.match_physical_via(posible_2):
                            cand_p2 = posible_2[:m_p2_num.start()].strip(" ,.-")
                            if cand_p2:
                                cand_p2_num = m_p2_num.group(1).lstrip("0") or "S/N"
                                posible_2 = cand_p2

                        m_p1_num = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', posible_1, re.IGNORECASE)
                        cand_p1_num = None
                        if m_p1_num and not CatalogMatcher.match_physical_zona(posible_1):
                            cand_p1 = posible_1[:m_p1_num.start()].strip(" ,.-")
                            if cand_p1:
                                cand_p1_num = m_p1_num.group(1).lstrip("0") or "S/N"
                                posible_1 = cand_p1

                        extracted_num = cand_p1_num or cand_p2_num or posible_num

                        m_v1 = CatalogMatcher.match_physical_via(posible_1)
                        m_z1 = CatalogMatcher.match_physical_zona(posible_1)
                        m_v2 = CatalogMatcher.match_physical_via(posible_2)
                        m_z2 = CatalogMatcher.match_physical_zona(posible_2)

                        # Desambiguación por anclaje del número municipal a la vía
                        if cand_p1_num and m_v1:
                            nom_via = posible_1
                            nom_zona = posible_2
                            num_via = extracted_num
                        elif (cand_p2_num or posible_num) and m_v2:
                            nom_via = posible_2
                            nom_zona = posible_1
                            num_via = extracted_num
                        # Prioridad 1: Zona - Vía (patrón dominante en Chiclayo)
                        elif m_z1 and m_v2:
                            nom_zona = posible_1
                            nom_via = posible_2
                            if extracted_num:
                                num_via = extracted_num
                        # Prioridad 2: Vía - Zona (invertido)
                        elif m_v1 and m_z2:
                            nom_via = posible_1
                            nom_zona = posible_2
                            if extracted_num:
                                num_via = extracted_num
                        # Prioridad 3: Ambos exclusivamente vías -> conflicto
                        elif m_v1 and m_v2:
                            two_vias_conflict = (posible_1, posible_2)
                            nom_via = posible_1
                            if extracted_num:
                                num_via = extracted_num
                        else:
                            if not nom_zona:
                                nom_zona = posible_1
                            if not re.match(r"^(?:MZ\.?|MZA\.?|MANZANA|LT\.?|LOTE)\b", posible_2, re.IGNORECASE):
                                if not nom_via:
                                    nom_via = posible_2
                                if extracted_num and not num_via:
                                    num_via = extracted_num
                        trailing = raw_text[match_zona_via.end():].strip(" ,.-")
                        if trailing and trailing.upper() not in ("CHICLAYO", "LAMBAYEQUE", "FERRENAFE", "PIMENTEL", "LA VICTORIA", "JLO"):
                            if not referencia and not re.match(r"^(?:CHICLAYO|LAMBAYEQUE|FERRENAFE|PIMENTEL|LA VICTORIA|JLO)\b", trailing, re.IGNORECASE):
                                referencia = trailing.upper()
                        heuristica_aplicada = True

        # 5. Respaldo Heurístico para numeración de vía (SOLO si existe una vía)
        if not nom_via:
            num_via = None
        elif not num_via:
            if re.search(r"\bS/N\b", raw_text, re.IGNORECASE):
                num_via = "S/N"
                heuristica_aplicada = True
            else:
                # Buscar número explícito tras prefijos como N°, NUM, NRO, o pegado al nombre de vía
                match_num = re.search(r"\b(?:N°\.?\s*|NUM°?\.?\s*|NRO\.?\s*|N\s*)(\d+)\b", raw_text, re.IGNORECASE)
                if not match_num and nom_via:
                    pat_after_via = rf"{re.escape(nom_via)}\s+(?:N°?\s*)?(\d+)\b"
                    match_num = re.search(pat_after_via, raw_text, re.IGNORECASE)

                if match_num:
                    num_via = match_num.group(1)
                    heuristica_aplicada = True
                    after_pos = match_num.end()
                    m_let = re.search(r"^\s*[-/]?\s*([A-Za-z])\b", raw_text[after_pos:])
                    if m_let and not slote:
                        slote = m_let.group(1).upper()

        # 6. Respaldo Heurístico para interiores ("INT-I", "INT- 1", "DPTO 2")
        if "INT-" in raw_text or "DPTO" in raw_text:
            match_int = re.search(r"\b(INT-[A-Z0-9]+|DPTO-[A-Z0-9]+)\b", raw_text)
            if match_int:
                interior_val = match_int.group(1)
                if not slote:
                    slote = interior_val
                    heuristica_aplicada = True

        # 6b. Respaldo Heurístico para Manzana y Lote
        if not manzana:
            match_mz = re.search(r"\b(?:MANZANA|MZA\.?|MZ\.?)\s*[:\-]?\s*([A-Z0-9]+)\b", raw_text, re.IGNORECASE)
            if match_mz:
                manzana = match_mz.group(1).upper()
                heuristica_aplicada = True

        if not lote:
            match_lt = re.search(r"\b(?:LT\.?|LOTE)\s*[:\-]?\s*([A-Z0-9]+)\b", raw_text, re.IGNORECASE)
            if match_lt:
                lote = match_lt.group(1).upper()
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

        # 7c. Si no se detectó zona específica, evaluar CERCADO solo si está explícito
        if not tipo_zona_detectada:
            if re.search(r"\bCERCADO\b", raw_text, re.IGNORECASE):
                tipo_zona_detectada = "CERCADO"
                if not nom_zona:
                    nom_zona = "CERCADO DE CHICLAYO"
                heuristica_aplicada = True

        # 7d. Respaldo Heurístico para nom_zona cuando no fue detectado
        if not nom_zona:
            # Caso 1: ZONA - MZA/LT (ej. "SAN JUAN DE DIOS - MZA. E LOTE 23")
            match_zona_mz = re.search(
                r"^([A-ZÁÉÍÓÚÑ\s\.]+?)\s+-\s*(?:MZ|MZA|MANZANA)\b",
                raw_text,
                re.IGNORECASE,
            )
            if match_zona_mz:
                cand_zona = match_zona_mz.group(1).strip(" ,.-")
                if cand_zona not in ("CHICLAYO", "LAMBAYEQUE", "FERRENAFE", "PIMENTEL", "LA VICTORIA", "JLO"):
                    nom_zona = cand_zona
                    heuristica_aplicada = True

            # Caso 2: Prefijos dinámicos de zona (URB, PJ, etc.)
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

        # 7e. Respaldo Heurístico Dinámico para Referencias (hitos urbanos, pisos, guías de ubicación)
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
            if not referencia:
                # Caso 2b: Hitos comerciales explícitos en raw_text (C.C. REAL PLAZA, OPEN PLAZA, BOULEVARD, etc.)
                m_comm = re.search(
                    r"\b((?:C\.?C\.?|CENTRO\s+COMERCIAL|MALL)\s+(?:REAL\s+PLAZA|OPEN\s+PLAZA|AVENTURA|BOLOGNESI)|REAL\s+PLAZA|OPEN\s+PLAZA|BOULEVARD|PLAZA\s+BOLOGNESI)\b",
                    raw_text,
                    re.IGNORECASE,
                )
                if m_comm:
                    comm_str = m_comm.group(0).strip().upper()
                    if not nom_via or comm_str not in nom_via.upper():
                        referencia = comm_str
                        heuristica_aplicada = True

        # Caso 3: Pisos o niveles (ej. '2DO. Y 3ER. PISO', '3ER. PISO')
        match_piso = re.search(
            r"\b((?:\d+(?:DO|ER|TO|VO|MO)?\.?\s*(?:Y\s*\d+(?:DO|ER|TO|VO|MO)?\.?\s*)?PISO)|(?:PISO\s*\d+))\b",
            raw_text,
            re.IGNORECASE,
        )
        if match_piso:
            piso_val = match_piso.group(1).strip().upper()
            if not referencia:
                referencia = piso_val
                heuristica_aplicada = True
            elif not re.search(r"\bPISO\b", referencia, re.IGNORECASE):
                referencia = f"{referencia} - {piso_val}".strip()
                heuristica_aplicada = True

        # 7f. Resolución de Doble Vía, Desambiguación e Inversión Via/Zona

        # Caso Urb. Quiñones con calles interiores (Iquitos, Rio Chira, Bagua, etc.)
        if raw_text and ("QUIÑONES" in raw_text.upper() or "QUINONES" in raw_text.upper()):
            for inner in ("IQUITOS", "RIO CHIRA", "BAGUA", "AMAZONAS", "MARAÑON", "MARANON"):
                if inner in raw_text.upper():
                    nom_zona = "CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA"
                    nom_via = inner
                    two_vias_conflict = None
                    if not num_via:
                        m_num_in = re.search(rf"\b{inner}\s*(\d+)\b", raw_text, re.IGNORECASE)
                        if m_num_in:
                            num_via = m_num_in.group(1).lstrip("0") or m_num_in.group(1)
                    if referencia and inner in referencia.upper():
                        referencia = re.sub(rf"\b{inner}\b", "", referencia, flags=re.IGNORECASE).strip(" ,.-")
                        if not referencia:
                            referencia = None
                    heuristica_aplicada = True
                    break

        # Respaldo Heurístico para Blocks / Pabellones / Torres
        match_block = re.search(r"(?<!DE LA\s)(?<!HAYA DE LA\s)\b(BLOCK\s+[A-Z0-9\-]+|TORRE\s+(?!N°|NRO|NUM|N\b)[A-Z0-9\-]+)\b", raw_text, re.IGNORECASE)
        if match_block:
            block_val = match_block.group(1).strip()
            if not nom_via or block_val.upper() not in nom_via.upper():
                if not referencia:
                    referencia = block_val
                elif block_val not in referencia:
                    referencia = f"{referencia} - {block_val}".strip()
                heuristica_aplicada = True

        # Si nom_via contiene dos vías separadas por guión, 'Y', 'CON', 'ESQ'
        if nom_via and not CatalogMatcher.match_physical_via(nom_via) and any(sep in nom_via for sep in (" - ", " Y ", " CON ", " ESQ ", " CRUCE ")):
            parts = re.split(r"\s+(?:-|Y|CON|ESQ\.?|CRUCE)\s+", nom_via, flags=re.IGNORECASE)
            if len(parts) >= 2:
                p1 = parts[0].strip()
                p2 = parts[1].strip()
                m_v1 = CatalogMatcher.match_physical_via(p1)
                m_z1 = CatalogMatcher.match_physical_zona(p1)
                m_v2 = CatalogMatcher.match_physical_via(p2)
                m_z2 = CatalogMatcher.match_physical_zona(p2)

                if m_z1 and m_v2 and not m_v1:
                    nom_zona = p1
                    nom_via = p2
                    heuristica_aplicada = True
                elif m_z2 and m_v1 and not m_v2:
                    nom_zona = p2
                    nom_via = p1
                    heuristica_aplicada = True
                elif m_v1 and m_v2:
                    if m_v1.get("id") != m_v2.get("id"):
                        two_vias_conflict = (p1, p2)
                        nom_via = p1
                    else:
                        nom_via = m_v1.get("nom_via", p1)

        # Limpieza de prefijos de centros comerciales, galerías o edificios en nom_via
        if nom_via:
            m_gal = re.match(r"^(?:GALERIAS?|GALERIA|EDIFICIO|CONDOMINIO|RESIDENCIAL)\s+(.+)", nom_via, re.IGNORECASE)
            if m_gal:
                raw_core = m_gal.group(1).strip()
                core_candidate = re.sub(
                    r"\s+(?:STAND|TIENDA|TDA\.?|LOCAL|DEP\.?|DPTO\.?|OFICINA|OF\.?|BLOCK|PISO)\b.*$",
                    "",
                    raw_core,
                    flags=re.IGNORECASE,
                ).strip()
                if CatalogMatcher.match_physical_via(core_candidate):
                    if not referencia:
                        referencia = raw_text
                    nom_via = core_candidate
                    num_via = None
                    heuristica_aplicada = True

        # Limpieza de mercados y establecimientos comerciales asignados a nom_via
        if nom_via and not CatalogMatcher.match_physical_via(nom_via) and re.match(r"^(?:MERCADO|MCDO|MCDONALD|CENTRO\s+DE\s+ABASTOS|C\.?C\.?|CENTRO\s+COMERCIAL|MALL|FERIA)\b", nom_via, re.IGNORECASE):
            if not referencia:
                referencia = nom_via
            elif nom_via not in referencia:
                referencia = f"{nom_via} - {referencia}".strip(" -")
            nom_via = None
            heuristica_aplicada = True

        # Limpieza de establecimientos comerciales asignados erróneamente como zona
        if nom_zona:
            is_commercial = (
                not CatalogMatcher.match_physical_zona(nom_zona)
                and (
                    re.search(r"\b(?:REAL\s+PLAZA|BOULEVARD|OPEN\s+PLAZA|PLAZA\s+BOLOGNESI|MALL\s+AVENTURA|MALL|GALERIAS?|EDIFICIO|STAND|C\.?C\.?|CENTRO\s+COMERCIAL|MERCADO|MCDO|MCDONALD|SUPERMERCADO|COMPLEJO|FERIA|TOTTUS|METRO|PROMART|SODIMAC)\b", nom_zona, re.IGNORECASE)
                    or re.match(r"^(?:GALERIAS?|EDIFICIO|STAND|C\.?C\.?|CENTRO\s+COMERCIAL|MERCADO|MCDO|SUPERMERCADO|COMPLEJO|FERIA|MALL)\b", nom_zona, re.IGNORECASE)
                )
            )
            if is_commercial:
                if not referencia:
                    referencia = nom_zona
                elif nom_zona not in referencia:
                    referencia = f"{nom_zona} - {referencia}".strip(" -")
                nom_zona = None
                tipo_zona_detectada = None
                heuristica_aplicada = True

        # Desacoplar numeración residual en nom_via o nom_zona si no fueron reconocidos directamente
        if nom_via:
            m_vnum = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', nom_via, re.IGNORECASE)
            if m_vnum and not CatalogMatcher.match_physical_via(nom_via):
                cand_clean_v = nom_via[:m_vnum.start()].strip(" ,.-")
                if cand_clean_v and (CatalogMatcher.match_physical_via(cand_clean_v) or CatalogMatcher.match_physical_zona(cand_clean_v)):
                    if not num_via:
                        num_via = m_vnum.group(1).lstrip("0") or "S/N"
                    nom_via = cand_clean_v
                    heuristica_aplicada = True

        if nom_zona:
            m_znum = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', nom_zona, re.IGNORECASE)
            if m_znum and not CatalogMatcher.match_physical_zona(nom_zona):
                cand_clean_z = nom_zona[:m_znum.start()].strip(" ,.-")
                if cand_clean_z and (CatalogMatcher.match_physical_zona(cand_clean_z) or CatalogMatcher.match_physical_via(cand_clean_z)):
                    if not num_via:
                        num_via = m_znum.group(1).lstrip("0") or "S/N"
                    nom_zona = cand_clean_z
                    heuristica_aplicada = True

        # Inversión Via/Zona Checker y Reasignación Semántica Cruzada
        if nom_via and nom_zona:
            v_as_via = CatalogMatcher.match_physical_via(nom_via)
            v_as_zona = CatalogMatcher.match_physical_zona(nom_via)
            z_as_via = CatalogMatcher.match_physical_via(nom_zona)
            z_as_zona = CatalogMatcher.match_physical_zona(nom_zona)

            # Blindaje contra falsas inversiones: Si ambos tienen prefijos tipográficos explícitos
            # (ej. "AV. SANTA VICTORIA" y "PP.JJ. BUENOS AIRES"), NUNCA invertir.
            raw_upper = raw_text.upper()
            via_has_via_prefix = bool(
                re.match(r"^(?:AV\.?|AVENIDA|CA\.?|CALLE|JR\.?|JIRON|PSJ\.?|PASAJE|PROL\.?|PROLONGACION|MALECON|ALAMEDA)\b", nom_via, re.IGNORECASE)
                or re.search(rf"\b(?:AV\.?|AVENIDA|CA\.?|CALLE|JR\.?|JIRON|PSJ\.?|PASAJE|PROL\.?)\s+{re.escape(nom_via[:10])}", raw_upper)
            )
            zona_has_zone_prefix = bool(
                re.match(r"^(?:URB\.?|URBANIZACION|PJ\.?|PP\.?JJ\.?|PUEBLO\s+JOVEN|A\.?H\.?|ASENTAMIENTO\s+HUMANO|CASERIO|FUNDO|COOP\.?|COOPERATIVA|SECTOR|ETAPA)\b", nom_zona, re.IGNORECASE)
                or re.search(rf"\b(?:URB\.?|PJ\.?|PP\.?JJ\.?|PUEBLO\s+JOVEN|A\.?H\.?|ASENTAMIENTO\s+HUMANO|CASERIO|FUNDO|COOP\.?)\s+{re.escape(nom_zona[:10])}", raw_upper)
            )

            can_swap = not (via_has_via_prefix and zona_has_zone_prefix)

            # Caso 1: Inversión Semántica de Entidades de Doble Rol
            # Si nom_via corresponde a una zona oficial (ej. DIEGO FERRE, JOSE OLAYA, REMIGIO SILVA, SANTA VICTORIA)
            # y nom_zona corresponde EXCLUSIVAMENTE a una vía oficial (ej. BAQUIJANO, MANUEL ARTEAGA, CERVANTES)
            # y nom_via no tiene prefijo explícito de vía (CALLE, AV), los roles fueron invertidos:
            if can_swap and v_as_zona and z_as_via and not z_as_zona and not via_has_via_prefix:
                nom_via, nom_zona = nom_zona, nom_via
                heuristica_aplicada = True
                if not num_via:
                    m_num_swap = re.search(rf"\b{re.escape(nom_via)}\s*(?:N°?\s*)?(\d+)\b", raw_text, re.IGNORECASE)
                    if m_num_swap:
                        num_via = m_num_swap.group(1).lstrip("0") or "S/N"
            # Caso 2: Cruzada de vías (Intersección en esquina asignada a zona, ej: CA. ARICA N 1028 - HEROES CIVILES N 178)
            # Solo aplica si NINGUNA de las dos entidades corresponde a una zona oficial
            elif v_as_via and z_as_via and not v_as_zona and not z_as_zona and not zona_has_zone_prefix:
                # nom_zona es en realidad una segunda vía (calle transversal / esquina)
                cross_ref = f"ESQ. {z_as_via.get('nom_via', nom_zona)}"
                if not referencia:
                    referencia = cross_ref
                elif cross_ref not in referencia:
                    referencia = f"{cross_ref} - {referencia}".strip(" -")
                nom_zona = None
                heuristica_aplicada = True
            elif can_swap:
                if not v_as_via and v_as_zona and z_as_via and not z_as_zona:
                    nom_via, nom_zona = nom_zona, nom_via
                    heuristica_aplicada = True
                elif not v_as_via and v_as_zona and not z_as_zona and not via_has_via_prefix:
                    # nom_via es definitivamente una zona oficial y nom_zona no lo es -> invertir roles
                    nom_via, nom_zona = nom_zona, nom_via
                    heuristica_aplicada = True

        # Reasignación Cruzada cuando uno de los roles está vacío o quedó en referencia
        if nom_via and not nom_zona:
            v_as_via = CatalogMatcher.match_physical_via(nom_via)
            v_as_zona = CatalogMatcher.match_physical_zona(nom_via)

            if not v_as_via and v_as_zona:
                # nom_via es indiscutiblemente una ZONA oficial (ej. "REMIGIO SILVA", "SAN NICOLAS")
                candidata_via = None

                # 1. Buscar si la vía quedó en referencia
                if referencia:
                    m_ref_num = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', referencia, re.IGNORECASE)
                    if m_ref_num and not CatalogMatcher.match_physical_via(referencia):
                        ref_cand = referencia[:m_ref_num.start()].strip(" ,.-")
                        if ref_cand:
                            if not num_via:
                                num_via = m_ref_num.group(1).lstrip("0") or "S/N"
                            candidata_via = ref_cand
                    else:
                        ref_clean = re.sub(r"\b(?:N°?|NUM°?|NRO\.?|N|\d+)\b.*$", "", referencia).strip(" ,.-")
                        if ref_clean:
                            candidata_via = ref_clean

                # 2. Si no hay en referencia, buscar en segmentos de raw_text
                if not candidata_via and ("-" in raw_text or "," in raw_text):
                    parts = [p.strip() for p in re.split(r"\s*[-–—,]\s*", raw_text) if p.strip()]
                    for p in parts:
                        m_p_num = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', p, re.IGNORECASE)
                        if m_p_num and not CatalogMatcher.match_physical_via(p):
                            p_clean = p[:m_p_num.start()].strip(" ,.-")
                            p_cand_num = m_p_num.group(1).lstrip("0") or "S/N"
                        else:
                            p_clean = re.sub(r"\b(?:N°?|NUM°?|NRO\.?|N|\d+)\b.*$", "", p).strip(" ,.-")
                            p_cand_num = None
                        if p_clean and p_clean.upper() != nom_via.upper():
                            candidata_via = p_clean
                            if not num_via and p_cand_num:
                                num_via = p_cand_num
                            break

                if candidata_via:
                    m_cand_num = re.search(r'(?:\s*N°?|\s*NUM°?|\s*NRO\.?|\s*N)?\s*(\d+)$', candidata_via, re.IGNORECASE)
                    if m_cand_num and not CatalogMatcher.match_physical_via(candidata_via):
                        if not num_via:
                            num_via = m_cand_num.group(1).lstrip("0") or "S/N"
                        candidata_via = candidata_via[:m_cand_num.start()].strip(" ,.-")

                    nom_zona = nom_via
                    nom_via = candidata_via
                    if referencia and candidata_via.upper() in referencia.upper():
                        referencia = None
                    heuristica_aplicada = True

        elif nom_zona and not nom_via:
            z_as_via = CatalogMatcher.match_physical_via(nom_zona)
            z_as_zona = CatalogMatcher.match_physical_zona(nom_zona)

            if z_as_via and not z_as_zona:
                nom_via = nom_zona
                nom_zona = None
                heuristica_aplicada = True

        # Sanitización de slote: Si contiene referencias urbanas (piso, esquina, etc.) o excede 20 chars, reubicar a referencia
        if slote:
            slote_clean = str(slote).strip()
            if len(slote_clean) > 20 or re.search(
                r"\b(?:PISO|ESQ|ESQUINA|FRENTE|ALTURA|CUADRA|BLOCK|EDIFICIO)\b",
                slote_clean,
                re.IGNORECASE,
            ):
                if not referencia:
                    referencia = slote_clean
                elif slote_clean.upper() not in referencia.upper():
                    referencia = f"{referencia} - {slote_clean}".strip(" -")
                slote = None
                heuristica_aplicada = True
            elif len(slote_clean) > 20:
                slote = slote_clean[:20].strip()
            else:
                slote = slote_clean

        # Limpieza de referencia y prevención de redundancia (preserva intactos nom_via y nom_zona)
        if referencia:
            referencia = re.sub(r"\s+", " ", referencia).strip(" ,.-").upper()
            if nom_zona and nom_zona.upper() in referencia:
                referencia = re.sub(re.escape(nom_zona), "", referencia, flags=re.IGNORECASE).strip(" ,.-")
            if nom_via and nom_via.upper() in referencia:
                referencia = re.sub(re.escape(nom_via), "", referencia, flags=re.IGNORECASE).strip(" ,.-")
            if not referencia:
                referencia = None

        # Sanitización de num_via: Aislar subunidades residuales (BLOCK, DPTO, INT, STAND, letras de puerta, etc.)
        if num_via:
            num_via_str = str(num_via).strip()
            m_sub = re.search(r"\b(BLOCK\s+[A-Z0-9\-]+|DPTO\.?\s*[A-Z0-9\-]+|INT\.?\s*[A-Z0-9\-]+|TIENDA\s*[A-Z0-9\-]+|TDA\.?\s*[A-Z0-9\-]+|STAND\s*[A-Z0-9\-]+|OF\.?\s*[A-Z0-9\-]+)\b", num_via_str, re.IGNORECASE)
            if m_sub:
                sub_val = m_sub.group(1).strip()
                if not slote:
                    slote = sub_val
                elif sub_val.upper() not in slote.upper():
                    slote = f"{slote} - {sub_val}"
                num_via_str = re.sub(re.escape(sub_val), "", num_via_str, flags=re.IGNORECASE).strip(" -/,.")

            # Detectar sufijo de letra de puerta (ej. '125-A', '125 A')
            m_letter = re.search(r"^(\d+)\s*[-/]?\s*([A-Za-z])$", num_via_str)
            if m_letter:
                num_via = m_letter.group(1).lstrip("0") or "S/N"
                letter_val = m_letter.group(2).upper()
                if not slote:
                    slote = letter_val
                elif letter_val not in slote.upper():
                    slote = f"{slote} - {letter_val}"
            else:
                m_digits = re.search(r"\b(\d+)\b", num_via_str)
                if m_digits and not re.match(r"^S/N$", num_via_str, re.IGNORECASE):
                    num_via = m_digits.group(1).lstrip("0") or "S/N"
                elif re.search(r"\bS/N\b", num_via_str, re.IGNORECASE):
                    num_via = "S/N"
                else:
                    num_via = None

        # Si no existe una vía identificada, num_via no corresponde
        if not nom_via or not nom_via.strip():
            num_via = None

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

        # 8a. Primero homologar zona para obtener el sector urbano
        zona_detectada_en_texto = bool(nom_zona and nom_zona.strip())
        matched_zona = (
            CatalogMatcher.match_physical_zona(
                text=nom_zona,
                tipo_zona_hint=id_tipo_zona,
                raw_text=raw_text,
                ollama_service=self.ollama,
            )
            if zona_detectada_en_texto
            else None
        )

        zona_sector = matched_zona.get("sector") if matched_zona else None

        # 8b. Homologar vía usando el sector de la zona para desambiguar vías homónimas
        via_detectada_en_texto = bool(nom_via and nom_via.strip())
        matched_via = (
            CatalogMatcher.match_physical_via(
                text=nom_via,
                tipo_via_hint=id_tipo_via,
                raw_text=raw_text,
                ollama_service=self.ollama,
                sector_hint=zona_sector,
            )
            if via_detectada_en_texto
            else None
        )

        observaciones = []

        # Construcción relacional V2 de Vías
        vias_result = []
        is_explicit_corner = bool(
            (extraction and getattr(extraction, "es_esquina", False))
            or re.search(r"\b(?:ESQ(?:UINA)?|CON|\bY\b)\b", raw_text, re.IGNORECASE)
        )
        if extraction and extraction.vias and len(extraction.vias) > 1:
            for ev in extraction.vias:
                ev_matched = CatalogMatcher.match_physical_via(ev.nombre)
                if ev_matched:
                    vias_result.append({
                        "via_id": ev_matched["id"],
                        "divi_numero": ev.numero or num_via or "S/N",
                        "divi_orden": ev.orden,
                        "via_nombre": ev_matched["nom_via"],
                        "tipo_via": ev_matched.get("id_tipo_via") or id_tipo_via,
                    })
            if vias_result:
                matched_via = {"id": vias_result[0]["via_id"], "nom_via": vias_result[0]["via_nombre"], "id_tipo_via": vias_result[0]["tipo_via"]}
                two_vias_conflict = None

        if not vias_result and two_vias_conflict and is_explicit_corner:
            # Evaluar si corresponde a esquina / intersección oficial
            m_v1_c = CatalogMatcher.match_physical_via(two_vias_conflict[0])
            m_v2_c = CatalogMatcher.match_physical_via(two_vias_conflict[1])
            if m_v1_c and m_v2_c:
                vias_result.append({
                    "via_id": m_v1_c["id"],
                    "divi_numero": num_via or "S/N",
                    "divi_orden": 1,
                    "via_nombre": m_v1_c["nom_via"],
                    "tipo_via": m_v1_c.get("id_tipo_via") or id_tipo_via,
                })
                vias_result.append({
                    "via_id": m_v2_c["id"],
                    "divi_numero": "S/N",
                    "divi_orden": 2,
                    "via_nombre": m_v2_c["nom_via"],
                    "tipo_via": m_v2_c.get("id_tipo_via"),
                })
                matched_via = m_v1_c
                two_vias_conflict = None

        if not vias_result and matched_via:
            vias_result.append({
                "via_id": matched_via["id"],
                "divi_numero": num_via or "S/N",
                "divi_orden": 1,
                "via_nombre": matched_via["nom_via"],
                "tipo_via": matched_via.get("id_tipo_via") or id_tipo_via,
            })

        # Construcción relacional V2 de Componentes
        componentes_result = []
        if extraction and extraction.componentes:
            for c in extraction.componentes:
                mc = CatalogMatcher.match_componente(c.nombre)
                if mc:
                    componentes_result.append({
                        "codi_id": mc[0],
                        "codi_nombre": mc[1],
                        "diti_nombre": str(c.valor).strip(),
                    })
        if manzana and not any(cr["codi_nombre"] == "MANZANA" for cr in componentes_result):
            componentes_result.append({"codi_id": 1, "codi_nombre": "MANZANA", "diti_nombre": str(manzana).strip()})
        if lote and not any(cr["codi_nombre"] == "LOTE" for cr in componentes_result):
            componentes_result.append({"codi_id": 2, "codi_nombre": "LOTE", "diti_nombre": str(lote).strip()})

        # Construcción relacional V2 de Módulos (Interiores, Dpto, Puerta, Stand, Block, etc.)
        modulos_result = []
        if extraction and extraction.modulos:
            for m in extraction.modulos:
                mm = CatalogMatcher.match_tipo_modulo(m.tipo_modulo)
                if mm:
                    modulos_result.append({
                        "timo_id": mm[0],
                        "timo_nombre": mm[1],
                        "ditm_nombre": str(m.valor).strip(),
                    })
        if not modulos_result:
            source_mod = f"{slote or ''} {referencia or ''}"
            m_sl = re.search(r"\b(INT(?:ERIOR)?|DPTO|DEP|PUERTA|PTA|STAND|TIENDA|TDA|BLOCK|BLQ|OFICINA|OF)\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)", source_mod, re.IGNORECASE)
            if m_sl:
                tname = m_sl.group(1).upper()
                mval = m_sl.group(2).strip()
                mm = CatalogMatcher.match_tipo_modulo(tname)
                if mm:
                    modulos_result.append({"timo_id": mm[0], "timo_nombre": mm[1], "ditm_nombre": mval})
            elif slote:
                modulos_result.append({"timo_id": 1, "timo_nombre": "INTERIOR", "ditm_nombre": str(slote).strip()})

        # Sanitización de Referencia: estrictamente hitos espaciales y comerciales
        clean_referencia = None
        if referencia:
            clean_referencia = str(referencia).strip()
            # Eliminar pisos y niveles
            clean_referencia = re.sub(
                r"\b(?:PISO\s*\d+|\d+\s*PISO)\b",
                "",
                clean_referencia,
                flags=re.IGNORECASE,
            )
            # Eliminar menciones de módulos o interiores (STAND, TIENDA, INT, DPTO, OFICINA, PUERTA, etc.)
            clean_referencia = re.sub(
                r"\b(?:STAND|TIENDA|TDA|LOCAL|INT(?:ERIOR)?|DEP(?:TO|ARTAMENTO)?|OF(?:ICINA)?|PTA|PUERTA|BLOCK|BLQ|PUESTO)\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)?",
                "",
                clean_referencia,
                flags=re.IGNORECASE,
            )
            # Eliminar menciones de componentes catastrales (MZ, LT, LOTE, etc.)
            clean_referencia = re.sub(
                r"\b(?:MZ|MZA|MANZANA|LT|LOTE|SUBLOTE|S_LOTE)\b\.?\s*[:\-]?\s*([A-Z0-9\-]+)?",
                "",
                clean_referencia,
                flags=re.IGNORECASE,
            )
            # Remover residuos de puntuación y espacios
            clean_referencia = re.sub(r"\s+", " ", clean_referencia).strip(" -/,.:;")
            if not clean_referencia:
                clean_referencia = None

        if two_vias_conflict:
            observaciones.append(
                f"Conflicto de vías: Se detectaron dos vías oficiales juntas ('{two_vias_conflict[0]}' y '{two_vias_conflict[1]}'). "
                "Verifique si corresponde a una intersección o confirme cuál es la vía principal."
            )

        if via_detectada_en_texto and not matched_via:
            det_via = f"Vía '{nom_via}' no figura en el catálogo maestro de vías de Chiclayo."
            if matched_zona:
                det_via += f" (Zona oficial confirmada: '{matched_zona['nom_zona']}' - ID {matched_zona['id']}). Verifique si la vía pertenece a otra jurisdicción o tiene denominación alternativa."
            observaciones.append(det_via)

        if zona_detectada_en_texto and not matched_zona:
            det_zona = f"Zona/Habilitación '{nom_zona}' no figura en el catálogo maestro de zonas de Chiclayo."
            if matched_via:
                det_zona += f" (Vía oficial confirmada: '{matched_via['nom_via']}' - ID {matched_via['id']})."
            observaciones.append(det_zona)

        if not via_detectada_en_texto and not zona_detectada_en_texto:
            observaciones.append("DIRECCIÓN NO RECONOCIDA: No se logró identificar vía ni habilitación urbana válida en el texto.")

        # Guardrail de Integridad Estricta:
        # Una dirección solo puede carecer de vía si es un predio catastral sin calle
        if not matched_via:
            tiene_predio_mz_lt = bool(matched_zona and (manzana or lote))
            if not tiene_predio_mz_lt or num_via:
                if not via_detectada_en_texto:
                    observaciones.append(
                        "Vía pública no identificada en el catálogo maestro de Chiclayo para la numeración municipal o predio registrado."
                    )

        # Integrar notas de la IA o advertencias específicas en el texto
        ai_notes = extraction.observaciones if extraction and extraction.observaciones else None
        if ai_notes and ai_notes not in observaciones and not two_vias_conflict:
            if len(ai_notes.strip()) > 5:
                observaciones.append(f"Nota IA: {ai_notes.strip()}")

        if "NO USAR LA VIA PUBLICA" in raw_text.upper():
            observaciones.append("Advertencia registrada: Restricción de uso de vía pública en la licencia.")

        if observaciones:
            # Caso observado: Se nullifican relaciones para consistencia
            return DireccionDestino(
                id_licencia=record.id_licencia,
                dire_id=None,
                zona_id=None,
                dire_referencia=None,
                vias=[],
                componentes=[],
                modulos=[],
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
                dire_id=None,
                zona_id=matched_zona["id"] if matched_zona else None,
                dire_referencia=clean_referencia,
                vias=vias_result,
                componentes=componentes_result,
                modulos=modulos_result,
                manzana=manzana,
                lote=lote,
                slote=slote,
                referencia=referencia or clean_referencia,
                es_procesado=True,
                observacion=None,
                tipo_via=matched_via.get("id_tipo_via") or id_tipo_via if matched_via else None,
                nom_via=matched_via["nom_via"] if matched_via else None,
                num_via=num_via,
                tipo_zona=matched_zona.get("id_tipo_zona") or id_tipo_zona if matched_zona else None,
                nom_zona=matched_zona["nom_zona"] if matched_zona else None,
                metodo_normalizacion=metodo,
            )
