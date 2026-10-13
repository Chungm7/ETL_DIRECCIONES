# 🚀 Guía de Inicio y Ejecución Paso a Paso (Linux y Windows)
## Sistema ETL de Normalización y Migración Catastral MPCH (Versión 2.0)

Esta guía detalla de forma didáctica y exhaustiva cómo configurar, desplegar y ejecutar el proyecto **ETL_DIRECCIONES** desde cero tanto en entornos **Linux** como en **Windows**.

---

## 📑 Tabla de Contenidos
1. [Requisitos Previos del Sistema](#1-requisitos-previos-del-sistema)
2. [Paso 1: Clonación y Ubicación del Proyecto](#paso-1-clonación-y-ubicación-del-proyecto)
3. [Paso 2: Creación y Activación del Entorno Virtual (venv)](#paso-2-creación-y-activación-del-entorno-virtual-venv)
4. [Paso 3: Instalación de Dependencias](#paso-3-instalación-de-dependencias)
5. [Paso 4: Configuración de Variables de Entorno (.env)](#paso-4-configuración-de-variables-de-entorno-env)
6. [Paso 5: Puesta en Marcha de Servicios (Docker y Ollama)](#paso-5-puesta-en-marcha-de-servicios-docker-y-ollama)
7. [Paso 6: Inicialización de la Base de Datos V2](#paso-6-inicialización-de-la-base-de-datos-v2)
8. [Paso 7: Métodos de Ejecución del Proyecto](#paso-7-métodos-de-ejecución-del-proyecto)
   - [Opción A: Interfaz Gráfica de Escritorio (GUI / Web Dashboard - Recomendado)](#opción-a-interfaz-gráfica-de-escritorio-gui--web-dashboard)
   - [Opción B: Menú Interactivo en Consola (TUI Rich)](#opción-b-menú-interactivo-en-consola-tui-rich)
   - [Opción C: Ejecución Directa por Línea de Comandos (CLI)](#opción-c-ejecución-directa-por-línea-de-comandos-cli)
9. [Paso 8: Ejecución de Pruebas Automatizadas](#paso-8-ejecución-de-pruebas-automatizadas)
10. [Solución de Problemas Frecuentes (Troubleshooting)](#solución-de-problemas-frecuentes-troubleshooting)
11. [Tabla Resumen Rápida: Linux vs. Windows (Cheat Sheet)](#tabla-resumen-rápida-linux-vs-windows-cheat-sheet)

---

## 1. Requisitos Previos del Sistema

Antes de iniciar, asegúrate de contar con las siguientes herramientas instaladas en tu equipo:

| Herramienta | Versión Mínima | Propósito |
| :--- | :--- | :--- |
| **Python** | `3.10` o superior (Recomendado `3.11` / `3.12`) | Intérprete base del motor ETL |
| **Git** | `2.30+` | Control de versiones del código fuente |
| **Docker & Docker Compose** | Docker v24+ / Compose v2+ | Contenedores de PostgreSQL 16 y pgAdmin 4 |
| **Ollama** | `0.1.30+` | Motor de inferencia local con modelos LLM |

### Instalación de Requisitos en Linux (Ubuntu / Debian / Mint)
```bash
# Actualizar repositorios e instalar Python, pip, venv y curl
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git curl

# Instalar Docker Engine y Docker Compose plugin (si no los tienes instalados):
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# (Cierra e inicia sesión para aplicar permisos de Docker)

# Instalar Ollama local
curl -fsSL https://ollama.com/install.sh | sh
```

### Instalación de Requisitos en Windows
1. **Python 3.11 o 3.12:**
   - Descarga el instalador desde [python.org](https://www.python.org/downloads/windows/).
   - > [!IMPORTANT]
     > En la primera pantalla del instalador, marca obligatoriamente la casilla: **☑ "Add python.exe to PATH"**.
2. **Docker Desktop:**
   - Descarga e instala [Docker Desktop para Windows](https://www.docker.com/products/docker-desktop/) asegurándote de habilitar el backend de **WSL 2**.
3. **Ollama:**
   - Descarga el instalador [OllamaSetup.exe](https://ollama.com/download/windows) e instálalo normalmente. Se ejecutará en la bandeja del sistema (*System Tray*).
4. **Git para Windows:**
   - Descarga desde [git-scm.com](https://git-scm.com/download/win).

---

## Paso 1: Clonación y Ubicación del Proyecto

Abre tu terminal favorita (Bash en Linux, PowerShell o CMD en Windows) y navega al directorio del proyecto:

```bash
# En Linux:
cd ~/IdeaProjects/ETL_DIRECCIONES

# En Windows (PowerShell o CMD):
cd C:\Ruta\A\Tu\Proyecto\ETL_DIRECCIONES
```

Comprueba que te encuentres en la raíz del proyecto verificando la presencia de archivos clave como `main.py`, `requirements.txt` y `docker-compose.yml`:
```bash
# Linux:
ls -la

# Windows (PowerShell):
dir
```

---

## Paso 2: Creación y Activación del Entorno Virtual (venv)

El entorno virtual aísla las librerías del proyecto para evitar conflictos con el sistema operativo.

### 🐧 En Linux / macOS:

#### Si usas Bash o Zsh (Terminal estándar):
```bash
# 1. Crear el entorno virtual en la carpeta 'venv'
python3 -m venv venv

# 2. Activar el entorno virtual
source venv/bin/activate
```
*Sabrás que está activo porque aparecerá `(venv)` al inicio de tu línea de comandos.*

#### 🐟 Si usas Fish shell (Prompt con `❯`):
```fish
# Activar el entorno virtual en Fish:
source venv/bin/activate.fish
```
*(O si prefieres usar Bash temporalmente, escribe `bash` y luego `source venv/bin/activate`).*

---

### 🪟 En Windows (PowerShell):
> [!TIP]
> Si PowerShell muestra un error de seguridad que indica que *la ejecución de scripts está deshabilitada en este sistema*, habilítala temporalmente en tu sesión con:
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

```powershell
# 1. Crear el entorno virtual
python -m venv venv

# 2. Activar el entorno virtual en PowerShell
.\venv\Scripts\Activate.ps1
```

---

### 🪟 En Windows (Símbolo del Sistema / CMD):
```cmd
:: 1. Crear el entorno virtual
python -m venv venv

:: 2. Activar el entorno virtual en CMD
venv\Scripts\activate.bat
```

---

## Paso 3: Instalación de Dependencias

Con el entorno virtual `(venv)` activo, actualiza el gestor `pip` e instala todas las librerías requeridas por el proyecto:

### 🐧 En Linux:
```bash
python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

### 🪟 En Windows (PowerShell o CMD):
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Librerías principales que se instalarán:
- **`fastapi` & `uvicorn`**: Servidor de backend web para la interfaz gráfica y eventos en vivo (SSE).
- **`pydantic` & `pydantic-settings`**: Validación de esquemas y lectura de `.env`.
- **`rich` & `tqdm`**: Menú interactivo TUI y barras de progreso en consola.
- **`sqlalchemy` & `psycopg2-binary`**: Conectores relacionales a PostgreSQL.
- **`pandas`, `openpyxl`, `xlrd`**: Manipulación de datasets y exportación a Excel (.xlsx) y CSV.
- **`ollama` & `httpx`**: Comunicación asíncrona con el motor de IA local.
- **`pytest`**: Suite de pruebas unitarias.

---

## Paso 4: Configuración de Variables de Entorno (.env)

El proyecto incluye una plantilla de configuración `.env.example`. Debes crear tu archivo local `.env`:

### 🐧 En Linux:
```bash
cp .env.example .env
```

### 🪟 En Windows (PowerShell o CMD):
```powershell
copy .env.example .env
```

### 🔍 Parámetros clave dentro de `.env`:
Si utilizas el stack Docker por defecto incluido en el proyecto, los valores iniciales ya están perfectamente configurados:

```ini
# Base de Datos PostgreSQL (Valores por defecto del contenedor Docker)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=bd_mpch
DB_USER=postgres
DB_PASSWORD=postgres

# Esquema y tabla de trabajo a procesar
DB_SCHEMA=public
DB_TABLE=direcciones_actual
DB_ID_COL=id_licencia
DB_DIR_COL=emp_direccion

# Conexión con Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
OLLAMA_TIMEOUT=60
OLLAMA_TEMPERATURE=0.0

# Parámetros del ETL
ETL_MODE=in_place
ETL_BATCH_SIZE=50
ETL_REQUIRE_AI=true
```

---

## Paso 5: Puesta en Marcha de Servicios (Docker y Ollama)

### 1. Iniciar PostgreSQL y pgAdmin con Docker Compose
En la raíz del proyecto, ejecuta:

```bash
# Linux o Windows:
docker compose up -d
```

Verifica que los contenedores estén corriendo y saludables:
```bash
docker compose ps
```
Deberás ver dos contenedores activos:
- **`mpch_postgres`**: PostgreSQL 16 expuesto en el puerto `5432`.
- **`mpch_pgadmin`**: pgAdmin 4 expuesto en el puerto `5050` (acceso web: [http://localhost:5050](http://localhost:5050) con usuario `admin@mpch.gob.pe` y clave `admin`).

---

### 2. Iniciar el Motor de IA Ollama y Descargar el Modelo

1. **Asegurar que Ollama esté corriendo:**
   - **En Linux:** Si está configurado como servicio systemd, ya estará corriendo (`systemctl status ollama`). Si no, ejecútalo en una terminal secundaria con:
     ```bash
     ollama serve
     ```
   - **En Windows:** Abre la aplicación Ollama desde el Menú Inicio. El icono de la llama aparecerá en la bandeja del sistema junto al reloj.

2. **Descargar el modelo LLM:**
   El modelo predeterminado es `llama3` (o puedes usar cualquier modelo ligero compatible como `patroclo-artesano-7b`, `llama3.1`, `qwen2.5:7b`, etc.):
   ```bash
   # En cualquier terminal:
   ollama pull llama3
   ```

3. **Verificar modelos disponibles:**
   ```bash
   ollama list
   ```

4. **Verificar conexión desde el proyecto:**
   ```bash
   # Con el venv activo:
   python main.py check-ollama
   ```
   *Debe responder con `✅ Servidor Ollama: EN LÍNEA` y listar los modelos disponibles.*

---

## Paso 6: Inicialización de la Base de Datos V2

El esquema relacional V2 consta de **11 tablas normalizadas en 3NF**, catálogos oficiales sembrados (2,935 vías y 460 zonas) y la vista consolidada `v_direcciones_v2`.

Aplica el script de creación ejecutando el siguiente comando:

### 🐧 En Linux:
```bash
docker exec -i mpch_postgres psql -U postgres -d bd_mpch < scripts_data_base/06_crear_estructura_v2_normalizada.sql
```

### 🪟 En Windows (PowerShell):
```powershell
Get-Content scripts_data_base\06_crear_estructura_v2_normalizada.sql | docker exec -i mpch_postgres psql -U postgres -d bd_mpch
```

### 🪟 En Windows (CMD):
```cmd
docker exec -i mpch_postgres psql -U postgres -d bd_mpch < scripts_data_base\06_crear_estructura_v2_normalizada.sql
```

> [!NOTE]
> También puedes verificar la conexión a la base de datos en cualquier momento usando el comando de diagnóstico:
> ```bash
> python main.py check-db --schema public
> ```

---

## Paso 7: Métodos de Ejecución del Proyecto

El sistema ofrece 3 formas de uso adaptadas a cualquier necesidad:

### Opción A: Interfaz Gráfica de Escritorio (GUI / Web Dashboard)
*(Método oficial y más cómodo)*

Inicia el lanzador de escritorio:

- **En Linux:**
  ```bash
  # Mediante el script lanzador:
  chmod +x run_gui.sh
  ./run_gui.sh

  # O directamente vía Python:
  python3 main.py gui
  ```

- **En Windows:**
  - Haz **doble clic** en el archivo [run_gui.bat](file:///home/chung/IdeaProjects/ETL_DIRECCIONES/run_gui.bat)
  - O en tu terminal con `venv` activo:
    ```powershell
    python main.py gui
    ```

El sistema abrirá automáticamente una ventana de aplicación o tu navegador web predeterminado en:
👉 **`http://localhost:8080`**

#### 🧭 Flujo del Asistente en 5 Pasos (Wizard):
1. **Paso 1: Diagnóstico de Conexión:** Comprueba en tiempo real la disponibilidad de PostgreSQL y Ollama.
2. **Paso 2: Selección del Modelo de IA:** Detecta automáticamente los modelos instalados en tu Ollama (`llama3`, `patroclo-artesano-7b`, etc.) y te permite seleccionar el deseado.
3. **Paso 3: Selección de Esquema y Tabla:** Elige el esquema (`public`) y la tabla con direcciones crudas a normalizar (ej. `tb_xxx` o `direcciones_actual`).
4. **Paso 4: Mapeo Asistido de Columnas:** Vincula la columna del ID primario, la columna de dirección cruda y llaves de negocio opcionales.
5. **Paso 5: Ejecución y Descarga en Vivo:**
   - Monitoreo en tiempo real con barras de progreso y métricas de registros por segundo.
   - Consola de eventos WebSocket con desglose de esquinas, vías y módulos.
   - **Botones de Descarga en 3 Formatos:**
     - 📄 **Exportar JSON:** Formato jerárquico V2 completo.
     - 📊 **Exportar Excel (XLSX):** Planilla desnormalizada para auditoría.
     - 📑 **Exportar CSV:** Archivo delimitado estándar.

---

### Opción B: Menú Interactivo en Consola (TUI Rich)
Para administrar el sistema mediante un panel interactivo visual en tu terminal:

```bash
# Linux o Windows con (venv) activo:
python main.py menu
```

Te permitirá:
- Ver configuración activa de esquemas y tablas.
- Diagnosticar PostgreSQL y Ollama.
- Cambiar de esquema activo al vuelo.
- Probar inferencia sobre cualquier dirección de texto.
- Gestionar catálogos maestros de vías y zonas.

---

### Opción C: Ejecución Directa por Línea de Comandos (CLI)

Ideal para scripts programados o automatización:

```bash
# 1. Probar la extracción de una dirección aislada:
python main.py test-ai --address "AV. BALTA 123 CHICLAYO"

# 2. Ejecutar el ETL con un límite de prueba de 50 registros:
python main.py run --schema public --limit 50

# 3. Procesar de forma continua toda la tabla hasta agotarla:
python main.py run --schema public --all

# 4. Reprocesar únicamente los registros observados (es_procesado = FALSE):
python main.py run --schema public --reprocess-observed

# 5. Ejecutar permitiendo degradación a heurística si la IA se satura:
python main.py run --schema public --limit 100 --allow-fallback
```

---

## Paso 8: Ejecución de Pruebas Automatizadas

El proyecto incluye una suite de más de **135 pruebas unitarias** que validan la Tercera Forma Normal (3NF), soporte de múltiples vías/esquinas, catálogo de 28 tipos de zonas, módulos y referencias:

```bash
# Ejecutar pruebas unitarias (sin requerir Ollama activo):
pytest tests/ -k "not ollama"

# Ejecutar la suite completa:
pytest tests/ -v
```

---

## Solución de Problemas Frecuentes (Troubleshooting)

### 1. 🪟 Windows PowerShell: "La ejecución de scripts está deshabilitada en este sistema"
- **Causa:** Política de seguridad restrictiva predeterminada en Windows.
- **Solución:** Abre PowerShell y ejecuta:
  ```powershell
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  ```
  Luego ejecuta nuevamente `.\venv\Scripts\Activate.ps1`.

---

### 2. ❌ "ERROR DE DEPENDENCIAS: No module named 'pydantic_settings'"
- **Causa:** Estás ejecutando el script con el Python del sistema en lugar del entorno virtual.
- **Solución:** Activa tu entorno virtual (`source venv/bin/activate` en Linux o `.\venv\Scripts\Activate.ps1` en Windows) o ejecuta directamente a través del binario del venv:
  ```bash
  # Linux:
  ./venv/bin/python main.py

  # Windows:
  .\venv\Scripts\python.exe main.py
  ```

---

### 3. 🔌 Error: "No se pudo conectar con el servidor Ollama"
- **Causa:** Ollama no está en ejecución o el puerto `11434` está bloqueado.
- **Solución:**
  1. Verifica que Ollama esté corriendo:
     - En Linux: `curl http://localhost:11434/api/tags`
     - En Windows: Revisa que el icono de Ollama esté activo en la bandeja del sistema.
  2. Si no está iniciado, ejecútalo en una terminal con `ollama serve`.
  3. Comprueba que el modelo exista con `ollama list`. Si no está, descárgalo con `ollama pull llama3`.

---

### 4. 🐳 Error de Docker: "Port 5432 is already in use"
- **Causa:** Ya tienes una instancia local de PostgreSQL instalada en tu equipo que ocupa el puerto `5432`.
- **Solución:**
  - Detén temporalmente tu PostgreSQL local:
    - En Linux: `sudo systemctl stop postgresql`
    - En Windows: Abre `services.msc`, busca `postgresql-x64-XX` y haz clic en *Detener*.
  - O cambia el puerto externo en `docker-compose.yml` (ej. `"5433:5432"`) y actualiza `DB_PORT=5433` en tu `.env`.

---

### 5. 🐧 Permiso denegado al ejecutar `run_gui.sh` en Linux
- **Causa:** El script carece de permisos de ejecución en Linux.
- **Solución:** Ejecuta:
  ```bash
  chmod +x run_gui.sh
  ./run_gui.sh
  ```

---

### 6. 🐟 Error en Linux / Fish shell: "'case' builtin usado fuera de un bloque 'switch'"
- **Causa:** Estás usando **Fish shell** (`fish`) y ejecutaste `source venv/bin/activate`. Ese archivo está escrito en sintaxis POSIX/Bash.
- **Solución:** Activa el entorno usando el archivo específico para Fish:
  ```fish
  source venv/bin/activate.fish
  ```
  *(O cambia a Bash ejecutando `bash` y luego `source venv/bin/activate`).*

---

## Tabla Resumen Rápida: Linux vs. Windows (Cheat Sheet)

| Tarea | 🐧 Linux (Bash/Zsh) | 🐟 Linux (Fish Shell) | 🪟 Windows (PowerShell) | 🪟 Windows (CMD) |
| :--- | :--- | :--- | :--- | :--- |
| **Crear venv** | `python3 -m venv venv` | `python3 -m venv venv` | `python -m venv venv` | `python -m venv venv` |
| **Activar venv** | `source venv/bin/activate` | `source venv/bin/activate.fish` | `.\venv\Scripts\Activate.ps1` | `venv\Scripts\activate.bat` |
| **Instalar librerías** | `pip install -r requirements.txt` | `pip install -r requirements.txt` | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| **Copiar .env** | `cp .env.example .env` | `cp .env.example .env` | `copy .env.example .env` | `copy .env.example .env` |
| **Iniciar Docker** | `docker compose up -d` | `docker compose up -d` | `docker compose up -d` | `docker compose up -d` |
| **Descargar Modelo IA** | `ollama pull llama3` | `ollama pull llama3` | `ollama pull llama3` | `ollama pull llama3` |
| **Aplicar DDL V2 en BD** | `docker exec -i mpch_postgres psql -U postgres -d bd_mpch < scripts_data_base/06_crear_estructura_v2_normalizada.sql` | `docker exec -i mpch_postgres psql -U postgres -d bd_mpch < scripts_data_base/06_crear_estructura_v2_normalizada.sql` | `Get-Content scripts_data_base\06_crear_estructura_v2_normalizada.sql \| docker exec -i mpch_postgres psql -U postgres -d bd_mpch` | `docker exec -i mpch_postgres psql -U postgres -d bd_mpch < scripts_data_base\06_crear_estructura_v2_normalizada.sql` |
| **Ejecutar GUI** | `./run_gui.sh` o `python3 main.py gui` | `./run_gui.sh` o `python3 main.py gui` | `.\run_gui.bat` o `python main.py gui` | `run_gui.bat` o `python main.py gui` |
| **Menú de Consola** | `python3 main.py menu` | `python3 main.py menu` | `python main.py menu` | `python main.py menu` |
| **Ejecutar Pruebas** | `pytest tests/ -k "not ollama"` | `pytest tests/ -k "not ollama"` | `pytest tests/ -k "not ollama"` | `pytest tests/ -k "not ollama"` |

---

---
*Municipalidad Provincial de Chiclayo — Subgerencia de Catastro y Tránsito / Gerencia de Tecnología de la Información.*
