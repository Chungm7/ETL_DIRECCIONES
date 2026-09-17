-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   02_crear_tabla_destino_normalizada.sql
-- DESCRIPCIÓN:
--   Creación de la tabla receptora normalizada (ej. direcciones_generales)
--   con relaciones hacia tipos_via y tipos_zona, conservando el ID original.
-- =============================================================================

CREATE TABLE IF NOT EXISTS direcciones_generales (
    id_licencia         INTEGER NOT NULL,
    tipo_via            INTEGER,
    nom_via             VARCHAR(150),
    num_via             VARCHAR(50),
    tipo_zona           INTEGER,
    nom_zona            VARCHAR(150),
    manzana             VARCHAR(20),
    lote                VARCHAR(20),
    slote               VARCHAR(20),
    referencia          VARCHAR(255),

    -- Clave Primaria (Conservando exactamente el ID del registro de origen)
    CONSTRAINT pk_direcciones_generales PRIMARY KEY (id_licencia),

    -- Claves Foráneas con catálogos oficiales
    CONSTRAINT fk_dg_tipo_via 
        FOREIGN KEY (tipo_via) 
        REFERENCES tipos_via (id_tipo_via) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL,

    CONSTRAINT fk_dg_tipo_zona 
        FOREIGN KEY (tipo_zona) 
        REFERENCES tipos_zona (id_tipo_zona) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

-- Índices de aceleración
CREATE INDEX IF NOT EXISTS idx_dg_tipo_via ON direcciones_generales (tipo_via);
CREATE INDEX IF NOT EXISTS idx_dg_tipo_zona ON direcciones_generales (tipo_zona);
CREATE INDEX IF NOT EXISTS idx_dg_nom_via ON direcciones_generales (nom_via);
CREATE INDEX IF NOT EXISTS idx_dg_nom_zona ON direcciones_generales (nom_zona);
