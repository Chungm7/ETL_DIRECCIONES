"""Interfaz de consola (CLI / TUI) para administración del ETL y pruebas de Ollama.

Permite ejecutar acciones interactivas mediante un menú visual con Rich o mediante comandos CLI.
Cuenta con fallback automático a consola estándar si Rich no estuviese instalado.
"""

import argparse
import json
import sys
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt
    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

from src.config.settings import get_settings
from src.config.logging_config import setup_logging
from src.services.ollama_service import OllamaService
from src.services.db_service import DatabaseService
from src.pipelines.etl_pipeline import ETLPipeline


def _print_panel(title: str, text: str) -> None:
    """Imprime un panel formateado con Rich o con caracteres ASCII si Rich no está disponible."""
    if RICH_AVAILABLE and console:
        console.print(Panel.fit(f"[bold cyan]{title}[/bold cyan]\n{text}", border_style="cyan"))
    else:
        print("\n" + "=" * 60)
        print(title)
        print(text)
        print("=" * 60)


def show_configuration_panel() -> None:
    """Muestra la configuración activa cargada desde las variables de entorno."""
    settings = get_settings()

    if RICH_AVAILABLE and console:
        table = Table(title="🔧 Configuración Activa del Sistema", show_header=True, header_style="bold cyan")
        table.add_column("Categoría", style="bold yellow", width=25)
        table.add_column("Parámetro (.env)", style="green", width=25)
        table.add_column("Valor Actual", style="white")

        table.add_row("Conexión BD", "DB_HOST:DB_PORT", f"{settings.db.host}:{settings.db.port}")
        table.add_row("Conexión BD", "DB_NAME", settings.db.name)
        table.add_row("Conexión BD", "DB_USER", settings.db.user)

        table.add_row("Tabla Direcciones (In-Place)", "DB_SCHEMA", settings.db.schema)
        table.add_row("Tabla Direcciones (In-Place)", "DB_TABLE", settings.db.table)
        table.add_row("Tabla Direcciones (In-Place)", "DB_ID_COL (PK)", settings.db.id_col)
        table.add_row("Tabla Direcciones (In-Place)", "DB_DIR_COL", settings.db.dir_col)

        table.add_row("Catálogos Categorizables", "DB_TABLE_TIPO_VIA", settings.db.table_tipo_via)
        table.add_row("Catálogos Categorizables", "DB_TABLE_TIPO_ZONA", settings.db.table_tipo_zona)
        table.add_row("Tablas Maestras Físicas", "DB_TABLE_VIAS", f"{settings.db.table_vias} (3,024 vías Chiclayo)")
        table.add_row("Tablas Maestras Físicas", "DB_TABLE_ZONAS", f"{settings.db.table_zonas} (461 zonas Chiclayo)")

        cols_str = (
            f"{settings.db.col_id_via}, {settings.db.col_tipo_via}, {settings.db.col_nom_via}, {settings.db.col_num_via}, "
            f"{settings.db.col_id_zona}, {settings.db.col_tipo_zona}, {settings.db.col_nom_zona}, {settings.db.col_manzana}, "
            f"{settings.db.col_lote}, {settings.db.col_slote}, {settings.db.col_referencia}"
        )
        table.add_row("Columnas Agregadas In-Place", "Campos Normalizados (11)", cols_str)

        table.add_row("IA Local (Ollama)", "OLLAMA_BASE_URL", settings.ollama.base_url)
        table.add_row("IA Local (Ollama)", "OLLAMA_MODEL", settings.ollama.model)
        table.add_row("IA Local (Ollama)", "Timeout / Temp", f"{settings.ollama.timeout}s / {settings.ollama.temperature}")

        table.add_row("Pipeline ETL", "Método Oficial Único", f"{settings.etl.mode} (In-Place / Conserva IDs)")
        table.add_row("Pipeline ETL", "Tamaño de Lote", str(settings.etl.batch_size))
        table.add_row("Pipeline ETL", "Uso de IA Habilitado", str(settings.etl.use_ai_parser))

        console.print(table)
    else:
        print("\n" + "=" * 60)
        print("🔧 CONFIGURACIÓN ACTIVA DEL SISTEMA (.env)")
        print("=" * 60)
        print(f"Base de Datos       : {settings.db.host}:{settings.db.port}/{settings.db.name}")
        print(f"Tabla Direcciones   : {settings.db.schema}.{settings.db.table} [ID: {settings.db.id_col}, Texto: {settings.db.dir_col}]")
        print(f"Catálogos           : {settings.db.table_tipo_via}, {settings.db.table_tipo_zona}, {settings.db.table_vias}, {settings.db.table_zonas}")
        print(f"Ollama URL / Modelo : {settings.ollama.base_url} ({settings.ollama.model})")
        print(f"Método ETL / Lote   : {settings.etl.mode} (In-Place) / {settings.etl.batch_size}")
        print("=" * 60)


