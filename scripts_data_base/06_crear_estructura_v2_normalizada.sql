-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   06_crear_estructura_v2_normalizada.sql
-- VERSIÓN:  2.0 - Arquitectura Relacional y Nomenclatura Corporativa tb_
-- DESCRIPCIÓN:
--   Implementación física en PostgreSQL del modelo de datos normalizado V2:
--     1. tb_tipo_via
--     2. tb_via
--     3. tb_tipo_zona (Exactamente los 28 tipos de zona oficiales)
--     4. tb_zona
--     5. tb_direccion
--     6. tb_direccion_via (Soporte N:M para esquinas / intersecciones viales)
--     7. tb_componente_direccion (Catálogo de atributos urbanos y rurales)
--     8. tb_contenido_componente_direccion (Valores de Mz, Lt, Piso, etc.)
--     9. tb_tipo_modulo (Catálogo de módulos: Interior, Dpto, Puerta, Stand, etc.)
--    10. tb_direccion_tipo_modulo (Valores de dependencias y módulos)
--    11. Datos semilla de catálogos y vista relacional completa (v_direcciones_v2)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Tabla Maestra: TIPOS DE VÍA (tb_tipo_via)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_via (
    tivi_id             BIGSERIAL NOT NULL,
    tivi_nombre         VARCHAR(50) NOT NULL,
    tivi_abreviatura    VARCHAR(10) NOT NULL,
    tivi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_tipo_via PRIMARY KEY (tivi_id),
    CONSTRAINT uq_tb_tipo_via_nombre UNIQUE (tivi_nombre)
);

COMMENT ON TABLE tb_tipo_via IS 'Catálogo maestro institucional de tipos de arteria vial (AVENIDA, CALLE, JIRÓN, etc.).';
COMMENT ON COLUMN tb_tipo_via.tivi_id IS 'Identificador numérico único del tipo de vía.';
COMMENT ON COLUMN tb_tipo_via.tivi_nombre IS 'Nombre completo oficial del tipo de vía.';
COMMENT ON COLUMN tb_tipo_via.tivi_abreviatura IS 'Abreviatura estándar oficial (AV., CA., JR., etc.).';
COMMENT ON COLUMN tb_tipo_via.tivi_estado IS 'Estado del registro: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 2. Tabla Maestra: VÍAS OFICIALES DE CHICLAYO (tb_via)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_via (
    via_id              BIGSERIAL NOT NULL,
    tivi_id             BIGINT NOT NULL,
    via_nombre          VARCHAR(255) NOT NULL,
    via_estado          VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_via PRIMARY KEY (via_id),
    CONSTRAINT fk_tb_via_tipo_via 
        FOREIGN KEY (tivi_id) 
        REFERENCES tb_tipo_via (tivi_id) 
        ON UPDATE CASCADE 
        ON DELETE RESTRICT
);

COMMENT ON TABLE tb_via IS 'Catálogo maestro de vías públicas habilitadas de la provincia de Chiclayo.';
COMMENT ON COLUMN tb_via.via_id IS 'Identificador secuencial único de la vía.';
COMMENT ON COLUMN tb_via.tivi_id IS 'Clave foránea hacia tb_tipo_via.';
COMMENT ON COLUMN tb_via.via_nombre IS 'Denominación oficial de la vía (ej. BALTA, LUIS GONZALES, 7 DE ENERO).';
COMMENT ON COLUMN tb_via.via_estado IS 'Estado del registro: ACT (Activo), INA (Inactivo).';

CREATE INDEX IF NOT EXISTS idx_tb_via_nombre ON tb_via (via_nombre);
CREATE INDEX IF NOT EXISTS idx_tb_via_tipo ON tb_via (tivi_id);

-- -----------------------------------------------------------------------------
-- 3. Tabla Maestra: TIPOS DE ZONA (tb_tipo_zona - 28 tipos oficiales)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_zona (
    tizo_id             BIGSERIAL NOT NULL,
    tizo_nombre         VARCHAR(100) NOT NULL,
    tizo_abreviatura    VARCHAR(10) NOT NULL,
    tizo_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_tipo_zona PRIMARY KEY (tizo_id),
    CONSTRAINT uq_tb_tipo_zona_nombre UNIQUE (tizo_nombre)
);

