-- =============================================================================
-- MUNICIPALIDAD PROVINCIAL DE CHICLAYO (MPCH)
-- SISTEMA ETL DE NORMALIZACIÓN CATASTRAL CON IA
-- =============================================================================
-- SCRIPT 01: DDL DE ESTRUCTURA CATASTRAL NORMALIZADA V2
-- ARCHIVO:   docs/01_ddl_estructura_catastral_mpch_v2.sql
-- VERSIÓN:   2.0 (Arquitectura Centralizada Polimórfica sin fecha_proceso)
-- =============================================================================
-- DESCRIPCIÓN:
--   Crea la arquitectura física relacional V2 completa (10 tablas normalizadas)
--   e índices optimizados para el procesamiento masivo con Inteligencia Artificial.
--   Es 100% idempotente (puede ejecutarse múltiples veces de forma segura).
--
-- ORDEN DE CREACIÓN RESPETANDO DEPENDENCIAS DE INTEGRIDAD REFERENCIAL:
--   1. tb_tipo_via
--   2. tb_via (FK -> tb_tipo_via)
--   3. tb_tipo_zona
--   4. tb_zona (FK -> tb_tipo_zona)
--   5. tb_direccion (FK -> tb_zona, referencia polimórfica a tablas de origen)
--   6. tb_direccion_via (FK -> tb_direccion, FK -> tb_via)
--   7. tb_componente_direccion
--   8. tb_contenido_componente_direccion (FK -> tb_direccion, FK -> tb_componente_direccion)
--   9. tb_tipo_modulo
--  10. tb_direccion_tipo_modulo (FK -> tb_direccion, FK -> tb_tipo_modulo)
--  11. Vista relacional de consulta: v_direcciones_v2
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. TABLA MAESTRA: TIPOS DE VÍA (tb_tipo_via)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_via (
    tivi_id             BIGSERIAL NOT NULL,
    tivi_nombre         VARCHAR(100) NOT NULL,
    tivi_abreviatura    VARCHAR(20),
    tivi_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (tivi_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_tipo_via PRIMARY KEY (tivi_id),
    CONSTRAINT uq_tb_tipo_via_nombre UNIQUE (tivi_nombre)
);

COMMENT ON TABLE tb_tipo_via IS 'Catálogo maestro institucional de tipos de arteria vial (AVENIDA, CALLE, JIRÓN, etc.).';
COMMENT ON COLUMN tb_tipo_via.tivi_id IS 'Identificador numérico único del tipo de vía.';
COMMENT ON COLUMN tb_tipo_via.tivi_nombre IS 'Nombre completo oficial del tipo de vía.';
COMMENT ON COLUMN tb_tipo_via.tivi_abreviatura IS 'Abreviatura estándar oficial (AV., CA., JR., etc.).';
COMMENT ON COLUMN tb_tipo_via.tivi_estado IS 'Estado del registro: A = Activo (tipo de vía vigente para normalización y uso oficial), I = Inactivo (deshabilitado o en desuso).';
COMMENT ON COLUMN tb_tipo_via.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_via.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_via.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_tipo_via.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_tipo_via.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_tipo_via.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_tipo_via.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_tipo_via.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

-- -----------------------------------------------------------------------------
-- 2. TABLA MAESTRA: VÍAS OFICIALES DE CHICLAYO (tb_via)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_via (
    via_id              BIGSERIAL NOT NULL,
    tivi_id             BIGINT NOT NULL,
    via_nombre          VARCHAR(250) NOT NULL,
    via_estado          VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (via_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

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
COMMENT ON COLUMN tb_via.via_nombre IS 'Denominación oficial de la vía sin prefijo de tipo (ej. BALTA, LUIS GONZALES, 7 DE ENERO).';
COMMENT ON COLUMN tb_via.via_estado IS 'Estado del registro: A = Activo (arteria vial vigente, habilitada y transitable), I = Inactivo (vía clausurada, renombrada históricamente o deshabilitada).';
COMMENT ON COLUMN tb_via.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_via.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_via.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_via.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_via.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_via.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_via.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_via.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE INDEX IF NOT EXISTS idx_tb_via_nombre ON tb_via (via_nombre);
CREATE INDEX IF NOT EXISTS idx_tb_via_tipo_nombre ON tb_via (tivi_id, via_nombre);

-- -----------------------------------------------------------------------------
-- 3. TABLA MAESTRA: TIPOS DE ZONA (tb_tipo_zona - 28 tipos oficiales)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_zona (
    tizo_id             BIGSERIAL NOT NULL,
    tizo_nombre         VARCHAR(100) NOT NULL,
    tizo_abreviatura    VARCHAR(20),
    tizo_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (tizo_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_tipo_zona PRIMARY KEY (tizo_id),
    CONSTRAINT uq_tb_tipo_zona_nombre UNIQUE (tizo_nombre)
);

COMMENT ON TABLE tb_tipo_zona IS 'Catálogo maestro de los 28 tipos oficiales de habilitación urbana y zona catastral.';
COMMENT ON COLUMN tb_tipo_zona.tizo_id IS 'Identificador secuencial único del tipo de zona.';
COMMENT ON COLUMN tb_tipo_zona.tizo_nombre IS 'Nombre oficial completo (URBANIZACION, PUEBLO JOVEN, ASOCIACION PRO VIVIENDA, etc.).';
COMMENT ON COLUMN tb_tipo_zona.tizo_abreviatura IS 'Abreviatura oficial (URB., P.J., A.H., etc.).';
COMMENT ON COLUMN tb_tipo_zona.tizo_estado IS 'Estado del registro: A = Activo (tipo de habilitación urbana oficial vigente y aplicable), I = Inactivo (tipo deshabilitado o en desuso).';
COMMENT ON COLUMN tb_tipo_zona.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_zona.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_zona.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_tipo_zona.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_tipo_zona.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_tipo_zona.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_tipo_zona.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_tipo_zona.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

-- -----------------------------------------------------------------------------
-- 4. TABLA MAESTRA: HABILITACIONES URBANAS Y ZONAS (tb_zona)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_zona (
    zona_id             BIGSERIAL NOT NULL,
    tizo_id             BIGINT NOT NULL,
    zona_nombre         VARCHAR(250) NOT NULL,
    zona_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (zona_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

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
COMMENT ON COLUMN tb_zona.zona_estado IS 'Estado del registro: A = Activo (sector o habilitación urbana formal vigente), I = Inactivo (zona histórica, fusionada o deshabilitada).';
COMMENT ON COLUMN tb_zona.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_zona.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_zona.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_zona.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_zona.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_zona.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_zona.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_zona.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE INDEX IF NOT EXISTS idx_tb_zona_nombre ON tb_zona (zona_nombre);
CREATE INDEX IF NOT EXISTS idx_tb_zona_tipo_nombre ON tb_zona (tizo_id, zona_nombre);

-- -----------------------------------------------------------------------------
-- 5. TABLA PRINCIPAL CENTRALIZADA: DIRECCIONES NORMALIZADAS (tb_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion (
    dire_id             BIGSERIAL NOT NULL,
    zona_id             BIGINT,
    dire_referencia     TEXT,
    dire_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (dire_estado IN ('A', 'I')),
    dire_esquema        VARCHAR(500),
    dire_tabla          VARCHAR(500),
    dire_columna        VARCHAR(500),
    dire_tabla_id       BIGINT,
    dire_valor_origen   VARCHAR(500),
    dire_es_procesado   BOOLEAN,
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_direccion PRIMARY KEY (dire_id),
    CONSTRAINT fk_tb_direccion_zona 
        FOREIGN KEY (zona_id) 
        REFERENCES tb_zona (zona_id) 
        ON UPDATE CASCADE 
        ON DELETE SET NULL
);

COMMENT ON TABLE tb_direccion IS 'Entidad central polimórfica que consolida la dirección normalizada de múltiples esquemas institucionales (licencias, rentas, catastro, etc.) mediante referencia lógica (dire_esquema, dire_tabla, dire_columna, dire_tabla_id) sin alterar tablas de origen.';
COMMENT ON COLUMN tb_direccion.dire_id IS 'Identificador secuencial único de la dirección normalizada.';
COMMENT ON COLUMN tb_direccion.zona_id IS 'Clave foránea hacia tb_zona. Permite NULL si el predio no posee zona registrada.';
COMMENT ON COLUMN tb_direccion.dire_referencia IS 'Hito espacial o comercial de orientación urbana (ej. CERCA AL SENATI, FRENTE AL PARQUE).';
COMMENT ON COLUMN tb_direccion.dire_estado IS 'Estado del registro: A = Activo (dirección normalizada vigente y válida para operaciones municipales), I = Inactivo (dirección dada de baja, reemplazada o anulada).';
COMMENT ON COLUMN tb_direccion.dire_esquema IS 'Nombre del esquema emisor de origen (ej. sc_migracion_direcciones, rentas, catastro, public).';
COMMENT ON COLUMN tb_direccion.dire_tabla IS 'Nombre de la tabla de negocio de origen.';
COMMENT ON COLUMN tb_direccion.dire_columna IS 'Nombre de la columna del sistema de origen que contiene la dirección sin estructurar (ej. emp_direccion, direccion, etc.).';
COMMENT ON COLUMN tb_direccion.dire_tabla_id IS 'Clave primaria del registro en la tabla de origen (referencia lógica polimórfica, sin FK rígida).';
COMMENT ON COLUMN tb_direccion.dire_valor_origen IS 'Texto crudo original de la dirección extraída de la fuente; se conserva como referencia hasta validación física manual.';
COMMENT ON COLUMN tb_direccion.dire_es_procesado IS 'Semántica Tri-State: NULL = Pendiente | TRUE = Normalizado 100% Certeza | FALSE = Rechazado / Incoherente.';
COMMENT ON COLUMN tb_direccion.usua_id IS 'Identificador numérico del usuario institucional.';
COMMENT ON COLUMN tb_direccion.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_direccion.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_direccion.update_at IS 'Fecha y hora de última modificación o normalización.';
COMMENT ON COLUMN tb_direccion.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_direccion.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_direccion.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_direccion.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE INDEX IF NOT EXISTS idx_tb_direccion_zona ON tb_direccion (zona_id);
CREATE INDEX IF NOT EXISTS idx_tb_direccion_proc ON tb_direccion (dire_esquema, dire_tabla, dire_es_procesado);
CREATE INDEX IF NOT EXISTS idx_tb_direccion_origen_lookup ON tb_direccion (dire_esquema, dire_tabla, dire_tabla_id);

-- -----------------------------------------------------------------------------
-- 6. TABLA INTERMEDIA: DIRECCIÓN - VÍAS (tb_direccion_via - Esquinas e Intersecciones)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion_via (
    divi_id             BIGSERIAL NOT NULL,
    dire_id             BIGINT NOT NULL,
    via_id              BIGINT NOT NULL,
    divi_numero         VARCHAR(50),
    divi_cuadra         VARCHAR(20),
    divi_orden          INTEGER NOT NULL DEFAULT 1,
    divi_es_principal   BOOLEAN NOT NULL DEFAULT TRUE,
    divi_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (divi_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_direccion_via PRIMARY KEY (divi_id),
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

COMMENT ON TABLE tb_direccion_via IS 'Relación que asocia vías con la dirección. Soporta esquinas e intersecciones múltiples ordenadas.';
COMMENT ON COLUMN tb_direccion_via.divi_id IS 'Identificador secuencial único de la relación dirección-vía.';
COMMENT ON COLUMN tb_direccion_via.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_direccion_via.via_id IS 'Clave foránea hacia tb_via.';
COMMENT ON COLUMN tb_direccion_via.divi_numero IS 'Numeración municipal en esta arteria (ej. 1020, 1024-B, S/N).';
COMMENT ON COLUMN tb_direccion_via.divi_cuadra IS 'Número de cuadra en la que se ubica la dirección (ej. CDA. 10).';
COMMENT ON COLUMN tb_direccion_via.divi_orden IS 'Orden de prelación vial: 1 = Principal, 2 = Secundaria / Esquina, 3 = Intersección adicional.';
COMMENT ON COLUMN tb_direccion_via.divi_es_principal IS 'Indica si es la vía principal (true) o una vía secundaria/intersección (false).';
COMMENT ON COLUMN tb_direccion_via.divi_estado IS 'Estado del registro: A = Activo (relación vial asociada vigente y vinculada a la dirección), I = Inactivo (relación vial desestimada o dada de baja).';
COMMENT ON COLUMN tb_direccion_via.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_direccion_via.usua_nombre IS 'Nombre o login del usuario institucional.';
COMMENT ON COLUMN tb_direccion_via.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_direccion_via.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_direccion_via.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_direccion_via.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_direccion_via.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_direccion_via.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_via_lookup ON tb_direccion_via (dire_id, via_id);
CREATE INDEX IF NOT EXISTS idx_tb_direccion_via_lookup ON tb_direccion_via (dire_id, via_id);
CREATE INDEX IF NOT EXISTS idx_tb_direccion_via_principal ON tb_direccion_via (divi_es_principal);

-- -----------------------------------------------------------------------------
-- 7. TABLA MAESTRA: COMPONENTES DE DIRECCIÓN (tb_componente_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_componente_direccion (
    codi_id             BIGSERIAL NOT NULL,
    codi_nombre         VARCHAR(100) NOT NULL,
    codi_abreviatura    VARCHAR(20),
    codi_es_urbano      BOOLEAN DEFAULT TRUE,
    codi_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (codi_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_componente_direccion PRIMARY KEY (codi_id),
    CONSTRAINT uq_tb_componente_direccion_nombre UNIQUE (codi_nombre)
);

COMMENT ON TABLE tb_componente_direccion IS 'Catálogo de atributos catastrales urbanos (Mz, Lote, Piso) y rurales (Valle, Predio, Sector).';
COMMENT ON COLUMN tb_componente_direccion.codi_id IS 'Identificador único del tipo de componente.';
COMMENT ON COLUMN tb_componente_direccion.codi_nombre IS 'Nombre del componente (MANZANA, LOTE, SUBLOTE, PISO, BLOCK, etc.).';
COMMENT ON COLUMN tb_componente_direccion.codi_abreviatura IS 'Abreviatura estandarizada (MZ., LT., SLT., PISO, BLK.).';
COMMENT ON COLUMN tb_componente_direccion.codi_es_urbano IS 'True: Urbano, False: Rural.';
COMMENT ON COLUMN tb_componente_direccion.codi_estado IS 'Estado del registro: A = Activo (tipo de componente predial habilitado para estructuración catastral), I = Inactivo (componente deshabilitado o no utilizado).';
COMMENT ON COLUMN tb_componente_direccion.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_componente_direccion.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_componente_direccion.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_componente_direccion.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_componente_direccion.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_componente_direccion.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_componente_direccion.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_componente_direccion.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

-- -----------------------------------------------------------------------------
-- 8. TABLA RELACIONAL: CONTENIDO DE COMPONENTES (tb_contenido_componente_direccion)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_contenido_componente_direccion (
    diti_id             BIGSERIAL NOT NULL,
    dire_id             BIGINT NOT NULL,
    codi_id             BIGINT NOT NULL,
    diti_valor          VARCHAR(100) NOT NULL,
    diti_orden          INTEGER NOT NULL DEFAULT 1,
    diti_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (diti_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_contenido_componente_direccion PRIMARY KEY (diti_id),
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
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_id IS 'Identificador secuencial del contenido del componente.';
COMMENT ON COLUMN tb_contenido_componente_direccion.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_contenido_componente_direccion.codi_id IS 'Clave foránea hacia tb_componente_direccion.';
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_valor IS 'Valor asignado al componente (ej. A, 14, 2, B).';
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_orden IS 'Orden secuencial de aparición o visualización del componente en la dirección (1, 2, ...).';
COMMENT ON COLUMN tb_contenido_componente_direccion.diti_estado IS 'Estado del registro: A = Activo (valor del componente predial vigente y asignado al predio), I = Inactivo (valor corregido, anulado o dado de baja).';
COMMENT ON COLUMN tb_contenido_componente_direccion.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_contenido_componente_direccion.usua_nombre IS 'Nombre o login del usuario institucional.';
COMMENT ON COLUMN tb_contenido_componente_direccion.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_contenido_componente_direccion.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_contenido_componente_direccion.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_contenido_componente_direccion.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_contenido_componente_direccion.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_contenido_componente_direccion.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_contenido_comp_lookup ON tb_contenido_componente_direccion (dire_id, codi_id);
CREATE INDEX IF NOT EXISTS idx_tb_contenido_comp_lookup ON tb_contenido_componente_direccion (dire_id, codi_id);

-- -----------------------------------------------------------------------------
-- 9. TABLA MAESTRA: TIPOS DE MÓDULO (tb_tipo_modulo)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_tipo_modulo (
    timo_id             BIGSERIAL NOT NULL,
    timo_nombre         VARCHAR(100) NOT NULL,
    timo_abreviatura    VARCHAR(20),
    timo_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (timo_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_tipo_modulo PRIMARY KEY (timo_id),
    CONSTRAINT uq_tb_tipo_modulo_nombre UNIQUE (timo_nombre)
);

COMMENT ON TABLE tb_tipo_modulo IS 'Catálogo de tipos de dependencias y subunidades (INTERIOR, DEPARTAMENTO, STAND, TIENDA, etc.).';
COMMENT ON COLUMN tb_tipo_modulo.timo_id IS 'Identificador único del tipo de modulo.';
COMMENT ON COLUMN tb_tipo_modulo.timo_nombre IS 'Nombre del tipo de modulo (DEPARTAMENTO, INTERIOR, STAND, TIENDA, etc.).';
COMMENT ON COLUMN tb_tipo_modulo.timo_abreviatura IS 'Abreviatura estandarizada (DPTO., INT., STD., TDA., OF.).';
COMMENT ON COLUMN tb_tipo_modulo.timo_estado IS 'Estado del registro: A = Activo (tipo de módulo o dependencia vigente y habilitada), I = Inactivo (tipo deshabilitado o en desuso).';
COMMENT ON COLUMN tb_tipo_modulo.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_modulo.usua_nombre IS 'Nombre o login del usuario responsable de la operación.';
COMMENT ON COLUMN tb_tipo_modulo.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_tipo_modulo.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_tipo_modulo.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_tipo_modulo.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_tipo_modulo.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_tipo_modulo.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

-- -----------------------------------------------------------------------------
-- 10. TABLA RELACIONAL: DIRECCIÓN - TIPOS DE MÓDULO (tb_direccion_tipo_modulo)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tb_direccion_tipo_modulo (
    ditm_id             BIGSERIAL NOT NULL,
    dire_id             BIGINT NOT NULL,
    timo_id             BIGINT NOT NULL,
    ditm_nombre         VARCHAR(100) NOT NULL,
    ditm_orden          INTEGER NOT NULL DEFAULT 1,
    ditm_estado         VARCHAR(1) NOT NULL DEFAULT 'A' CHECK (ditm_estado IN ('A', 'I')),
    usua_id             BIGINT,
    usua_nombre         VARCHAR(200),
    create_at           TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    update_at           TIMESTAMP WITHOUT TIME ZONE,
    audit_user_pc       VARCHAR(100),
    audit_nombre_pc     VARCHAR(100),
    audit_ip            VARCHAR(50),
    audit_mac_address   VARCHAR(50),

    CONSTRAINT pk_tb_direccion_tipo_modulo PRIMARY KEY (ditm_id),
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
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_id IS 'Identificador único de la relación dirección-modulo.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.dire_id IS 'Clave foránea hacia tb_direccion.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.timo_id IS 'Clave foránea hacia tb_tipo_modulo.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_nombre IS 'Identificador o número del módulo (ej. 402, 12, A-3).';
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_orden IS 'Orden secuencial de aparición o jerarquía del módulo en la dirección (1 = Módulo principal, 2 = Submódulo, etc.).';
COMMENT ON COLUMN tb_direccion_tipo_modulo.ditm_estado IS 'Estado del registro: A = Activo (módulo inmobiliario específico asociado y vigente), I = Inactivo (módulo deshabilitado o dado de baja).';
COMMENT ON COLUMN tb_direccion_tipo_modulo.usua_id IS 'Identificador numérico del usuario responsable de la operación.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.usua_nombre IS 'Nombre o login del usuario institucional.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.create_at IS 'Fecha y hora de creación del registro en el sistema.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.update_at IS 'Fecha y hora de última modificación en el sistema.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.audit_user_pc IS 'Nombre de usuario del sistema operativo cliente/auditoría.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.audit_nombre_pc IS 'Nombre de host o equipo de la estación cliente.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.audit_ip IS 'Dirección IP de la estación que ejecutó la transacción.';
COMMENT ON COLUMN tb_direccion_tipo_modulo.audit_mac_address IS 'Dirección MAC física de la estación cliente.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_tb_direccion_modulo_lookup ON tb_direccion_tipo_modulo (dire_id, timo_id, ditm_nombre);

-- -----------------------------------------------------------------------------
-- 11. VISTA DE CONSULTA Y RECONSTRUCCIÓN CATASTRAL COMPLETA (v_direcciones_v2)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_direcciones_v2 AS
SELECT 
    d.dire_id,
    d.zona_id,
    d.dire_referencia,
    d.dire_estado,
    d.dire_esquema,
    d.dire_tabla,
    d.dire_columna,
    d.dire_tabla_id,
    d.dire_valor_origen,
    d.dire_es_procesado,
    d.usua_id,
    d.usua_nombre,
    d.create_at,
    d.update_at,
    d.audit_user_pc,
    d.audit_nombre_pc,
    d.audit_ip,
    d.audit_mac_address,
    -- Datos de Zona Oficial
    z.zona_id AS id_zona_oficial,
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
    dv2.divi_numero AS num_via_secundaria,
    -- Datos de Vía 3 / Intersección Adicional (divi_orden = 3)
    v3.via_id AS via_3_id,
    v3.via_nombre AS via_3_nombre,
    tv3.tivi_nombre AS tipo_via_3,
    dv3.divi_numero AS num_via_3
FROM tb_direccion d
LEFT JOIN tb_zona z ON d.zona_id = z.zona_id
LEFT JOIN tb_tipo_zona tz ON z.tizo_id = tz.tizo_id
LEFT JOIN tb_direccion_via dv1 ON d.dire_id = dv1.dire_id AND dv1.divi_orden = 1
LEFT JOIN tb_via v1 ON dv1.via_id = v1.via_id
LEFT JOIN tb_tipo_via tv1 ON v1.tivi_id = tv1.tivi_id
LEFT JOIN tb_direccion_via dv2 ON d.dire_id = dv2.dire_id AND dv2.divi_orden = 2
LEFT JOIN tb_via v2 ON dv2.via_id = v2.via_id
LEFT JOIN tb_tipo_via tv2 ON v2.tivi_id = tv2.tivi_id
LEFT JOIN tb_direccion_via dv3 ON d.dire_id = dv3.dire_id AND dv3.divi_orden = 3
LEFT JOIN tb_via v3 ON dv3.via_id = v3.via_id
LEFT JOIN tb_tipo_via tv3 ON v3.tivi_id = tv3.tivi_id;
