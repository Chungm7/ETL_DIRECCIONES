-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   scripts_data_actual.sql
-- TABLA:    direcciones_actual (Datos Origen / Legacy)
-- DESCRIPCIÓN:
--   Estructura DDL en PostgreSQL para la tabla fuente de direcciones de licencias.
--   Basada en la estructura:
--     - id_licencia   : Identificador numérico de la licencia (PK)
--     - emp_direccion : Dirección registrada sin estructurar/normalizar
-- =============================================================================

-- 1. Eliminar la tabla si ya existe (para reiniciar estructura en pruebas)
DROP TABLE IF EXISTS direcciones_actual CASCADE;

-- 2. Creación de la tabla de direcciones de origen
CREATE TABLE direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),

    -- Definición de Clave Primaria
    CONSTRAINT pk_direcciones_actual PRIMARY KEY (id_licencia)
);

-- 3. Documentación y comentarios en el catálogo de PostgreSQL
COMMENT ON TABLE direcciones_actual IS 'Tabla de datos actuales (origen) con las direcciones de licencias para el proceso de ETL y normalización.';
COMMENT ON COLUMN direcciones_actual.id_licencia IS 'Identificador único de la licencia comercial / empresa (Clave Primaria).';
COMMENT ON COLUMN direcciones_actual.emp_direccion IS 'Texto completo y no estructurado de la dirección registrada del establecimiento.';

-- 4. Índices
-- Nota: id_licencia ya cuenta con un índice B-Tree creado automáticamente por la PRIMARY KEY.
-- Índice opcional para optimizar búsquedas y limpiezas de texto:
CREATE INDEX IF NOT EXISTS idx_direcciones_actual_direccion 
    ON direcciones_actual (emp_direccion);

-- 5. Vista opcional de conveniencia (para consultar directamente como "direcciones")
CREATE OR REPLACE VIEW direcciones AS
SELECT 
    id_licencia,
    emp_direccion
FROM direcciones_actual;

-- =============================================================================
-- INSTRUCCIONES DE CARGA Y VALIDACIÓN (Opcional)
-- =============================================================================
-- Para importar los 42,350 registros desde 'Direcciones_.csv' usando psql:
-- \copy direcciones_actual (id_licencia, emp_direccion) FROM 'docs/data/Direcciones_.csv' WITH (FORMAT csv, HEADER true, DELIMITER ',', ENCODING 'UTF8');
--
-- Consultas de verificación:
-- SELECT COUNT(*) AS total_registros FROM direcciones_actual;
-- SELECT * FROM direcciones_actual LIMIT 10;
