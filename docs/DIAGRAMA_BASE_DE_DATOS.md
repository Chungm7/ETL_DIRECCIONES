# Diagrama de Arquitectura y Modelo Relacional de Base de Datos

## 🏛️ Modelo Relacional Consolidado (Tercera Forma Normal - 3NF)

El siguiente diagrama entidad-relación (ER) describe la estructura consolidada oficial de la base de datos para la **Municipalidad Provincial de Chiclayo (MPCH)**.

En este modelo, la tabla `direcciones_actual` elimina la duplicidad y redundancia de almacenar cadenas de texto (`nom_via`, `nom_zona`, `tipo_via`, `tipo_zona`), enlazando directamente mediante claves foráneas (`id_via`, `id_zona`) hacia los catálogos maestros físicos oficiales de Chiclayo.

```mermaid
erDiagram
    TIPOS_VIA ||--o{ VIAS : "clasifica (1:N)"
    TIPOS_ZONA ||--o{ ZONAS : "clasifica (1:N)"
    VIAS ||--o{ DIRECCIONES_ACTUAL : "asocia (0..N)"
    ZONAS ||--o{ DIRECCIONES_ACTUAL : "asocia (0..N)"

    TIPOS_VIA {
        int id_tipo_via PK "Identificador único (1..12)"
        string nombre_tipo_via "Nombre oficial (AVENIDA, CALLE, etc.)"
        string abreviatura "Abreviatura oficial (AV., CA., JR., etc.)"
    }

    TIPOS_ZONA {
        int id_tipo_zona PK "Identificador único (1..28)"
        string nombre_tipo_zona "Nombre oficial (URBANIZACION, A.H., etc.)"
        string abreviatura "Abreviatura oficial (URB., A.H., etc.)"
    }

    VIAS {
        int id_via PK "ID único de la vía oficial (1..174)"
        int id_tipo_via FK "FK hacia tipos_via (Tipo de arteria)"
        string nom_via "Nombre oficial de la vía (ej. BALTA, FITZCARRAL, SALAVERRY)"
    }

    ZONAS {
        int id_zona PK "ID único de la zona oficial (1..460)"
        int id_tipo_zona FK "FK hacia tipos_zona (Tipo de habilitación)"
        string nom_zona "Nombre oficial de la zona (ej. SANTA VICTORIA, REMIGIO B. SILVA)"
    }

    DIRECCIONES_ACTUAL {
        int id_licencia PK "Identificador único de licencia (PK original)"
        string emp_direccion "Dirección original completa conservada"
        int id_via FK "FK hacia vias.id_via (NULL si no procesado)"
        string num_via "Número de puerta / numeración municipal"
        int id_zona FK "FK hacia zonas.id_zona (NULL si no procesado)"
        string manzana "Manzana catastral (Mz)"
        string lote "Lote catastral (Lt)"
        string slote "Sublote o división interna"
        string referencia "Punto de referencia o hito urbano"
        boolean es_procesado "TRUE = Validado en catastro | FALSE = Observado"
        text observacion "Diagnóstico/motivo si no se pudo procesar"
    }
```

---

## 📋 Diccionario de Datos de la Tabla Consolidada: `direcciones_actual`

| Columna | Tipo de Dato | Nulable | Restricción / FK | Descripción |
| :--- | :--- | :---: | :--- | :--- |
| **`id_licencia`** | `INTEGER` | **NO** | `PRIMARY KEY` | Llave primaria original inmutable del registro. |
| **`emp_direccion`** | `VARCHAR(255)` / `TEXT`| **NO** | Ninguna | Cadena original intacta de la dirección para auditoría histórica. |
| **`id_via`** | `INTEGER` | SÍ | `FK -> vias(id_via)` | Vía física oficial de Chiclayo vinculada. `NULL` si no existe o fue observada. |
| **`num_via`** | `VARCHAR(50)` | SÍ | Ninguna | Numeración de la vía (ej. `129`, `450`, `S/N`). `NULL` si fue observada. |
| **`id_zona`** | `INTEGER` | SÍ | `FK -> zonas(id_zona)` | Habilitación urbana oficial vinculada. `NULL` si no existe o fue observada. |
| **`manzana`** | `VARCHAR(20)` | SÍ | Ninguna | Manzana del predio. `NULL` si fue observada. |
| **`lote`** | `VARCHAR(20)` | SÍ | Ninguna | Lote del predio. `NULL` si fue observada. |
| **`slote`** | `VARCHAR(20)` | SÍ | Ninguna | Sublote o departamento interno. `NULL` si fue observada. |
| **`referencia`** | `VARCHAR(255)` | SÍ | Ninguna | Hito urbano de guía (ej. `CERCA AL SENATI`). `NULL` si fue observada. |
| **`es_procesado`** | `BOOLEAN` | **NO** | `DEFAULT FALSE` | Indicador de control: `TRUE` (Éxito oficial), `FALSE` (Observado/No procesado). |
| **`observacion`** | `TEXT` | SÍ | Ninguna | Detalle explicativo de la inconsistencia o motivo de rechazo. |

