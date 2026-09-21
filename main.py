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
venv_python = ROOT_DIR / "venv" / "bin" / "python"
if venv_python.exists() and sys.prefix == sys.base_prefix:
    # Si el usuario ejecutó 'python main.py' con el python del sistema,
    # reiniciamos el proceso usando el python de 'venv'
    os.execv(str(venv_python), [str(venv_python)] + sys.argv)

try:
    from src.cli import main
except ModuleNotFoundError as e:
    print("\n" + "=" * 65)
    print("❌ ERROR DE DEPENDENCIAS:")
    print(f"   {e}")
    print("=" * 65)
    print("💡 No se encontraron las librerías necesarias.")
    print("   Por favor activa el entorno virtual o instálalas ejecutando:")
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
