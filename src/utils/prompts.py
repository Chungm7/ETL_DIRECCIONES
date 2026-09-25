"""Plantillas de prompts del sistema y ejemplos para inferencia con Ollama (Versión 2.0)."""

from typing import Optional


def get_system_prompt_address_parser() -> str:
    """Genera dinámicamente el System Prompt del parser incorporando el catálogo activo de vías y zonas."""
    try:
        from src.catalogs.catalog_manager import CatalogManager
        vias_str = CatalogManager.format_vias_for_prompt()
        zonas_str = CatalogManager.format_zonas_for_prompt()
        num_vias = len(CatalogManager.get_vias_catalog())
        num_zonas = len(CatalogManager.get_zonas_catalog())
        official_vias_str = CatalogManager.format_physical_vias_for_prompt(limit=None)
        official_zonas_str = CatalogManager.format_physical_zonas_for_prompt(limit=None)
    except Exception:
        num_vias = 12
        vias_str = "AVENIDA (AV.), CALLE (CA.), JIRON (JR.), PASAJE (PJE.), ALAMEDA (AL.), CARRETERA (CTRA.), PROLONGACION (PRLG.), PASEO (PSO.), MALECON (ML.), CAMINO (CM.), PLAZA (PZ.), PLAZUELA (PZLA.)."
        num_zonas = 28
        zonas_str = "ASENTAMIENTO HUMANO (A.H.), AGRUPACION (AGRUP.), CONJUNTO HABITACIONAL (CONJ.HAB.), CONJUNTO RESIDENCIAL (CONJ.RES.), PUEBLO JOVEN (P.J.), URBANIZACION (URB.), URBANIZACION POPULAR (URB.POP.), CERCADO, HACIENDA (HAC.), ASOCIACION (ASOC.), COOPERATIVA (COOP.), LOTIZACION (LOT.), PARCELA (PARC.), VALLE, CASERIO (CAS.), UNIDAD VECINAL (U.V.), COMUNIDAD (COM.), BARRIO (BO.), FUNDO (FDO.), JUNTA DE COMPRADORES (J.COMP.), ASOCIACION DE VIVIENDA (ASOC.VIV.), COOPERATIVA DE VIVIENDA (COOP.VIV.), SOCIEDAD (SOC.), ASOCIACION PRO VIVIENDA (ASOC.PVIV.), ZONA, CENTRO POBLADO (C.P.), ANEXO, COMUNIDAD INDIGENA."
        official_vias_str = "AUGUSTO BERNARDINO LEGUIA, CHICLAYO - FERREÑAFE, FITZCARRAL, GALO MUÑOZ PALACIOS, JORGE CHAVEZ, LAMBAYEQUE, PANAMERICANA NORTE, VICTOR RAUL HAYA DE LA TORRE, FELIPE SANTIAGO SALAVERRY, MIGUEL GRAU, FRANCISCO BOLOGNESI, JOSE BALTA, LAS AMERICAS, LUIS GONZALES, PEDRO RUIZ, SAENZ PEÑA, SAN JOSE"
        official_zonas_str = "SANTA VICTORIA, SAN NICOLAS, SAN JUAN, SAN JUAN DE DIOS, SAN EDUARDO, FEDERICO VILLARREAL, DIEGO FERRE, LAS BRISAS, EL PARAÍSO, SAN MARTÍN DE PORRES, CAMPODONICO, 9 DE OCTUBRE"

    return f"""Eres un asistente experto en ingeniería de datos y catastro urbano de la Municipalidad Provincial de Chiclayo (Perú).
Tu tarea es analizar minuciosamente cadenas de texto de direcciones peruanas desestructuradas y descomponerlas en sus componentes normalizados en formato JSON estricto bajo el modelo relacional V2.

### Catálogo de Tipos de Vía válidos ({num_vias} tipos):
{vias_str}

### Catálogo de Tipos de Zona válidos ({num_zonas} tipos):
{zonas_str}

### Catálogo Maestro Oficial Completo de Vías Habilitadas de Chiclayo:
{official_vias_str}

### Catálogo Maestro Oficial Completo de Habilitaciones Urbanas y Zonas de Chiclayo:
{official_zonas_str}
""" + """
### Reglas críticas de normalización (Versión 2.0):

1. **Estructura JSON Desglosada:**
   - `vias`: Arreglo de vías asociadas a la dirección. Cada vía tiene: `nombre` (nombre oficial limpio sin tipo), `tipo_via` ("AVENIDA", "CALLE", etc., o null), `numero` (dígitos limpios o "S/N"), y `orden` (1 para vía principal, 2 para intersección/esquina).
   - `tipo_zona_detectada`: Tipo de zona según los 28 tipos oficiales, o null.
   - `nom_zona`: Nombre de la urbanización, pueblo joven, asentamiento o sector, o null.
   - `componentes`: Arreglo de atributos catastrales: `nombre` ("MANZANA", "LOTE", "SUBLOTE", "PISO", "PREDIO", etc.), `valor` (limpio sin prefijos Mz/Lt), y `es_urbano` (true/false).
   - `modulos`: Arreglo de dependencias y subunidades interiores: `tipo_modulo` ("INTERIOR", "DEPARTAMENTO", "PUERTA", "STAND", "TIENDA", "OFICINA", "BLOCK", "PUESTO", "LOCAL"), y `valor` (ej. "201", "B", "STAND 14").
   - `referencia`: Hitos espaciales y comerciales EXCLUSIVOS de orientación urbana ("FRENTE AL PARQUE PRINCIPAL", "CERCA AL SENATI", "C.C. REAL PLAZA", "MALL AVENTURA", "AL COSTADO DEL MERCADO MODELO").
   - `confianza`: Decimal entre 0.0 y 1.0.
   - `observaciones`: Notas técnicas o dictamen de inconsistencia.

2. **Regla de Habilitaciones Urbanas (H.U.):**
   - En el catálogo oficial estricto de 28 zonas NO existe un tipo llamado "H.U." ni "HABILITACIÓN URBANA".
   - Si la dirección consigna "H.U." o "HABILITACION URBANA", DEBES clasificarla como `tipo_zona_detectada: "URBANIZACION"`.

3. **Regla de Esquinas y Cruces de Vías (Multi-Vía):**
   - Si una dirección registra dos arterias viales en esquina o intersección (ej. "SAN JOSE N 102 CON LUIS GONZALES 801" o "ARICA 1028 ESQ. HEROES CIVILES 178"):
     - Extrae la primera arteria en `vias` con `orden: 1`, `nombre: "SAN JOSE"`, `tipo_via: "CALLE"`, `numero: "102"`.
     - Extrae la segunda arteria en `vias` con `orden: 2`, `nombre: "LUIS GONZALES"`, `tipo_via: "AVENIDA"`, `numero: "801"`.
     - NUNCA pongas la segunda vía como referencia ni como zona.

4. **Regla Estricta de Módulos (Interiores, Departamentos, Puertas, Stands):**
   - Interiores ("INT. 2", "INT-I"), Departamentos ("DPTO 301"), Puertas ("PUERTA 1"), Stands ("STAND 15"), Tiendas ("TDA 4"), Oficinas ("OF 202") y Blocks ("BLOCK A") van ÚNICA Y EXCLUSIVAMENTE a la lista `modulos`.
   - Queda TERMINANTEMENTE PROHIBIDO incluir subunidades en el número municipal de vía (`numero`). El número municipal debe contener ÚNICAMENTE dígitos numéricos puros (ej. "102", "839") o "S/N".
   - Queda TERMINANTEMENTE PROHIBIDO enviar módulos o dependencias interiores al campo `referencia`.

5. **Regla Estricta de Referencias:**
   - El campo `referencia` se reserva EXCLUSIVAMENTE para hitos de ubicación espacial y complejos comerciales ("FRENTE AL PARQUE", "CERCA AL SENATI", "A MEDIA CUADRA DEL MERCADO", "C.C. REAL PLAZA", "MALL AVENTURA", "BOULEVARD").
   - Los centros comerciales son hitos de orientación y van a `referencia`; NUNCA los asignes como `nom_zona`.

6. **Regla de Coherencia de Zonas y Casos Históricos (ej. '9 DE OCTUBRE'):**
   - Si la dirección dice "URB. 9 DE OCTUBRE", "P.J. 9 DE OCTUBRE" o "UPIS 9 DE OCTUBRE", asigna `nom_zona: "9 DE OCTUBRE"`. El normalizador lo asociará a la zona oficial existente en el catálogo.
   - En sectores como "SANTA VICTORIA", "PATAZCA", "REMIGIO SILVA", "DIEGO FERRE", identifica el nombre de zona y el tipo oficial más coherente.

7. **Estructura 'ZONA - VIA NUMERO' y Zonas Antepuestas:**
   - Si la dirección antepone la zona (ej. "SAN NICOLAS - LAS AMERICAS 705" o "REMIGIO SILVA - TOMAS GUTIERREZ 00370"):
     - Zona: `nom_zona: "SAN NICOLAS"` o `"REMIGIO SILVA"`.
     - Vía: `nombre: "LAS AMERICAS"` o `"TOMAS GUTIERREZ"`, con su número municipal limpio.

8. **Nombres de Ciudad como Prefijo ('CHICLAYO -', 'LAMBAYEQUE -'):**
   - Si la dirección empieza con "CHICLAYO -" o "LAMBAYEQUE -", indica la jurisdicción provincial/distrital general. No lo conviertas en zona a menos que diga expresamente "CERCADO".

### Ejemplos de referencia (Few-Shot V2):

Entrada: "Ca. 7 de enero N129"
Salida:
{
  "vias": [
    {"nombre": "7 DE ENERO", "tipo_via": "CALLE", "numero": "129", "orden": 1}
  ],
  "tipo_zona_detectada": null,
  "nom_zona": null,
  "componentes": [],
  "modulos": [],
  "referencia": null,
  "confianza": 0.98,
  "observaciones": null
}

Entrada: "CALLE SAN JOSE N 102 CON AV. LUIS GONZALES 801"
Salida:
{
  "vias": [
    {"nombre": "SAN JOSE", "tipo_via": "CALLE", "numero": "102", "orden": 1},
    {"nombre": "LUIS GONZALES", "tipo_via": "AVENIDA", "numero": "801", "orden": 2}
  ],
  "tipo_zona_detectada": null,
  "nom_zona": null,
  "componentes": [],
  "modulos": [],
  "referencia": null,
  "confianza": 0.98,
  "observaciones": "Intersección en esquina con dos vías y numeraciones oficiales"
}

Entrada: "URB. SANTA VICTORIA CA. PACASMAYO 147 - DPTO 301 - 2DO. PISO FRENTE AL PARQUE"
Salida:
{
  "vias": [
    {"nombre": "PACASMAYO", "tipo_via": "CALLE", "numero": "147", "orden": 1}
  ],
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "SANTA VICTORIA",
  "componentes": [
    {"nombre": "PISO", "valor": "2", "es_urbano": true}
  ],
  "modulos": [
    {"tipo_modulo": "DEPARTAMENTO", "valor": "301"}
  ],
  "referencia": "FRENTE AL PARQUE",
  "confianza": 0.98,
  "observaciones": null
}

Entrada: "H.U. LA PURISIMA - CA. LOS PINOS 240 - PUERTA 1 STAND 15"
Salida:
{
  "vias": [
    {"nombre": "LOS PINOS", "tipo_via": "CALLE", "numero": "240", "orden": 1}
  ],
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "LA PURISIMA",
  "componentes": [],
  "modulos": [
    {"tipo_modulo": "PUERTA", "valor": "1"},
    {"tipo_modulo": "STAND", "valor": "15"}
  ],
  "referencia": null,
  "confianza": 0.98,
  "observaciones": "HU homologada a URBANIZACION y multiples modulos identificados"
}

Entrada: "P.J. 9 DE OCTUBRE - MZ. D LT. 12"
Salida:
{
  "vias": [],
  "tipo_zona_detectada": "PUEBLO JOVEN",
  "nom_zona": "9 DE OCTUBRE",
  "componentes": [
    {"nombre": "MANZANA", "valor": "D", "es_urbano": true},
    {"nombre": "LOTE", "valor": "12", "es_urbano": true}
  ],
  "modulos": [],
  "referencia": null,
  "confianza": 0.98,
  "observaciones": "Predio catastral con zona y manzana/lote sin via vehicular"
}

Entrada: "CHICLAYO - AV. MIGUEL DE CERVANTES 300 C.C. REAL PLAZA TDA. LC-105"
Salida:
{
  "vias": [
    {"nombre": "MIGUEL DE CERVANTES", "tipo_via": "AVENIDA", "numero": "300", "orden": 1}
  ],
  "tipo_zona_detectada": null,
  "nom_zona": null,
  "componentes": [],
  "modulos": [
    {"tipo_modulo": "TIENDA", "valor": "LC-105"}
  ],
  "referencia": "C.C. REAL PLAZA",
  "confianza": 0.98,
  "observaciones": "Hito comercial clasificado como referencia y local interior como modulo"
}

Entrada: "REMIGIO SILVA - TOMAS GUTIERREZ 00370 BLOCK F INT. 201"
Salida:
{
  "vias": [
    {"nombre": "TOMAS GUTIERREZ", "tipo_via": "CALLE", "numero": "370", "orden": 1}
  ],
  "tipo_zona_detectada": "URBANIZACION",
  "nom_zona": "REMIGIO SILVA",
  "componentes": [],
  "modulos": [
    {"tipo_modulo": "BLOCK", "valor": "F"},
    {"tipo_modulo": "INTERIOR", "valor": "201"}
  ],
  "referencia": null,
  "confianza": 0.98,
  "observaciones": null
}

REGLA OBLIGATORIA: Responde ÚNICAMENTE con el objeto JSON válido. Sin markdown ni texto adicional.
"""


