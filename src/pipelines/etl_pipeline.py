"""Orquestador maestro del pipeline ETL con seguimiento visual detallado registro por registro."""

import concurrent.futures
import logging
import queue
import sys
import threading
import time
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Callable, Dict, Any

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

from src.extractors.base_extractor import BaseExtractor
from src.extractors.db_extractor import DatabaseExtractor
from src.transformers.base_transformer import BaseTransformer
from src.transformers.pipeline_transformer import PipelineTransformer
from src.transformers.catalog_matcher import CatalogMatcher
from src.loaders.base_loader import BaseLoader
from src.loaders.db_loader import DatabaseLoader
from src.services.db_service import DatabaseService
from src.services.ollama_service import OllamaService
from src.config.settings import get_settings

logger = logging.getLogger("etl_mpch.pipeline")


@dataclass
class ETLSummary:
    """Métricas y resumen de ejecución del proceso ETL."""
    mode: str = "in_place"
    total_records: int = 0
    processed_records: int = 0
    successful_records: int = 0
    failed_records: int = 0
    valid_processed_records: int = 0
    observed_records: int = 0
    ai_records: int = 0
    hybrid_records: int = 0
    heuristic_records: int = 0
    ai_status_message: str = "No evaluado"


class ETLPipeline:
    """Orquesta la extracción, enriquecimiento con IA y carga in-place conservando IDs."""

    def __init__(
        self,
        schema: Optional[str] = None,
        table: Optional[str] = None,
        extractor: Optional[BaseExtractor] = None,
        transformer: Optional[BaseTransformer] = None,
        loader: Optional[BaseLoader] = None,
        batch_size: Optional[int] = None,
        db_service: Optional[DatabaseService] = None,
        mode: Optional[str] = None,
        require_ai: Optional[bool] = None,
        on_record_processed: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_progress_update: Optional[Callable[[Any], None]] = None,
        num_workers: Optional[int] = None,
    ):
        settings = get_settings()
        self.mode = "in_place"
        self.schema = schema or settings.db.schema
        self.table = table or settings.db.table
        self.batch_size = batch_size or settings.etl.batch_size
        self.db = db_service or DatabaseService()
        self.require_ai = settings.etl.require_ai if require_ai is None else require_ai
        self.ai_status_message = "Pendiente"
        self.on_record_processed = on_record_processed
        self.on_progress_update = on_progress_update
        self._stop_requested = False
        self.num_workers = max(1, int(num_workers or 1))
        self._metrics_lock = threading.Lock()
        self._index_lock = threading.Lock()
        self._current_index = 0

        # Mapeo dinámico de configuración de base de datos
        db_settings = getattr(self.db, "settings", None) or settings.db

        # Extractor (extrae de la tabla de direcciones en el esquema configurado)
        self.extractor = extractor or DatabaseExtractor(
            db_service=self.db,
            schema=self.schema,
            table=self.table,
            id_col=getattr(db_settings, "id_col", "id_licencia"),
            dir_col=getattr(db_settings, "dir_col", "emp_direccion"),
        )

        # Transformer
        self.transformer = transformer or PipelineTransformer()

        # Loader (actualiza in-place en la misma tabla y esquema conservando los IDs originales)
        self.loader = loader or DatabaseLoader(
            db_service=self.db,
            schema=self.schema,
            table=self.table,
            mode="in_place",
            db_settings=db_settings,
        )

    def request_stop(self) -> None:
        """Solicita la detención segura del pipeline tras culminar el registro actual."""
        self._stop_requested = True
        logger.info("Detención de pipeline solicitada.")

    def prepare_environment(self) -> None:
        """Prepara el entorno para el ETL In-Place:
        0. Comprueba la salud del motor de Inteligencia Artificial (Ollama).
        1. Examina si existen las 2 tablas categorizables (tipos_via y tipos_zona):
           - Si no existen, las crea y siembra con catálogos oficiales.
           - Si existen, verifica que tengan la columna 'abreviatura' (la agrega si falta),
             respeta los registros e IDs ya ocupados, y agrega únicamente los faltantes.
        2. Sincroniza dinámicamente CatalogMatcher con los IDs reales de este esquema.
        3. Verifica y agrega las 8 columnas normalizadas in-place en la tabla actual conservando sus IDs.
        """
        # Paso 0: Verificación de salud y respuesta en vivo del modelo IA
        ollama_svc = None
        if hasattr(self.transformer, "ai_parser") and self.transformer.ai_parser:
            ollama_svc = getattr(self.transformer.ai_parser, "ollama", None)
        if ollama_svc is None:
            ollama_svc = OllamaService()

        ai_check = ollama_svc.test_model_inference()
        if ai_check["model_ready"]:
            self.ai_status_message = f"OPERATIVO ({ollama_svc.model_name} en {ai_check['latency_seconds']}s)"
            if RICH_AVAILABLE and console:
                console.print(f"[bold cyan][CONFIG][/bold cyan] IA: [bold green]OPERATIVO[/bold green] ({ollama_svc.model_name}, {ai_check['latency_seconds']}s)")
            else:
                print(f"[CONFIG] IA: OPERATIVO ({ollama_svc.model_name}, {ai_check['latency_seconds']}s)")
        else:
            self.ai_status_message = f"NO DISPONIBLE ({ai_check['error'] or ai_check['message']})"
            warn_detail = f"[CONFIG] IA: NO DISPONIBLE ({ai_check['error'] or ai_check['message']}) - Usando contingencia Heurística"
            if RICH_AVAILABLE and console:
                console.print(f"[bold yellow]{warn_detail}[/bold yellow]")
            else:
                print(warn_detail)

            if self.require_ai:
                raise RuntimeError(
                    f"Ejecución abortada (--require-ai): El modelo '{ollama_svc.model_name}' está apagado o no responde."
                )

        # Paso 1: Asegurar arquitectura relacional V2 completa con nomenclatura tb_
        self.db.ensure_v2_tables_exist(schema=self.schema)
        cols = self.db.ensure_v2_source_columns(schema=self.schema, table=self.table)

        # Paso 2: Sincronizar mapeo dinámico de CatalogMatcher para el esquema
        CatalogMatcher.sync_with_db(self.db, self.schema)
        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan][CONFIG][/bold cyan] BD: Esquema '{self.schema}', Tabla '{self.table}' lista (vinculación V2 lista)")
        else:
            print(f"[CONFIG] BD: Esquema '{self.schema}', Tabla '{self.table}' lista (vinculación V2 lista)")
        sys.stdout.flush()

    def _log_record_progress(
        self,
        index: int,
        total: int,
        raw_text: Optional[str],
        destino,
        success: bool,
        worker_id: Optional[str] = None,
    ) -> None:
        """Emite una sola línea limpia, rápida y de alta visibilidad para trazabilidad en consola."""
        time_str = datetime.now().strftime("%H:%M:%S")
        pad = len(str(total))
        index_str = f"{index:>{pad}}/{total}"

        # Identificación del worker o instancia
        worker_plain = f"[{worker_id}] " if worker_id else ""
        worker_rich = f"[bold cyan][{worker_id}][/bold cyan] " if worker_id else ""

        # 1. Identificación del motor
        metodo = getattr(destino, "metodo_normalizacion", "IA")
        if "IA" in metodo:
            motor_lbl = "IA"
        elif "Híbrido" in metodo or "Hibrido" in metodo:
            motor_lbl = "Híbrido"
        else:
            motor_lbl = "Heurístico"

        # 2. Resumen de texto de entrada
        raw_clean = (raw_text or "VACÍO").replace("\n", " ").strip()
        raw_disp = f'"{raw_clean[:28]}..."' if len(raw_clean) > 30 else f'"{raw_clean}"'

        # 3. Estado, etiqueta y detalle
        if not success:
            tag_plain = "[ERROR      ]"
            tag_rich = "[bold red][ERROR      ][/bold red]"
            detail = f"Fallo al registrar en BD ({motor_lbl})"
        elif destino.es_procesado:
            tag_plain = "[NORMALIZADO]"
            tag_rich = "[bold green][NORMALIZADO][/bold green]"

            # Manejo V2 de vías (soporte esquina / multi-vía)
            if destino.vias and len(destino.vias) > 1:
                via_names = []
                for v in destino.vias:
                    t_via = CatalogMatcher.get_via_name(v.get("tipo_via")) or ""
                    v_nom = f"{t_via} {v.get('via_nombre') or ''}".strip()
                    if v.get("divi_numero"):
                        v_nom += f" N° {v.get('divi_numero')}"
                    via_names.append(v_nom)
                via_part = " / ".join(via_names)
            else:
                tipo_via = CatalogMatcher.get_via_name(destino.tipo_via) or ""
                via_part = f"{tipo_via} {destino.nom_via or ''}".strip()
                if destino.num_via:
                    via_part = f"{via_part} N° {destino.num_via}".strip()

            tipo_zona = CatalogMatcher.get_zona_name(destino.tipo_zona) or ""
            zona_part = f"{tipo_zona} {destino.nom_zona or ''}".strip()

            cat_part = []
            if destino.componentes:
                for c in destino.componentes:
                    cat_part.append(f"{c.get('codi_nombre', '')}: {c.get('diti_nombre', '')}")
            else:
                if destino.manzana:
                    cat_part.append(f"Mz. {destino.manzana}")
                if destino.lote:
                    cat_part.append(f"Lt. {destino.lote}")
                if getattr(destino, "slote", None):
                    cat_part.append(f"Sl. {destino.slote}")
            cat_str = " ".join(cat_part)

            mod_part = []
            if destino.modulos:
                for m in destino.modulos:
                    mod_part.append(f"{m.get('timo_nombre', '')} {m.get('ditm_nombre', '')}".strip())
            mod_str = " ".join(mod_part)

            parts = [p for p in [via_part, zona_part, cat_str, mod_str] if p]
            res_str = ", ".join(parts) if parts else (destino.referencia or "NORMALIZADO")
            if len(res_str) > 55:
                res_str = res_str[:52] + "..."
            detail = f"-> {res_str} ({motor_lbl})"
        else:
            tag_plain = "[OBSERVADO  ]"
            tag_rich = "[bold yellow][OBSERVADO  ][/bold yellow]"
            obs = (destino.observacion or "No validado en catálogos oficiales").replace("\n", " ").strip()
            if len(obs) > 50:
                obs = obs[:47] + "..."
            detail = f"-> [Motivo: {obs}] ({motor_lbl})"

        if RICH_AVAILABLE and console:
            console.print(
                f"[dim]{time_str}[/dim] [[bold]{index_str}[/bold]] {tag_rich} {worker_rich}ID {destino.id_licencia}: {raw_disp} {detail}",
                soft_wrap=True,
            )
        else:
            print(f"{time_str} [{index_str}] {tag_plain} {worker_plain}ID {destino.id_licencia}: {raw_disp} {detail}")
        sys.stdout.flush()

    def _process_single_record(self, rec_raw):
        """Procesa y persiste un único registro (Transformación con IA + Carga en BD)."""
        logger.debug("Analizando ID %s: %s", rec_raw.id_licencia, rec_raw.emp_direccion)
        rec_dest = self.transformer.transform_record(rec_raw)
        loaded_count = self.loader.load_batch([rec_dest])
        is_success = (loaded_count == 1)
        return rec_raw, rec_dest, is_success

    def _record_metrics_and_notify(
        self,
        rec_raw,
        rec_dest,
        is_success: bool,
        current_index: int,
        total_records: int,
        summary: ETLSummary,
        worker_id: Optional[str] = None,
    ):
        """Actualiza métricas protegidas, emite eventos visuales a consola y notifica callbacks."""
        with self._metrics_lock:
            metodo = getattr(rec_dest, "metodo_normalizacion", "")
            if "IA (" in metodo:
                summary.ai_records += 1
            elif "Híbrido" in metodo:
                summary.hybrid_records += 1
            else:
                summary.heuristic_records += 1

            if is_success:
                summary.successful_records += 1
            else:
                summary.failed_records += 1
            summary.processed_records += 1

            if rec_dest.es_procesado:
                summary.valid_processed_records += 1
            else:
                summary.observed_records += 1

            snap_valid = summary.valid_processed_records
            snap_obs = summary.observed_records
            snap_proc = summary.processed_records
            snap_failed = summary.failed_records
            snap_ai = summary.ai_records
            snap_hyb = summary.hybrid_records
            snap_heu = summary.heuristic_records

        # Calcular descripciones enriquecidas idénticas a consola
        via_name = CatalogMatcher.get_via_name(rec_dest.tipo_via)
        zona_name = CatalogMatcher.get_zona_name(rec_dest.tipo_zona)
        via_id_str = f"[{rec_dest.tipo_via}: {via_name}]" if rec_dest.tipo_via else "[SIN TIPO]"
        zona_id_str = f"[{rec_dest.tipo_zona}: {zona_name}]" if rec_dest.tipo_zona else "[SIN ZONA]"
        via_desc = f"{via_id_str} {rec_dest.nom_via or 'N/D'} N° {rec_dest.num_via or 'S/N'}"
        if getattr(rec_dest, "id_via", None):
            via_desc += f" [ID Vía: {rec_dest.id_via}]"
        zona_desc = f"{zona_id_str} {rec_dest.nom_zona or 'N/D'}"
        if getattr(rec_dest, "id_zona", None):
            zona_desc += f" [ID Zona: {rec_dest.id_zona}]"
        catastro = f"Mz: {rec_dest.manzana or '-'} | Lt: {rec_dest.lote or '-'} | Sublote: {rec_dest.slote or '-'}"
        status_str = "Cargado en BD ✅" if is_success else "Error en Carga ❌"

        # Mostrar seguimiento visual en vivo al instante en consola (1 sola línea limpia)
        self._log_record_progress(
            index=current_index,
            total=total_records,
            raw_text=rec_raw.emp_direccion,
            destino=rec_dest,
            success=is_success,
            worker_id=worker_id,
        )

        # Emitir evento en tiempo real hacia GUI/SSE si el callback está registrado
        if self.on_record_processed:
            try:
                self.on_record_processed({
                    "index": current_index,
                    "total": total_records,
                    "worker_id": worker_id,
                    "id_licencia": rec_raw.id_licencia,
                    "raw_text": rec_raw.emp_direccion or "",
                    "metodo": metodo,
                    "tipo_via": rec_dest.tipo_via,
                    "tipo_via_name": via_name,
                    "id_via": rec_dest.id_via,
                    "nom_via": rec_dest.nom_via,
                    "num_via": rec_dest.num_via,
                    "via_desc": via_desc,
                    "tipo_zona": rec_dest.tipo_zona,
                    "tipo_zona_name": zona_name,
                    "id_zona": rec_dest.id_zona,
                    "nom_zona": rec_dest.nom_zona,
                    "zona_desc": zona_desc,
                    "manzana": rec_dest.manzana,
                    "lote": rec_dest.lote,
                    "slote": rec_dest.slote,
                    "catastro": catastro,
                    "referencia": rec_dest.referencia,
                    "dire_id": getattr(rec_dest, "dire_id", None),
                    "dire_referencia": getattr(rec_dest, "dire_referencia", None),
                    "vias": getattr(rec_dest, "vias", []),
                    "componentes": getattr(rec_dest, "componentes", []),
                    "modulos": getattr(rec_dest, "modulos", []),
                    "es_procesado": bool(rec_dest.es_procesado),
                    "observacion": rec_dest.observacion or "",
                    "success": is_success,
                    "status_str": status_str,
                    "valid_count": snap_valid,
                    "observed_count": snap_obs,
                    "processed_count": snap_proc,
                    "failed_count": snap_failed,
                    "ai_records": snap_ai,
                    "hybrid_records": snap_hyb,
                    "heuristic_records": snap_heu,
                })
            except Exception as cb_err:
                logger.warning("Error notificando on_record_processed: %s", cb_err)

        if self.on_progress_update:
            try:
                self.on_progress_update(summary)
            except Exception:
                pass

    def _record_metrics_and_notify_error(
        self,
        rec_raw,
        rec_err: Exception,
        current_index: int,
        total_records: int,
        summary: ETLSummary,
        worker_id: Optional[str] = None,
    ):
        with self._metrics_lock:
            summary.failed_records += 1
            summary.processed_records += 1
            snap_valid = summary.valid_processed_records
            snap_obs = summary.observed_records
            snap_proc = summary.processed_records
            snap_failed = summary.failed_records
            snap_ai = summary.ai_records
            snap_hyb = summary.hybrid_records
            snap_heu = summary.heuristic_records

        time_str = datetime.now().strftime("%H:%M:%S")
        pad = len(str(total_records))
        index_str = f"{current_index:>{pad}}/{total_records}"
        raw_clean = (rec_raw.emp_direccion or "VACÍO").replace("\n", " ").strip()
        raw_disp = f'"{raw_clean[:28]}..."' if len(raw_clean) > 30 else f'"{raw_clean}"'
        err_str = str(rec_err).replace("\n", " ").strip()
        if len(err_str) > 50:
            err_str = err_str[:47] + "..."

        worker_plain = f"[{worker_id}] " if worker_id else ""
        worker_rich = f"[bold cyan][{worker_id}][/bold cyan] " if worker_id else ""

        if RICH_AVAILABLE and console:
            console.print(
                f"[dim]{time_str}[/dim] [[bold]{index_str}[/bold]] [bold red][ERROR      ][/bold red] {worker_rich}ID {rec_raw.id_licencia}: {raw_disp} -> Fallo: {err_str}",
                soft_wrap=True,
            )
        else:
            print(f"{time_str} [{index_str}] [ERROR      ] {worker_plain}ID {rec_raw.id_licencia}: {raw_disp} -> Fallo: {err_str}")
        sys.stdout.flush()

        if self.on_record_processed:
            try:
                self.on_record_processed({
                    "index": current_index,
                    "total": total_records,
                    "worker_id": worker_id,
                    "id_licencia": rec_raw.id_licencia,
                    "raw_text": rec_raw.emp_direccion or "",
                    "metodo": "ERROR",
                    "id_via": None,
                    "nom_via": None,
                    "num_via": None,
                    "id_zona": None,
                    "nom_zona": None,
                    "manzana": None,
                    "lote": None,
                    "slote": None,
                    "referencia": None,
                    "es_procesado": False,
                    "observacion": f"ERROR_EJECUCION: {str(rec_err)[:200]}",
                    "success": False,
                    "valid_count": snap_valid,
                    "observed_count": snap_obs,
                    "processed_count": snap_proc,
                    "failed_count": snap_failed,
                    "ai_records": snap_ai,
                    "hybrid_records": snap_hyb,
                    "heuristic_records": snap_heu,
                })
            except Exception:
                pass

        if self.on_progress_update:
            try:
                self.on_progress_update(summary)
            except Exception:
                pass

    def run(
        self,
        max_records: Optional[int] = None,
        limit: Optional[int] = None,
        filter_mode: str = "pending",
        process_all: bool = False,
    ) -> ETLSummary:
        """Ejecuta el ciclo de vida del ETL por lotes con reanudación automática y seguimiento visual."""
        # Soporta tanto limit como max_records para interoperabilidad transparente entre CLI y GUI
        effective_limit = limit if limit is not None else max_records

        self.prepare_environment()

        summary = ETLSummary(mode=self.mode, ai_status_message=self.ai_status_message)
        
        # Consultar métricas de estado en la base de datos de manera segura
        counts = {}
        try:
            raw_counts = self.extractor.get_status_counts()
            if isinstance(raw_counts, dict):
                counts = raw_counts
        except Exception:
            counts = {}

        total_available = counts.get("total", self.extractor.get_total_records())
        if not isinstance(total_available, int):
            try:
                total_available = int(total_available)
            except Exception:
                total_available = 0

        pending_count = counts.get("pendientes", total_available)
        valid_count = counts.get("validos", 0)
        observed_count = counts.get("observados", 0)

        # Determinar universo objetivo normalizando variantes de filtro
        norm_filter = str(filter_mode).lower().strip()
        if norm_filter in ("pending", "pendientes"):
            target_pool = pending_count
            filter_mode = "pending"
        elif norm_filter in ("observed", "observados", "unprocessed"):
            target_pool = observed_count
            filter_mode = "observed"
        else:
            target_pool = total_available
            filter_mode = "all"

        if target_pool == 0 and not process_all and effective_limit is None:
            if RICH_AVAILABLE and console:
                console.print(
                    f"\n[bold green][ETL] Todos los registros ({total_available}) ya se encuentran procesados en {self.schema}.{self.table}[/bold green]\n"
                    f"       Validados: {valid_count} | Observados: {observed_count} | Pendientes: 0\n"
                )
            else:
                print(f"\n[ETL] Todos los registros ({total_available}) ya han sido procesados. No hay registros pendientes.\n")
            return summary

        records_to_process = target_pool if process_all else (min(target_pool, effective_limit) if effective_limit else target_pool)
        summary.total_records = records_to_process

        valid_pct = (valid_count / total_available * 100) if total_available else 0
        obs_pct = (observed_count / total_available * 100) if total_available else 0
        pend_pct = (pending_count / total_available * 100) if total_available else 0

        if RICH_AVAILABLE and console:
            console.print(
                f"[bold cyan][ETL][/bold cyan] {self.schema}.{self.table} | "
                f"Objetivo: [bold green]{records_to_process}[/bold green] (Filtro: [magenta]{filter_mode.upper()}[/magenta], Lote: {self.batch_size}, Workers: [bold cyan]{self.num_workers}[/bold cyan]) | "
                f"BD: [dim]{valid_count} válidos, {observed_count} observados, {pending_count} pendientes[/dim]"
            )
        else:
            print(
                f"[ETL] {self.schema}.{self.table} | "
                f"Objetivo: {records_to_process} (Filtro: {filter_mode.upper()}, Lote: {self.batch_size}, Workers: {self.num_workers}) | "
                f"BD: {valid_count} válidos, {observed_count} observados, {pending_count} pendientes"
            )
        sys.stdout.flush()

        start_time = time.time()
        self._current_index = 0

        # Cola thread-safe con capacidad controlada (arquitectura Work-Stealing / Productor-Consumidor)
        queue_size = max(50, self.num_workers * 4)
        work_queue: queue.Queue[Optional[DireccionOrigen]] = queue.Queue(maxsize=queue_size)
        producer_done = threading.Event()

        def _producer_feeder():
            """Productor en streaming: extrae bloques continuos de BD y los alimenta a la cola sin duplicados."""
            enqueued = 0
            last_seen_id = None

            while enqueued < records_to_process and not self._stop_requested:
                limit_chunk = min(self.batch_size, records_to_process - enqueued)
                try:
                    # Intenta primero keyset pagination con after_id para inmunidad total ante concurrencia
                    try:
                        batch_raw = self.extractor.extract_batch(
                            limit=limit_chunk,
                            filter_mode=filter_mode,
                            after_id=last_seen_id,
                        )
                    except TypeError:
                        # Fallback seguro para extractores personalizados o mocks sin soporte after_id
                        fetch_offset = 0 if filter_mode == "pending" else enqueued
                        batch_raw = self.extractor.extract_batch(
                            offset=fetch_offset,
                            limit=limit_chunk,
                            filter_mode=filter_mode,
                        )

                    if not batch_raw:
                        break

                    for rec in batch_raw:
                        if self._stop_requested or enqueued >= records_to_process:
                            break

                        while not self._stop_requested:
                            try:
                                work_queue.put(rec, timeout=0.2)
                                enqueued += 1
                                if hasattr(rec, "id_licencia") and rec.id_licencia is not None:
                                    last_seen_id = rec.id_licencia
                                break
                            except queue.Full:
                                continue

                except Exception as ex_feeder:
                    logger.error("Error en productor de registros: %s", ex_feeder)
                    break

            producer_done.set()

            # Encolar sentinelas None para señalar fin a cada worker
            for _ in range(self.num_workers):
                while not self._stop_requested:
                    try:
                        work_queue.put(None, timeout=0.2)
                        break
                    except queue.Full:
                        continue

        def _worker_consumer(worker_num: int):
            """Consumidor concurrente: procesa registros individuales de forma completamente autónoma."""
            worker_id = f"Instancia IA #{worker_num}"

            while not self._stop_requested:
                try:
                    item = work_queue.get(timeout=0.4)
                except queue.Empty:
                    if producer_done.is_set():
                        break
                    continue

                if item is None:
                    work_queue.task_done()
                    break

                rec_raw = item
                with self._index_lock:
                    self._current_index += 1
                    current_idx = self._current_index

                try:
                    rec_raw, rec_dest, is_success = self._process_single_record(rec_raw)
                    self._record_metrics_and_notify(
                        rec_raw=rec_raw,
                        rec_dest=rec_dest,
                        is_success=is_success,
                        current_index=current_idx,
                        total_records=records_to_process,
                        summary=summary,
                        worker_id=worker_id,
                    )
                except Exception as rec_err:
                    rec_id = getattr(rec_raw, "id_licencia", -1)
                    logger.error("Error procesando registro %s en %s: %s", rec_id, worker_id, rec_err)
                    self._record_metrics_and_notify_error(
                        rec_raw=rec_raw,
                        rec_err=rec_err,
                        current_index=current_idx,
                        total_records=records_to_process,
                        summary=summary,
                        worker_id=worker_id,
                    )
                finally:
                    work_queue.task_done()

        feeder_thread = threading.Thread(target=_producer_feeder, name="ETL-Producer", daemon=True)
        feeder_thread.start()

        worker_threads = []
        for i in range(self.num_workers):
            t = threading.Thread(target=_worker_consumer, args=(i + 1,), name=f"ETL-Worker-{i+1}", daemon=True)
            worker_threads.append(t)
            t.start()

        feeder_thread.join()
        for t in worker_threads:
            t.join()

        elapsed = time.time() - start_time
        if RICH_AVAILABLE and console:
            console.print(
                f"\n[bold cyan][ETL][/bold cyan] Finalizado en [bold]{elapsed:.2f}s[/bold]: "
                f"[bold]{summary.processed_records}[/bold] procesados ("
                f"[green]{summary.valid_processed_records} normalizados[/green], "
                f"[yellow]{summary.observed_records} observados[/yellow], "
                f"[red]{summary.failed_records} errores[/red]) | "
                f"Motor: {summary.ai_records} IA, {summary.hybrid_records} Híbrido, {summary.heuristic_records} Heurístico\n"
            )
        else:
            print(
                f"\n[ETL] Finalizado en {elapsed:.2f}s: "
                f"{summary.processed_records} procesados ("
                f"{summary.valid_processed_records} normalizados, "
                f"{summary.observed_records} observados, "
                f"{summary.failed_records} errores) | "
                f"Motor: {summary.ai_records} IA, {summary.hybrid_records} Híbrido, {summary.heuristic_records} Heurístico\n"
            )
        sys.stdout.flush()

        if self.on_progress_update:
            try:
                self.on_progress_update(summary)
            except Exception:
                pass

        return summary

