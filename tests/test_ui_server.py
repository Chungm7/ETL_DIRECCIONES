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
    assert "Municipalidad Provincial de Chiclayo" in response.text
    assert "Normalización" in response.text


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


def test_run_pipeline_worker_with_limit_and_without_limit():
    """Verifica que el worker de pipeline no falle con limit int o None y llame run correctamente."""
    from src.ui.server import _run_pipeline_worker, StartPipelineRequest
    with patch("src.ui.server.DatabaseService"), \
         patch("src.ui.server.ETLPipeline") as mock_pipeline:
        mock_pipe_inst = mock_pipeline.return_value
        mock_pipe_inst.extractor.get_status_counts.return_value = {
            "total": 10,
            "pendientes": 5,
            "validos": 4,
            "observados": 1,
        }
        mock_pipe_inst.run.return_value = MagicMock(
            total_records=5,
            processed_records=5,
            valid_processed_records=4,
            observed_records=1,
            successful_records=5,
            failed_records=0,
            ai_records=5,
            hybrid_records=0,
            heuristic_records=0,
        )

        req_with_limit = StartPipelineRequest(
            schema_name="public",
            table_name="direcciones_actual",
            limit=2,
            filter_mode="pending",
        )
        _run_pipeline_worker(req_with_limit)
        mock_pipe_inst.run.assert_called_with(max_records=2, limit=2, filter_mode="pending")

        req_no_limit = StartPipelineRequest(
            schema_name="public",
            table_name="direcciones_actual",
            limit=None,
            filter_mode="pending",
        )
        _run_pipeline_worker(req_no_limit)
        mock_pipe_inst.run.assert_called_with(max_records=None, limit=None, filter_mode="pending")


def test_api_detect_models_success(client):
    """Verifica que /api/detect-models liste los modelos retornados por Ollama."""
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "patroclo-artesano-7b:latest"}, {"name": "llama3:latest"}]
        }
        mock_get.return_value = mock_resp

        response = client.post("/api/detect-models", json={"host": "localhost", "port": 11434})
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert data["count"] == 2
        assert "patroclo-artesano-7b:latest" in data["models"]


def test_api_detect_models_offline(client):
    """Verifica que /api/detect-models maneje errores de red sin caerse."""
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        response = client.post("/api/detect-models", json={"host": "127.0.0.1", "port": 9999})
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is False
        assert data["count"] == 0
        assert "No se pudo conectar" in data["message"]


def test_api_connect_ai_success(client):
    """Verifica que /api/connect-ai valide la conexión y guarde el servicio dinámico."""
    with patch("src.ui.server.OllamaService") as mock_ollama_cls:
        mock_instance = mock_ollama_cls.return_value
        mock_instance.check_connection.return_value = {
            "connected": True,
            "model_available": True,
            "available_models": ["patroclo-artesano-7b:latest"],
            "message": "Modelo disponible",
        }

        req_body = {
            "host": "localhost",
            "port": 11434,
            "model": "patroclo-artesano-7b:latest"
        }
        response = client.post("/api/connect-ai", json=req_body)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["model"] == "patroclo-artesano-7b:latest"
        assert state.dynamic_ollama_service is not None


def test_api_connect_ai_model_missing(client):
    """Verifica que /api/connect-ai rechace modelos no descargados con error 400 descriptivo."""
    with patch("src.ui.server.OllamaService") as mock_ollama_cls:
        mock_instance = mock_ollama_cls.return_value
        mock_instance.check_connection.return_value = {
            "connected": True,
            "model_available": False,
            "available_models": ["llama3:latest"],
            "message": "Modelo no instalado",
        }

        req_body = {
            "host": "localhost",
            "port": 11434,
            "model": "modelo-inexistente:latest"
        }
        response = client.post("/api/connect-ai", json=req_body)
        assert response.status_code == 400
        assert "no está disponible" in response.json()["detail"]


def test_pipeline_worker_uses_dynamic_services():
    """Verifica que _run_pipeline_worker inyecte los servicios dinámicos de IA y BD."""
    from src.ui.server import _run_pipeline_worker, StartPipelineRequest

    mock_db_svc = MagicMock()
    mock_ollama_svc = MagicMock()
    mock_ollama_svc.base_url = "http://192.168.1.50:11434"
    mock_ollama_svc.model_name = "modelo-remoto:latest"

    try:
        state.dynamic_db_service = mock_db_svc
        state.dynamic_ollama_service = mock_ollama_svc

        with patch("src.ui.server.ETLPipeline") as mock_pipeline:
            mock_pipe_inst = mock_pipeline.return_value
            mock_pipe_inst.extractor.get_status_counts.return_value = {
                "total": 5, "pendientes": 5, "validos": 0, "observados": 0
            }
            mock_pipe_inst.run.return_value = MagicMock(
                total_records=5, processed_records=5, valid_processed_records=5,
                observed_records=0, successful_records=5, failed_records=0,
                ai_records=5, hybrid_records=0, heuristic_records=0
            )

            req = StartPipelineRequest(
                schema_name="public",
                table_name="direcciones_actual",
                limit=5,
                filter_mode="pending",
            )
            _run_pipeline_worker(req)

            # Verificar que ETLPipeline recibió el transformer y db_service dinámicos
            call_kwargs = mock_pipeline.call_args.kwargs
            assert call_kwargs["db_service"] is mock_db_svc
            assert call_kwargs["transformer"].ai_parser.ollama is mock_ollama_svc
    finally:
        state.dynamic_db_service = None
        state.dynamic_ollama_service = None


