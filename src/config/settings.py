"""Módulo de configuración centralizado del proyecto ETL.

Carga variables de entorno desde el archivo .env utilizando Pydantic Settings.
Permite parametrizar esquemas, tablas y columnas de forma totalmente dinámica
sin modificar código, enfocado en el método único In-Place (evolución de tabla en sitio).
"""

from functools import lru_cache
from typing import Optional
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """Configuración de conexión a PostgreSQL (Servidor único con soporte multi-schema e in-place)."""
    host: str = Field(default="localhost", validation_alias=AliasChoices("DB_HOST"))
    port: int = Field(default=5432, validation_alias=AliasChoices("DB_PORT"))
    name: str = Field(default="bd_mpch", validation_alias=AliasChoices("DB_NAME"))
    user: str = Field(default="postgres", validation_alias=AliasChoices("DB_USER"))
    password: str = Field(default="postgres", validation_alias=AliasChoices("DB_PASSWORD"))

    # --- Esquema y Tabla de Direcciones a Procesar (In-Place) ---
    db_schema: str = Field(
        default="public",
        validation_alias=AliasChoices("DB_SCHEMA", "DB_SOURCE_SCHEMA", "DB_TARGET_SCHEMA"),
        description="Esquema donde reside la tabla de direcciones y sus catálogos",
    )
    table: str = Field(
        default="direcciones_actual",
        validation_alias=AliasChoices("DB_TABLE", "DB_SOURCE_TABLE", "DB_TARGET_TABLE"),
        description="Tabla única de direcciones que se lee y se enriquece in-place",
    )
    id_col: str = Field(
        default="id_licencia",
        validation_alias=AliasChoices("DB_ID_COL", "DB_SOURCE_ID_COL", "DB_TARGET_ID_COL"),
        description="Columna identificadora (PK) a conservar estrictamente intacta",
    )
    dir_col: str = Field(
        default="emp_direccion",
        validation_alias=AliasChoices("DB_DIR_COL", "DB_SOURCE_DIR_COL"),
        description="Columna con el texto original sin procesar de la dirección",
    )

    # --- Tablas Maestras Categorizables (En el mismo esquema) ---
    table_tipo_via: str = Field(
        default="tipos_via",
        validation_alias=AliasChoices("DB_TABLE_TIPO_VIA", "DB_TARGET_TABLE_TIPO_VIA", "table_tipo_via"),
        description="Nombre de la tabla maestra de tipos de vía en el esquema",
    )
    table_tipo_zona: str = Field(
        default="tipos_zona",
        validation_alias=AliasChoices("DB_TABLE_TIPO_ZONA", "DB_TARGET_TABLE_TIPO_ZONA", "table_tipo_zona"),
        description="Nombre de la tabla maestra de tipos de zona en el esquema",
    )
    table_vias: str = Field(
        default="vias",
        validation_alias=AliasChoices("DB_TABLE_VIAS", "DB_TARGET_TABLE_VIAS", "table_vias"),
        description="Nombre de la tabla maestra de vías de Chiclayo en el esquema",
    )
    table_zonas: str = Field(
        default="zonas",
        validation_alias=AliasChoices("DB_TABLE_ZONAS", "DB_TARGET_TABLE_ZONAS", "table_zonas"),
        description="Nombre de la tabla maestra de habilitaciones urbanas de Chiclayo en el esquema",
    )

    # --- Nombres Dinámicos de Columnas Normalizadas (Agregadas In-Place) ---
    col_id_via: str = Field(
        default="id_via",
        validation_alias=AliasChoices("COL_ID_VIA", "DB_TARGET_ID_VIA_COL", "col_id_via"),
    )
    col_tipo_via: str = Field(
        default="tipo_via",
        validation_alias=AliasChoices("COL_TIPO_VIA", "DB_TARGET_TIPO_VIA_COL", "col_tipo_via"),
    )
    col_nom_via: str = Field(
        default="nom_via",
        validation_alias=AliasChoices("COL_NOM_VIA", "DB_TARGET_NOM_VIA_COL", "col_nom_via"),
    )
    col_num_via: str = Field(
        default="num_via",
        validation_alias=AliasChoices("COL_NUM_VIA", "DB_TARGET_NUM_VIA_COL", "col_num_via"),
    )
    col_id_zona: str = Field(
        default="id_zona",
        validation_alias=AliasChoices("COL_ID_ZONA", "DB_TARGET_ID_ZONA_COL", "col_id_zona"),
    )
    col_tipo_zona: str = Field(
        default="tipo_zona",
        validation_alias=AliasChoices("COL_TIPO_ZONA", "DB_TARGET_TIPO_ZONA_COL", "col_tipo_zona"),
    )
    col_nom_zona: str = Field(
        default="nom_zona",
        validation_alias=AliasChoices("COL_NOM_ZONA", "DB_TARGET_NOM_ZONA_COL", "col_nom_zona"),
    )
    col_manzana: str = Field(
        default="manzana",
        validation_alias=AliasChoices("COL_MANZANA", "DB_TARGET_MZ_COL", "col_manzana"),
    )
    col_lote: str = Field(
        default="lote",
        validation_alias=AliasChoices("COL_LOTE", "DB_TARGET_LT_COL", "col_lote"),
    )
    col_slote: str = Field(
        default="slote",
        validation_alias=AliasChoices("COL_SLOTE", "DB_TARGET_SLT_COL", "col_slote"),
    )
    col_referencia: str = Field(
        default="referencia",
        validation_alias=AliasChoices("COL_REFERENCIA", "DB_TARGET_REF_COL", "col_referencia"),
    )
    col_es_procesado: str = Field(
        default="es_procesado",
        validation_alias=AliasChoices("COL_ES_PROCESADO", "DB_TARGET_PROCESADO_COL", "col_es_procesado"),
    )
    col_observacion: str = Field(
        default="observacion",
        validation_alias=AliasChoices("COL_OBSERVACION", "DB_TARGET_OBSERVACION_COL", "col_observacion"),
    )


    # --- Propiedades de compatibilidad hacia atrás ---
    @property
    def schema(self) -> str:
        return self.db_schema

    @property
    def source_schema(self) -> str:
        return self.schema

    @property
    def source_table(self) -> str:
        return self.table

    @property
    def source_id_col(self) -> str:
        return self.id_col

    @property
    def source_dir_col(self) -> str:
        return self.dir_col

    @property
    def target_schema(self) -> str:
        return self.schema

    @property
    def target_table(self) -> str:
        return self.table

    @property
    def target_table_tipo_via(self) -> str:
        return self.table_tipo_via

    @property
    def target_table_tipo_zona(self) -> str:
        return self.table_tipo_zona

    @property
    def target_id_col(self) -> str:
        return self.id_col

    @property
    def target_tipo_via_col(self) -> str:
        return self.col_tipo_via

    @property
    def target_nom_via_col(self) -> str:
        return self.col_nom_via

    @property
    def target_num_via_col(self) -> str:
        return self.col_num_via

    @property
    def target_tipo_zona_col(self) -> str:
        return self.col_tipo_zona

    @property
    def target_nom_zona_col(self) -> str:
        return self.col_nom_zona

    @property
    def target_mz_col(self) -> str:
        return self.col_manzana

    @property
    def target_lt_col(self) -> str:
        return self.col_lote

    @property
    def target_slt_col(self) -> str:
        return self.col_slote

    @property
    def url(self) -> str:
        """Genera el Connection String para SQLAlchemy."""
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class OllamaSettings(BaseSettings):
    """Configuración para el modelo local de Inteligencia Artificial con Ollama."""
    base_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_BASE_URL",
        description="URL base de la instancia externa de Ollama",
    )
    model: str = Field(
        default="llama3",
        alias="OLLAMA_MODEL",
        description="Nombre del modelo LLM ejecutándose localmente",
    )
    timeout: int = Field(
        default=60,
        alias="OLLAMA_TIMEOUT",
        description="Tiempo máximo de espera en segundos por petición al LLM",
    )
    temperature: float = Field(
        default=0.0,
        alias="OLLAMA_TEMPERATURE",
        description="Temperatura de inferencia (0.0 para respuestas deterministas)",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class ETLSettings(BaseSettings):
    """Configuración general de ejecución del proceso ETL."""
    mode: str = Field(default="in_place", alias="ETL_MODE")  # in_place (Método único: altera en sitio y conserva IDs)
    batch_size: int = Field(default=50, alias="ETL_BATCH_SIZE")
    max_retries: int = Field(default=3, alias="ETL_MAX_RETRIES")
    use_ai_parser: bool = Field(default=True, alias="USE_AI_PARSER")

    path_codificador_vias: str = Field(
        default="docs/cod_vias_y_habilitaciones_urbanas/CODIFICADOR DE VIAS - CHICLAYO _ FINAL 26-02-2024 (1).xlsx",
        alias="PATH_CODIFICADOR_VIAS",
    )
    path_codificador_zonas: str = Field(
        default="docs/cod_vias_y_habilitaciones_urbanas/CODIFICADOR DE HABILITACIONES URBANAS -.xlsx",
        alias="PATH_CODIFICADOR_ZONAS",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class Settings(BaseSettings):
    """Contenedor maestro de todas las configuraciones del sistema."""
    env: str = Field(default="development", alias="ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    db: DatabaseSettings = Field(default_factory=DatabaseSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    etl: ETLSettings = Field(default_factory=ETLSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Retorna una instancia única (singleton) de la configuración."""
    return Settings()
