-- =============================================================================
-- INICIALIZACIÓN AUTOMÁTICA DE BASE DE DATOS DOCKER - MPCH
-- =============================================================================
-- Este script se ejecuta automáticamente al inicializar el contenedor PostgreSQL.
-- Configura el esquema principal ('public') con ÚNICAMENTE la tabla de direcciones
-- para ser procesada in-place por el ETL, además de 3 esquemas de prueba
-- que representan los diferentes escenarios que el ETL maneja dinámicamente:
--   1. public / schema_solo_tabla : Solo tabla de direcciones (sin catálogos).
--   2. schema_cat_vacios          : Con catálogos creados pero sin datos y sin columna abreviatura.
--   3. schema_cat_parciales       : Con catálogos con 3-4 registros e IDs pre-ocupados.
-- =============================================================================

-- =============================================================================
-- ESQUEMA 1: public (Esquema Principal / Carga de Producción)
-- Únicamente la tabla origen 'direcciones_actual'.
-- Las tablas 'tipos_via' y 'tipos_zona' NO existen; el ETL las creará y sembrará in-place.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_direcciones_actual PRIMARY KEY (id_licencia)
);

-- Carga de registros desde /data_import/Direcciones_.csv (o semillas de respaldo)
DO $$
BEGIN
    IF pg_stat_file('/data_import/Direcciones_.csv', true) IS NOT NULL THEN
        COPY public.direcciones_actual (id_licencia, emp_direccion)
        FROM '/data_import/Direcciones_.csv'
        WITH (FORMAT csv, HEADER true, DELIMITER ',', ENCODING 'UTF8');
        RAISE NOTICE 'Registros importados exitosamente desde /data_import/Direcciones_.csv a public.direcciones_actual';
    ELSE
        INSERT INTO public.direcciones_actual (id_licencia, emp_direccion) VALUES
            (199, 'CALLE ARICA N 1364  -  CHICLAYO'),
            (200, 'CHICLAYOALFREDO LAPOINT 882  INT- I'),
            (201, 'AV. FITZCARRAL S/N (AEREOPUERTO JOSÉ ABELARDO QUIÑONES GONZALES) - CHICLAYO '),
            (202, 'CA. TIGRE N 213 URB. JOSÉ QUIÑONES GONZALES - CHICLAYO'),
            (203, 'CA. VICENTE DE LA VEGA N 1113 - CHICLAYO ')
        ON CONFLICT (id_licencia) DO NOTHING;
        RAISE NOTICE 'Semillas de prueba insertadas en public.direcciones_actual';
    END IF;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Aviso durante la carga de /data_import/Direcciones_.csv: %', SQLERRM;
END $$;


-- =============================================================================
-- ESQUEMA 2: schema_solo_tabla (Caso 1 de Prueba: Solo tabla de direcciones)
-- Sin tablas de catálogos. El ETL debe crearlas de cero y poblar las 12 vías y 28 zonas.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS schema_solo_tabla;

CREATE TABLE IF NOT EXISTS schema_solo_tabla.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_sst_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_solo_tabla.direcciones_actual (id_licencia, emp_direccion) VALUES
    (101, 'AV. BALTA N° 500 URB. LOS FICUS - CHICLAYO'),
    (102, 'CALLE SAN JOSE 120 - CHICLAYO'),
    (103, 'JR. SAENZ PEÑA 340 INT. B - CHICLAYO'),
    (104, 'PASAJE LAS FLORES MZ. A LOTE 5 P.J. SAN CRISTOBAL'),
    (105, 'CARRETERA PIMENTEL KM 5 FUNDO LA ESPERANZA')
ON CONFLICT (id_licencia) DO NOTHING;


-- =============================================================================
-- ESQUEMA 3: schema_cat_vacios (Caso 2 de Prueba: Catálogos vacíos y sin abreviatura)
-- Las tablas tipos_via y tipos_zona existen pero NO tienen registros y NO tienen columna abreviatura.
-- El ETL debe detectar la falta de 'abreviatura', agregarla vía ALTER TABLE y sembrar los catálogos.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS schema_cat_vacios;

