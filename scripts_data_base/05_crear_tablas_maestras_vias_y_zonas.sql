-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   05_crear_tablas_maestras_vias_y_zonas.sql
-- DESCRIPCIÓN:
--   Creación de las tablas terciarias maestras de vías físicas (3,024 vías)
--   y de habilitaciones urbanas/zonas (461 zonas) de la provincia de Chiclayo.
-- =============================================================================

-- 1. Tabla Maestra: VÍAS FÍSICAS DE CHICLAYO
CREATE TABLE IF NOT EXISTS vias (
    id_via              INTEGER NOT NULL,
    codigo_via          VARCHAR(20),
    id_tipo_via         INTEGER,
    nom_via             VARCHAR(150) NOT NULL,
    clasificacion_vial  VARCHAR(100),
    jurisdiccion        VARCHAR(100),

    CONSTRAINT pk_vias PRIMARY KEY (id_via),
    CONSTRAINT fk_vias_tipo_via 
        FOREIGN KEY (id_tipo_via) 
        REFERENCES tipos_via (id_tipo_via) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE vias IS 'Catálogo maestro de vías urbanas oficiales de Chiclayo.';
COMMENT ON COLUMN vias.id_via IS 'Identificador numérico secuencial único de la vía.';
COMMENT ON COLUMN vias.codigo_via IS 'Código catastral oficial de la vía (ej. 000105, 010010).';
COMMENT ON COLUMN vias.id_tipo_via IS 'Clave foránea hacia tipos_via (1: AV, 2: CA, etc.).';
COMMENT ON COLUMN vias.nom_via IS 'Denominación oficial de la vía (ej. 7 DE ENERO SUR, FELIPE SANTIAGO SALAVERRY).';

CREATE INDEX IF NOT EXISTS idx_vias_nom ON vias (nom_via);
CREATE INDEX IF NOT EXISTS idx_vias_codigo ON vias (codigo_via);
CREATE INDEX IF NOT EXISTS idx_vias_tipo ON vias (id_tipo_via);

-- 2. Tabla Maestra: HABILITACIONES URBANAS Y ZONAS DE CHICLAYO
CREATE TABLE IF NOT EXISTS zonas (
    id_zona             INTEGER NOT NULL,
    codigo_zona         VARCHAR(20),
    id_tipo_zona        INTEGER,
    nom_zona            VARCHAR(150) NOT NULL,
    sector_catastral    VARCHAR(50),
    condicion           VARCHAR(20),

    CONSTRAINT pk_zonas PRIMARY KEY (id_zona),
    CONSTRAINT fk_zonas_tipo_zona 
        FOREIGN KEY (id_tipo_zona) 
        REFERENCES tipos_zona (id_tipo_zona) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE zonas IS 'Catálogo maestro de habilitaciones urbanas y zonas de Chiclayo.';
COMMENT ON COLUMN zonas.id_zona IS 'Identificador numérico secuencial único de la zona.';
COMMENT ON COLUMN zonas.codigo_zona IS 'Código de habilitación urbana oficial (ej. 0001, 0465).';
COMMENT ON COLUMN zonas.id_tipo_zona IS 'Clave foránea hacia tipos_zona (1: A.H., 6: URB., etc.).';
COMMENT ON COLUMN zonas.nom_zona IS 'Nombre oficial de la habilitación urbana o zona (ej. SANTA VICTORIA, COLIBRI).';

CREATE INDEX IF NOT EXISTS idx_zonas_nom ON zonas (nom_zona);
CREATE INDEX IF NOT EXISTS idx_zonas_codigo ON zonas (codigo_zona);
CREATE INDEX IF NOT EXISTS idx_zonas_tipo ON zonas (id_tipo_zona);
