"""Servidor backend FastAPI con soporte SSE (Server-Sent Events) para la GUI del ETL MPCH."""

import asyncio
import logging
import queue
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config.settings import get_settings
from src.extractors.db_extractor import DatabaseExtractor
from src.pipelines.etl_pipeline import ETLPipeline
from src.services.db_service import DatabaseService
from src.services.ollama_service import OllamaService

logger = logging.getLogger("etl_mpch.gui")

# Configuración del servidor y directorios estáticos
STATIC_DIR = Path(__file__).resolve().parent / "static"


class ExecutionState:
    """Estado compartido en memoria de la ejecución del pipeline."""

    def __init__(self):
        self.is_running: bool = False
        self.pipeline: Optional[ETLPipeline] = None
        self.thread: Optional[threading.Thread] = None
        self.active_schema: str = "public"
        self.active_table: str = "direcciones_locales"
        self.recent_records: List[Dict[str, Any]] = []
        self.max_recent_records: int = 150
        self.log_history: List[str] = []
        self.max_log_history: int = 200
        self.stats: Dict[str, Any] = {
            "status": "IDLE",
            "total_to_process": 0,
            "processed": 0,
            "valid": 0,
            "observed": 0,
            "failed": 0,
            "ai_records": 0,
            "hybrid_records": 0,
            "heuristic_records": 0,
            "progress_pct": 0.0,
            "start_time": None,
            "elapsed_seconds": 0,
        }
        self.clients: List[asyncio.Queue] = []
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def reset_for_run(self, total: int, schema: str, table: str):
        with self._lock:
            self.is_running = True
            self.active_schema = schema
            self.active_table = table
            self.recent_records.clear()
            self.stats = {
                "status": "RUNNING",
                "total_to_process": total,
                "processed": 0,
                "valid": 0,
                "observed": 0,
                "failed": 0,
                "ai_records": 0,
                "hybrid_records": 0,
                "heuristic_records": 0,
                "progress_pct": 0.0,
                "start_time": time.time(),
                "elapsed_seconds": 0,
            }

    def add_log(self, message: str):
        with self._lock:
            self.log_history.append(message)
            if len(self.log_history) > self.max_log_history:
                self.log_history.pop(0)
        self.broadcast({"type": "log", "payload": message})

    def add_record(self, record_data: Dict[str, Any]):
        with self._lock:
            self.recent_records.append(record_data)
            if len(self.recent_records) > self.max_recent_records:
                self.recent_records.pop(0)

            total = self.stats.get("total_to_process", 0)
            processed = record_data.get("processed_count", 0)
            pct = round((processed / total * 100), 1) if total > 0 else 0.0

            start_t = self.stats.get("start_time")
            elapsed = round(time.time() - start_t, 1) if start_t else 0

            self.stats.update({
                "processed": processed,
                "valid": record_data.get("valid_count", 0),
                "observed": record_data.get("observed_count", 0),
                "failed": record_data.get("failed_count", 0),
                "ai_records": record_data.get("ai_records", 0),
                "hybrid_records": record_data.get("hybrid_records", 0),
                "heuristic_records": record_data.get("heuristic_records", 0),
                "progress_pct": pct,
                "elapsed_seconds": elapsed,
            })

        self.broadcast({"type": "record", "payload": record_data})
        self.broadcast({"type": "stats", "payload": self.stats})

    def finish_run(self, summary_data: Optional[Dict[str, Any]] = None, error: Optional[str] = None):
        with self._lock:
            self.is_running = False
            self.pipeline = None
            self.stats["status"] = "ERROR" if error else "FINISHED"
            if error:
                self.stats["error"] = error
        if error:
            self.broadcast({"type": "error", "payload": {"error": error}})
        else:
            self.broadcast({"type": "done", "payload": summary_data or self.stats})

    def register_client(self, q: asyncio.Queue):
        with self._lock:
            self.clients.append(q)

    def unregister_client(self, q: asyncio.Queue):
        with self._lock:
            if q in self.clients:
                self.clients.remove(q)

    def broadcast(self, event: Dict[str, Any]):
        if not self.loop:
            return
        with self._lock:
            targets = list(self.clients)
        for q in targets:
            try:
                self.loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass


