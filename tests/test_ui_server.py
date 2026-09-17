"""Pruebas unitarias para el servidor FastAPI y endpoints de la GUI del ETL MPCH."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.ui.server import app, state, ExecutionState


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_index_served(client):
    """Verifica que el archivo index.html sea servido correctamente en la raíz."""
    response = client.get("/")
    assert response.status_code == 200
    assert "MUNICIPALIDAD PROVINCIAL DE CHICLAYO" in response.text
    assert "ETL Catastral IA" in response.text


def test_api_status_endpoint(client):
    """Verifica que /api/status devuelva los componentes de salud y esquemas."""
    with patch("src.ui.server.DatabaseService") as mock_db, \
         patch("src.ui.server.OllamaService") as mock_ollama, \
         patch("src.ui.server.DatabaseExtractor") as mock_ext:

        mock_db.return_value.check_connection.return_value = {
            "connected": True,
            "schema": "public",
            "table_exists": True,
            "available_schemas": ["public", "schema_solo_tabla"],
            "message": "OK",
        }
        mock_ollama.return_value.check_connection.return_value = {
            "connected": True,
            "model": "patroclo-artesano-7b:latest",
            "model_installed": True,
            "message": "Disponible",
        }
        mock_ext.return_value.get_status_counts.return_value = {
            "total": 100,
            "pendientes": 40,
            "validos": 50,
            "observados": 10,
        }

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        assert data["db"]["connected"] is True
        assert "public" in data["available_schemas"]
        assert data["table_counts"]["total"] == 100


def test_api_schemas_endpoint(client):
    """Verifica que /api/schemas devuelva la lista de esquemas de BD."""
    with patch("src.ui.server.DatabaseService") as mock_db:
        mock_db.return_value.get_available_schemas.return_value = ["public", "catastro"]
        response = client.get("/api/schemas")
        assert response.status_code == 200
        assert response.json() == {"schemas": ["public", "catastro"]}


def test_api_counts_endpoint(client):
    """Verifica que /api/counts consulte el estado de la tabla."""
    with patch("src.ui.server.DatabaseExtractor") as mock_ext:
        mock_ext.return_value.get_status_counts.return_value = {
            "total": 500,
            "pendientes": 120,
            "validos": 350,
            "observados": 30,
        }
        response = client.get("/api/counts?schema=public&table=direcciones_locales")
        assert response.status_code == 200
        assert response.json()["total"] == 500
        assert response.json()["pendientes"] == 120


def test_api_test_ai_endpoint(client):
    """Verifica que /api/test-ai ejecute la comprobación de inferencia con Ollama."""
    with patch("src.ui.server.OllamaService") as mock_ollama:
        mock_ollama.return_value.check_connection.return_value = {"connected": True}
        mock_ollama.return_value.model_name = "patroclo-artesano-7b:latest"
        mock_ext = MagicMock()
        mock_ext.model_dump.return_value = {
            "tipo_via": "CALLE",
            "nombre_via": "SAN JOSE",
            "numero": "456",
            "tipo_zona": "URB",
            "nombre_zona": "SANTA VICTORIA",
        }
        mock_ollama.return_value.parse_address_with_ai.return_value = mock_ext

        response = client.post("/api/test-ai?sample_address=CALLE+SAN+JOSE+456")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["parsed"]["nombre_via"] == "SAN JOSE"


def test_api_stop_when_not_running(client):
    """Verifica que /api/stop responda correctamente cuando no hay pipeline activo."""
    state.is_running = False
    state.pipeline = None
    response = client.post("/api/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "NOT_RUNNING"


def test_execution_state_add_record_and_broadcast():
    """Verifica el cálculo de estadísticas y almacenamiento de registros en memoria."""
    test_state = ExecutionState()
    test_state.reset_for_run(total=10, schema="public", table="direcciones_locales")

    record_payload = {
        "index": 1,
        "total": 10,
        "id_licencia": 999,
        "raw_text": "AV BALTA 123",
        "metodo": "IA (patroclo)",
        "id_via": 10,
        "nom_via": "AVENIDA JOSE BALTA",
        "num_via": "123",
        "id_zona": None,
        "nom_zona": None,
        "manzana": None,
        "lote": None,
        "slote": None,
        "referencia": None,
        "es_procesado": True,
        "observacion": "",
        "success": True,
        "valid_count": 1,
        "observed_count": 0,
        "processed_count": 1,
        "failed_count": 0,
        "ai_records": 1,
        "hybrid_records": 0,
        "heuristic_records": 0,
    }

    test_state.add_record(record_payload)

    assert len(test_state.recent_records) == 1
    assert test_state.stats["valid"] == 1
    assert test_state.stats["processed"] == 1
    assert test_state.stats["progress_pct"] == 10.0