def cmd_check_ollama() -> None:
    """Verifica el estado de conexión con el servicio externo de Ollama y ejecuta una prueba en vivo."""
    settings = get_settings()
    _print_panel(
        "🔍 DIAGNÓSTICO EN VIVO DE IA (OLLAMA / MODELO)",
        f"URL: {settings.ollama.base_url} | Modelo Configurado: {settings.ollama.model}",
    )

    service = OllamaService(settings.ollama)

    print("Verificando servidor y realizando prueba de inferencia en tiempo real...")
    live_test = service.test_model_inference()

    if live_test["connected"]:
        print("✅ Conexión con el servidor Ollama: ESTABLECIDA")
        
        # Mostrar modelos instalados
        conn_status = service.check_connection()
        if RICH_AVAILABLE and console:
            table = Table(title="Modelos Instalados en Ollama", show_header=True)
            table.add_column("Modelo", style="white")
            table.add_column("Seleccionado", justify="center")

            for m in conn_status.get("available_models", []):
                is_target = m == settings.ollama.model or m.startswith(settings.ollama.model + ":")
                indicator = "👉 [bold green]ACTIVO[/bold green]" if is_target else "-"
                table.add_row(m, indicator)
            console.print(table)
            console.print()
        else:
            print("Modelos disponibles:", conn_status.get("available_models", []))

        # Estado del modelo
        if live_test["model_ready"]:
            if RICH_AVAILABLE and console:
                console.print(Panel(
                    f"[bold green]🎉 EL MODELO '{settings.ollama.model}' ESTÁ OPERATIVO Y RESPONDIENDO[/bold green]\n\n"
                    f"⏱️  [bold]Latencia de Inferencia:[/bold] [cyan]{live_test['latency_seconds']} segundos[/cyan]\n"
                    f"💬 [bold]Mensaje:[/bold] {live_test['message']}",
                    title="[bold green]✅ PRUEBA DE INFERENCIA EXITOSA[/bold green]",
                    border_style="green",
                ))

                ext = live_test["extracted"]
                if ext:
                    t_ext = Table(title="Desglose de Prueba de Fuego ('CALLE BALTA N° 520 - CHICLAYO')", show_header=True)
                    t_ext.add_column("Campo", style="bold yellow")
                    t_ext.add_column("Valor Extraído por el Modelo", style="green")
                    t_ext.add_row("tipo_via_detectado", str(ext.tipo_via_detectado or '-'))
                    t_ext.add_row("nom_via", str(ext.nom_via or '-'))
                    t_ext.add_row("num_via", str(ext.num_via or '-'))
                    t_ext.add_row("tipo_zona_detectada", str(ext.tipo_zona_detectada or '-'))
                    t_ext.add_row("nom_zona", str(ext.nom_zona or '-'))
                    t_ext.add_row("manzana", str(ext.manzana or '-'))
                    t_ext.add_row("lote", str(ext.lote or '-'))
                    t_ext.add_row("slote", str(ext.slote or '-'))
                    t_ext.add_row("referencia", str(ext.referencia or '-'))
                    t_ext.add_row("confianza", str(ext.confianza or '-'))
                    console.print(t_ext)
            else:
                print(f"🎉 Modelo '{settings.ollama.model}' OPERATIVO (Latencia: {live_test['latency_seconds']}s)")
                print(f"Resultado de prueba: {live_test['extracted']}")
        else:
            print(f"\n⚠️ El servidor respondió pero el modelo '{settings.ollama.model}' NO generó inferencia.")
            print(f"   Causa: {live_test['error'] or live_test['message']}")
            print(f"   Asegúrate de que el modelo esté cargado o ejecuta: ollama run {settings.ollama.model}")
    else:
        print("❌ Conexión con el servidor Ollama: FALLÓ (Desconectado o apagado)")
        print(f"Detalle: {live_test['error'] or live_test['message']}")
        print(
            "\n💡 Sugerencias:\n"
            "   1. Comprueba que Ollama esté corriendo en la URL configurada (.env).\n"
            "   2. Si es una máquina remota, verifica que el puerto 11434 esté abierto.\n"
            "   3. Si el modelo patroclo está apagado, enciéndelo antes de iniciar el ETL para máxima precisión."
        )


