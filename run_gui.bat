@echo off
REM ==============================================================================
REM Lanzador de Escritorio Windows: ETL Normalización Catastral MPCH (GUI Desktop)
REM ==============================================================================

echo =================================================================
echo   INICIANDO SISTEMA ETL CATASTRAL MPCH (INTERFAZ GRAFICA)
echo =================================================================

cd /d "%~dp0"

REM 1. Deteccion de venv cruzado de Linux en Windows (bin/ sin Scripts/)
IF EXIST "venv\bin" (
    IF NOT EXIST "venv\Scripts\python.exe" (
        echo [AVISO] Se detecto un entorno virtual creado en Linux/Mac dentro de Windows.
        echo Limpiando entorno incompatible para recrear binarios nativos de Windows...
        rmdir /s /q venv
    )
)

REM 2. Crear entorno virtual si no existe
IF NOT EXIST "venv\Scripts\python.exe" (
    echo [INFO] Creando entorno virtual 'venv' para Windows...
    python -m venv venv
    IF ERRORLEVEL 1 (
        echo [ERROR] No se pudo crear el entorno virtual. Asegurate de tener Python instalado y en el PATH.
        pause
        exit /b 1
    )
    echo [INFO] Instalando dependencias de requirements.txt...
    venv\Scripts\python.exe -m pip install --upgrade pip
    venv\Scripts\python.exe -m pip install -r requirements.txt
)

REM 3. Validar integridad de librerias nativas (ej. pydantic_core)
venv\Scripts\python.exe -c "import pydantic" >nul 2>&1
IF ERRORLEVEL 1 (
    echo [AVISO] Se detecto una inconsistencia en las librerias compiladas de Pydantic.
    echo Reinstalando componentes nativos para Windows...
    venv\Scripts\python.exe -m pip install --force-reinstall --no-cache-dir pydantic pydantic-core pydantic-settings
)

IF EXIST "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python main.py gui %*
if ERRORLEVEL 1 (
    echo.
    echo [AVISO] La aplicacion finalizo con errores.
    echo Revisa los mensajes superiores para mayor detalle.
)
pause
