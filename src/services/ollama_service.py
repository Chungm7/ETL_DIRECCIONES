"""Servicio de conexión y cliente para modelo de Inteligencia Artificial local con Ollama."""

import json
import logging
from typing import Any, Dict, List, Optional

import httpx
try:
    import ollama
    OLLAMA_LIB_AVAILABLE = True
except ImportError:
    OLLAMA_LIB_AVAILABLE = False

from src.config.settings import OllamaSettings, get_settings
from src.models.llm_schemas import OllamaAddressExtraction, OllamaCandidateDisambiguation
from src.utils.prompts import (
    SYSTEM_PROMPT_ADDRESS_PARSER,
    build_user_prompt_for_address,
    get_system_prompt_address_parser,
)

logger = logging.getLogger("etl_mpch.ollama_service")



class OllamaService:
    """Cliente para la conexión y consulta del modelo LLM local alojado en Ollama."""

    def __init__(self, settings: Optional[OllamaSettings] = None):
        self.settings = settings or get_settings().ollama
        self.base_url = self.settings.base_url.rstrip("/")
        self.model_name = self.settings.model
        self.timeout = self.settings.timeout
        self.temperature = self.settings.temperature

        # Inicialización del cliente oficial de Ollama si está disponible
        if OLLAMA_LIB_AVAILABLE:
            self._client = ollama.Client(host=self.base_url, timeout=float(self.timeout))
        else:
            self._client = None
            logger.warning(
                "Librería 'ollama' no detectada en el entorno. Usando cliente HTTP directo (httpx)."
            )

    def check_connection(self) -> Dict[str, Any]:
        """Verifica la conectividad con el servidor local de Ollama y comprueba si el modelo existe.

        Retorna:
            dict con el estado de conexión, modelos instalados y confirmación del modelo objetivo.
        """
        result: Dict[str, Any] = {
            "connected": False,
            "base_url": self.base_url,
            "target_model": self.model_name,
            "model_available": False,
            "available_models": [],
            "message": "",
        }

        try:
            # Petición al endpoint /api/tags de Ollama
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/api/tags")

            if response.status_code == 200:
                data = response.json()
                models = [m.get("name") for m in data.get("models", [])]
                result["connected"] = True
                result["available_models"] = models

                # Comprobación de existencia del modelo (coincidencia con o sin tag :latest)
                model_match = any(
                    m == self.model_name
                    or m.startswith(f"{self.model_name}:")
                    or self.model_name.startswith(f"{m}:")
                    for m in models
                )
                result["model_available"] = model_match

                if model_match:
                    result["message"] = f"Conexión exitosa con Ollama. Modelo '{self.model_name}' disponible."
                    logger.info(result["message"])
                else:
                    result["message"] = (
                        f"Conectado a Ollama, pero el modelo '{self.model_name}' NO está descargado. "
                        f"Modelos disponibles: {models}. "
                        f"Ejecuta en tu terminal: 'ollama run {self.model_name}'"
                    )
                    logger.warning(result["message"])
            else:
                result["message"] = f"Servidor Ollama respondió con código HTTP {response.status_code}"
                logger.error(result["message"])

        except httpx.ConnectError:
            result["message"] = (
                f"No se pudo conectar al servidor Ollama en {self.base_url}. "
                "Asegúrate de que Ollama esté ejecutándose externamente (ej. 'ollama serve')."
            )
            logger.error(result["message"])
        except Exception as e:
            result["message"] = f"Error al verificar conexión con Ollama: {str(e)}"
            logger.exception(result["message"])

        return result

    def list_available_models(self) -> List[str]:
        """Lista todos los nombres de modelos presentes en la instancia de Ollama."""
        status = self.check_connection()
        return status.get("available_models", [])

    def test_model_inference(self, sample_address: str = "CALLE BALTA N° 520 - CHICLAYO") -> Dict[str, Any]:
        """Realiza una prueba en vivo de inferencia con el modelo configurado.
        
        Comprueba no solo la disponibilidad HTTP del servidor sino también que el modelo
        esté levantado en memoria, activo y respondiendo con un JSON estructurado válido.

        Args:
            sample_address: Dirección de prueba para realizar la inferencia.

        Returns:
            Diccionario detallado:
            {
                "connected": bool,
                "model_available": bool,
                "model_ready": bool,
                "latency_seconds": float,
                "extracted": Optional[OllamaAddressExtraction],
                "error": Optional[str],
                "message": str
            }
        """
        import time

        result: Dict[str, Any] = {
            "connected": False,
            "model_available": False,
            "model_ready": False,
            "latency_seconds": 0.0,
            "extracted": None,
            "error": None,
            "message": "",
        }

        # 1. Comprobar primero conexión básica y catálogo de modelos
        conn_status = self.check_connection()
        result["connected"] = conn_status["connected"]
        result["model_available"] = conn_status["model_available"]

        if not result["connected"]:
            result["error"] = conn_status["message"]
            result["message"] = f"Servidor Ollama no disponible en {self.base_url}."
            return result

        if not result["model_available"]:
            result["error"] = f"El modelo '{self.model_name}' no existe en Ollama."
            result["message"] = f"Servidor online, pero el modelo '{self.model_name}' no está descargado."
            return result

        # 2. Prueba en vivo de inferencia con medición de latencia
        start_time = time.perf_counter()
        try:
            extraction = self.parse_address_with_ai(sample_address)
            elapsed = time.perf_counter() - start_time
            result["latency_seconds"] = round(elapsed, 2)

            if extraction is not None:
                result["model_ready"] = True
                result["extracted"] = extraction
                result["message"] = (
                    f"Modelo '{self.model_name}' OPERATIVO y respondiendo correctamente "
                    f"(Latencia: {result['latency_seconds']}s)."
                )
                logger.info(result["message"])
            else:
                result["model_ready"] = False
                result["error"] = "El modelo no retornó una extracción estructurada válida."
                result["message"] = f"El servidor respondió, pero el modelo '{self.model_name}' no pudo procesar la inferencia."
                logger.warning(result["message"])

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            result["latency_seconds"] = round(elapsed, 2)
            result["model_ready"] = False
            result["error"] = str(e)
            result["message"] = f"Error en inferencia de prueba del modelo '{self.model_name}': {str(e)}"
            logger.error(result["message"])

        return result

    def parse_address_with_ai(self, address_text: str) -> Optional[OllamaAddressExtraction]:
        """Envía una dirección no estructurada a Ollama para su extracción semántica en formato JSON.

        Args:
            address_text: Cadena cruda de la dirección (ej. 'URB. LOS PRECURSORES CA. MOISES R. VALIENTE N 349').

        Returns:
            Instancia de OllamaAddressExtraction con los campos normalizados o None en caso de fallo.
        """
        if not address_text or not address_text.strip():
            logger.debug("Dirección vacía recibida en parse_address_with_ai.")
            return None

        prompt_user = build_user_prompt_for_address(address_text)

        try:
            raw_response_content = self._call_ollama_chat(prompt_user)
            if not raw_response_content:
                return None

            # Deserializar y validar contra el esquema Pydantic
            parsed_json = json.loads(raw_response_content)
            return OllamaAddressExtraction(**parsed_json)

        except json.JSONDecodeError as jde:
            logger.warning(
                "Ollama no retornó un JSON válido para la dirección: '%s'. Error: %s",
                address_text,
                jde,
            )
            return None
        except Exception as ex:
            logger.error(
                "Error en inferencia de Ollama para '%s': %s", address_text, ex
            )
            return None

    def disambiguate_candidate(
        self,
        raw_text: str,
        entity_type: str,
        search_term: str,
        candidates: List[Dict[str, Any]],
    ) -> Optional[OllamaCandidateDisambiguation]:
        """Evalúa semánticamente mediante Ollama una lista de candidatos oficiales de Chiclayo
        frente a una dirección cruda con un término mal redactado o variante
        (etapas, omisión de iniciales, abreviaturas, etc.).
        """
        if not candidates:
            return None

        cands_formatted = "\n".join(
            f"{i+1}. ID {c['id']}: {c['nom_via'] if 'nom_via' in c else c.get('nom_zona', '')}"
            for i, c in enumerate(candidates)
        )

        system_prompt = (
            "Eres un experto normalizador catastral de la Municipalidad Provincial de Chiclayo (Perú).\n"
            "Tu objetivo es determinar si una dirección con redacción informal, abreviada o variante\n"
            "(omisión de iniciales intermedias, redacción de etapas como 'Etapa 1' = 'Primera Etapa', etc.)\n"
            f"corresponde inequívocamente a alguno de los candidatos oficiales de {entity_type} en Chiclayo.\n"
            "Si la dirección se refiere inequívocamente a uno de los candidatos oficiales, selecciona su ID y nombre oficial exacto.\n"
            "Si NO corresponde a ninguno de los candidatos oficiales de Chiclayo (es una vía o zona distinta, o inventada), responde con id_seleccionado: null."
        )

        user_prompt = (
            f'Dirección original cruda: "{raw_text}"\n'
            f'Término buscado ({entity_type}): "{search_term}"\n\n'
            f"Candidatos oficiales disponibles en Chiclayo:\n{cands_formatted}\n\n"
            "Responde ÚNICAMENTE un objeto JSON válido con este formato:\n"
            '{\n  "id_seleccionado": <número_id o null>,\n  "nombre_oficial": <string_nombre o null>,\n  "motivo": <string_explicación>\n}'
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw_response = self._call_ollama_messages(messages, temperature=0.0)
            if not raw_response:
                return None
            parsed_json = json.loads(raw_response)
            return OllamaCandidateDisambiguation(**parsed_json)
        except Exception as ex:
            logger.warning("Error en desambiguación semántica con Ollama para '%s': %s", search_term, ex)
            return None

    def _call_ollama_chat(self, user_prompt: str) -> Optional[str]:
        """Ejecuta la llamada a la API de Chat de Ollama forzando salida JSON."""
        messages = [
            {"role": "system", "content": get_system_prompt_address_parser()},
            {"role": "user", "content": user_prompt},
        ]
        return self._call_ollama_messages(messages, temperature=self.temperature)

    def _call_ollama_messages(self, messages: List[Dict[str, str]], temperature: float = 0.0) -> Optional[str]:
        """Ejecuta una llamada estructurada de chat con mensajes arbitrarios hacia Ollama."""
        call_options = {
            "temperature": temperature,
            "num_ctx": getattr(self.settings, "num_ctx", 16384),
        }

        # Prioridad 1: Cliente oficial si está disponible
        if self._client is not None:
            try:
                response = self._client.chat(
                    model=self.model_name,
                    messages=messages,
                    format="json",
                    options=call_options,
                )
                return response.get("message", {}).get("content")
            except Exception as ex_client:
                logger.debug("Fallo cliente ollama, intentando fallback httpx: %s", ex_client)

        # Prioridad 2: Solicitud HTTP directa mediante httpx
        with httpx.Client(timeout=float(self.timeout)) as client:
            payload = {
                "model": self.model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": call_options,
            }
            res = client.post(f"{self.base_url}/api/chat", json=payload)
            res.raise_for_status()
            data = res.json()
            return data.get("message", {}).get("content")