def cmd_check_db(schema: Optional[str] = None) -> None:
    """Verifica el estado de conexión con PostgreSQL e inspecciona esquemas y tablas."""
    settings = get_settings()
    active_schema = schema or settings.db.schema

    _print_panel(
        "🔍 DIAGNÓSTICO DE POSTGRESQL (MULTI-SCHEMA)",
        f"Host: {settings.db.host}:{settings.db.port} | BD: {settings.db.name} | Esquema Activo: {active_schema}",
    )

    db_service = DatabaseService(settings.db)
    status = db_service.check_connection(schema=active_schema)

    if status["connected"]:
        print("✅ Estado de conexión: CONECTADO\n")

        if RICH_AVAILABLE and console:
            # 1. Esquemas de aplicación detectados en la BD
            if status.get("available_schemas"):
                schema_table = Table(title="📦 Esquemas de Aplicación Detectados en PostgreSQL", show_header=True, header_style="bold cyan")
                schema_table.add_column("Esquema", style="bold yellow")
                schema_table.add_column("Estado", justify="center")

                for sch in status["available_schemas"]:
                    is_active = sch == active_schema
                    indicator = "👉 [bold green]ACTIVO[/bold green]" if is_active else "[dim]Disponible[/dim]"
                    schema_table.add_row(sch, indicator)
                console.print(schema_table)
                console.print()

            # 2. Estado de tablas en el esquema examinado
            table = Table(title=f"📋 Entidades en Esquema '{active_schema}'", show_header=True, header_style="bold magenta")
            table.add_column("Entidad", style="bold")
            table.add_column("Esquema", style="cyan")
            table.add_column("Tabla Configurada", style="yellow")
            table.add_column("¿Existe en BD?", justify="center")

            src_status = "✅ SÍ" if status["table_exists"] else "❌ NO (Se creará en ETL o Staging)"
            table.add_row("Tabla de Direcciones", active_schema, settings.db.table, src_status)

            via_exists = settings.db.table_tipo_via in status["catalogs_found"]
            zona_exists = settings.db.table_tipo_zona in status["catalogs_found"]
            table.add_row("Catálogo Tipos Vía", active_schema, settings.db.table_tipo_via, "✅ SÍ" if via_exists else "⚠️ NO (Se auto-crea en ETL)")
            table.add_row("Catálogo Tipos Zona", active_schema, settings.db.table_tipo_zona, "✅ SÍ" if zona_exists else "⚠️ NO (Se auto-crea en ETL)")

            console.print(table)
        else:
            print(f"Esquemas disponibles en BD: {status.get('available_schemas', [])}")
            print(f"Tabla Direcciones ({active_schema}.{settings.db.table}): {'Existe' if status['table_exists'] else 'No existe'}")
            print(f"Catálogos encontrados en '{active_schema}': {status['catalogs_found']}")
    else:
        print("❌ Estado de conexión: FALLÓ")
        print(f"Detalle: {status['message']}")


def cmd_init_ddl() -> None:
    """Ejecuta la inicialización de tablas maestras y catálogos en el esquema configurado."""
    settings = get_settings()
    active_schema = settings.db.schema
    _print_panel(
        "🏗️ INICIALIZACIÓN DE TABLAS MAESTRAS Y CATÁLOGOS",
        f"Esquema Activo: {active_schema}",
    )

    db_service = DatabaseService(settings.db)
    print(f"Examinando y sembrando catálogos en esquema '{active_schema}'...")
    res = db_service.ensure_catalogs_exist(schema=active_schema)
    print("✅ Catálogos de vías y zonas examinados/sincronizados exitosamente:")
    for cat_name, info in res.items():
        print(f"   - {cat_name}: Creada={info['table_created']}, Agregados={info['added_records']}, Total={info['total_records']}")


