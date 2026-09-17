"""Pruebas unitarias para el servicio de conexión con Ollama."""

import unittest
from unittest.mock import MagicMock, patch

from src.config.settings import OllamaSettings
from src.services.ollama_service import OllamaService
from src.models.llm_schemas import OllamaAddressExtraction


class TestOllamaService(unittest.TestCase):
    """Pruebas para validar la inicialización y el manejo de respuestas del servicio Ollama."""

    def setUp(self):
        self.settings = OllamaSettings(
            base_url="http://localhost:11434",
            model="llama3",
            timeout=10,
            temperature=0.0,
        )
        self.service = OllamaService(self.settings)
        # Forzar model_name en el servicio para pruebas unitarias deterministas
        self.service.model_name = "llama3"

    @patch("httpx.Client.get")
    def test_check_connection_success(self, mock_get):
        """Valida que check_connection reconozca cuando el servidor y el modelo existen."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:latest"},
                {"name": "mistral:latest"},
            ]
        }
        mock_get.return_value = mock_response

        status = self.service.check_connection()
        self.assertTrue(status["connected"])
        self.assertTrue(status["model_available"])
        self.assertIn("llama3:latest", status["available_models"])

    @patch.object(OllamaService, "_call_ollama_chat")
    def test_parse_address_with_ai(self, mock_chat):
        """Valida la deserialización correcta a OllamaAddressExtraction."""
        mock_chat.return_value = """{
            "tipo_via_detectado": "CALLE",
            "nom_via": "MOISES R. VALIENTE",
            "num_via": "349",
            "tipo_zona_detectada": "URBANIZACION",
            "nom_zona": "LOS PRECURSORES",
            "manzana": null,
            "lote": null,
            "slote": null,
            "confianza": 0.98,
            "observaciones": null
        }"""

        result = self.service.parse_address_with_ai("URB. LOS PRECURSORES CA. MOISES R. VALIENTE N 349")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, OllamaAddressExtraction)
        self.assertEqual(result.tipo_via_detectado, "CALLE")
        self.assertEqual(result.nom_via, "MOISES R. VALIENTE")
        self.assertEqual(result.num_via, "349")
        self.assertEqual(result.nom_zona, "LOS PRECURSORES")

    @patch.object(OllamaService, "check_connection")
    @patch.object(OllamaService, "parse_address_with_ai")
    def test_model_inference_success(self, mock_parse, mock_conn):
        """Valida que test_model_inference reporte éxito y latencia cuando el modelo responde."""
        mock_conn.return_value = {
            "connected": True,
            "model_available": True,
            "available_models": ["llama3:latest"],
            "message": "OK",
        }
        mock_parse.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="BALTA",
            num_via="520",
            confianza=0.95,
        )

        res = self.service.test_model_inference("CALLE BALTA N° 520")
        self.assertTrue(res["connected"])
        self.assertTrue(res["model_available"])
        self.assertTrue(res["model_ready"])
        self.assertGreaterEqual(res["latency_seconds"], 0.0)
        self.assertIsNotNone(res["extracted"])
        self.assertEqual(res["extracted"].nom_via, "BALTA")

    @patch.object(OllamaService, "check_connection")
    def test_model_inference_offline(self, mock_conn):
        """Valida que test_model_inference capture la desconexión del servidor."""
        mock_conn.return_value = {
            "connected": False,
            "model_available": False,
            "available_models": [],
            "message": "No se pudo conectar al servidor Ollama",
        }

        res = self.service.test_model_inference("CALLE BALTA N° 520")
        self.assertFalse(res["connected"])
        self.assertFalse(res["model_ready"])
        self.assertIn("No se pudo conectar", res["error"])

    @patch.object(OllamaService, "check_connection")
    def test_model_inference_model_not_downloaded(self, mock_conn):
        """Valida cuando el servidor está en línea pero el modelo no existe."""
        mock_conn.return_value = {
            "connected": True,
            "model_available": False,
            "available_models": ["mistral:latest"],
            "message": "Modelo no disponible",
        }

        res = self.service.test_model_inference("CALLE BALTA N° 520")
        self.assertTrue(res["connected"])
        self.assertFalse(res["model_available"])
        self.assertFalse(res["model_ready"])
        self.assertIn("no existe en Ollama", res["error"])


if __name__ == "__main__":
    unittest.main()