---

## ⚙️ Reglas de Negocio y Estados de Procesamiento

```mermaid
flowchart TD
    START(["Dirección Cruda: emp_direccion"]) --> EXTRACT["Extracción con IA & Heurística\n(vía tentativa, zona tentativa, números, referencias)"]
    EXTRACT --> CHECK_VIAS{"¿La vía existe en\ntabla vias (2,935)?"}
    
    CHECK_VIAS -- Sí --> CHECK_ZONAS{"¿La zona existe en\ntabla zonas (460)?"}
    CHECK_VIAS -- No --> RECHAZAR_VIA["Observación: Vía no encontrada en catálogo oficial\nid_via = NULL\nnum_via = NULL"]
    
    CHECK_ZONAS -- Sí --> EXITO["es_procesado = TRUE\nid_via = ID Vía\nnum_via = Extraído\nid_zona = ID Zona\nmz, lt, slote, ref = Extraídos\nobservacion = NULL"]
    CHECK_ZONAS -- No --> RECHAZAR_ZONA["Observación: Zona no encontrada en catálogo oficial\nid_zona = NULL\nmz, lt, slote = NULL"]

    RECHAZAR_VIA --> OBSERVAR["es_procesado = FALSE\nTodas las columnas normalizadas = NULL\nobservacion = Explicación detallada\nemp_direccion = Conservada intacta"]
    RECHAZAR_ZONA --> OBSERVAR
```

### 1. Caso `es_procesado = TRUE` (Normalización Exitosa)
- Todas las entidades identificadas en la dirección coincidieron con las tablas oficiales `vias` y/o `zonas`.
- `id_via` y/o `id_zona` quedan debidamente poblados con sus claves foráneas.
- Las columnas de desglose municipal (`num_via`, `manzana`, `lote`, `slote`, `referencia`) se conservan con su valor correspondiente.
- `observacion` queda en `NULL`.

### 2. Caso `es_procesado = FALSE` (Registro Observado)
- Si una vía o zona mencionada en la dirección **no se encuentra en las tablas maestras oficiales**, o el registro es ambiguo:
- `id_via = NULL`
- `num_via = NULL`
- `id_zona = NULL`
- `manzana = NULL`
- `lote = NULL`
- `slote = NULL`
- `referencia = NULL`
- **`emp_direccion` permanece intacta** con el texto completo original para permitir la subsanación.
- **`observacion` registra el motivo exacto:**
  - *Ejemplo:* `"Vía 'TRINDIAD' no existe en el catálogo maestro de vías de Chiclayo."`
  - *Ejemplo:* `"Zona/Habilitación 'URB. DESCONOCIDA' no existe en el catálogo de zonas oficiales de Chiclayo."`
  - *Ejemplo:* `"DIRECCIÓN NO RECONOCIDA: No se identificó ninguna vía ni habilitación urbana válida en el texto."`

---

## 🔍 Consultas SQL de Explotación y Reportes

### 1. Reconstruir la dirección normalizada completa con nombres oficiales:
```sql
SELECT 
    d.id_licencia,
    d.emp_direccion AS direccion_original,
    tv.nombre_tipo_via,
    v.nom_via AS via_oficial,
    d.num_via,
    tz.nombre_tipo_zona,
    z.nom_zona AS zona_oficial,
    d.manzana,
    d.lote,
    d.referencia,
    d.es_procesado
FROM direcciones_actual d
LEFT JOIN vias v ON d.id_via = v.id_via
LEFT JOIN tipos_via tv ON v.id_tipo_via = tv.id_tipo_via
LEFT JOIN zonas z ON d.id_zona = z.id_zona
LEFT JOIN tipos_zona tz ON z.id_tipo_zona = tz.id_tipo_zona
WHERE d.es_procesado = TRUE;
```

### 2. Consultar direcciones observadas para regularización catastral:
```sql
SELECT 
    id_licencia,
    emp_direccion,
    observacion
FROM direcciones_actual
WHERE es_procesado = FALSE;
```

### 3. Métricas de efectividad de normalización:
```sql
SELECT 
    COUNT(*) AS total_direcciones,
    COUNT(*) FILTER (WHERE es_procesado = TRUE) AS normalizadas_exitosas,
    COUNT(*) FILTER (WHERE es_procesado = FALSE) AS observadas_pendientes,
    ROUND(COUNT(*) FILTER (WHERE es_procesado = TRUE) * 100.0 / COUNT(*), 2) AS porcentaje_efectividad
FROM direcciones_actual;
```