def cmd_test_ai(address: Optional[str] = None) -> None:
    """Prueba la extracción de componentes de una dirección con Ollama."""
    default_addr = "URB. LOS PRECURSORES CA. MOISES R. VALIENTE N 349"
    if address:
        test_address = address
    elif RICH_AVAILABLE and console:
        test_address = Prompt.ask("\nIngresa la dirección a evaluar", default=default_addr)
    else:
        user_input = input(f"\nIngresa la dirección a evaluar [{default_addr}]: ").strip()
        test_address = user_input if user_input else default_addr

    print(f"\nDirección de prueba: \"{test_address}\"")
    from src.transformers.ai_parser import AIAddressParser
    from src.models.direccion_origen import DireccionOrigen
    from src.transformers.catalog_matcher import CatalogMatcher

    parser = AIAddressParser()
    origen = DireccionOrigen(id_licencia=1, emp_direccion=test_address)

    print("Procesando con modelo de IA y motor de normalización...")
    destino = parser.parse(origen)

    via_nombre = CatalogMatcher.get_via_name(destino.tipo_via)
    zona_nombre = CatalogMatcher.get_zona_name(destino.tipo_zona)

    print("\n✅ Resultado de Normalización:")
    if RICH_AVAILABLE and console:
        t = Table(title="Desglose Normalizado", show_header=True, header_style="bold cyan")
        t.add_column("Campo Normalizado", style="bold yellow")
        t.add_column("Valor Asignado", style="green")
        t.add_column("Catálogo Oficial", style="cyan")

        t.add_row("tipo_via", str(destino.tipo_via or 'null'), via_nombre)
        t.add_row("nom_via", destino.nom_via or 'null', "-")
        t.add_row("num_via", destino.num_via or 'null', "-")
        t.add_row("tipo_zona", str(destino.tipo_zona or 'null'), zona_nombre)
        t.add_row("nom_zona", destino.nom_zona or 'null', "-")
        t.add_row("manzana", destino.manzana or 'null', "-")
        t.add_row("lote", destino.lote or 'null', "-")
        t.add_row("slote", destino.slote or 'null', "(Interior/Sublote)")
        t.add_row("referencia", destino.referencia or 'null', "(Hito / Referencia)")

        console.print(t)
    else:
        print(f"  tipo_via  : {destino.tipo_via} ({via_nombre})")
        print(f"  nom_via   : {destino.nom_via}")
        print(f"  num_via   : {destino.num_via}")
        print(f"  tipo_zona : {destino.tipo_zona} ({zona_nombre})")
        print(f"  nom_zona  : {destino.nom_zona}")
        print(f"  manzana   : {destino.manzana}")
        print(f"  lote      : {destino.lote}")
        print(f"  slote     : {destino.slote}")
        print(f"  referencia: {destino.referencia}")


def cmd_catalog_list() -> None:
    """Lista los catálogos y diccionarios maestros cargados desde los archivos JSON."""
    from src.catalogs.catalog_manager import CatalogManager

    summary = CatalogManager.get_summary()

    _print_panel(
        "📚 CATÁLOGOS Y DICCIONARIOS MAESTROS (CAPA JSON)",
        f"Ubicación Vías : {summary['vias_file']}\n"
        f"Ubicación Zonas: {summary['zonas_file']}\n"
        f"Total Vías: {summary['total_vias']} | Total Zonas: {summary['total_zonas']}",
    )

    vias = CatalogManager.get_vias_catalog()
    zonas = CatalogManager.get_zonas_catalog()

    if RICH_AVAILABLE and console:
        # Tabla de Vías
        t_vias = Table(title=f"🛣️ Tipos de Vía ({len(vias)} registros)", show_header=True)
        t_vias.add_column("ID", style="bold cyan", width=5)
        t_vias.add_column("Nombre Oficial", style="bold yellow", width=20)
        t_vias.add_column("Abrev.", style="green", width=10)
        t_vias.add_column("Sinónimos y Variantes", style="white")

        for v in vias:
            t_vias.add_row(str(v["id"]), v["nombre"], v.get("abreviatura", ""), ", ".join(v.get("sinonimos", [])))
        console.print(t_vias)
        console.print()

        # Tabla de Zonas
        t_zonas = Table(title=f"🏙️ Tipos de Zona ({len(zonas)} registros)", show_header=True)
        t_zonas.add_column("ID", style="bold cyan", width=5)
        t_zonas.add_column("Nombre Oficial", style="bold yellow", width=30)
        t_zonas.add_column("Abrev.", style="green", width=12)
        t_zonas.add_column("Sinónimos y Variantes", style="white")

        for z in zonas:
            t_zonas.add_row(str(z["id"]), z["nombre"], z.get("abreviatura", ""), ", ".join(z.get("sinonimos", [])))
        console.print(t_zonas)
    else:
        print(f"\n--- 🛣️ Tipos de Vía ({len(vias)}) ---")
        for v in vias:
            print(f"[{v['id']}] {v['nombre']} ({v.get('abreviatura', '')}) -> {', '.join(v.get('sinonimos', []))}")
        print(f"\n--- 🏙️ Tipos de Zona ({len(zonas)}) ---")
        for z in zonas:
            print(f"[{z['id']}] {z['nombre']} ({z.get('abreviatura', '')}) -> {', '.join(z.get('sinonimos', []))}")


