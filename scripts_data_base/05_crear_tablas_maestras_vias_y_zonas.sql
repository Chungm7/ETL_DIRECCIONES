-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   05_crear_tablas_maestras_vias_y_zonas.sql
-- DESCRIPCIÓN:
--   Creación de las tablas maestras de vías físicas (3,024 vías)
--   y de zonas/habilitaciones urbanas (461 zonas) de la provincia de Chiclayo.
--   Estructura simplificada requerida: Únicamente ID y Nombre de la entidad.
-- =============================================================================

-- 1. Tabla Maestra: VÍAS FÍSICAS DE CHICLAYO
CREATE TABLE IF NOT EXISTS vias (
    id_via              INTEGER NOT NULL,
    nom_via             VARCHAR(150) NOT NULL,

    CONSTRAINT pk_vias PRIMARY KEY (id_via)
);

COMMENT ON TABLE vias IS 'Catálogo maestro de vías urbanas oficiales de Chiclayo (simplificado).';
COMMENT ON COLUMN vias.id_via IS 'Identificador numérico secuencial único de la vía.';
COMMENT ON COLUMN vias.nom_via IS 'Denominación oficial de la arteria o vía (ej. 7 DE ENERO SUR, FELIPE SANTIAGO SALAVERRY).';

CREATE INDEX IF NOT EXISTS idx_vias_nom ON vias (nom_via);

-- 2. Tabla Maestra: HABILITACIONES URBANAS Y ZONAS DE CHICLAYO
CREATE TABLE IF NOT EXISTS zonas (
    id_zona             INTEGER NOT NULL,
    nom_zona            VARCHAR(150) NOT NULL,

    CONSTRAINT pk_zonas PRIMARY KEY (id_zona)
);

COMMENT ON TABLE zonas IS 'Catálogo maestro de habilitaciones urbanas y zonas de Chiclayo (simplificado).';
COMMENT ON COLUMN zonas.id_zona IS 'Identificador numérico secuencial único de la zona.';
COMMENT ON COLUMN zonas.nom_zona IS 'Nombre oficial de la habilitación urbana o zona (ej. SANTA VICTORIA, COLIBRI).';

CREATE INDEX IF NOT EXISTS idx_zonas_nom ON zonas (nom_zona);