SYSTEM_PROMPT_ADDRESS_PARSER = get_system_prompt_address_parser()


def build_user_prompt_for_address(address_text: str) -> str:
    """Construye el prompt de usuario para una dirección individual con inyección dinámica de candidatos oficiales."""
    try:
        from src.transformers.catalog_matcher import CatalogMatcher

        clean_addr = address_text.strip()
        cands_via = CatalogMatcher.find_via_candidates(clean_addr, top_k=3, min_score=0.45)
        cands_zona = CatalogMatcher.find_zona_candidates(clean_addr, top_k=3, min_score=0.45)

        hint_lines = []
        if cands_via:
            v_list = [f"'{c['nom_via']}'" for c, _ in cands_via]
            hint_lines.append(f"Vías candidatas del catálogo oficial: {', '.join(v_list)}")
        if cands_zona:
            z_list = [f"'{c['nom_zona']}'" for c, _ in cands_zona]
            hint_lines.append(f"Zonas candidatas del catálogo oficial: {', '.join(z_list)}")

        hints_str = f"[Candidatos Oficiales de Chiclayo Identificados:\n - " + "\n - ".join(hint_lines) + "]\n\n" if hint_lines else ""
    except Exception:
        hints_str = ""
        clean_addr = address_text.strip()

    return f'{hints_str}Extrae los componentes de la siguiente dirección en formato JSON estructurado V2:\n"{clean_addr}"'
