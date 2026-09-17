-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   03_alter_tabla_origen_in_place.sql
-- DESCRIPCIÓN:
--   Script DDL para agregar columnas normalizadas de forma dinámica e in-place
--   a la tabla de direcciones existente, sin perder registros, sin modificar IDs
--   y minimizando el impacto en aplicaciones en producción.
-- =============================================================================

-- Modificación dinámica de la tabla receptora en sitio:
-- (Reemplazar 'public' y 'direcciones_actual' según tu esquema y tabla configurados en .env)
ALTER TABLE IF EXISTS direcciones_actual
    ADD COLUMN IF NOT EXISTS id_via INTEGER,
    ADD COLUMN IF NOT EXISTS tipo_via INTEGER,
    ADD COLUMN IF NOT EXISTS nom_via VARCHAR(150),
    ADD COLUMN IF NOT EXISTS num_via VARCHAR(50),
    ADD COLUMN IF NOT EXISTS id_zona INTEGER,
    ADD COLUMN IF NOT EXISTS tipo_zona INTEGER,
    ADD COLUMN IF NOT EXISTS nom_zona VARCHAR(150),
    ADD COLUMN IF NOT EXISTS manzana VARCHAR(20),
    ADD COLUMN IF NOT EXISTS lote VARCHAR(20),
    ADD COLUMN IF NOT EXISTS slote VARCHAR(20),
    ADD COLUMN IF NOT EXISTS referencia VARCHAR(255);

-- Agregar Foreign Keys si las tablas maestras ya existen
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
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_tipo_via'
    ) THEN
        ALTER TABLE direcciones_actual
            ADD CONSTRAINT fk_in_place_tipo_via
            FOREIGN KEY (tipo_via) REFERENCES tipos_via(id_tipo_via)
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

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_in_place_tipo_zona'
    ) THEN
        ALTER TABLE direcciones_actual
            ADD CONSTRAINT fk_in_place_tipo_zona
            FOREIGN KEY (tipo_zona) REFERENCES tipos_zona(id_tipo_zona)
            ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;
END $$;
