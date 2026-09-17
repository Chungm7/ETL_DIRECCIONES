-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   scripts_data_etl_new.sql
-- MODELO:   Modelo Normalizado de Direcciones (Destino ETL)
-- DESCRIPCIÓN:
--   Script DDL en PostgreSQL para la estructura normalizada de direcciones.
--   Incluye:
--     1. Tabla maestra: tipos_via (ID, nombre, abreviatura)
--     2. Tabla maestra: tipos_zona (ID, nombre, abreviatura)
--     3. Tabla principal: direcciones_generales (id_licencia, vías, zonas, mz, lt)
--     4. Relaciones de Claves Foráneas (Foreign Keys)
--     5. Índices de optimización y comentarios de catálogo
--     6. Datos semilla (Inserts) para tablas maestras
--     7. Vista descriptiva con nombres completos (JOIN)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 0. Limpieza previa (orden inverso para respetar dependencias de claves foráneas)
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS v_direcciones_completas CASCADE;
DROP TABLE IF EXISTS direcciones_generales CASCADE;
DROP TABLE IF EXISTS tipos_zona CASCADE;
DROP TABLE IF EXISTS tipos_via CASCADE;

-- -----------------------------------------------------------------------------
-- 1. Tabla Maestra: TIPOS DE VÍA
-- -----------------------------------------------------------------------------
CREATE TABLE tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    abreviatura         VARCHAR(15),

    CONSTRAINT pk_tipos_via PRIMARY KEY (id_tipo_via)
);

COMMENT ON TABLE tipos_via IS 'Catálogo maestro de tipos de vía urbana según codificador catastral MPCH / Nacional.';
COMMENT ON COLUMN tipos_via.id_tipo_via IS 'Identificador numérico único del tipo de vía.';
COMMENT ON COLUMN tipos_via.nombre_tipo_via IS 'Denominación completa del tipo de vía (ej. CALLE, AVENIDA, JIRÓN).';
COMMENT ON COLUMN tipos_via.abreviatura IS 'Abreviatura estándar (ej. CA., AV., JR., PJE.).';

-- -----------------------------------------------------------------------------
-- 2. Tabla Maestra: TIPOS DE ZONA / HABILITACIÓN URBANA
-- -----------------------------------------------------------------------------
CREATE TABLE tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    abreviatura         VARCHAR(20),

    CONSTRAINT pk_tipos_zona PRIMARY KEY (id_tipo_zona)
);

COMMENT ON TABLE tipos_zona IS 'Catálogo maestro de tipos de zona y habilitaciones urbanas según codificador MPCH.';
COMMENT ON COLUMN tipos_zona.id_tipo_zona IS 'Identificador numérico único del tipo de zona / habilitación urbana.';
COMMENT ON COLUMN tipos_zona.nombre_tipo_zona IS 'Nombre completo del tipo de zona (ej. URBANIZACIÓN, PUEBLO JOVEN, CONJUNTO RESIDENCIAL).';
COMMENT ON COLUMN tipos_zona.abreviatura IS 'Abreviatura estándar (ej. URB., P.J., CONJ.RES., A.H.).';