COMMENT ON TABLE tb_tipo_zona IS 'Catálogo maestro de los 28 tipos oficiales de habilitación urbana y zona catastral.';
COMMENT ON COLUMN tb_tipo_zona.tizo_id IS 'Identificador secuencial único del tipo de zona.';
COMMENT ON COLUMN tb_tipo_zona.tizo_nombre IS 'Nombre oficial completo (URBANIZACION, PUEBLO JOVEN, etc.).';
COMMENT ON COLUMN tb_tipo_zona.tizo_abreviatura IS 'Abreviatura oficial (URB., P.J., A.H., etc.).';
COMMENT ON COLUMN tb_tipo_zona.tizo_estado IS 'Estado del registro: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 4. Tabla Maestra: HABILITACIONES URBANAS Y ZONAS (tb_zona)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_zona (
    zona_id             BIGSERIAL NOT NULL,
    tizo_id             BIGINT NOT NULL,
    zona_nombre         VARCHAR(255) NOT NULL,
    zona_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_zona PRIMARY KEY (zona_id),
    CONSTRAINT fk_tb_zona_tipo_zona 
        FOREIGN KEY (tizo_id) 
        REFERENCES tb_tipo_zona (tizo_id) 
        ON UPDATE CASCADE 
        ON DELETE RESTRICT
);

COMMENT ON TABLE tb_zona IS 'Catálogo maestro de habilitaciones urbanas, sectores y zonas oficiales de Chiclayo.';
COMMENT ON COLUMN tb_zona.zona_id IS 'Identificador secuencial único de la zona.';
COMMENT ON COLUMN tb_zona.tizo_id IS 'Clave foránea hacia tb_tipo_zona.';
COMMENT ON COLUMN tb_zona.zona_nombre IS 'Nombre oficial de la zona (ej. SANTA VICTORIA, 9 DE OCTUBRE, FEDERICO VILLARREAL).';
COMMENT ON COLUMN tb_zona.zona_estado IS 'Estado del registro: ACT (Activo), INA (Inactivo).';

CREATE INDEX IF NOT EXISTS idx_tb_zona_nombre ON tb_zona (zona_nombre);
CREATE INDEX IF NOT EXISTS idx_tb_zona_tipo ON tb_zona (tizo_id);