def cmd_catalog_add_via(nombre: str, abreviatura: Optional[str] = None, sinonimos: Optional[str] = None) -> None:
    """Agrega un nuevo tipo de vía al catálogo JSON sin tocar código fuente."""
    from src.catalogs.catalog_manager import CatalogManager

    syn_list = [s.strip() for s in sinonimos.split(",") if s.strip()] if sinonimos else None
    res = CatalogManager.add_tipo_via(nombre=nombre, abreviatura=abreviatura, sinonimos=syn_list)
    if res["success"]:
        print(f"\n✅ {res['message']} (Total vías: {res['total_records']})\n")
    else:
        print(f"\n⚠️ {res['message']}\n")


def cmd_catalog_add_zona(nombre: str, abreviatura: Optional[str] = None, sinonimos: Optional[str] = None) -> None:
    """Agrega un nuevo tipo de zona al catálogo JSON sin tocar código fuente."""
    from src.catalogs.catalog_manager import CatalogManager

    syn_list = [s.strip() for s in sinonimos.split(",") if s.strip()] if sinonimos else None
    res = CatalogManager.add_tipo_zona(nombre=nombre, abreviatura=abreviatura, sinonimos=syn_list)
    if res["success"]:
        print(f"\n✅ {res['message']} (Total zonas: {res['total_records']})\n")
    else:
        print(f"\n⚠️ {res['message']}\n")


def catalog_menu() -> None:
    """Submenú interactivo para visualizar y agregar vías o zonas dinámicamente."""
    from src.catalogs.catalog_manager import CatalogManager

    while True:
        summary = CatalogManager.get_summary()
        print("\n" + "=" * 60)
        print("      📚 GESTIÓN DE CATÁLOGOS Y DICCIONARIOS (CAPA JSON)")
        print(f"      Total Vías: {summary['total_vias']} | Total Zonas: {summary['total_zonas']}")
        print("=" * 60)
        print("1. 📋 Listar tipos de vía y zona actuales")
        print("2. ➕ Agregar nuevo Tipo de Zona (ej. sumar zonas 29, 30, ...)")
        print("3. ➕ Agregar nuevo Tipo de Vía")
        print("0. 🔙 Volver al menú principal")
        print("-" * 60)

        if RICH_AVAILABLE and console:
            sub_choice = Prompt.ask("Selecciona una opción", choices=["0", "1", "2", "3"], default="1")
        else:
            sub_choice = input("Selecciona una opción [1]: ").strip() or "1"

        if sub_choice == "1":
            cmd_catalog_list()
        elif sub_choice == "2":
            if RICH_AVAILABLE and console:
                nom = Prompt.ask("Nombre de la nueva Zona (ej. PARQUE INDUSTRIAL)").strip()
                abr = Prompt.ask("Abreviatura (ej. P.I.)").strip()
                syn = Prompt.ask("Sinónimos separados por coma (opcional, Enter para omitir)").strip()
            else:
                nom = input("Nombre de la nueva Zona (ej. PARQUE INDUSTRIAL): ").strip()
                abr = input("Abreviatura (ej. P.I.): ").strip()
                syn = input("Sinónimos separados por coma (opcional): ").strip()

            if nom:
                cmd_catalog_add_zona(nombre=nom, abreviatura=abr or None, sinonimos=syn or None)
            else:
                print("Operación cancelada: El nombre no puede estar vacío.")
        elif sub_choice == "3":
            if RICH_AVAILABLE and console:
                nom = Prompt.ask("Nombre de la nueva Vía (ej. BOULEVARD)").strip()
                abr = Prompt.ask("Abreviatura (ej. BLVD.)").strip()
                syn = Prompt.ask("Sinónimos separados por coma (opcional, Enter para omitir)").strip()
            else:
                nom = input("Nombre de la nueva Vía (ej. BOULEVARD): ").strip()
                abr = input("Abreviatura (ej. BLVD.): ").strip()
                syn = input("Sinónimos separados por coma (opcional): ").strip()

            if nom:
                cmd_catalog_add_via(nombre=nom, abreviatura=abr or None, sinonimos=syn or None)
            else:
                print("Operación cancelada: El nombre no puede estar vacío.")
        elif sub_choice == "0":
            break


