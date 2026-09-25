"""Modelos de datos para las tablas maestras y catálogos de Chiclayo (Versión 2.0)."""

from typing import Optional
from pydantic import BaseModel, Field


class TipoVia(BaseModel):
    """Representa un tipo de vía de la tabla maestra `tb_tipo_via`."""
    tivi_id: int = Field(description="Identificador único del tipo de vía")
    tivi_nombre: str = Field(description="Nombre completo (CALLE, AVENIDA, JIRÓN, etc.)")
    tivi_abreviatura: Optional[str] = Field(default=None, description="Abreviatura oficial (CA., AV., etc.)")
    tivi_estado: str = Field(default="ACT", description="Estado: ACT, INA")

    # Propiedades de compatibilidad con código anterior
    @property
    def id_tipo_via(self) -> int:
        return self.tivi_id

    @property
    def nombre_tipo_via(self) -> str:
        return self.tivi_nombre

    @property
    def abreviatura(self) -> Optional[str]:
        return self.tivi_abreviatura


class Via(BaseModel):
    """Representa una vía oficial de la tabla maestra `tb_via`."""
    via_id: int = Field(description="Identificador único de la vía")
    tivi_id: int = Field(description="Clave foránea hacia `tb_tipo_via`")
    via_nombre: str = Field(description="Nombre oficial de la arteria vial")
    via_estado: str = Field(default="ACT", description="Estado: ACT, INA")

    @property
    def id_via(self) -> int:
        return self.via_id

    @property
    def nom_via(self) -> str:
        return self.via_nombre


class TipoZona(BaseModel):
    """Representa un tipo de zona de la tabla maestra `tb_tipo_zona` (28 tipos oficiales)."""
    tizo_id: int = Field(description="Identificador único del tipo de zona")
    tizo_nombre: str = Field(description="Nombre completo (URBANIZACIÓN, PUEBLO JOVEN, etc.)")
    tizo_abreviatura: Optional[str] = Field(default=None, description="Abreviatura oficial (URB., P.J., etc.)")
    tizo_estado: str = Field(default="ACT", description="Estado: ACT, INA")

    # Propiedades de compatibilidad con código anterior
    @property
    def id_tipo_zona(self) -> int:
        return self.tizo_id

    @property
    def nombre_tipo_zona(self) -> str:
        return self.tizo_nombre

    @property
    def abreviatura(self) -> Optional[str]:
        return self.tizo_abreviatura


class Zona(BaseModel):
    """Representa una zona u habilitación urbana oficial de la tabla maestra `tb_zona`."""
    zona_id: int = Field(description="Identificador único de la zona")
    tizo_id: int = Field(description="Clave foránea hacia `tb_tipo_zona`")
    zona_nombre: str = Field(description="Nombre oficial de la zona o habilitación")
    zona_estado: str = Field(default="ACT", description="Estado: ACT, INA")


class ComponenteDireccion(BaseModel):
    """Representa un tipo de componente catastral de `tb_componente_direccion`."""
    codi_id: int = Field(description="Identificador único del componente")
    codi_nombre: str = Field(description="Nombre (MANZANA, LOTE, SUBLOTE, PISO, PREDIO, etc.)")
    codi_es_urbano: bool = Field(default=True, description="True para componentes urbanos, False para rurales")
    codi_estado: str = Field(default="ACT", description="Estado: ACT, INA")


class TipoModulo(BaseModel):
    """Representa un tipo de módulo o dependencia de `tb_tipo_modulo`."""
    timo_id: int = Field(description="Identificador único del tipo de módulo")
    timo_nombre: str = Field(description="Nombre (INTERIOR, DEPARTAMENTO, PUERTA, STAND, TIENDA, BLOCK, etc.)")
    timo_estado: str = Field(default="ACT", description="Estado: ACT, INA")