def test_cli_default_launches_gui():
    """Verifica que invocar la CLI sin argumentos ejecute directamente la GUI de escritorio."""
    from src.cli import main
    with patch("sys.argv", ["main.py"]), \
         patch("src.cli.cmd_run_gui") as mock_run_gui:
        main()
        mock_run_gui.assert_called_once_with(port=8080, open_browser=True)


def test_api_shutdown_endpoint(client):
    """Verifica que /api/shutdown detenga el pipeline si corre y responda adecuadamente."""
    with patch("threading.Thread") as mock_thread:
        response = client.post("/api/shutdown")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "SHUTTING_DOWN"
        assert "apagado correctamente" in data["message"]
        mock_thread.assert_called_once()


def test_api_clear_session_endpoint(client):
    """Verifica que /api/clear-session limpie los registros y estadísticas acumuladas."""
    state.recent_records.append({"id_licencia": 999, "raw_text": "CALLE TEST"})
    state.log_history.append("Log de prueba")
    
    response = client.post("/api/clear-session")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CLEARED"
    assert len(state.recent_records) == 0
    assert len(state.log_history) == 0


def test_ui_state_cumulative_and_in_place_update():
    """Verifica que reset_for_run conserve recent_records y que add_record actualice registros por ID."""
    state.clear_session()
    
    # Registro 1
    state.add_record({
        "id_licencia": 101,
        "raw_text": "AV BALTA 100",
        "es_procesado": False,
        "observacion": "SIN VIA VALIDA",
    })
    assert len(state.recent_records) == 1
    assert state.recent_records[0]["es_procesado"] is False

    # Nueva corrida: reset_for_run NO debe borrar los registros previos
    state.reset_for_run(total=1, schema="public", table="direcciones")
    assert len(state.recent_records) == 1

    # Reintento del mismo ID 101 que ahora sí se procesa
    state.add_record({
        "id_licencia": 101,
        "raw_text": "AV BALTA 100",
        "es_procesado": True,
        "observacion": "",
    })
    # Debe seguir teniendo longitud 1 (actualizado in-place, sin duplicar)
    assert len(state.recent_records) == 1
    assert state.recent_records[0]["es_procesado"] is True


def test_api_export_excel_endpoint(client):
    """Verifica que /api/export-excel genere un archivo .xlsx descargable con los registros enviados."""
    records_payload = [
        {
            "id_licencia": 501,
            "raw_text": "CALLE SAN JOSE 123",
            "nom_via": "SAN JOSE",
            "tipo_via_name": "CALLE",
            "num_via": "123",
            "id_via": 10,
            "nom_zona": "CHICLAYO",
            "tipo_zona_name": "URB.",
            "id_zona": 5,
            "manzana": "A",
            "lote": "1",
            "es_procesado": True,
            "metodo": "IA (patroclo)",
            "observacion": "",
            "time": "11:50:00"
        }
    ]

    response = client.post("/api/export-excel", json={"records": records_payload})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "reporte_catastral_mpch_" in response.headers.get("content-disposition", "")
    assert len(response.content) > 1000  # Archivo binario Excel generado válidamente


def test_api_export_csv_endpoint(client):
    """Verifica que /api/export-csv genere un archivo CSV descargable con BOM UTF-8."""
    records_payload = [
        {
            "id_licencia": 502,
            "raw_text": "AV BALTA 200",
            "nom_via": "BALTA",
            "tipo_via_name": "AVENIDA",
            "num_via": "200",
            "id_via": 12,
            "nom_zona": "SAN JOSE",
            "tipo_zona_name": "URB.",
            "id_zona": 6,
            "es_procesado": True,
            "metodo": "IA (patroclo)",
            "observacion": "",
            "time": "11:55:00"
        }
    ]

    response = client.post("/api/export-csv", json={"records": records_payload})
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "reporte_catastral_mpch_" in response.headers.get("content-disposition", "")
    content = response.content.decode("utf-8-sig")
    assert "ID,Direccion_Original,Tipo_Via" in content
    assert "502" in content
    assert "AVENIDA" in content


