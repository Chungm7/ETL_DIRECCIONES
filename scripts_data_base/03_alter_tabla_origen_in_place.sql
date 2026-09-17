-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   03_alter_tabla_origen_in_place.sql
-- DESCRIPCIÓN:
--   Script DDL para consolidar la tabla de direcciones normalizada en 3NF,
--   vinculando directamente con las tablas maestras físicas (vias y zonas),
--   incorporando las columnas de control es_procesado y observacion,
--   y eliminando duplicidades de nombres en texto plano.
-- =============================================================================

-- Modificación dinámica de la tabla receptora en sitio:
-- (Reemplazar 'public' y 'direcciones_actual' según tu esquema y tabla configurados en .env)
ALTER TABLE IF EXISTS direcciones_actual
    ADD COLUMN IF NOT EXISTS id_via INTEGER,
    ADD COLUMN IF NOT EXISTS num_via VARCHAR(50),
    ADD COLUMN IF NOT EXISTS id_zona INTEGER,
    ADD COLUMN IF NOT EXISTS manzana VARCHAR(20),
    ADD COLUMN IF NOT EXISTS lote VARCHAR(20),
    ADD COLUMN IF NOT EXISTS slote VARCHAR(20),
    ADD COLUMN IF NOT EXISTS referencia VARCHAR(255),
    ADD COLUMN IF NOT EXISTS es_procesado BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS observacion TEXT;

-- Depuración de columnas de texto redundantes (ya provistas por las tablas maestras)
ALTER TABLE IF EXISTS direcciones_actual
    DROP COLUMN IF EXISTS tipo_via,
    DROP COLUMN IF EXISTS nom_via,
    DROP COLUMN IF EXISTS tipo_zona,
    DROP COLUMN IF EXISTS nom_zona;

-- Agregar Foreign Keys hacia las tablas maestras físicas
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_id_via'
    ) THEN
        ALTER TABLE direcciones_actual
            ADD CONSTRAINT fk_in_place_id_via
            FOREIGN KEY (id_via) REFERENCES vias(id_via)
            ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_id_zona'
    ) THEN
        ALTER TABLE direcciones_actual
            ADD CONSTRAINT fk_in_place_id_zona
            FOREIGN KEY (id_zona) REFERENCES zonas(id_zona)
            ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;