-- -----------------------------------------------------------------------------
-- 3. Tabla Principal: DIRECCIONES GENERALES (Normalizadas)
-- -----------------------------------------------------------------------------
CREATE TABLE direcciones_generales (
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

    -- Clave Primaria (1 a 1 con la licencia comercial)
    CONSTRAINT pk_direcciones_generales PRIMARY KEY (id_licencia),

    -- Claves Foráneas
    CONSTRAINT fk_direcciones_tipo_via 
        FOREIGN KEY (tipo_via) 
        REFERENCES tipos_via (id_tipo_via) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL,

    CONSTRAINT fk_direcciones_tipo_zona 
        FOREIGN KEY (tipo_zona) 
        REFERENCES tipos_zona (id_tipo_zona) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE direcciones_generales IS 'Tabla normalizada resultante del proceso ETL que desglosa las direcciones en componentes atómicos estructurados.';
COMMENT ON COLUMN direcciones_generales.id_licencia IS 'Identificador de la licencia comercial asociada (Clave Primaria).';
COMMENT ON COLUMN direcciones_generales.tipo_via IS 'Clave foránea que referencia a la tabla maestra tipos_via.';
COMMENT ON COLUMN direcciones_generales.nom_via IS 'Nombre o denominación oficial de la vía (ej. MOISES R. VALIENTE, SESQUICENTENARIO).';
COMMENT ON COLUMN direcciones_generales.num_via IS 'Numeración municipal de la vía o indicación (ej. 349, 1673 - DPTO 2, S/N).';
COMMENT ON COLUMN direcciones_generales.tipo_zona IS 'Clave foránea que referencia a la tabla maestra tipos_zona.';
COMMENT ON COLUMN direcciones_generales.nom_zona IS 'Denominación de la habilitación urbana / sector (ej. LOS PRECURSORES, SANTA VICTORIA II ETAPA).';
COMMENT ON COLUMN direcciones_generales.manzana IS 'Identificador de Manzana (ej. D, 18, R).';
COMMENT ON COLUMN direcciones_generales.lote IS 'Identificador de Lote (ej. 43, 12, 25).';
COMMENT ON COLUMN direcciones_generales.slote IS 'Sub-lote o división interna si aplica.';

-- -----------------------------------------------------------------------------
-- 4. Índices para Acelerar Consultas y Cruces Relacionales
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_direcciones_gen_tipo_via 
    ON direcciones_generales (tipo_via);

CREATE INDEX IF NOT EXISTS idx_direcciones_gen_tipo_zona 
    ON direcciones_generales (tipo_zona);

CREATE INDEX IF NOT EXISTS idx_direcciones_gen_nom_via 
    ON direcciones_generales (nom_via);

CREATE INDEX IF NOT EXISTS idx_direcciones_gen_nom_zona 
    ON direcciones_generales (nom_zona);

-- -----------------------------------------------------------------------------
-- 5. Carga de Datos Semilla (Catálogos Oficiales de Vías y Zonas de Chiclayo)
-- -----------------------------------------------------------------------------

-- Catálogo de Tipos de Vía
INSERT INTO tipos_via (id_tipo_via, nombre_tipo_via, abreviatura) VALUES
    (1, 'CALLE', 'CA.'),
    (2, 'AVENIDA', 'AV.'),
    (3, 'JIRÓN', 'JR.'),
    (4, 'PASAJE', 'PJE.'),
    (5, 'CARRETERA', 'CTRA.'),
    (6, 'PROLONGACIÓN', 'PRLG.'),
    (7, 'PROLONGACIÓN AVENIDA', 'PRLG.AV'),
    (8, 'ALAMEDA', 'AL.'),
    (9, 'PARQUE', 'PQ.'),
    (10, 'ÓVALO', 'OV.'),
    (99, 'OTRO / SIN TIPO', 'OTRO')
ON CONFLICT (id_tipo_via) DO UPDATE 
SET nombre_tipo_via = EXCLUDED.nombre_tipo_via,
    abreviatura     = EXCLUDED.abreviatura;

-- Catálogo de Tipos de Zona / Habilitación Urbana
INSERT INTO tipos_zona (id_tipo_zona, nombre_tipo_zona, abreviatura) VALUES
    (1, 'URBANIZACIÓN', 'URB.'),
    (2, 'CONJUNTO RESIDENCIAL', 'CONJ.RES.'),
    (3, 'PUEBLO JOVEN', 'P.J.'),
    (4, 'ASENTAMIENTO HUMANO', 'A.H.'),
    (5, 'CERCADO DE CHICLAYO', 'CERCADO'),
    (6, 'HABILITACIÓN URBANA', 'H.U.'),
    (7, 'ASOCIACIÓN DE VIVIENDA', 'ASOC.VIV.'),
    (8, 'ASOCIACIÓN PRO-VIVIENDA', 'ASOC.PVIV.'),
    (9, 'COOPERATIVA DE VIVIENDA', 'COOP.VIV.'),
    (10, 'CONJUNTO HABITACIONAL', 'CONJ.HAB.'),
    (11, 'PROGRAMA MUNICIPAL / UPIS', 'UPIS'),
    (12, 'FUNDO / PREDIO', 'FDO.'),
    (99, 'OTRO / SECTOR GENERAL', 'OTRO')
ON CONFLICT (id_tipo_zona) DO UPDATE 
SET nombre_tipo_zona = EXCLUDED.nombre_tipo_zona,
    abreviatura      = EXCLUDED.abreviatura;

-- -----------------------------------------------------------------------------
-- 6. Vista Descriptiva Completa (Facilita Reportes y Consumo de Aplicaciones)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_direcciones_completas AS
SELECT 
    d.id_licencia,
    d.tipo_via,
    tv.abreviatura AS abrev_tipo_via,
    tv.nombre_tipo_via,
    d.nom_via,
    d.num_via,
    d.tipo_zona,
    tz.abreviatura AS abrev_tipo_zona,
    tz.nombre_tipo_zona,
    d.nom_zona,
    d.manzana,
    d.lote,
    d.slote,
    -- Dirección legible concatenada automáticamente
    TRIM(
        CONCAT_WS(' ',
            tv.abreviatura,
            d.nom_via,
            CASE WHEN d.num_via IS NOT NULL THEN 'N° ' || d.num_via END,
            CASE WHEN d.manzana IS NOT NULL THEN 'Mz. ' || d.manzana END,
            CASE WHEN d.lote IS NOT NULL THEN 'Lt. ' || d.lote END,
            CASE WHEN d.slote IS NOT NULL THEN 'Slte. ' || d.slote END,
            tz.abreviatura,
            d.nom_zona
        )
    ) AS direccion_formateada
FROM direcciones_generales d
LEFT JOIN tipos_via  tv ON d.tipo_via  = tv.id_tipo_via
LEFT JOIN tipos_zona tz ON d.tipo_zona = tz.id_tipo_zona;
