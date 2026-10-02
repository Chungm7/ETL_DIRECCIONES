"""Pruebas unitarias para la arquitectura de dos modelos (Extractor + Juez / Observador)
y concurrencia segura con Row-Level Locking (SELECT ... FOR UPDATE SKIP LOCKED).
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.models.direccion_origen import DireccionOrigen
from src.models.llm_schemas import OllamaAddressExtraction
from src.transformers.ai_parser import AIAddressParser
from src.services.ollama_service import OllamaService
from src.extractors.db_extractor import DatabaseExtractor
from src.ui.server import app, state


@pytest.fixture(autouse=True)
def reset_server_state():
    """Limpia el estado dinámico del servidor antes y después de cada test."""
    state.dynamic_ollama_service = None
    state.dynamic_ollama_settings = None
    state.active_judge_model = None
    state.active_model = None
    yield
    state.dynamic_ollama_service = None
    state.dynamic_ollama_settings = None
    state.active_judge_model = None
    state.active_model = None


@pytest.fixture
def client():
    return TestClient(app)


def test_two_model_sequential_flow_valid_address_never_calls_judge():
    """Garantiza la protección secuencial de hardware:
    Si el Modelo 1 extrae y el Paso 3 (Validación Lógica) aprueba la dirección contra
    los catálogos oficiales de Chiclayo, el Modelo 2 (El Juez) NUNCA debe ser invocado.
    """
    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.model_name = "patroclo-artesano-7b:latest"
    mock_ollama.judge_model_name = "mistral:latest"

    # Simular extracción perfecta del Modelo 1
    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
        tipo_via_detectado="CALLE",
        nom_via="SAN JOSE",
        num_via="456",
        tipo_zona_detectada="URBANIZACION",
        nom_zona="SANTA VICTORIA",
        manzana=None,
        lote=None,
        referencia=None,
    )

    parser = AIAddressParser(ollama_service=mock_ollama)
    record = DireccionOrigen(id_licencia=101, emp_direccion="CALLE SAN JOSE 456 URB SANTA VICTORIA CHICLAYO")
    dest = parser.parse(record)

    # La dirección debe ser normalizada con éxito
    assert dest.es_procesado is True
    assert len(dest.vias) > 0
    assert dest.zona_id is not None

    # ¡Protección estricta de hardware! El Modelo 2 jamás se invoca si el registro es válido
    mock_ollama.judge_address_observation.assert_not_called()


def test_two_model_sequential_flow_incomplete_address_calls_judge_sequentially():
    """Garantiza que ante direcciones incompletas (ej. falta de número y predio),
    el Paso 3 rechaza y se invoca secuencialmente al Modelo 2 (El Juez) con la rúbrica.
    """
    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.model_name = "patroclo-artesano-7b:latest"
    mock_ollama.judge_model_name = "llama3:latest"

    # Simular extracción del Modelo 1 que detecta vía pero sin numeración ni predio
    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
        tipo_via_detectado="CALLE",
        nom_via="JOSE BALTA",
        num_via=None,
        tipo_zona_detectada=None,
        nom_zona=None,
        manzana=None,
        lote=None,
        referencia=None,
    )

    # El Modelo 2 emite un dictamen normado
    veredicto_esperado = "Dirección incompleta: Carece de numeración municipal o lote catastral en la vía Balta."
    mock_ollama.judge_address_observation.return_value = veredicto_esperado

    parser = AIAddressParser(ollama_service=mock_ollama)
    record = DireccionOrigen(id_licencia=202, emp_direccion="CALLE JOSE BALTA - CHICLAYO")
    dest = parser.parse(record)

    # Registro observado
    assert dest.es_procesado is False
    # El dictamen del Juez debe ser registrado en la observación
    assert dest.observacion == veredicto_esperado

    # El Juez debe ser invocado exactamente una vez
    mock_ollama.judge_address_observation.assert_called_once()
    call_kwargs = mock_ollama.judge_address_observation.call_args[1]
    assert "CALLE JOSE BALTA - CHICLAYO" in call_kwargs["raw_text"]
    assert "validation_facts" in call_kwargs
    assert any("Dirección incompleta" in fact for fact in call_kwargs["validation_facts"])


def test_two_model_sequential_flow_nonexistent_street_calls_judge():
    """Verifica que una vía inexistente en Chiclayo sea rechazada en el Paso 3
    y evaluada por el Juez para dictaminar su observación oficial.
    """
    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.model_name = "patroclo-artesano-7b:latest"
    mock_ollama.judge_model_name = "llama3:latest"

    mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
        tipo_via_detectado="AVENIDA",
        nom_via="KRYPTON FANTASMA INEXISTENTE",
        num_via="999",
        tipo_zona_detectada=None,
        nom_zona=None,
        manzana=None,
        lote=None,
        referencia=None,
    )

    dictamen_juez = "Dirección incoherente: La vía 'KRYPTON FANTASMA INEXISTENTE' no pertenece a la nomenclatura oficial de Chiclayo."
    mock_ollama.judge_address_observation.return_value = dictamen_juez

    parser = AIAddressParser(ollama_service=mock_ollama)
    record = DireccionOrigen(id_licencia=303, emp_direccion="AVENIDA KRYPTON FANTASMA INEXISTENTE 999")
    dest = parser.parse(record)

    assert dest.es_procesado is False
    assert dest.observacion == dictamen_juez
    mock_ollama.judge_address_observation.assert_called_once()


def test_api_connect_ai_judge_success(client):
    """Verifica el endpoint /api/connect-ai-judge con un modelo juez disponible."""
    with patch("src.ui.server.OllamaService") as mock_ollama_cls:
        mock_instance = mock_ollama_cls.return_value
        mock_instance.check_judge_connection.return_value = {
            "connected": True,
            "judge_model": "llama3:latest",
            "model_available": True,
            "available_models": ["llama3:latest", "patroclo-artesano-7b:latest"],
            "message": "Modelo Juez verificado",
        }

        response = client.post(
            "/api/connect-ai-judge",
            json={
                "host": "localhost",
                "port": 11434,
                "judge_model": "llama3:latest",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["judge_model"] == "llama3:latest"
        assert state.active_judge_model == "llama3:latest"


def test_api_connect_ai_judge_unavailable_model(client):
    """Verifica que /api/connect-ai-judge falle con 400 si el modelo juez no está instalado en Ollama."""
    with patch("src.ui.server.OllamaService") as mock_ollama_cls:
        mock_instance = mock_ollama_cls.return_value
        mock_instance.check_judge_connection.return_value = {
            "connected": True,
            "judge_model": "modelo_que_no_existe:latest",
            "model_available": False,
            "available_models": ["patroclo-artesano-7b:latest"],
            "message": "No disponible",
        }

        response = client.post(
            "/api/connect-ai-judge",
            json={
                "host": "localhost",
                "port": 11434,
                "judge_model": "modelo_que_no_existe:latest",
            },
        )
        assert response.status_code == 400
        assert "no está disponible" in response.json()["detail"]


def test_api_test_ai_judge_endpoint(client):
    """Verifica que /api/test-ai-judge realice la prueba en vivo del Juez y retorne su dictamen."""
    with patch("src.ui.server.OllamaService") as mock_ollama_cls:
        mock_instance = mock_ollama_cls.return_value
        mock_instance.judge_model_name = "llama3:latest"
        mock_instance.check_judge_connection.return_value = {
            "connected": True,
            "judge_model": "llama3:latest",
            "model_available": True,
            "available_models": ["llama3:latest"],
        }
        mock_instance.test_judge_inference.return_value = {
            "connected": True,
            "model_ready": True,
            "observation": "Dirección incompleta: Carece de numeración municipal o lote catastral.",
            "latency_seconds": 0.45,
            "message": "Dictamen emitido",
        }

        response = client.post("/api/test-ai-judge?sample_address=CALLE+BALTA+-+CHICLAYO")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["judge_model"] == "llama3:latest"
        assert "Dirección incompleta" in data["observation"]


def test_row_level_locking_postgresql():
    """Verifica que DatabaseExtractor aplique row-level locking (SELECT ... FOR UPDATE SKIP LOCKED)
    en PostgreSQL para garantizar que múltiples instancias trabajadoras (workers) nunca colisionen.
    """
    mock_db = MagicMock()
    mock_db._engine.dialect.name = "postgresql"

    mock_session = MagicMock()
    mock_db.get_session.return_value.__enter__.return_value = mock_session
    mock_session.execute.return_value.fetchall.return_value = []

    extractor = DatabaseExtractor(
        db_service=mock_db,
        schema="public",
        table="direcciones_test",
        id_col="id",
        dir_col="direccion",
    )

    # Ejecutar con lock_for_update=True
    extractor.extract_batch(offset=0, limit=50, filter_mode="pending", lock_for_update=True)

    # Verificar que la sentencia SQL ejecutada contenga "FOR UPDATE SKIP LOCKED"
    executed_call = mock_session.execute.call_args
    sql_text = str(executed_call[0][0])
    assert "FOR UPDATE SKIP LOCKED" in sql_text


def test_fetch_next_free_record_atomic_locking():
    """Verifica el método de asignación atómica de tareas registro a registro con row-level locking."""
    mock_db = MagicMock()
    mock_db._engine.dialect.name = "postgresql"

    extractor = DatabaseExtractor(
        db_service=mock_db,
        schema="public",
        table="direcciones_test",
        id_col="id",
        dir_col="direccion",
    )

    mock_session = MagicMock()
    mock_row = MagicMock()
    mock_row.id_val = 555
    mock_row.dir_val = "AVENIDA JOSE BALTA 882"
    mock_session.execute.return_value.fetchone.return_value = mock_row

    rec = extractor.fetch_next_free_record(mock_session, filter_mode="pending")

    assert rec is not None
    assert rec.id_licencia == 555
    assert rec.emp_direccion == "AVENIDA JOSE BALTA 882"

    executed_call = mock_session.execute.call_args
    sql_text = str(executed_call[0][0])
    assert "FOR UPDATE SKIP LOCKED" in sql_text
