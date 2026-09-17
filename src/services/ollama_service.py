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
from src.models.llm_schemas import OllamaAddressExtraction
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
            self._client = ollama.Client(host=self.base_url)
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

    def _call_ollama_chat(self, user_prompt: str) -> Optional[str]:
        """Ejecuta la llamada a la API de Chat de Ollama forzando salida JSON."""
        messages = [
            {"role": "system", "content": get_system_prompt_address_parser()},
            {"role": "user", "content": user_prompt},
        ]


        # Prioridad 1: Cliente oficial si está disponible
        if self._client is not None:
            response = self._client.chat(
                model=self.model_name,
                messages=messages,
                format="json",
                options={"temperature": self.temperature},
            )
            return response.get("message", {}).get("content")

        # Prioridad 2: Solicitud HTTP directa mediante httpx
        with httpx.Client(timeout=float(self.timeout)) as client:
            payload = {
                "model": self.model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {"temperature": self.temperature},
            }
            res = client.post(f"{self.base_url}/api/chat", json=payload)
            res.raise_for_status()
            data = res.json()
            return data.get("message", {}).get("content")
