#!/bin/bash
# ==============================================================================
# Lanzador de Escritorio: ETL Normalización Catastral MPCH (GUI Desktop)
# ==============================================================================

set -e

# Cambiar al directorio del proyecto
cd "$(dirname "$0")"

echo "================================================================="
echo "  🏛️  INICIANDO SISTEMA ETL CATASTRAL MPCH (INTERFAZ GRÁFICA)"
echo "================================================================="

# Activar entorno virtual si existe
if [ -d "venv" ]; then
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
fi

# Iniciar interfaz gráfica en ventana ejecutable
python3 main.py gui "$@"
