@echo off
REM ==============================================================================
REM Lanzador de Escritorio Windows: ETL Normalización Catastral MPCH (GUI Desktop)
REM ==============================================================================

echo =================================================================
echo   INICIANDO SISTEMA ETL CATASTRAL MPCH (INTERFAZ GRAFICA)
echo =================================================================

cd /d "%~dp0"

IF EXIST "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python main.py gui %*
pause
