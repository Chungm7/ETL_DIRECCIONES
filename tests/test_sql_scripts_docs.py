"""Pruebas de validación e integridad para los scripts SQL en docs/:

1. docs/01_ddl_estructura_catastral_mpch_v2.sql
2. docs/02_dml_insercion_catalogos_oficiales_mpch_v2.sql
"""

import os
import re
import pytest

DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
DDL_FILE = os.path.join(DOCS_DIR, "01_ddl_estructura_catastral_mpch_v2.sql")
DML_FILE = os.path.join(DOCS_DIR, "02_dml_insercion_catalogos_oficiales_mpch_v2.sql")


def test_ddl_script_exists_and_not_empty():
    assert os.path.isfile(DDL_FILE), f"El archivo DDL no existe en {DDL_FILE}"
    size = os.path.getsize(DDL_FILE)
    assert size > 1000, f"El archivo DDL es demasiado pequeño ({size} bytes)"


def test_ddl_contains_all_v2_tables_and_views():
    with open(DDL_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    expected_tables = [
        "tb_tipo_via",
        "tb_via",
        "tb_tipo_zona",
        "tb_zona",
        "tb_direccion",
        "tb_direccion_via",
        "tb_componente_direccion",
        "tb_contenido_componente_direccion",
        "tb_tipo_modulo",
        "tb_direccion_tipo_modulo",
    ]

    for tbl in expected_tables:
        pattern = rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?{tbl}\b"
        assert re.search(pattern, content, re.IGNORECASE), f"Falta la tabla {tbl} en el DDL"

    # Vista v_direcciones_v2
    assert "CREATE OR REPLACE VIEW" in content and "v_direcciones_v2" in content


def test_ddl_contains_audit_columns_and_zero_fecha_proceso():
    with open(DDL_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Columnas de auditoría deben existir
    assert "create_at" in content
    assert "update_at" in content

    # NO DEBE EXISTIR columna de definición fecha_proceso en las tablas
    assert not re.search(r"\bfecha_proceso\b\s+", content, re.IGNORECASE), "Columna fecha_proceso no debe existir en DDL"
    assert not re.search(r"\bfecha_procesamiento\b\s+", content, re.IGNORECASE), "Columna fecha_procesamiento no debe existir en DDL"


def test_dml_script_exists_and_not_empty():
    assert os.path.isfile(DML_FILE), f"El archivo DML no existe en {DML_FILE}"
    size = os.path.getsize(DML_FILE)
    assert size > 50000, f"El archivo DML debe contener los catálogos masivos (obtenido {size} bytes)"


def test_dml_contains_catalogs_and_sequences():
    with open(DML_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Catálogos maestros (con o sin schema)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_tipo_via\b", content, re.IGNORECASE)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_tipo_zona\b", content, re.IGNORECASE)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_tipo_modulo\b", content, re.IGNORECASE)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_componente_direccion\b", content, re.IGNORECASE)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_zona\b", content, re.IGNORECASE)
    assert re.search(r"INSERT\s+INTO\s+(?:public\.)?tb_via\b", content, re.IGNORECASE)

    # Concurrencia segura
    assert "ON CONFLICT" in content

    # Sincronización de secuencias
    assert "setval" in content
    assert "pg_get_serial_sequence('tb_via', 'via_id')" in content
    assert "pg_get_serial_sequence('tb_zona', 'zona_id')" in content

    # Cero columna fecha_proceso
    assert not re.search(r"\bfecha_proceso\b", content, re.IGNORECASE)


def test_ddl_catalog_tables_have_all_audit_columns():
    """Verifica que las 6 tablas maestras de catálogos en el DDL oficial
    contengan las 8 columnas de auditoría estándar requeridas por el plan."""
    with open(DDL_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    CATALOG_TABLES = [
        "tb_tipo_via",
        "tb_via",
        "tb_tipo_zona",
        "tb_zona",
        "tb_componente_direccion",
        "tb_tipo_modulo",
    ]

    AUDIT_COLUMNS = [
        "usua_id",
        "usua_nombre",
        "create_at",
        "update_at",
        "audit_user_pc",
        "audit_nombre_pc",
        "audit_ip",
        "audit_mac_address",
    ]

    # Para cada tabla maestra extraer su bloque CREATE TABLE y verificar cada columna de auditoría
    for table in CATALOG_TABLES:
        # Buscar el bloque CREATE TABLE de esta tabla
        pattern = rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?{table}\s*\((.+?)(?=CONSTRAINT\s+pk_|CONSTRAINT\s+fk_|\);)"
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        assert match, f"No se encontró el bloque CREATE TABLE de {table} en el DDL"

        table_body = match.group(0)
        for col in AUDIT_COLUMNS:
            assert col in table_body, (
                f"Columna de auditoría '{col}' faltante en la definición DDL de {table}"
            )