state = ExecutionState()


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Ciclo de vida de FastAPI: registra el event loop activo en el estado."""
    state.loop = asyncio.get_running_loop()
    yield


app = FastAPI(
    title="MPCH ETL - Interfaz Gráfica de Normalización",
    description="Panel interactivo de control y visualización registro por registro con IA",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class StartPipelineRequest(BaseModel):
    schema_name: str = Field(default="public", description="Esquema destino en PostgreSQL")
    table_name: str = Field(default="direcciones_locales", description="Nombre de tabla de direcciones")
    limit: Optional[int] = Field(default=None, description="Límite máximo de registros a procesar")
    batch_size: int = Field(default=10, ge=1, le=100, description="Tamaño de lote por transacción")
    filter_mode: str = Field(default="pending", description="Filtro: pending, all, o unprocessed")
    require_ai: bool = Field(default=True, description="Si es True, exige disponibilidad del modelo IA")


@app.get("/", response_class=FileResponse)
async def serve_ui():
    """Sirve la página de interfaz gráfica de escritorio."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Archivo UI index.html no encontrado.")
    return FileResponse(str(index_path))


@app.get("/api/status")
async def get_system_status():
    """Retorna el estado del sistema, conexiones, esquemas y métricas actuales."""
    settings = get_settings()
    db_svc = DatabaseService()
    ollama_svc = OllamaService()

    db_health = db_svc.check_connection(schema=state.active_schema)
    ai_health = ollama_svc.check_connection()

    table_counts = {}
    try:
        extractor = DatabaseExtractor(
            db_service=db_svc,
            schema=state.active_schema,
            table=state.active_table,
        )
        table_counts = extractor.get_status_counts()
    except Exception as e:
        logger.warning("No se pudo obtener conteo de tabla: %s", e)
        table_counts = {"total": 0, "pendientes": 0, "validos": 0, "observados": 0}

    return {
        "running": state.is_running,
        "active_schema": state.active_schema,
        "active_table": state.active_table,
        "available_schemas": db_health.get("available_schemas", ["public"]),
        "db": {
            "connected": db_health.get("connected", False),
            "schema": db_health.get("schema", state.active_schema),
            "table_exists": db_health.get("table_exists", False),
            "message": db_health.get("message", ""),
        },
        "ai": {
            "connected": ai_health.get("connected", False),
            "model": ai_health.get("model", ollama_svc.model_name),
            "installed": ai_health.get("model_installed", False),
            "message": ai_health.get("message", ""),
        },
        "table_counts": table_counts,
        "stats": state.stats,
        "recent_records": state.recent_records[-30:],
    }