def cmd_run_etl(

    schema: Optional[str] = None,
    limit: Optional[int] = None,
    batch_size: Optional[int] = None,
    mode: Optional[str] = None,
    require_ai: bool = False,
) -> None:
    """Ejecuta el pipeline ETL en su método único In-Place sobre el esquema seleccionado."""
    settings = get_settings()
    active_schema = schema or settings.db.schema
    active_table = settings.db.table

    _print_panel(
        "🚀 EJECUCIÓN DEL PIPELINE ETL MPCH (MÉTODO IN-PLACE ÚNICO)",
        f"Esquema: {active_schema}\n"
        f"Tabla Objetivo: {active_schema}.{active_table} (Modificación en sitio preservando IDs)\n"
        f"Lote: {batch_size or settings.etl.batch_size} | Límite: {limit or 'Todos'} | Requerir IA: {'Sí' if require_ai else 'No'}",
    )

    pipeline = ETLPipeline(
        schema=active_schema,
        table=active_table,
        batch_size=batch_size,
        require_ai=require_ai,
    )
    summary = pipeline.run(max_records=limit)

    total_proc = max(1, summary.processed_records)
    pct_ai = (summary.ai_records / total_proc) * 100
    pct_hybrid = (summary.hybrid_records / total_proc) * 100
    pct_heur = (summary.heuristic_records / total_proc) * 100

    if RICH_AVAILABLE and console:
        table = Table(title="📊 Resumen Final de Ejecución", show_header=True)
        table.add_column("Métrica", style="bold")
        table.add_column("Detalle / Cantidad", style="green", justify="right")

        table.add_row("Esquema Procesado", active_schema)
        table.add_row("Método Utilizado", "In-Place (Modificación en sitio preservando IDs)")
        table.add_row("Estado Motor de IA", summary.ai_status_message)
        table.add_row("Total Registros a Procesar", str(summary.total_records))
        table.add_row("Registros Procesados", str(summary.processed_records))
        table.add_row("Cargados Exitosamente", str(summary.successful_records))
        table.add_row("Registros Fallidos", str(summary.failed_records))
        table.add_row("🤖 Normalizados con IA (Pura)", f"{summary.ai_records} ({pct_ai:.1f}%)")
        table.add_row("🧩 Normalizados Híbridos (IA + Heurística)", f"{summary.hybrid_records} ({pct_hybrid:.1f}%)")
        table.add_row("⚠️ Normalizados con Heurística (Fallback)", f"{summary.heuristic_records} ({pct_heur:.1f}%)")
        console.print(table)
    else:
        print("\n" + "=" * 50)
        print("📊 RESUMEN FINAL DE EJECUCIÓN")
        print(f"Esquema Procesado       : {active_schema}")
        print("Método Utilizado        : In-Place (Modificación en sitio preservando IDs)")
        print(f"Estado Motor IA         : {summary.ai_status_message}")
        print(f"Total a Procesar        : {summary.total_records}")
        print(f"Procesados              : {summary.processed_records}")
        print(f"Cargados Exitosamente   : {summary.successful_records}")
        print(f"Registros Fallidos      : {summary.failed_records}")
        print(f"Normalizados con IA     : {summary.ai_records} ({pct_ai:.1f}%)")
        print(f"Normalizados Híbridos   : {summary.hybrid_records} ({pct_hybrid:.1f}%)")
        print(f"Normalizados Heurística : {summary.heuristic_records} ({pct_heur:.1f}%)")
        print("=" * 50)