-- -----------------------------------------------------------------------------
-- 5. Tabla Principal: DIRECCIONES NORMALIZADAS (tb_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion (
    dire_id             BIGSERIAL NOT NULL,
    zona_id             BIGINT,
    dire_referencia     VARCHAR(500),
    dire_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_direccion PRIMARY KEY (dire_id),
    CONSTRAINT fk_tb_direccion_zona 
        FOREIGN KEY (zona_id) 
        REFERENCES tb_zona (zona_id) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE tb_direccion IS 'Entidad central que consolida la dirección normalizada, su zona oficial e hitos espaciales.';
COMMENT ON COLUMN tb_direccion.dire_id IS 'Identificador secuencial único de la dirección normalizada.';
COMMENT ON COLUMN tb_direccion.zona_id IS 'Clave foránea hacia tb_zona. Permite NULL si el predio no posee zona registrada.';
COMMENT ON COLUMN tb_direccion.dire_referencia IS 'Hito espacial o comercial de orientación urbana (ej. CERCA AL SENATI, FRENTE AL PARQUE).';
COMMENT ON COLUMN tb_direccion.dire_estado IS 'Estado del registro: ACT (Activo), INA (Inactivo).';

CREATE INDEX IF NOT EXISTS idx_tb_direccion_zona ON tb_direccion (zona_id);

-- -----------------------------------------------------------------------------
-- 6. Tabla Intermedia: DIRECCIÓN - VÍAS (tb_direccion_via - Esquinas e Intersecciones)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion_via (
    dire_id             BIGINT NOT NULL,
    via_id              BIGINT NOT NULL,
    divi_numero         VARCHAR(20),
    divi_orden          INT DEFAULT 1,
    divi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_direccion_via PRIMARY KEY (dire_id, via_id),
    CONSTRAINT fk_tb_direccion_via_dir 
        FOREIGN KEY (dire_id) 
        REFERENCES tb_direccion (dire_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_tb_direccion_via_via 
        FOREIGN KEY (via_id) 
        REFERENCES tb_via (via_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

COMMENT ON TABLE tb_direccion_via IS 'Relación N:M que asocia vías con la dirección. Soporta esquinas (San José 102 con Luis Gonzales 801).';
COMMENT ON COLUMN tb_direccion_via.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_direccion_via.via_id IS 'Clave foránea hacia tb_via.';
COMMENT ON COLUMN tb_direccion_via.divi_numero IS 'Numeración municipal en esta arteria (ej. 102, 801, S/N).';
COMMENT ON COLUMN tb_direccion_via.divi_orden IS 'Orden de prelación vial: 1 para vía principal, 2 para vía de cruce / intersección.';
COMMENT ON COLUMN tb_direccion_via.divi_estado IS 'Estado: ACT (Activo), INA (Inactivo).';

CREATE INDEX IF NOT EXISTS idx_tb_direccion_via_via ON tb_direccion_via (via_id);

-- -----------------------------------------------------------------------------
-- 7. Tabla Maestra: COMPONENTES DE DIRECCIÓN (tb_componente_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_componente_direccion (
    codi_id             BIGSERIAL NOT NULL,
    codi_nombre         VARCHAR(100) NOT NULL,
    codi_es_urbano      BOOLEAN DEFAULT TRUE,
    codi_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_componente_direccion PRIMARY KEY (codi_id),
    CONSTRAINT uq_tb_componente_direccion_nombre UNIQUE (codi_nombre)
);

COMMENT ON TABLE tb_componente_direccion IS 'Catálogo de atributos catastrales urbanos (Mz, Lote, Piso) y rurales (Valle, Predio, Coordenadas).';
COMMENT ON COLUMN tb_componente_direccion.codi_id IS 'Identificador del tipo de componente.';
COMMENT ON COLUMN tb_componente_direccion.codi_nombre IS 'Nombre del componente (MANZANA, LOTE, SUBLOTE, PISO, PREDIO, etc.).';
COMMENT ON COLUMN tb_componente_direccion.codi_es_urbano IS 'True: Urbano, False: Rural.';
COMMENT ON COLUMN tb_componente_direccion.codi_estado IS 'Estado: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 8. Tabla Relacional: CONTENIDO DE COMPONENTES (tb_contenido_componente_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_contenido_componente_direccion (
    dire_id             BIGINT NOT NULL,
    codi_id             BIGINT NOT NULL,
    diti_nombre         VARCHAR(100) NOT NULL,
    diti_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_contenido_componente_direccion PRIMARY KEY (dire_id, codi_id),
    CONSTRAINT fk_tb_contenido_componente_dir 
        FOREIGN KEY (dire_id) 
        REFERENCES tb_direccion (dire_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_tb_contenido_componente_codi 
        FOREIGN KEY (codi_id) 
        REFERENCES tb_componente_direccion (codi_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

COMMENT ON TABLE tb_contenido_componente_direccion IS 'Valores atómicos asignados a cada componente catastral en una dirección.';
COMMENT ON COLUMN tb_contenido_componente_direccion.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_contenido_componente_direccion.codi_id IS 'Clave foránea hacia tb_componente_direccion.';
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_nombre IS 'Valor del componente (ej. A, 14, 2, SECTOR 3).';
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_estado IS 'Estado: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 9. Tabla Maestra: TIPOS DE MÓDULO (tb_tipo_modulo)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_modulo (
    timo_id             BIGSERIAL NOT NULL,
    timo_nombre         VARCHAR(100) NOT NULL,
    timo_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_tipo_modulo PRIMARY KEY (timo_id),
    CONSTRAINT uq_tb_tipo_modulo_nombre UNIQUE (timo_nombre)
);

COMMENT ON TABLE tb_tipo_modulo IS 'Catálogo de tipos de dependencias y subunidades (INTERIOR, DEPARTAMENTO, PUERTA, STAND, etc.).';
COMMENT ON COLUMN tb_tipo_modulo.timo_id IS 'Identificador único del tipo de módulo.';
COMMENT ON COLUMN tb_tipo_modulo.timo_nombre IS 'Nombre del módulo (INTERIOR, DEPARTAMENTO, PUERTA, STAND, TIENDA, BLOCK, OFICINA).';
COMMENT ON COLUMN tb_tipo_modulo.timo_estado IS 'Estado: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 10. Tabla Relacional: DIRECCIÓN - TIPOS DE MÓDULO (tb_direccion_tipo_modulo)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion_tipo_modulo (
    dire_id             BIGINT NOT NULL,
    timo_id             BIGINT NOT NULL,
    ditm_nombre         VARCHAR(100) NOT NULL,
    ditm_estado         VARCHAR(3) NOT NULL DEFAULT 'ACT',

    CONSTRAINT pk_tb_direccion_tipo_modulo PRIMARY KEY (dire_id, timo_id),
    CONSTRAINT fk_tb_direccion_modulo_dir 
        FOREIGN KEY (dire_id) 
        REFERENCES tb_direccion (dire_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE,
    CONSTRAINT fk_tb_direccion_modulo_timo 
        FOREIGN KEY (timo_id) 
        REFERENCES tb_tipo_modulo (timo_id) 
        ON UPDATE CASCADE 
        ON DELETE CASCADE
);

COMMENT ON TABLE tb_direccion_tipo_modulo IS 'Dependencias y módulos inmobiliarios asociados a la dirección.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.timo_id IS 'Clave foránea hacia tb_tipo_modulo.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_nombre IS 'Detalle del módulo (ej. 2, B, 101, STAND 4).';
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_estado IS 'Estado: ACT (Activo), INA (Inactivo).';

-- -----------------------------------------------------------------------------
-- 11. Carga de Datos Semilla Oficiales (Catálogos V2)
-- -----------------------------------------------------------------------------

-- 11.1 Tipos de Vía Oficiales
INSERT INTO tb_tipo_via (tivi_id, tivi_nombre, tivi_abreviatura, tivi_estado) VALUES
    (1, 'AVENIDA', 'AV.', 'ACT'),
    (2, 'CALLE', 'CA.', 'ACT'),
    (3, 'JIRÓN', 'JR.', 'ACT'),
    (4, 'PASAJE', 'PJE.', 'ACT'),
    (5, 'ALAMEDA', 'AL.', 'ACT'),
    (6, 'CARRETERA', 'CTRA.', 'ACT'),
    (7, 'PROLONGACIÓN', 'PRLG.', 'ACT'),
    (8, 'PASEO', 'PSO.', 'ACT'),
    (9, 'MALECÓN', 'ML.', 'ACT'),
    (10, 'CAMINO', 'CM.', 'ACT'),
    (11, 'PLAZA', 'PZ.', 'ACT'),
    (12, 'PLAZUELA', 'PZLA.', 'ACT')
ON CONFLICT (tivi_nombre) DO UPDATE
SET tivi_abreviatura = EXCLUDED.tivi_abreviatura,
    tivi_estado      = EXCLUDED.tivi_estado;

-- 11.2 Tipos de Zona Oficiales (Estrictamente los 28 tipos oficiales de Chiclayo)
INSERT INTO tb_tipo_zona (tizo_id, tizo_nombre, tizo_abreviatura, tizo_estado) VALUES
    (1, 'ASENTAMIENTO HUMANO', 'A.H.', 'ACT'),
    (2, 'AGRUPACION', 'AGRUP.', 'ACT'),
    (3, 'CONJUNTO HABITACIONAL', 'CONJ.HAB.', 'ACT'),
    (4, 'CONJUNTO RESIDENCIAL', 'CONJ.RES.', 'ACT'),
    (5, 'PUEBLO JOVEN', 'P.J.', 'ACT'),
    (6, 'URBANIZACION', 'URB.', 'ACT'),
    (7, 'URBANIZACION POPULAR', 'URB.POP.', 'ACT'),
    (8, 'CERCADO', 'CERCADO', 'ACT'),
    (9, 'HACIENDA', 'HAC.', 'ACT'),
    (10, 'ASOCIACION', 'ASOC.', 'ACT'),
    (11, 'COOPERATIVA', 'COOP.', 'ACT'),
    (12, 'LOTIZACION', 'LOT.', 'ACT'),
    (13, 'PARCELA', 'PARC.', 'ACT'),
    (14, 'VALLE', 'VALLE', 'ACT'),
    (15, 'CASERIO', 'CAS.', 'ACT'),
    (16, 'UNIDAD VECINAL', 'U.V.', 'ACT'),
    (17, 'COMUNIDAD', 'COM.', 'ACT'),
    (18, 'BARRIO', 'BO.', 'ACT'),
    (19, 'FUNDO', 'FDO.', 'ACT'),
    (20, 'JUNTA DE COMPRADORES', 'J.COMP.', 'ACT'),
    (21, 'ASOCIACION DE VIVIENDA', 'ASOC.VIV.', 'ACT'),
    (22, 'COOPERATIVA DE VIVIENDA', 'COOP.VIV.', 'ACT'),
    (23, 'SOCIEDAD', 'SOC.', 'ACT'),
    (24, 'ASOCIACION PRO VIVIENDA', 'ASOC.PVIV.', 'ACT'),
    (25, 'ZONA', 'ZONA', 'ACT'),
    (26, 'CENTRO POBLADO', 'C.P.', 'ACT'),
    (27, 'ANEXO', 'ANEXO', 'ACT'),
    (28, 'COMUNIDAD INDIGENA', 'COM.IND.', 'ACT')
ON CONFLICT (tizo_nombre) DO UPDATE
SET tizo_abreviatura = EXCLUDED.tizo_abreviatura,
    tizo_estado      = EXCLUDED.tizo_estado;

-- 11.3 Componentes de Dirección (Urbanos y Rurales)
INSERT INTO tb_componente_direccion (codi_id, codi_nombre, codi_es_urbano, codi_estado) VALUES
    (1, 'MANZANA', TRUE, 'ACT'),
    (2, 'LOTE', TRUE, 'ACT'),
    (3, 'SUBLOTE', TRUE, 'ACT'),
    (4, 'PISO', TRUE, 'ACT'),
    (5, 'PREDIO', FALSE, 'ACT'),
    (6, 'VALLE', FALSE, 'ACT'),
    (7, 'SECTOR', FALSE, 'ACT'),
    (8, 'UNIDAD CATASTRAL', FALSE, 'ACT'),
    (9, 'COORDENADA NORTE', FALSE, 'ACT'),
    (10, 'COORDENADA ESTE', FALSE, 'ACT')
ON CONFLICT (codi_nombre) DO UPDATE
SET codi_es_urbano = EXCLUDED.codi_es_urbano,
    codi_estado    = EXCLUDED.codi_estado;

-- 11.4 Tipos de Módulo (Subunidades e Interiores)
INSERT INTO tb_tipo_modulo (timo_id, timo_nombre, timo_estado) VALUES
    (1, 'INTERIOR', 'ACT'),
    (2, 'DEPARTAMENTO', 'ACT'),
    (3, 'PUERTA', 'ACT'),
    (4, 'STAND', 'ACT'),
    (5, 'TIENDA', 'ACT'),
    (6, 'OFICINA', 'ACT'),
    (7, 'BLOCK', 'ACT'),
    (8, 'PUESTO', 'ACT'),
    (9, 'LOCAL', 'ACT'),
    (10, 'COCHERA', 'ACT')
ON CONFLICT (timo_nombre) DO UPDATE
SET timo_estado = EXCLUDED.timo_estado;

-- -----------------------------------------------------------------------------
-- 12. Vista de Reconstrucción de Direcciones Normalizadas V2
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_direcciones_v2 AS
SELECT 
    d.dire_id,
    d.dire_referencia,
    d.dire_estado,
    -- Datos de Zona
    z.zona_id,
    z.zona_nombre AS zona_oficial,
    tz.tizo_nombre AS tipo_zona_oficial,
    tz.tizo_abreviatura AS abrev_tipo_zona,
    -- Datos de Vía Principal (divi_orden = 1)
    v1.via_id AS via_principal_id,
    v1.via_nombre AS via_principal_nombre,
    tv1.tivi_nombre AS tipo_via_principal,
    dv1.divi_numero AS num_via_principal,
    -- Datos de Vía Secundaria / Intersección (divi_orden = 2)
    v2.via_id AS via_secundaria_id,
    v2.via_nombre AS via_secundaria_nombre,
    tv2.tivi_nombre AS tipo_via_secundaria,
    dv2.divi_numero AS num_via_secundaria
FROM tb_direccion d
LEFT JOIN tb_zona z ON d.zona_id = z.zona_id
LEFT JOIN tb_tipo_zona tz ON z.tizo_id = tz.tizo_id
LEFT JOIN tb_direccion_via dv1 ON d.dire_id = dv1.dire_id AND dv1.divi_orden = 1
LEFT JOIN tb_via v1 ON dv1.via_id = v1.via_id
LEFT JOIN tb_tipo_via tv1 ON v1.tivi_id = tv1.tivi_id
LEFT JOIN tb_direccion_via dv2 ON d.dire_id = dv2.dire_id AND dv2.divi_orden = 2
LEFT JOIN tb_via v2 ON dv2.via_id = v2.via_id
LEFT JOIN tb_tipo_via tv2 ON v2.tivi_id = tv2.tivi_id;