@app.get("/api/schemas")
async def get_schemas():
    """Devuelve la lista de esquemas accesibles en la base de datos."""
    try:
        db_svc = DatabaseService()
        schemas = db_svc.get_available_schemas()
        return {"schemas": schemas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando esquemas: {e}")


@app.get("/api/counts")
async def get_table_counts(
    schema: str = Query("public"),
    table: str = Query("direcciones_locales")
):
    """Devuelve los conteos catastrales de la tabla especificada."""
    try:
        db_svc = DatabaseService()
        extractor = DatabaseExtractor(db_service=db_svc, schema=schema, table=table)
        counts = extractor.get_status_counts()
        return counts
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error obteniendo conteo: {e}")


@app.post("/api/test-ai")
async def test_ai_connection(sample_address: Optional[str] = None):
    """Ejecuta una prueba de inferencia en vivo con el modelo local Ollama."""
    ollama_svc = OllamaService()
    test_addr = sample_address or "CALLE SAN JOSE 456 URB SANTA VICTORIA CHICLAYO"

    start_time = time.perf_counter()
    health = ollama_svc.check_connection()
    if not health.get("connected"):
        return {
            "success": False,
            "model": ollama_svc.model_name,
            "latency_ms": 0,
            "message": health.get("message", "Ollama fuera de línea"),
        }

    try:
        result = ollama_svc.parse_address_with_ai(test_addr)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
        parsed_dict = result.model_dump() if hasattr(result, "model_dump") else (result.dict() if result else None)
        return {
            "success": bool(result),
            "model": ollama_svc.model_name,
            "latency_ms": elapsed_ms,
            "input": test_addr,
            "parsed": parsed_dict,
            "message": f"Inferencia exitosa en {elapsed_ms} ms" if result else "Modelo respondió pero no extrajo estructura",
        }
    except Exception as e:
        return {
            "success": False,
            "model": ollama_svc.model_name,
            "latency_ms": 0,
            "message": f"Error de inferencia: {e}",
        }


def _run_pipeline_worker(req: StartPipelineRequest):
    """Función que ejecuta el pipeline ETL en un hilo secundario para no bloquear el servidor."""
    state.add_log(f"Iniciando pipeline ETL en esquema [{req.schema_name}] tabla [{req.table_name}]...")
    try:
        db_svc = DatabaseService()
        pipeline = ETLPipeline(
            schema=req.schema_name,
            table=req.table_name,
            batch_size=req.batch_size,
            db_service=db_svc,
            require_ai=req.require_ai,
            on_record_processed=state.add_record,
        )
        state.pipeline = pipeline

        state.add_log("Preparando entorno y tablas maestras...")
        pipeline.prepare_environment()

        # Calcular número total a procesar
        extractor = pipeline.extractor
        status_counts = extractor.get_status_counts()
        total_avail = status_counts.get("total", 0)
        pending_avail = status_counts.get("pendientes", 0)
        observed_avail = status_counts.get("observados", 0)

        if req.filter_mode == "pending":
            target_pool = pending_avail
        elif req.filter_mode == "unprocessed":
            target_pool = observed_avail
        else:
            target_pool = total_avail

        to_process = min(req.limit, target_pool) if req.limit else target_pool
        state.reset_for_run(total=to_process, schema=req.schema_name, table=req.table_name)
        state.add_log(f"Total registros a normalizar: {to_process} (Filtro: {req.filter_mode})")

        summary = pipeline.run(limit=req.limit, filter_mode=req.filter_mode)

        summary_dict = {
            "total_records": summary.total_records,
            "processed_records": summary.processed_records,
            "valid_processed_records": summary.valid_processed_records,
            "observed_records": summary.observed_records,
            "successful_records": summary.successful_records,
            "failed_records": summary.failed_records,
            "ai_records": summary.ai_records,
            "hybrid_records": summary.hybrid_records,
            "heuristic_records": summary.heuristic_records,
        }
        state.add_log("Pipeline completado exitosamente.")
        state.finish_run(summary_data=summary_dict)

    except Exception as e:
        logger.exception("Error crítico durante la ejecución del pipeline: %s", e)
        state.add_log(f"ERROR: {e}")
        state.finish_run(error=str(e))


@app.post("/api/start")
async def start_pipeline(req: StartPipelineRequest):
    """Inicia la ejecución del pipeline ETL en segundo plano."""
    if state.is_running:
        raise HTTPException(status_code=409, detail="Ya hay un pipeline en ejecución actualmente.")

    state.active_schema = req.schema_name
    state.active_table = req.table_name

    worker = threading.Thread(
        target=_run_pipeline_worker,
        args=(req,),
        name="ETLWorkerThread",
        daemon=True,
    )
    state.thread = worker
    worker.start()

    return {"status": "STARTED", "message": "Pipeline iniciado correctamente."}


@app.post("/api/stop")
async def stop_pipeline():
    """Detiene la ejecución del pipeline de manera ordenada tras culminar el registro en curso."""
    if not state.is_running or not state.pipeline:
        return {"status": "NOT_RUNNING", "message": "No hay un pipeline en ejecución activa."}

    state.pipeline.request_stop()
    state.add_log("⏹️ Solicitud de detención manual recibida. Esperando finalización del registro actual...")
    return {"status": "STOPPING", "message": "Detención solicitada. El proceso finalizará en breve."}


@app.get("/api/stream")
async def sse_event_stream():
    """Canal SSE (Server-Sent Events) para transmitir registros y métricas en tiempo real."""
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    state.register_client(client_queue)

    async def event_generator():
        try:
            # Enviar saludo inicial y estado actual
            yield f"data: {{\"type\": \"connected\", \"payload\": {{\"running\": {str(state.is_running).lower()}}}}}\n\n"
            while True:
                try:
                    # Esperar evento con timeout para enviar ping periódico
                    event = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    import json
                    json_data = json.dumps(event, default=str)
                    yield f"data: {json_data}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            state.unregister_client(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