def interactive_menu() -> None:
    """Menú interactivo visual de consola con soporte para Rich y cambio de esquema."""
    settings = get_settings()
    active_schema = settings.db.schema
    db_service = DatabaseService(settings.db)

    while True:
        print("\n" + "=" * 65)
        print("      SISTEMA ETL DE MIGRACIÓN DE DIRECCIONES - MPCH")
        print("      Normalización Catastral asistida con IA Local (Ollama)")
        print(f"      📍 Esquema Activo: [{active_schema}] | BD: [{settings.db.name}]")
        print("=" * 65)
        print("1. 📊 Ver Configuración Activa (.env / Schemas / Tablas)")
        print("2. 🩺 Diagnóstico de Conexiones (PostgreSQL y Prueba en Vivo IA)")
        print(f"3. ⚡ Ejecutar ETL In-Place en [{active_schema}] (Conserva IDs y catálogos)")
        print("4. 🔄 Cambiar Esquema Activo de Trabajo (public, schema_solo_tabla, etc.)")
        print("5. 🤖 Probar Inferencia y Salud del Modelo IA (patroclo)")
        print("6. 📚 Gestionar Catálogos y Diccionarios (Vías y Zonas en JSON)")
        print("0. 🚪 Salir")
        print("-" * 65)

        if RICH_AVAILABLE and console:
            choice = Prompt.ask("Selecciona una opción", choices=["0", "1", "2", "3", "4", "5", "6"], default="3")
        else:
            choice = input("Selecciona una opción [3]: ").strip() or "3"

        if choice == "1":
            show_configuration_panel()
        elif choice == "2":
            cmd_check_db(schema=active_schema)
            print()
            cmd_check_ollama()
        elif choice == "3":
            # Comprobación previa de la IA antes de pedir registros
            ollama_svc = OllamaService(settings.ollama)
            ai_test = ollama_svc.test_model_inference()

            if not ai_test["model_ready"]:
                if RICH_AVAILABLE and console:
                    console.print(Panel(
                        f"[bold yellow]⚠️ ADVERTENCIA: El modelo IA '{settings.ollama.model}' no está respondiendo.[/bold yellow]\n\n"
                        f"Detalle: {ai_test['error'] or ai_test['message']}\n"
                        f"[white]Sin la IA, el ETL operará con el motor [bold red]HEURÍSTICO de contingencia[/bold red], "
                        f"lo cual puede reducir la precisión en direcciones complejas.[/white]",
                        title="[bold red]⚠️ MOTOR IA INACCESIBLE[/bold red]",
                        border_style="yellow",
                    ))
                    continuar = Prompt.ask(
                        "¿Deseas continuar en modo solo Heurístico o cancelar para encender la IA? (s/n)",
                        choices=["s", "n", "si", "no"],
                        default="n",
                    )
                else:
                    print(f"\n⚠️ ADVERTENCIA: El modelo IA '{settings.ollama.model}' no responde.")
                    print("Sin la IA, el ETL operará en modo HEURÍSTICO de menor precisión.")
                    continuar = input("¿Deseas continuar de todas formas? (s/n) [n]: ").strip().lower() or "n"

                if continuar not in ("s", "si"):
                    print("Operación cancelada. Enciende el modelo IA (ej. patroclo) y vuelve a intentar.\n")
                    continue

            prompt_msg = f"¿Cuántos registros procesar en '{active_schema}'? (Enter para todos): "
            if RICH_AVAILABLE and console:
                limit_str = Prompt.ask(f"¿Cuántos registros procesar en '{active_schema}'? (Enter para todos)", default="")
            else:
                limit_str = input(prompt_msg).strip()
            limit = int(limit_str) if limit_str.strip().isdigit() else None
            cmd_run_etl(schema=active_schema, limit=limit)
        elif choice == "4":
            available = db_service.get_available_schemas()
            print(f"\nEsquemas de aplicación disponibles: {', '.join(available) if available else 'public'}")
            if RICH_AVAILABLE and console:
                new_sch = Prompt.ask("Ingresa el nuevo esquema activo", default=active_schema)
            else:
                new_sch = input(f"Ingresa el nuevo esquema activo [{active_schema}]: ").strip() or active_schema
            active_schema = new_sch.strip()
            print(f"✅ Esquema activo cambiado a: '{active_schema}'")
        elif choice == "5":
            cmd_check_ollama()
        elif choice == "6":
            catalog_menu()
        elif choice == "0":
            print("\n¡Hasta pronto!\n")
            break


