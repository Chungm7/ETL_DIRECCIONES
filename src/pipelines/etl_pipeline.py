"""Orquestador maestro del pipeline ETL con seguimiento visual detallado registro por registro."""

import logging
import sys
from dataclasses import dataclass
from typing import Optional

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
        require_ai: bool = False,
    ):
        settings = get_settings()
        self.mode = "in_place"
        self.schema = schema or settings.db.schema
        self.table = table or settings.db.table
        self.batch_size = batch_size or settings.etl.batch_size
        self.db = db_service or DatabaseService()
        self.require_ai = require_ai
        self.ai_status_message = "Pendiente"

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

        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan]🤖 Comprobando motor de IA Local/Remoto ({ollama_svc.model_name})...[/bold cyan]")
        else:
            print(f"🤖 Comprobando motor de IA Local/Remoto ({ollama_svc.model_name})...")

        ai_check = ollama_svc.test_model_inference()
        if ai_check["model_ready"]:
            self.ai_status_message = f"OPERATIVO ({ollama_svc.model_name} en {ai_check['latency_seconds']}s)"
            if RICH_AVAILABLE and console:
                console.print(f"   • Estado IA: [bold green]ACTIVO Y OPERATIVO[/bold green] | Modelo: [yellow]{ollama_svc.model_name}[/yellow] | Latencia: [cyan]{ai_check['latency_seconds']}s[/cyan] ✅\n")
            else:
                print(f"   • Estado IA: ACTIVO Y OPERATIVO | Modelo: {ollama_svc.model_name} | Latencia: {ai_check['latency_seconds']}s ✅\n")
        else:
            self.ai_status_message = f"NO DISPONIBLE ({ai_check['error'] or ai_check['message']})"
            warn_detail = (
                f"El modelo IA '{ollama_svc.model_name}' NO está respondiendo en {ollama_svc.base_url}.\n"
                f"Causa: {ai_check['error'] or ai_check['message']}\n"
                f"⚠️ ATENCIÓN: El ETL continuará con el motor de contingencia HEURÍSTICO (menor precisión semántica)."
            )
            if RICH_AVAILABLE and console:
                console.print(Panel(
                    warn_detail,
                    title="[bold yellow]⚠️ ADVERTENCIA: MOTOR DE IA APAGADO / INACCESIBLE[/bold yellow]",
                    border_style="yellow",
                ))
            else:
                print(f"\n⚠️ ADVERTENCIA: MOTOR DE IA APAGADO / INACCESIBLE\n{warn_detail}\n")

            if self.require_ai:
                raise RuntimeError(
                    f"Ejecución abortada (--require-ai): El modelo '{ollama_svc.model_name}' está apagado o no responde."
                )

        # Paso 1: Examinar tablas categorizables
        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan]🔍 [Paso 1/3] Examinando tablas categorizables en esquema '{self.schema}'...[/bold cyan]")
        else:
            print(f"🔍 [Paso 1/3] Examinando tablas categorizables en esquema '{self.schema}'...")

        catalog_status = self.db.ensure_catalogs_exist(schema=self.schema, directions_table=self.table)
        for cat_name, status in catalog_status.items():
            t_created = status.get("table_created", False)
            col_added = status.get("column_added", False)
            existing = status.get("existing_records", 0)
            remapped = status.get("remapped_records", 0)
            added = status.get("added_records", 0)
            total = status.get("total_records", existing + added)
            fk_remapped = status.get("fk_remapped_records", 0)

            details = []
            if t_created:
                details.append("Tabla creada 🏗️")
            else:
                details.append("Tabla ya existía ✅")
            if col_added:
                details.append("Columna 'abreviatura' agregada ➕")
            if remapped > 0:
                details.append(f"{remapped} registros estandarizados a IDs canónicos 🔄")
            if fk_remapped > 0:
                details.append(f"{fk_remapped} relaciones en direcciones reasignadas 🔗")
            if existing > 0 and remapped == 0:
                details.append(f"{existing} registros previos estándar 🔒")
            if added > 0:
                details.append(f"{added} registros faltantes incorporados 🚀")
            details.append(f"Total: {total} registros")

            summary_msg = " | ".join(details)
            if RICH_AVAILABLE and console:
                console.print(f"   • Catálogo [bold yellow]{cat_name}[/bold yellow]: [green]{summary_msg}[/green]")
            else:
                print(f"   • Catálogo {cat_name}: {summary_msg}")

        # Paso 2: Sincronizar mapeo dinámico de CatalogMatcher para el esquema
        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan]🔗 [Paso 2/3] Sincronizando catálogo dinámico con los IDs de '{self.schema}'...[/bold cyan]")
        else:
            print(f"🔗 [Paso 2/3] Sincronizando catálogo dinámico con los IDs de '{self.schema}'...")
        CatalogMatcher.sync_with_db(self.db, self.schema)

        # Paso 3: Asegurar columnas in-place en la tabla
        if RICH_AVAILABLE and console:
            console.print(f"[bold cyan]⚡ [Paso 3/3] Verificando columnas in-place en '{self.schema}.{self.table}' (conservando IDs)...[/bold cyan]")
        else:
            print(f"⚡ [Paso 3/3] Verificando columnas in-place en '{self.schema}.{self.table}' (conservando IDs)...")

        cols = self.db.ensure_in_place_columns(schema=self.schema, table=self.table)
        if RICH_AVAILABLE and console:
            console.print(f"   • Columnas disponibles: [green]{', '.join(cols)}[/green]\n")
        else:
            print(f"   • Columnas disponibles: {', '.join(cols)}\n")
        sys.stdout.flush()

    def _log_record_progress(
        self,
        index: int,
        total: int,
        raw_text: Optional[str],
        destino,
        success: bool,
    ) -> None:
        """Imprime un bloque de seguimiento visual claro sobre la asignación del registro,
        indicando explícitamente qué motor (IA, Heurístico o Híbrido) realizó la extracción.
        """
        via_name = CatalogMatcher.get_via_name(destino.tipo_via)
        zona_name = CatalogMatcher.get_zona_name(destino.tipo_zona)

        via_id_str = f"[{destino.tipo_via}: {via_name}]" if destino.tipo_via else "[SIN TIPO]"
        zona_id_str = f"[{destino.tipo_zona}: {zona_name}]" if destino.tipo_zona else "[SIN ZONA]"

        via_desc = f"{via_id_str} {destino.nom_via or 'N/D'} N° {destino.num_via or 'S/N'}"
        if getattr(destino, "id_via", None):
            via_desc += f" [ID Vía: {destino.id_via}]"
        zona_desc = f"{zona_id_str} {destino.nom_zona or 'N/D'}"
        if getattr(destino, "id_zona", None):
            zona_desc += f" [ID Zona: {destino.id_zona}]"
        catastro = f"Mz: {destino.manzana or '-'} | Lt: {destino.lote or '-'} | Sublote: {destino.slote or '-'}"
        status_str = "Cargado en BD ✅" if success else "Error en Carga ❌"

        # Identificación visual del motor utilizado
        metodo = getattr(destino, "metodo_normalizacion", "IA")
        if "IA (" in metodo:
            motor_badge = f"🤖 {metodo}"
            motor_style = "bold green"
        elif "Híbrido" in metodo:
            motor_badge = f"🧩 {metodo}"
            motor_style = "bold cyan"
        else:
            motor_badge = f"⚠️ {metodo}"
            motor_style = "bold yellow"

        if RICH_AVAILABLE and console:
            content = Text()
            content.append(f"📍 Entrada  : ", style="bold")
            content.append(f"\"{raw_text or 'VACÍO'}\"\n", style="white")
            content.append(f"⚙️  Motor    : ", style="bold")
            content.append(f"{motor_badge}\n", style=motor_style)
            content.append(f"🛣️  Vía      : ", style="bold yellow")
            content.append(f"{via_desc}\n", style="yellow")
            content.append(f"🏙️  Zona     : ", style="bold magenta")
            content.append(f"{zona_desc}\n", style="magenta")
            content.append(f"📐 Catastro : ", style="bold cyan")
            content.append(f"{catastro}\n", style="cyan")
            if destino.referencia:
                content.append(f"🏛️  Ref      : ", style="bold blue")
                content.append(f"{destino.referencia}\n", style="blue")
            proc_badge = "PROCESADO (Válido en Catastro) ✅" if destino.es_procesado else "OBSERVADO (No Procesado) ⚠️"
            content.append(f"📋 Catastro : ", style="bold")
            content.append(f"{proc_badge}\n", style="bold green" if destino.es_procesado else "bold yellow")
            if destino.observacion:
                content.append(f"⚠️  Motivo   : ", style="bold red")
                content.append(f"{destino.observacion}\n", style="red")
            content.append(f"💾 Estado   : ", style="bold")
            content.append(f"{status_str}", style="bold green" if success else "bold red")

            title = f"Registro {index}/{total} | ID Licencia: {destino.id_licencia}"
            console.print(Panel(content, title=title, border_style="green" if (success and destino.es_procesado) else "yellow" if success else "red", expand=False))
        else:
            print(f"\n┌── [Registro {index}/{total} | ID Licencia: {destino.id_licencia}] ───────────────")
            print(f"│ 📍 Entrada  : \"{raw_text or 'VACÍO'}\"")
            print(f"│ ⚙️  Motor    : {motor_badge}")
            print(f"│ 🛣️  Vía      : {via_desc}")
            print(f"│ 🏙️  Zona     : {zona_desc}")
            print(f"│ 📐 Catastro : {catastro}")
            if destino.referencia:
                print(f"│ 🏛️  Ref      : {destino.referencia}")
            proc_badge = "PROCESADO ✅" if destino.es_procesado else "OBSERVADO ⚠️"
            print(f"│ 📋 Catastro : {proc_badge}")
            if destino.observacion:
                print(f"│ ⚠️  Motivo   : {destino.observacion}")
            print(f"└── 💾 Estado : {status_str}")

        sys.stdout.flush()

    def run(
        self,
        max_records: Optional[int] = None,
        filter_mode: str = "pending",
        process_all: bool = False,
    ) -> ETLSummary:
        """Ejecuta el ciclo de vida del ETL por lotes con reanudación automática y seguimiento visual."""
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

        # Determinar universo objetivo según el filtro seleccionado
        if filter_mode == "pending":
            target_pool = pending_count
        elif filter_mode == "observed":
            target_pool = observed_count
        else:
            target_pool = total_available

        if target_pool == 0 and not process_all and max_records is None:
            if RICH_AVAILABLE and console:
                console.print(
                    f"\n[bold green]🎉 Todos los registros ({total_available}) ya se encuentran procesados en {self.schema}.{self.table}[/bold green]\n"
                    f"├─ ✅ Validados en Catastro: [green]{valid_count}[/green]\n"
                    f"├─ ⚠️  Observados            : [yellow]{observed_count}[/yellow]\n"
                    f"└─ ⏳ Pendientes por IA     : [cyan]0[/cyan]\n"
                )
            else:
                print(f"\n🎉 Todos los registros ({total_available}) ya han sido procesados. No hay registros pendientes.\n")
            return summary

        records_to_process = target_pool if process_all else (min(target_pool, max_records) if max_records else target_pool)
        summary.total_records = records_to_process

        valid_pct = (valid_count / total_available * 100) if total_available else 0
        obs_pct = (observed_count / total_available * 100) if total_available else 0
        pend_pct = (pending_count / total_available * 100) if total_available else 0

        if RICH_AVAILABLE and console:
            console.rule(f"[bold cyan]Pipeline ETL In-Place [{self.schema}.{self.table}] (Reanudación Automática)[/bold cyan]")
            console.print(
                f"Esquema Activo: [cyan]{self.schema}[/cyan] | Tabla: [yellow]{self.table}[/yellow]\n"
                f"📊 Estado BD: Total: [bold]{total_available}[/bold] | "
                f"✅ Válidos: [green]{valid_count} ({valid_pct:.1f}%)[/green] | "
                f"⚠️ Observados: [yellow]{observed_count} ({obs_pct:.1f}%)[/yellow] | "
                f"⏳ Pendientes: [cyan]{pending_count} ({pend_pct:.1f}%)[/cyan]\n"
                f"🚀 A Procesar: [bold green]{records_to_process}[/bold green] (Filtro: [magenta]{filter_mode.upper()}[/magenta]) | "
                f"Tamaño Lote: [blue]{self.batch_size}[/blue]\n"
            )
        else:
            print(f"\n=== Pipeline ETL In-Place [{self.schema}.{self.table}] (Reanudación Automática) ===")
            print(f"Total: {total_available} | Válidos: {valid_count} | Observados: {observed_count} | Pendientes: {pending_count}")
            print(f"A Procesar: {records_to_process} | Filtro: {filter_mode} | Lote: {self.batch_size}\n")
        sys.stdout.flush()

        processed_in_run = 0
        current_index = 0

        while processed_in_run < records_to_process:
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
                    current_index += 1
                    try:
                        # Indicador visual inmediato de inicio de análisis
                        if RICH_AVAILABLE and console:
                            console.print(
                                f"[dim]⏳ [{current_index}/{records_to_process}] Analizando ID {rec_raw.id_licencia}: \"{rec_raw.emp_direccion or 'VACÍO'}\"...[/dim]"
                            )
                        else:
                            print(f"⏳ [{current_index}/{records_to_process}] Analizando ID {rec_raw.id_licencia}...")
                        sys.stdout.flush()

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

                        # Mostrar seguimiento visual en vivo al instante
                        self._log_record_progress(
                            index=current_index,
                            total=records_to_process,
                            raw_text=rec_raw.emp_direccion,
                            destino=rec_dest,
                            success=is_success,
                        )
                    except Exception as rec_err:
                        logger.error("Error procesando registro %d: %s", rec_raw.id_licencia, rec_err)
                        summary.failed_records += 1
                        summary.processed_records += 1

                processed_in_run += len(batch_raw)

            except Exception as e:
                logger.error("Fallo durante la extracción del lote en offset %d: %s", fetch_offset, e)
                summary.failed_records += limit
                processed_in_run += limit

        return summary

