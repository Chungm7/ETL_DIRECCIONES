"""Orquestador maestro del pipeline ETL con seguimiento visual detallado registro por registro."""

import logging
import sys
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

        # Extractor (extrae de la tabla de direcciones en el esquema configurado)
        self.extractor = extractor or DatabaseExtractor(
            db_service=self.db,
            schema=self.schema,
            table=self.table,
            id_col=settings.db.id_col,
            dir_col=settings.db.dir_col,
        )

        # Transformer
        self.transformer = transformer or PipelineTransformer()

        # Loader (actualiza in-place en la misma tabla y esquema conservando los IDs originales)
        self.loader = loader or DatabaseLoader(
            db_service=self.db,
            schema=self.schema,
            table=self.table,
            mode="in_place",
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

        # Paso 1: Examinar tablas categorizables
        self.db.ensure_catalogs_exist(schema=self.schema, directions_table=self.table)

        # Paso 2: Sincronizar mapeo dinámico de CatalogMatcher para el esquema
        CatalogMatcher.sync_with_db(self.db, self.schema)

        # Paso 3: Asegurar columnas in-place en la tabla
        cols = self.db.ensure_in_place_columns(schema=self.schema, table=self.table)
        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan][CONFIG][/bold cyan] BD: Esquema '{self.schema}', Tabla '{self.table}' lista ({len(cols)} columnas)")
        else:
            print(f"[CONFIG] BD: Esquema '{self.schema}', Tabla '{self.table}' lista ({len(cols)} columnas)")
        sys.stdout.flush()

    def _log_record_progress(
        self,
        index: int,
        total: int,
        raw_text: Optional[str],
        destino,
        success: bool,
    ) -> None:
        """Emite una sola línea limpia, rápida y de alta visibilidad para trazabilidad en consola."""
        time_str = datetime.now().strftime("%H:%M:%S")
        pad = len(str(total))
        index_str = f"{index:>{pad}}/{total}"

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

            tipo_via = CatalogMatcher.get_via_name(destino.tipo_via) or ""
            via_part = f"{tipo_via} {destino.nom_via or ''}".strip()
            if destino.num_via:
                via_part = f"{via_part} N° {destino.num_via}".strip()

            tipo_zona = CatalogMatcher.get_zona_name(destino.tipo_zona) or ""
            zona_part = f"{tipo_zona} {destino.nom_zona or ''}".strip()

            cat_part = []
            if destino.manzana:
                cat_part.append(f"Mz. {destino.manzana}")
            if destino.lote:
                cat_part.append(f"Lt. {destino.lote}")
            if getattr(destino, "slote", None):
                cat_part.append(f"Sl. {destino.slote}")
            cat_str = " ".join(cat_part)

            parts = [p for p in [via_part, zona_part, cat_str] if p]
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
                f"[dim]{time_str}[/dim] [[bold]{index_str}[/bold]] {tag_rich} ID {destino.id_licencia}: {raw_disp} {detail}",
                soft_wrap=True,
            )
        else:
            print(f"{time_str} [{index_str}] {tag_plain} ID {destino.id_licencia}: {raw_disp} {detail}")
        sys.stdout.flush()

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
                f"Objetivo: [bold green]{records_to_process}[/bold green] (Filtro: [magenta]{filter_mode.upper()}[/magenta], Lote: {self.batch_size}) | "
                f"BD: [dim]{valid_count} válidos, {observed_count} observados, {pending_count} pendientes[/dim]"
            )
        else:
            print(
                f"[ETL] {self.schema}.{self.table} | "
                f"Objetivo: {records_to_process} (Filtro: {filter_mode.upper()}, Lote: {self.batch_size}) | "
                f"BD: {valid_count} válidos, {observed_count} observados, {pending_count} pendientes"
            )
        sys.stdout.flush()

        start_time = time.time()
        processed_in_run = 0
        current_index = 0

        while processed_in_run < records_to_process:
            if self._stop_requested:
                logger.info("Pipeline interrumpido por solicitud de usuario.")
                break

            limit = min(self.batch_size, records_to_process - processed_in_run)

            try:
                # 1. Extracción (en modo pending, los registros actualizados dejan de ser NULL,
                # por lo que offset=0 siempre apunta al siguiente conjunto de registros pendientes)
                fetch_offset = 0 if filter_mode == "pending" else processed_in_run
                batch_raw = self.extractor.extract_batch(offset=fetch_offset, limit=limit, filter_mode=filter_mode)
                if not batch_raw:
                    break

                # 2. Procesamiento, carga y visualización en tiempo real registro por registro
                for rec_raw in batch_raw:
                    if self._stop_requested:
                        logger.info("Pipeline detenido por usuario antes de procesar siguiente registro.")
                        break

                    current_index += 1
                    try:
                        logger.debug("Analizando ID %s: %s", rec_raw.id_licencia, rec_raw.emp_direccion)

                        # Transformación (Limpieza + Inferencia IA / Heurística + Catálogos)
                        rec_dest = self.transformer.transform_record(rec_raw)

                        # Métricas de motor utilizado
                        metodo = getattr(rec_dest, "metodo_normalizacion", "")
                        if "IA (" in metodo:
                            summary.ai_records += 1
                        elif "Híbrido" in metodo:
                            summary.hybrid_records += 1
                        else:
                            summary.heuristic_records += 1

                        # Carga inmediata en base de datos
                        loaded_count = self.loader.load_batch([rec_dest])
                        is_success = loaded_count == 1

                        if is_success:
                            summary.successful_records += 1
                        else:
                            summary.failed_records += 1
                        summary.processed_records += 1

                        if rec_dest.es_procesado:
                            summary.valid_processed_records += 1
                        else:
                            summary.observed_records += 1

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
                            total=records_to_process,
                            raw_text=rec_raw.emp_direccion,
                            destino=rec_dest,
                            success=is_success,
                        )

                        # Emitir evento en tiempo real hacia GUI/SSE si el callback está registrado
                        if self.on_record_processed:
                            try:
                                self.on_record_processed({
                                    "index": current_index,
                                    "total": records_to_process,
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
                                    "es_procesado": bool(rec_dest.es_procesado),
                                    "observacion": rec_dest.observacion or "",
                                    "success": is_success,
                                    "status_str": status_str,
                                    "valid_count": summary.valid_processed_records,
                                    "observed_count": summary.observed_records,
                                    "processed_count": summary.processed_records,
                                    "failed_count": summary.failed_records,
                                    "ai_records": summary.ai_records,
                                    "hybrid_records": summary.hybrid_records,
                                    "heuristic_records": summary.heuristic_records,
                                })
                            except Exception as cb_err:
                                logger.warning("Error notificando on_record_processed: %s", cb_err)

                    except Exception as rec_err:
                        logger.error("Error procesando registro %d: %s", rec_raw.id_licencia, rec_err)
                        summary.failed_records += 1
                        summary.processed_records += 1

                        # Log conciso en consola para trazabilidad inmediata de excepciones
                        time_str = datetime.now().strftime("%H:%M:%S")
                        pad = len(str(records_to_process))
                        index_str = f"{current_index:>{pad}}/{records_to_process}"
                        raw_clean = (rec_raw.emp_direccion or "VACÍO").replace("\n", " ").strip()
                        raw_disp = f'"{raw_clean[:28]}..."' if len(raw_clean) > 30 else f'"{raw_clean}"'
                        err_str = str(rec_err).replace("\n", " ").strip()
                        if len(err_str) > 50:
                            err_str = err_str[:47] + "..."

                        if RICH_AVAILABLE and console:
                            console.print(
                                f"[dim]{time_str}[/dim] [[bold]{index_str}[/bold]] [bold red][ERROR      ][/bold red] ID {rec_raw.id_licencia}: {raw_disp} -> Fallo: {err_str}",
                                soft_wrap=True,
                            )
                        else:
                            print(f"{time_str} [{index_str}] [ERROR      ] ID {rec_raw.id_licencia}: {raw_disp} -> Fallo: {err_str}")
                        sys.stdout.flush()

                        if self.on_record_processed:
                            try:
                                self.on_record_processed({
                                    "index": current_index,
                                    "total": records_to_process,
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
                                    "valid_count": summary.valid_processed_records,
                                    "observed_count": summary.observed_records,
                                    "processed_count": summary.processed_records,
                                    "failed_count": summary.failed_records,
                                    "ai_records": summary.ai_records,
                                    "hybrid_records": summary.hybrid_records,
                                    "heuristic_records": summary.heuristic_records,
                                })
                            except Exception:
                                pass

                    if self.on_progress_update:
                        try:
                            self.on_progress_update(summary)
                        except Exception:
                            pass

                processed_in_run += len(batch_raw)

            except Exception as e:
                logger.error("Fallo durante la extracción del lote en offset %d: %s", fetch_offset, e)
                summary.failed_records += limit
                processed_in_run += limit

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

