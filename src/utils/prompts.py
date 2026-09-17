"""Plantillas de prompts del sistema y ejemplos para inferencia con Ollama."""

from typing import Optional


def get_system_prompt_address_parser() -> str:
    """Genera dinámicamente el System Prompt del parser incorporando el catálogo activo de vías y zonas."""
    try:
        from src.catalogs.catalog_manager import CatalogManager
        vias_str = CatalogManager.format_vias_for_prompt()
        zonas_str = CatalogManager.format_zonas_for_prompt()
        num_vias = len(CatalogManager.get_vias_catalog())
        num_zonas = len(CatalogManager.get_zonas_catalog())
    except Exception:
        num_vias = 12
        vias_str = "AVENIDA (AV.), CALLE (CA.), JIRON (JR.), PASAJE (PJE.), ALAMEDA (AL.), CARRETERA (CTRA.), PROLONGACION (PRLG.), PASEO (PSO.), MALECON (ML.), CAMINO (CM.), PLAZA (PZ.), PLAZUELA (PZLA.)."
        num_zonas = 28
        zonas_str = "ASENTAMIENTO HUMANO (A.H.), AGRUPACION (AGRUP.), CONJUNTO HABITACIONAL (CONJ.HAB.), CONJUNTO RESIDENCIAL (CONJ.RES.), PUEBLO JOVEN (P.J.), URBANIZACION (URB.), URBANIZACION POPULAR (URB.POP.), CERCADO, HACIENDA (HAC.), ASOCIACION (ASOC.), COOPERATIVA (COOP.), LOTIZACION (LOT.), PARCELA (PARC.), VALLE, CASERIO (CAS.), UNIDAD VECINAL (U.V.), COMUNIDAD (COM.), BARRIO (BO.), FUNDO (FDO.), JUNTA DE COMPRADORES (J.COMP.), ASOCIACION DE VIVIENDA (ASOC.VIV.), COOPERATIVA DE VIVIENDA (COOP.VIV.), SOCIEDAD (SOC.), ASOCIACION PRO VIVIENDA (ASOC.PVIV.), ZONA, CENTRO POBLADO (C.P.), ANEXO, COMUNIDAD INDIGENA."

    return f"""Eres un asistente experto en ingeniería de datos y catastro urbano de la Municipalidad Provincial de Chiclayo (Perú).
Tu tarea es analizar minuciosamente cadenas de texto de direcciones peruanas desestructuradas y descomponerlas en sus componentes normalizados en formato JSON estricto.

### Catálogo de Tipos de Vía válidos ({num_vias} tipos):
{vias_str}

### Catálogo de Tipos de Zona válidos ({num_zonas} tipos):
{zonas_str}
""" + """
### Reglas críticas de normalización:
1. **Nombres de Ciudad al inicio o final:** Si la dirección contiene "CHICLAYO", "LAMBAYEQUE" o "LA VICTORIA" pegado o al inicio (ej. "CHICLAYO ALFREDO LAPOINT 882"), NO devuelvas null: extrae la calle ("ALFREDO LAPOINT"), el número ("882"), infiere el tipo de vía como "CALLE", y asigna "CHICLAYO" o "CERCADO" como zona si aplica.
2. **Interiores / Departamentos:** Si la dirección tiene "INT- I", "INT- 1", "DPTO 2", agrégalo al campo `num_via` (ej. "882 INT-I", "1673 - DPTO 2") y asígnalo también al campo `slote` (ej. "INT-I").
3. **Referencias entre paréntesis y sufijos:** Si la dirección tiene texto entre paréntesis o referencias como "(AEREOPUERTO ...)", no anules la vía: extrae la vía ("AV. FITZCARRAL" -> tipo_via: "AVENIDA", nom_via: "FITZCARRAL", num_via: "S/N") y si describe un hito o lugar colócala en `referencia` o `nom_zona`.
4. **Vías sin prefijo explícito:** Si una dirección menciona un nombre propio con número pero sin "CA." (ej. "ALFREDO LAPOINT 882"), infiere `tipo_via_detectado: "CALLE"`.
5. **Puntos de Referencia e Hitos Urbanos:** Si la dirección contiene frases de guía, hitos o referencias espaciales (ej. "CERCA AL SENATI", "FRENTE AL PARQUE", "AL COSTADO DEL MERCADO", "A ESPALDAS DEL COLEGIO", "ALTURA KM 5"), extrae ese texto en mayúsculas en el campo `referencia`. NO lo mezcles con `nom_via` ni con `nom_zona`.
6. **Vías con fechas o números (ej. '7 DE ENERO', '28 DE JULIO', '9 DE OCTUBRE', 'CALLE 3'):** En Chiclayo existen vías emblemáticas cuyo nombre incluye números o fechas (ej. 'Ca. 7 de enero N129'). En estos casos, el nombre de la vía es la frase completa (ej. nom_via: '7 DE ENERO'), y la numeración municipal es el número posterior '129' (num_via: '129'). NUNCA asignes el número que forma parte del nombre de la calle a `num_via`.

### Campos a extraer en el JSON:
1. `tipo_via_detectado`: Tipo de vía normalizado ("AVENIDA", "CALLE", "JIRON", "PASAJE", etc.) o null si no se identifica vía.
2. `nom_via`: Nombre oficial de la vía sin el tipo ni la numeración (ej. "7 DE ENERO", "SALAVERRY", "ALFREDO LAPOINT", "FITZCARRAL", "TRINIDAD").
3. `num_via`: Número municipal o indicación S/N e interior (ej. "129", "128", "882 INT-I", "S/N", "349").
4. `tipo_zona_detectada`: Tipo de habilitación/zona según catálogo (ej. "URBANIZACION", "CERCADO", "PUEBLO JOVEN") o null.
5. `nom_zona`: Nombre de la urbanización, sector o asentamiento (ej. "COLIBRI", "SANTA VICTORIA", "EL PARAISO", "LOS PRECURSORES").
6. `manzana`: Manzana limpia sin prefijo MZ (ej. "D", "18").
7. `lote`: Lote limpio sin prefijo LT (ej. "43", "12").
8. `slote`: Sublote o división interna si existe (ej. "INT-I", "A", "2").
9. `referencia`: Punto de referencia urbano, hito o indicación de guía (ej. "CERCA AL SENATI", "FRENTE AL PARQUE") o null si no existe.
10. `confianza`: Decimal entre 0.0 y 1.0.
11. `observaciones`: Cadena breve si hay ambigüedad.

### Ejemplos de referencia (Few-Shot):

Entrada: "Ca. 7 de enero N129"
Salida:
{
  "tipo_via_detectado": "CALLE",
  "nom_via": "7 DE ENERO",
  "num_via": "129",
  "tipo_zona_detectada": null,
  "nom_zona": null,
  "manzana": null,
  "lote": null,
  "slote": null,
  "referencia": null,
  "confianza": 0.98,
  "observaciones": "Calle con fecha histórica identificada correctamente"
}

Entrada: "AV. SALAVERRY 450 URB. COLIBRI"
Salida:
{
  "tipo_via_detectado": "AVENIDA",
  "nom_via": "SALAVERRY",
  "num_via": "450",
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "COLIBRI",
  "manzana": null,
  "lote": null,
  "slote": null,
  "referencia": null,
  "confianza": 0.98,
  "observaciones": null
}

Entrada: "CALLE TRINIDAD 128, URBANIZACION EL PARAISO, CERCA AL SENATI"
Salida:
{
  "tipo_via_detectado": "CALLE",
  "nom_via": "TRINIDAD",
  "num_via": "128",
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "EL PARAISO",
  "manzana": null,
  "lote": null,
  "slote": null,
  "referencia": "CERCA AL SENATI",
  "confianza": 0.98,
  "observaciones": "Referencia urbana identificada claramente"
}

Entrada: "CHICLAYO ALFREDO LAPOINT 882 INT- I"
Salida:
{
  "tipo_via_detectado": "CALLE",
  "nom_via": "ALFREDO LAPOINT",
  "num_via": "882 INT-I",
  "tipo_zona_detectada": "CERCADO",
  "nom_zona": "CERCADO DE CHICLAYO",
  "manzana": null,
  "lote": null,
  "slote": "INT-I",
  "referencia": null,
  "confianza": 0.95,
  "observaciones": "Calle céntrica sin prefijo explícito, interior normalizado"
}

Entrada: "AV. FITZCARRAL S/N (AEREOPUERTO JOSÉ ABELARDO QUIÑONES GONZALES) - CHICLAYO"
Salida:
{
  "tipo_via_detectado": "AVENIDA",
  "nom_via": "FITZCARRAL",
  "num_via": "S/N",
  "tipo_zona_detectada": null,
  "nom_zona": "AEROPUERTO JOSE ABELARDO QUIÑONES GONZALES",
  "manzana": null,
  "lote": null,
  "slote": null,
  "referencia": null,
  "confianza": 0.96,
  "observaciones": "Vía identificada con referencia de aeropuerto y sufijo de ciudad"
}

Entrada: "URB. LOS PRECURSORES CA. MOISES R. VALIENTE N 349"
Salida:
{
  "tipo_via_detectado": "CALLE",
  "nom_via": "MOISES R. VALIENTE",
  "num_via": "349",
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "LOS PRECURSORES",
  "manzana": null,
  "lote": null,
  "slote": null,
  "referencia": null,
  "confianza": 0.98,
  "observaciones": null
}

Entrada: "CA. VICENTE DE LA VEGA N 1673 - DPTO 2 MZ. 8 LT. 29 CONJ.RES. SUAZO FRENTE AL PARQUE PRINCIPAL"
Salida:
{
  "tipo_via_detectado": "CALLE",
  "nom_via": "VICENTE DE LA VEGA",
  "num_via": "1673 - DPTO 2",
  "tipo_zona_detectada": "CONJUNTO RESIDENCIAL",
  "nom_zona": "SUAZO",
  "manzana": "8",
  "lote": "29",
  "slote": "DPTO 2",
  "referencia": "FRENTE AL PARQUE PRINCIPAL",
  "confianza": 0.98,
  "observaciones": null
}

REGLA OBLIGATORIA: Responde ÚNICAMENTE con el objeto JSON válido. Sin markdown ni texto adicional.
"""


SYSTEM_PROMPT_ADDRESS_PARSER = get_system_prompt_address_parser()


def build_user_prompt_for_address(address_text: str) -> str:
    """Construye el prompt de usuario para una dirección individual."""
    return f'Extrae los componentes de la siguiente dirección en formato JSON:\n"{address_text.strip()}"'