CREATE TABLE IF NOT EXISTS schema_cat_vacios.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_scv_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_cat_vacios.direcciones_actual (id_licencia, emp_direccion) VALUES
    (201, 'AV. JOSE LEONARDO ORTIZ 450 URB. SANTA VICTORIA'),
    (202, 'CA. TACNA 234 - CHICLAYO'),
    (203, 'ALAMEDA DE LA PAZ 110 URB. POP. CHICLAYO'),
    (204, 'PRLG. BOLOGNESI S/N MZ. B LT. 12 A.H. NUEVA ESPERANZA'),
    (205, 'MALECON PEDRO RUIZ 800 CERCADO')
ON CONFLICT (id_licencia) DO NOTHING;

-- Tablas maestras intencionalmente sin columna 'abreviatura' y sin filas
CREATE TABLE IF NOT EXISTS schema_cat_vacios.tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    CONSTRAINT pk_scv_tipos_via PRIMARY KEY (id_tipo_via)
);

CREATE TABLE IF NOT EXISTS schema_cat_vacios.tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    CONSTRAINT pk_scv_tipos_zona PRIMARY KEY (id_tipo_zona)
);


-- =============================================================================
-- ESQUEMA 4: schema_cat_parciales (Caso 3 de Prueba: Catálogos con registros pre-ocupados)
-- Las tablas tipos_via y tipos_zona ya tienen 3 registros con IDs específicos:
--   tipos_via : 1=CALLE, 2=AVENIDA, 3=JIRON (¡nótese que CALLE es 1 y AVENIDA es 2!)
--   tipos_zona: 1=URBANIZACION, 2=PUEBLO JOVEN, 3=ASENTAMIENTO HUMANO
-- El ETL debe:
--   1. Detectar los registros existentes y estandarizar sus IDs al orden canónico del JSON (AVENIDA=1, CALLE=2).
--   2. Reasignar cualquier relación existente en la tabla de direcciones para mantener la consistencia relacional.
--   3. Completar las vías y zonas faltantes del JSON con sus IDs canónicos (12 vías, 28 zonas).
--   4. Sincronizar dinámicamente CatalogMatcher para que use el estándar canónico unificado.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS schema_cat_parciales;

CREATE TABLE IF NOT EXISTS schema_cat_parciales.direcciones_actual (
    id_licencia     INTEGER NOT NULL,
    emp_direccion   VARCHAR(255),
    CONSTRAINT pk_scp_direcciones PRIMARY KEY (id_licencia)
);

INSERT INTO schema_cat_parciales.direcciones_actual (id_licencia, emp_direccion) VALUES
    (301, 'CALLE ARICA 1364 - CHICLAYO'),
    (302, 'AVENIDA BOLOGNESI 780 URB. SANTA VICTORIA'),
    (303, 'JIRON ELVIRA GARCIA 200 P.J. VICTOR RAUL'),
    (304, 'PASEO LAS MUSAS 150 MZ. C LT. 4 ASENTAMIENTO HUMANO EL PORVENIR'),
    (305, 'CARRETERA CHICLAYO FERREÑAFE KM 2')
ON CONFLICT (id_licencia) DO NOTHING;

CREATE TABLE IF NOT EXISTS schema_cat_parciales.tipos_via (
    id_tipo_via         INTEGER NOT NULL,
    nombre_tipo_via     VARCHAR(50) NOT NULL,
    abreviatura         VARCHAR(15),
    CONSTRAINT pk_scp_tipos_via PRIMARY KEY (id_tipo_via)
);

INSERT INTO schema_cat_parciales.tipos_via (id_tipo_via, nombre_tipo_via, abreviatura) VALUES
    (1, 'CALLE',   'CA.'),
    (2, 'AVENIDA', 'AV.'),
    (3, 'JIRON',   'JR.')
ON CONFLICT (id_tipo_via) DO NOTHING;

CREATE TABLE IF NOT EXISTS schema_cat_parciales.tipos_zona (
    id_tipo_zona        INTEGER NOT NULL,
    nombre_tipo_zona    VARCHAR(100) NOT NULL,
    abreviatura         VARCHAR(20),
    CONSTRAINT pk_scp_tipos_zona PRIMARY KEY (id_tipo_zona)
);

INSERT INTO schema_cat_parciales.tipos_zona (id_tipo_zona, nombre_tipo_zona, abreviatura) VALUES
    (1, 'URBANIZACION',        'URB.'),
    (2, 'PUEBLO JOVEN',        'P.J.'),
    (3, 'ASENTAMIENTO HUMANO', 'A.H.')
ON CONFLICT (id_tipo_zona) DO NOTHING;
