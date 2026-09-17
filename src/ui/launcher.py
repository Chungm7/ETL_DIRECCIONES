"""Lanzador de escritorio para la interfaz gráfica del ETL MPCH en ventana autónoma."""

import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Optional

import uvicorn

logger = logging.getLogger("etl_mpch.gui_launcher")


def find_free_port(start_port: int = 8080, max_attempts: int = 20) -> int:
    """Encuentra un puerto TCP libre a partir de start_port."""
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start_port


def launch_desktop_window(url: str) -> None:
    """Lanza la URL en modo ventana de aplicación independiente (estilo ejecutable de escritorio)."""
    # 1. Intento Chrome / Chromium / Brave / Edge (soporta flag --app=URL para modo ventana limpia sin barra de URL)
    app_browsers = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "brave-browser",
        "microsoft-edge",
    ]
    for browser in app_browsers:
        browser_path = shutil.which(browser)
        if browser_path:
            try:
                subprocess.Popen(
                    [browser_path, f"--app={url}", "--new-window"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                logger.info("Ventana de aplicación lanzada con %s en modo --app.", browser)
                return
            except Exception as e:
                logger.debug("No se pudo iniciar %s en modo app: %s", browser, e)

    # 2. Intento Firefox en nueva ventana
    firefox_path = shutil.which("firefox")
    if firefox_path:
        try:
            subprocess.Popen(
                [firefox_path, "--new-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Ventana de aplicación lanzada con Firefox.")
            return
        except Exception as e:
            logger.debug("No se pudo iniciar Firefox: %s", e)

    # 3. Fallback a navegador por defecto del sistema
    logger.info("Abriendo en navegador predeterminado del sistema...")
    webbrowser.open_new(url)


def start_gui_server(port: int = 8080, open_browser: bool = True, host: str = "127.0.0.1") -> None:
    """Inicia el servidor backend y abre la interfaz gráfica de escritorio."""
    actual_port = find_free_port(start_port=port)
    url = f"http://{host}:{actual_port}"

    print("\n" + "=" * 65)
    print("  🏛️  SISTEMA ETL DE MIGRACIÓN CATASTRAL - MPCH (GUI DESKTOP)")
    print("  Interfaz Gráfica de Control y Visualización con IA Local")
    print("=" * 65)
    print(f"  🚀 Servidor local activo en: {url}")
    print("  Presiona Ctrl+C en esta consola para apagar el servidor.")
    print("=" * 65 + "\n")

    if open_browser:
        # Abrir navegador tras 1.2 segundos para dar tiempo a FastAPI a iniciar
        def _deferred_open():
            time.sleep(1.2)
            launch_desktop_window(url)

        threading.Thread(target=_deferred_open, daemon=True).start()

    from src.ui.server import app

    uvicorn_config = uvicorn.Config(
        app=app,
        host=host,
        port=actual_port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    server.run()


if __name__ == "__main__":
    start_gui_server()
