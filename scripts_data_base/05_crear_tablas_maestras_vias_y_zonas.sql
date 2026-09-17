-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   05_crear_tablas_maestras_vias_y_zonas.sql
-- DESCRIPCIÓN:
--   Creación de las tablas maestras de vías oficiales (3,024 vías)
--   y de zonas/habilitaciones urbanas (461 zonas) de la provincia de Chiclayo.
--   Estructura normalizada en 3NF: ID, FK al Tipo (tipo_via / tipo_zona) y Nombre Oficial.
-- =============================================================================

-- 1. Tabla Maestra: VÍAS OFICIALES DE CHICLAYO
CREATE TABLE IF NOT EXISTS vias (
    id_via              INTEGER NOT NULL,
    id_tipo_via         INTEGER,
    nom_via             VARCHAR(150) NOT NULL,

    CONSTRAINT pk_vias PRIMARY KEY (id_via),
    CONSTRAINT fk_vias_tipo_via 
        FOREIGN KEY (id_tipo_via) 
        REFERENCES tipos_via (id_tipo_via) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE vias IS 'Catálogo maestro de vías urbanas oficiales de Chiclayo.';
COMMENT ON COLUMN vias.id_via IS 'Identificador numérico secuencial único de la vía.';
COMMENT ON COLUMN vias.id_tipo_via IS 'Clave foránea hacia tipos_via (1: AV, 2: CA, etc.).';
COMMENT ON COLUMN vias.nom_via IS 'Denominación oficial de la vía (ej. 7 DE ENERO SUR, BALTA).';

CREATE INDEX IF NOT EXISTS idx_vias_nom ON vias (nom_via);
CREATE INDEX IF NOT EXISTS idx_vias_tipo ON vias (id_tipo_via);

-- 2. Tabla Maestra: HABILITACIONES URBANAS Y ZONAS DE CHICLAYO
CREATE TABLE IF NOT EXISTS zonas (
    id_zona             INTEGER NOT NULL,
    id_tipo_zona        INTEGER,
    nom_zona            VARCHAR(150) NOT NULL,

    CONSTRAINT pk_zonas PRIMARY KEY (id_zona),
    CONSTRAINT fk_zonas_tipo_zona 
        FOREIGN KEY (id_tipo_zona) 
        REFERENCES tipos_zona (id_tipo_zona) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE zonas IS 'Catálogo maestro de habilitaciones urbanas y zonas de Chiclayo.';
COMMENT ON COLUMN zonas.id_zona IS 'Identificador numérico secuencial único de la zona.';
COMMENT ON COLUMN zonas.id_tipo_zona IS 'Clave foránea hacia tipos_zona (1: A.H., 6: URB., etc.).';
COMMENT ON COLUMN zonas.nom_zona IS 'Nombre oficial de la habilitación urbana o zona (ej. SANTA VICTORIA, REMIGIO B. SILVA).';

CREATE INDEX IF NOT EXISTS idx_zonas_nom ON zonas (nom_zona);
CREATE INDEX IF NOT EXISTS idx_zonas_tipo ON zonas (id_tipo_zona);