def test_api_export_db_excel_endpoint(client):
    """Verifica que /api/export-db genere un archivo Excel consultando la base de datos."""
    mock_records = [
        {
            "id_licencia": 101,
            "raw_text": "AV BALTA 100",
            "id_via": 1,
            "nom_via": "BALTA",
            "tipo_via": 1,
            "tipo_via_name": "AVENIDA",
            "num_via": "100",
            "id_zona": 2,
            "nom_zona": "CHICLAYO",
            "tipo_zona": 1,
            "tipo_zona_name": "URB.",
            "manzana": "A",
            "lote": "5",
            "slote": "",
            "referencia": "",
            "es_procesado": True,
            "observacion": "",
            "estado": "NORMALIZADO",
            "metodo": "Catastro Oficial",
            "success": True,
            "time": "-",
        }
    ]

    with patch("src.ui.server.fetch_db_records_for_export", return_value=mock_records) as mock_fetch:
        response = client.post("/api/export-db", json={
            "schema_name": "public",
            "table_name": "direcciones",
            "scope": "processed",
            "format": "excel"
        })
        assert response.status_code == 200
        assert "application/vnd.openxmlformats-officedocument" in response.headers["content-type"]
        assert "reporte_direcciones_processed_" in response.headers.get("content-disposition", "")
        assert len(response.content) > 1000
        mock_fetch.assert_called_once()


def test_api_export_db_csv_observed_endpoint(client):
    """Verifica que /api/export-db con scope=observed y format=csv filtre y descargue CSV."""
    mock_records = [
        {
            "id_licencia": 102,
            "raw_text": "CALLE DESCONOCIDA S/N",
            "id_via": None,
            "nom_via": "",
            "tipo_via": None,
            "tipo_via_name": "",
            "num_via": "",
            "id_zona": None,
            "nom_zona": "",
            "tipo_zona": None,
            "tipo_zona_name": "",
            "manzana": "",
            "lote": "",
            "slote": "",
            "referencia": "",
            "es_procesado": False,
            "observacion": "Vía no encontrada en catálogo oficial",
            "estado": "OBSERVADO",
            "metodo": "Evaluado (Observado)",
            "success": True,
            "time": "-",
        }
    ]

    with patch("src.ui.server.fetch_db_records_for_export", return_value=mock_records) as mock_fetch:
        response = client.get("/api/export-db?schema=public&table=direcciones&scope=observed&format=csv")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "reporte_direcciones_observed_" in response.headers.get("content-disposition", "")
        content = response.content.decode("utf-8-sig")
        assert "102" in content
        assert "OBSERVADO" in content
        assert "Vía no encontrada en catálogo oficial" in content
        mock_fetch.assert_called_once()


def test_api_export_db_empty_raises_404(client):
    """Verifica que /api/export-db lance 404 cuando no hay registros para el filtro."""
    with patch("src.ui.server.fetch_db_records_for_export", return_value=[]):
        response = client.get("/api/export-db?schema=public&table=direcciones&scope=observed")
        assert response.status_code == 404
        assert "No se encontraron registros" in response.json()["detail"]


def test_fetch_db_records_for_export_standard_table_resolution():
    """Verifica que fetch_db_records_for_export resuelva nombres estándar de tabla y consulte sin errores SQL."""
    from src.services.db_service import DatabaseService
    from src.ui.server import fetch_db_records_for_export

    db = DatabaseService()
    if not db.check_connection().get("connected"):
        pytest.skip("Base de datos PostgreSQL local no disponible")

    # Prueba con nombre alternativo 'direcciones' que debe auto-resolver a 'direcciones_actual'
    records_proc = fetch_db_records_for_export(db, schema="public", table="direcciones", scope="all")
    assert isinstance(records_proc, list)
    assert len(records_proc) > 0
    first = records_proc[0]
    assert "id_licencia" in first
    assert "raw_text" in first
    assert "estado" in first
    assert "tipo_via_name" in first
    assert "nom_via" in first


def test_api_export_db_end_to_end_real_db(client):
    """Verifica el endpoint /api/export-db end-to-end con la base de datos real."""
    from src.services.db_service import DatabaseService
    db = DatabaseService()
    if not db.check_connection().get("connected"):
        pytest.skip("Base de datos PostgreSQL local no disponible")

    # Descarga en CSV con scope all
    res_csv = client.get("/api/export-db?schema=public&table=direcciones_actual&scope=all&format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert len(res_csv.content) > 100

    # Descarga en Excel con scope all
    res_excel = client.get("/api/export-db?schema=public&table=direcciones_actual&scope=all&format=excel")
    assert res_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument" in res_excel.headers["content-type"]
    assert len(res_excel.content) > 1000


def test_clean_shutdown_interception():
    """Verifica que state.shutdown() drene y cierre de forma limpia las colas SSE sin errores."""
    import asyncio
    q = asyncio.Queue()
    state.register_client(q)
    assert q in state.clients

    state.shutdown()
    assert len(state.clients) == 0
    # Debe haber recibido el centinela None para cerrar el generador
    assert q.get_nowait() is None







