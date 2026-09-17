-- =============================================================================
-- PROYECTO: ETL MIGRACIÓN MPCH (Municipalidad Provincial de Chiclayo)
-- SCRIPT:   04_crear_schemas_de_prueba.sql
-- DESCRIPCIÓN:
--   Crea o reinicia los esquemas de prueba en PostgreSQL para validar
--   el comportamiento dinámico del método de ETL in-place en los 4 casos:
--
--   1. public: Esquema base con únicamente 'direcciones_actual' (sin catálogos).
--   2. schema_solo_tabla: Solo tabla de direcciones con registros muestra.
--   3. schema_cat_vacios: Con tablas categorizables sin filas y sin columna 'abreviatura'.
--   4. schema_cat_parciales: Con tablas categorizables con registros desalineados (CALLE=1, URB=1) para verificar la estandarización canónica y reasignación de relaciones.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. ESQUEMA: schema_solo_tabla (Caso 1: Solo tabla de direcciones)
-- -----------------------------------------------------------------------------
DROP SCHEMA IF EXISTS schema_solo_tabla CASCADE;
CREATE SCHEMA schema_solo_tabla;

CREATE TABLE schema_solo_tabla.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_sst_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_solo_tabla.direcciones_actual (id_licencia, emp_direccion) VALUES
    (101, 'AV. BALTA N° 500 URB. LOS FICUS - CHICLAYO'),
    (102, 'CALLE SAN JOSE 120 - CHICLAYO'),
    (103, 'JR. SAENZ PEÑA 340 INT. B - CHICLAYO'),
    (104, 'PASAJE LAS FLORES MZ. A LOTE 5 P.J. SAN CRISTOBAL'),
    (105, 'CARRETERA PIMENTEL KM 5 FUNDO LA ESPERANZA');


-- -----------------------------------------------------------------------------
-- 2. ESQUEMA: schema_cat_vacios (Caso 2: Catálogos vacíos y sin 'abreviatura')
-- -----------------------------------------------------------------------------
DROP SCHEMA IF EXISTS schema_cat_vacios CASCADE;
CREATE SCHEMA schema_cat_vacios;

CREATE TABLE schema_cat_vacios.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_scv_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_cat_vacios.direcciones_actual (id_licencia, emp_direccion) VALUES
    (201, 'AV. JOSE LEONARDO ORTIZ 450 URB. SANTA VICTORIA'),
    (202, 'CA. TACNA 234 - CHICLAYO'),
    (203, 'ALAMEDA DE LA PAZ 110 URB. POP. CHICLAYO'),
    (204, 'PRLG. BOLOGNESI S/N MZ. B LT. 12 A.H. NUEVA ESPERANZA'),
    (205, 'MALECON PEDRO RUIZ 800 CERCADO');

-- Tablas maestras intencionalmente sin columna 'abreviatura' y sin registros
CREATE TABLE schema_cat_vacios.tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    CONSTRAINT pk_scv_tipos_via PRIMARY KEY (id_tipo_via)
);

CREATE TABLE schema_cat_vacios.tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    CONSTRAINT pk_scv_tipos_zona PRIMARY KEY (id_tipo_zona)
);


-- -----------------------------------------------------------------------------
-- 3. ESQUEMA: schema_cat_parciales (Caso 3: Catálogos con registros pre-ocupados)
-- -----------------------------------------------------------------------------
DROP SCHEMA IF EXISTS schema_cat_parciales CASCADE;
CREATE SCHEMA schema_cat_parciales;

CREATE TABLE schema_cat_parciales.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_scp_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_cat_parciales.direcciones_actual (id_licencia, emp_direccion) VALUES
    (301, 'CALLE ARICA 1364 - CHICLAYO'),
    (302, 'AVENIDA BOLOGNESI 780 URB. SANTA VICTORIA'),
    (303, 'JIRON ELVIRA GARCIA 200 P.J. VICTOR RAUL'),
    (304, 'PASEO LAS MUSAS 150 MZ. C LT. 4 ASENTAMIENTO HUMANO EL PORVENIR'),
    (305, 'CARRETERA CHICLAYO FERREÑAFE KM 2');

-- Vías con 3 registros pre-ocupados (CALLE=1, AVENIDA=2, JIRON=3)
CREATE TABLE schema_cat_parciales.tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    abreviatura         VARCHAR(15),
    CONSTRAINT pk_scp_tipos_via PRIMARY KEY (id_tipo_via)
);

INSERT INTO schema_cat_parciales.tipos_via (id_tipo_via, nombre_tipo_via, abreviatura) VALUES
    (1, 'CALLE',   'CA.'),
    (2, 'AVENIDA', 'AV.'),
    (3, 'JIRON',   'JR.');

-- Zonas con 3 registros pre-ocupados (URB=1, PJ=2, AH=3)
CREATE TABLE schema_cat_parciales.tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    abreviatura         VARCHAR(20),
    CONSTRAINT pk_scp_tipos_zona PRIMARY KEY (id_tipo_zona)
);

INSERT INTO schema_cat_parciales.tipos_zona (id_tipo_zona, nombre_tipo_zona, abreviatura) VALUES
    (1, 'URBANIZACION',        'URB.'),
    (2, 'PUEBLO JOVEN',        'P.J.'),
    (3, 'ASENTAMIENTO HUMANO', 'A.H.');

-- -----------------------------------------------------------------------------
-- Fin del script de inicialización de pruebas
-- -----------------------------------------------------------------------------
