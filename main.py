"""Punto de entrada principal del proyecto ETL de Migración MPCH.

Detecta automáticamente si existe un entorno virtual 'venv' en el proyecto
y lo utiliza para garantizar que todas las librerías requeridas (como 'rich')
estén disponibles sin importar cómo fue invocado el script.
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# 1. Asegurar que el directorio raíz esté en el PYTHONPATH
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 2. Auto-detección y cambio transparente al entorno virtual si estamos en Python global
if sys.platform == "win32":
    venv_python = ROOT_DIR / "venv" / "Scripts" / "python.exe"
else:
    venv_python = ROOT_DIR / "venv" / "bin" / "python"

if venv_python.exists() and sys.prefix == sys.base_prefix:
    # Si el usuario ejecutó 'python main.py' con el python global del sistema,
    # reiniciamos el proceso usando el python de 'venv'
    if sys.platform == "win32":
        import subprocess
        res = subprocess.call([str(venv_python)] + sys.argv[1:])
        sys.exit(res)
    else:
        os.execv(str(venv_python), [str(venv_python)] + sys.argv)

try:
    from src.cli import main
except (ModuleNotFoundError, ImportError) as e:
    print("\n" + "=" * 65)
    print("❌ ERROR DE DEPENDENCIAS O ENTORNO VIRTUAL:")
    print(f"   {e}")
    print("=" * 65)

    is_cross_platform_issue = (
        "pydantic_core" in str(e)
        or "ArgsKwargs" in str(e)
        or (sys.platform == "win32" and (ROOT_DIR / "venv" / "bin").exists() and not (ROOT_DIR / "venv" / "Scripts").exists())
    )

    if is_cross_platform_issue:
        print("⚠️  DIAGNÓSTICO: INCOMPATIBILIDAD DE BINARIOS EN EL ENTORNO VIRTUAL.")
        print("   Se detectó que el entorno 'venv' contiene binarios de otra plataforma (ej. Linux en Windows)")
        print("   o que las librerías C/Rust compiladas (pydantic-core) no coinciden con este sistema.")
        print("\n🔧 SOLUCIÓN RÁPIDA (PowerShell en Windows):")
        print("   1. Remove-Item -Recurse -Force venv")
        print("   2. python -m venv venv")
        print("   3. .\\venv\\Scripts\\Activate.ps1")
        print("   4. pip install --upgrade pip")
        print("   5. pip install -r requirements.txt")
        print("   6. python main.py\n")
        print("   (O ejecuta directamente: .\\run_gui.bat para auto-reparar e iniciar)\n")
    else:
        print("💡 No se encontraron las librerías necesarias.")
        print("   Por favor activa el entorno virtual o instálalas ejecutando:")
        if sys.platform == "win32":
            print("\n   .\\venv\\Scripts\\Activate.ps1")
            print("   pip install -r requirements.txt\n")
            print("   O ejecuta directamente:")
            print("   .\\venv\\Scripts\\python.exe main.py\n")
        else:
            print("\n   source venv/bin/activate")
            print("   pip install -r requirements.txt\n")
            print("   O ejecuta directamente:")
            print("   ./venv/bin/python main.py\n")
    sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            sys.exit(e.code)
        sys.exit(0)
