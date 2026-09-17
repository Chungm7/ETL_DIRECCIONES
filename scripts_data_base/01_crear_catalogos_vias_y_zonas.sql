-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   01_crear_catalogos_vias_y_zonas.sql
-- DESCRIPCIÓN:
--   Creación y sembrado de las tablas maestras de TIPOS DE VÍA y TIPOS DE ZONA
--   conforme a las directivas oficiales (12 tipos de vía y 28 tipos de zona).
-- =============================================================================

-- 1. Tabla Maestra: TIPOS DE VÍA
CREATE TABLE IF NOT EXISTS tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    abreviatura         VARCHAR(15),

    CONSTRAINT pk_tipos_via PRIMARY KEY (id_tipo_via)
);

COMMENT ON TABLE tipos_via IS 'Catálogo maestro de tipos de vía urbana oficial de la MPCH.';
COMMENT ON COLUMN tipos_via.id_tipo_via IS 'Identificador numérico único del tipo de vía.';
COMMENT ON COLUMN tipos_via.nombre_tipo_via IS 'Denominación completa del tipo de vía (AVENIDA, CALLE, etc.).';
COMMENT ON COLUMN tipos_via.abreviatura IS 'Abreviatura oficial (AV., CA., JR., etc.).';

-- Inserción / Actualización de Datos Semilla para TIPOS DE VÍA (12 registros)
INSERT INTO tipos_via (id_tipo_via, nombre_tipo_via, abreviatura) VALUES
    (1,  'AVENIDA',      'AV.'),
    (2,  'CALLE',        'CA.'),
    (3,  'JIRON',        'JR.'),
    (4,  'PASAJE',       'PJE.'),
    (5,  'ALAMEDA',      'AL.'),
    (6,  'CARRETERA',    'CTRA.'),
    (7,  'PROLONGACION', 'PRLG.'),
    (8,  'PASEO',        'PSO.'),
    (9,  'MALECON',      'ML.'),
    (10, 'CAMINO',       'CM.'),
    (11, 'PLAZA',        'PZ.'),
    (12, 'PLAZUELA',     'PZLA.')
ON CONFLICT (id_tipo_via) DO UPDATE SET
    nombre_tipo_via = EXCLUDED.nombre_tipo_via,
    abreviatura     = EXCLUDED.abreviatura;

-- -----------------------------------------------------------------------------
-- 2. Tabla Maestra: TIPOS DE ZONA
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    abreviatura         VARCHAR(20),

    CONSTRAINT pk_tipos_zona PRIMARY KEY (id_tipo_zona)
);

COMMENT ON TABLE tipos_zona IS 'Catálogo maestro de tipos de zona y habilitaciones urbanas de la MPCH.';
COMMENT ON COLUMN tipos_zona.id_tipo_zona IS 'Identificador numérico único del tipo de zona.';
COMMENT ON COLUMN tipos_zona.nombre_tipo_zona IS 'Nombre completo del tipo de zona.';
COMMENT ON COLUMN tipos_zona.abreviatura IS 'Abreviatura oficial estándar.';

-- Inserción / Actualización de Datos Semilla para TIPOS DE ZONA (28 registros)
INSERT INTO tipos_zona (id_tipo_zona, nombre_tipo_zona, abreviatura) VALUES
    (1,  'ASENTAMIENTO HUMANO',       'A.H.'),
    (2,  'AGRUPACION',                'AGRUP.'),
    (3,  'CONJUNTO HABITACIONAL',     'CONJ.HAB.'),
    (4,  'CONJUNTO RESIDENCIAL',      'CONJ.RES.'),
    (5,  'PUEBLO JOVEN',              'P.J.'),
    (6,  'URBANIZACION',              'URB.'),
    (7,  'URBANIZACION POPULAR',      'URB.POP.'),
    (8,  'CERCADO',                   'CERCADO'),
    (9,  'HACIENDA',                  'HAC.'),
    (10, 'ASOCIACION',                'ASOC.'),
    (11, 'COOPERATIVA',               'COOP.'),
    (12, 'LOTIZACION',                'LOT.'),
    (13, 'PARCELA',                   'PARC.'),
    (14, 'VALLE',                     'VALLE'),
    (15, 'CASERIO',                   'CAS.'),
    (16, 'UNIDAD VECINAL',            'U.V.'),
    (17, 'COMUNIDAD',                 'COM.'),
    (18, 'BARRIO',                    'BO.'),
    (19, 'FUNDO',                     'FDO.'),
    (20, 'JUNTA DE COMPRADORES',      'J.COMP.'),
    (21, 'ASOCIACION DE VIVIENDA',     'ASOC.VIV.'),
    (22, 'COOPERATIVA DE VIVIENDA',    'COOP.VIV.'),
    (23, 'SOCIEDAD',                  'SOC.'),
    (24, 'ASOCIACION PRO VIVIENDA',   'ASOC.PVIV.'),
    (25, 'ZONA',                      'ZONA'),
    (26, 'CENTRO POBLADO',            'C.P.'),
    (27, 'ANEXO',                     'ANEXO'),
    (28, 'COMUNIDAD INDIGENA',        'COM.IND.')
ON CONFLICT (id_tipo_zona) DO UPDATE SET
    nombre_tipo_zona = EXCLUDED.nombre_tipo_zona,
    abreviatura      = EXCLUDED.abreviatura;