def main() -> None:
    """Punto de entrada con soporte para comandos de terminal y menú interactivo."""
    setup_logging()

    parser = argparse.ArgumentParser(
        description="CLI del Proyecto ETL de Migración de Direcciones - MPCH"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ejecutar")

    subparsers.add_parser("menu", help="Abre el menú interactivo visual")
    subparsers.add_parser("config", help="Muestra la configuración activa")
    subparsers.add_parser("check-ollama", help="Verifica la conexión con el servidor local Ollama y prueba el modelo")

    check_db_parser = subparsers.add_parser("check-db", help="Verifica la conexión con PostgreSQL")
    check_db_parser.add_argument("--schema", type=str, default=None, help="Esquema específico a inspeccionar")

    subparsers.add_parser("init-db", help="Crea tablas maestras de vías y zonas en el schema destino")

    test_ai_parser = subparsers.add_parser("test-ai", help="Prueba la extracción de una dirección con Ollama")
    test_ai_parser.add_argument("--address", type=str, default=None, help="Texto de la dirección")

    # Subcomandos para gestión de catálogos y diccionarios
    cat_parser = subparsers.add_parser("catalog", help="Gestión de catálogos y diccionarios (vías y zonas en JSON)")
    cat_sub = cat_parser.add_subparsers(dest="catalog_action", help="Acción de catálogo")

    cat_sub.add_parser("list", help="Lista todas las vías y zonas registradas en la capa JSON")

    add_via_p = cat_sub.add_parser("add-via", help="Agrega un nuevo tipo de vía al catálogo JSON")
    add_via_p.add_argument("--nombre", type=str, required=True, help="Nombre oficial de la vía (ej. BOULEVARD)")
    add_via_p.add_argument("--abreviatura", type=str, default=None, help="Abreviatura oficial (ej. BLVD.)")
    add_via_p.add_argument("--sinonimos", type=str, default=None, help="Sinónimos separados por coma")

    add_zona_p = cat_sub.add_parser("add-zona", help="Agrega un nuevo tipo de zona al catálogo JSON (ej. 29, 30...)")
    add_zona_p.add_argument("--nombre", type=str, required=True, help="Nombre oficial de la zona (ej. PARQUE INDUSTRIAL)")
    add_zona_p.add_argument("--abreviatura", type=str, default=None, help="Abreviatura oficial (ej. P.I.)")
    add_zona_p.add_argument("--sinonimos", type=str, default=None, help="Sinónimos separados por coma")

    run_parser = subparsers.add_parser("run", help="Ejecuta el proceso ETL in-place conservando IDs")
    run_parser.add_argument(
        "--schema",
        type=str,
        default=None,
        help="Esquema de base de datos a procesar (por defecto .env)",
    )
    run_parser.add_argument(
        "--mode",
        type=str,
        default="in_place",
        help="Modo de ejecución del ETL (in_place)",
    )
    run_parser.add_argument("--limit", type=int, default=None, help="Límite de registros a procesar")
    run_parser.add_argument("--batch-size", type=int, default=None, help="Tamaño de lote")
    run_parser.add_argument(
        "--require-ai",
        action="store_true",
        default=False,
        help="Falla y detiene la ejecución si el modelo de IA no está disponible en memoria",
    )

    args = parser.parse_args()

    if args.command is None or args.command == "menu":
        interactive_menu()
    elif args.command == "config":
        show_configuration_panel()
    elif args.command == "check-ollama":
        cmd_check_ollama()
    elif args.command == "check-db":
        cmd_check_db(schema=args.schema)
    elif args.command == "init-db":
        cmd_init_ddl()
    elif args.command == "test-ai":
        cmd_test_ai(address=args.address)
    elif args.command == "catalog":
        if getattr(args, "catalog_action", None) == "list" or not getattr(args, "catalog_action", None):
            cmd_catalog_list()
        elif args.catalog_action == "add-via":
            cmd_catalog_add_via(args.nombre, args.abreviatura, args.sinonimos)
        elif args.catalog_action == "add-zona":
            cmd_catalog_add_zona(args.nombre, args.abreviatura, args.sinonimos)
    elif args.command == "run":
        cmd_run_etl(
            schema=args.schema,
            limit=args.limit,
            batch_size=args.batch_size,
            mode=args.mode,
            require_ai=args.require_ai,
        )



if __name__ == "__main__":
    main()
