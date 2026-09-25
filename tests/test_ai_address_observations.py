"""Pruebas unitarias para la interpretación resiliente de direcciones con IA,
detección de conflictos de dos vías y generación de observaciones explicativas y detalladas.
"""

import unittest
from unittest.mock import MagicMock

from src.models.direccion_origen import DireccionOrigen
from src.models.llm_schemas import OllamaAddressExtraction
from src.transformers.ai_parser import AIAddressParser


class TestAIAddressObservations(unittest.TestCase):
    """Verifica la resiliencia del esquema Pydantic, la desambiguación de dos vías

    y la redacción de diagnósticos detallados para las observaciones de catastro.
    """

    def setUp(self):
        self.mock_ollama = MagicMock()
        self.parser = AIAddressParser(self.mock_ollama)

    def test_ollama_extraction_flexible_keys(self):
        """Verifica que OllamaAddressExtraction mapee llaves en lenguaje natural del modelo local."""
        raw_dict = {
            "tipo via": "AVENIDA",
            "nombre via": "JOSE BALTA",
            "número via": "882",
            "tipo zona": "URBANIZACION",
            "nombre zona": "SANTA VICTORIA",
            "Mz": "B",
            "LT.": "14",
            "Sub LT.": "A",
            "Dep.": "301",
            "STAND.": "12",
            "Piso": "3",
            "Referencia": "FRENTE AL PARQUE",
            "observaciones": "Requiere verificación de numeración municipal",
            "confianza": "0.95",
        }
        extraction = OllamaAddressExtraction.model_validate(raw_dict)
        self.assertEqual(extraction.tipo_via_detectado, "AVENIDA")
        self.assertEqual(extraction.nom_via, "JOSE BALTA")
        self.assertEqual(extraction.num_via, "882")
        self.assertEqual(extraction.tipo_zona_detectada, "URBANIZACION")
        self.assertEqual(extraction.nom_zona, "SANTA VICTORIA")
        self.assertEqual(extraction.manzana, "B")
        self.assertEqual(extraction.lote, "14")
        self.assertEqual(extraction.slote, "A")
        self.assertIn("DEP 301", extraction.referencia)
        self.assertIn("STAND 12", extraction.referencia)
        self.assertIn("PISO 3", extraction.referencia)
        self.assertIn("FRENTE AL PARQUE", extraction.referencia)
        self.assertEqual(extraction.observaciones, "Requiere verificación de numeración municipal")
        self.assertEqual(extraction.confianza, 0.95)

    def test_urb_quinones_internal_streets(self):
        """Verifica que JOSE QUIÑONES GONZALES seguido de calles interiores (Iquitos, Rio Chira, Bagua)

        se reconozca como Zona Quiñones y Vía interior.
        """
        self.mock_ollama.parse_address_with_ai.return_value = None

        # 1. IQUITOS
        rec1 = DireccionOrigen(id_licencia=1, emp_direccion="JOSE QUIÑONES GONZALES-IQUITOS00191")
        dest1 = self.parser.parse(rec1)
        self.assertTrue(dest1.es_procesado)
        self.assertEqual(dest1.id_zona, 62)  # CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA
        self.assertEqual(dest1.id_via, 459)  # IQUITOS
        self.assertEqual(dest1.num_via, "191")

        # 2. RIO CHIRA
        rec2 = DireccionOrigen(id_licencia=15, emp_direccion="JOSE QUIÑONES GONZALES-RIO CHIRA00096")
        dest2 = self.parser.parse(rec2)
        self.assertTrue(dest2.es_procesado)
        self.assertEqual(dest2.id_zona, 62)
        self.assertEqual(dest2.id_via, 468)  # RIO CHIRA
        self.assertEqual(dest2.num_via, "96")

        # 3. BAGUA
        rec3 = DireccionOrigen(id_licencia=16, emp_direccion="JOSE QUIÑONES GONZALES-BAGUA00200")
        dest3 = self.parser.parse(rec3)
        self.assertTrue(dest3.es_procesado)
        self.assertEqual(dest3.id_zona, 62)
        self.assertEqual(dest3.id_via, 461)  # BAGUA
        self.assertEqual(dest3.num_via, "200")

    def test_inversion_via_zona_jose_obrero_los_gorriones(self):
        """Verifica que 'JOSE OBRERO-LOS GORRIONES - MZ. B LOTE 10' asigne vía Los Gorriones y zona San José Obrero."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=3, emp_direccion="JOSE OBRERO-LOS GORRIONES - MZ. B LOTE 10")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 1418)  # CA. LOS GORRIONES
        self.assertEqual(dest.id_zona, 207)  # PROGRESIVA SAN JOSÉ OBRERO
        self.assertEqual(dest.manzana, "B")
        self.assertEqual(dest.lote, "10")

    def test_inversion_via_zona_with_ai_extraction(self):
        """Verifica que si la IA invierte vía y zona, el parser las intercambie y valide correctamente."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="JOSÉ OBRERO",
            nom_zona="LOS GORRIONES",
            manzana="B",
            lote="10",
        )

        rec = DireccionOrigen(id_licencia=3, emp_direccion="JOSE OBRERO-LOS GORRIONES - MZ. B LOTE 10")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 1418)  # CA. LOS GORRIONES
        self.assertEqual(dest.id_zona, 207)  # PROGRESIVA SAN JOSÉ OBRERO
        self.assertEqual(dest.manzana, "B")
        self.assertEqual(dest.lote, "10")

    def test_jose_olaya_manuel_arteaga_resolved_as_zona_via(self):
        """Verifica que 'JOSE OLAYA - MANUEL ARTEAGA, 00260' se resuelva como zona y vía.

        JOSE OLAYA es tanto zona (P.J. José Olaya, ID 70) como vía en Chiclayo.
        Con la prioridad zona-vía, el parser asigna zona=JOSE OLAYA, vía=MANUEL ARTEAGA.
        """
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=18, emp_direccion="JOSE OLAYA - MANUEL ARTEAGA, 00260")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_zona, 70)   # P.J. JOSÉ OLAYA
        self.assertEqual(dest.id_via, 510)   # MANUEL ARTEAGA
        self.assertIn(dest.num_via, ("260", "00260"))

    def test_two_vias_conflict_with_ai_extraction(self):
        """Verifica detección de conflicto de vías cuando la IA devuelve ambas juntas en nom_via."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="JOSE OLAYA - MANUEL ARTEAGA",
            num_via="260",
        )

        rec = DireccionOrigen(id_licencia=18, emp_direccion="JOSE OLAYA - MANUEL ARTEAGA, 00260")
        dest = self.parser.parse(rec)
        self.assertFalse(dest.es_procesado)
        self.assertIn("Conflicto de vías", dest.observacion)

    def test_detailed_observation_with_confirmed_zone(self):
        """Verifica que si la vía no figura en catastro pero la zona sí, la observación

        explique detalladamente la confirmación de la zona y la ausencia de la vía.
        """
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=7, emp_direccion="CESAR VALLEJO-AGRICULTURA 00710")
        dest = self.parser.parse(rec)
        self.assertFalse(dest.es_procesado)
        self.assertIsNotNone(dest.observacion)
        self.assertIn("AGRICULTURA", dest.observacion)
        self.assertIn("CÉSAR VALLEJO", dest.observacion)
        self.assertIn("280", dest.observacion)  # ID de la zona confirmada

    def test_detailed_observation_with_restriction_warning(self):
        """Verifica que notas sobre no usar vía pública se agreguen a las observaciones."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=13, emp_direccion="SAN LORENZO-SALAS00140 (NO USAR LA VIA PUBLICA)")
        dest = self.parser.parse(rec)
        self.assertFalse(dest.es_procesado)
        self.assertIn("SAN LORENZO", dest.observacion)
        self.assertIn("Zona oficial confirmada", dest.observacion)
        self.assertIn("Restricción de uso de vía pública", dest.observacion)

    def test_cuglievan_synonym_resolution(self):
        """Verifica que NICOLAS CUGLIEVAN y GALERIAS NICOLAS CUGLIEVAN resuelvan a JUAN CUGLIEVAN."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        # Caso vía directa
        rec1 = DireccionOrigen(id_licencia=12, emp_direccion="CHICLAYO-NICOLAS CUGLIEVAN00280")
        dest1 = self.parser.parse(rec1)
        self.assertTrue(dest1.es_procesado)
        self.assertEqual(dest1.id_via, 104)  # JUAN CUGLIEVAN
        self.assertEqual(dest1.num_via, "280")

        # Caso galería comercial
        rec2 = DireccionOrigen(id_licencia=10, emp_direccion="CHICLAYO-GALERIAS NICOLAS CUGLIEVAN STAND 3 B - I")
        dest2 = self.parser.parse(rec2)
        self.assertTrue(dest2.es_procesado)
        self.assertEqual(dest2.id_via, 104)
        self.assertIn("STAND 3 B - I", dest2.referencia)

    def test_condominio_la_primavera_and_angel_cornejo(self):
        """Verifica que CONDOMINIO LA PRIMAVERA resuelva a LA PRIMAVERA y ANGEL CORNEJO a ANGEL GUSTAVO CORNEJO."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=6, emp_direccion="CONDOMINIO LA PRIMAVERA-ANGEL CORNEJO BLOCK F-101")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_zona, 45)   # LA PRIMAVERA
        self.assertEqual(dest.id_via, 421)   # ANGEL GUSTAVO CORNEJO
        self.assertIn("BLOCK F", dest.referencia)

    def test_3_de_octubre_and_salaverry(self):
        """Verifica que '3 DE OCTUBRE-FELIPE SANTIAGO SALAVERRY01731' resuelva vía y zona oficiales."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=9, emp_direccion="3 DE OCTUBRE-FELIPE SANTIAGO SALAVERRY01731")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_zona, 81)   # 3 DE OCTUBRE - PAMPA Y MOLINO DE VIENTO
        self.assertEqual(dest.id_via, 2862)  # FELIPE SANTIAGO SALAVERRY
        self.assertEqual(dest.num_via, "1731")

    def test_orthographic_variant_porcuya_to_porculla(self):
        """Verifica que variantes ortográficas como PORCUYA se resuelvan a PORCULLA por similitud."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        rec = DireccionOrigen(id_licencia=1321, emp_direccion="PATAZCA-PORCUYA00330")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 285)   # PORCULLA
        self.assertEqual(dest.nom_via, "PORCULLA")
        self.assertEqual(dest.id_zona, 40)   # PATAZCA
        self.assertEqual(dest.num_via, "330")

    def test_salas_not_matched_as_salinas(self):
        """Verifica que SALAS no se confunda con SALINAS por falso positivo ortográfico."""
        self.mock_ollama.parse_address_with_ai.return_value = None

    def test_quinones_iquitos_with_ai_extraction_and_redundant_reference(self):
        """Verifica que 'JOSE QUIÑONES GONZALES-IQUITOS00191' no destruya nom_via si la IA colocó 'IQUITOS' en referencia."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="AVENIDA",
            nom_via="JOSE A. QUIÑONES GONZALES",
            num_via="191",
            referencia="IQUITOS",
        )

        rec = DireccionOrigen(id_licencia=1212, emp_direccion="JOSE QUIÑONES GONZALES-IQUITOS00191")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 459)   # IQUITOS
        self.assertEqual(dest.nom_via, "IQUITOS")
        self.assertEqual(dest.id_zona, 62)   # CAP. FAP JOSÉ QUIÑONES GONZALES - I ETAPA
        self.assertEqual(dest.num_via, "191")
        self.assertIsNone(dest.referencia)

    def test_strict_guardrail_prevents_fake_sin_via_with_street_number(self):
        """Verifica que una dirección con numeración municipal y vía no mapeada NUNCA sea normalizada como SIN VIA."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="CALLE FANTASMA NO CATASTRADA",
            num_via="450",
            nom_zona="SANTA VICTORIA",
        )

        rec = DireccionOrigen(id_licencia=9991, emp_direccion="CALLE FANTASMA NO CATASTRADA 450 SANTA VICTORIA")
        dest = self.parser.parse(rec)
        self.assertFalse(dest.es_procesado)
        self.assertIsNone(dest.id_via)
        self.assertIsNotNone(dest.observacion)
        self.assertIn("CALLE FANTASMA NO CATASTRADA", dest.observacion)

    def test_nueve_de_octubre_las_margaritas_sector_resolution(self):
        """Verifica que 'NUEVE DE OCTUBRE-LAS MARGARITAS00455' resuelva la vía sectorizada ID 418 y zona ID 60."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="LAS MARGARITAS",
            num_via="455",
            tipo_zona_detectada="PUEBLO JOVEN",
            nom_zona="09 DE OCTUBRE",
        )

        rec = DireccionOrigen(id_licencia=1342, emp_direccion="NUEVE DE OCTUBRE-LAS MARGARITAS00455")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 418)   # LAS MARGARITAS (Sector 23 25)
        self.assertEqual(dest.nom_via, "LAS MARGARITAS")
        self.assertEqual(dest.id_zona, 60)   # 9 DE OCTUBRE (Sector 23 25)
        self.assertEqual(dest.num_via, "455")
        self.assertIsNone(dest.observacion)

    def test_three_canonical_structures(self):
        """Verifica la validación formal de las 3 estructuras canónicas de direcciones."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        # Estructura 1: Vía + Número (Sin Zona ni Mz/Lt)
        rec1 = DireccionOrigen(id_licencia=101, emp_direccion="AV. JOSE BALTA 520")
        dest1 = self.parser.parse(rec1)
        self.assertTrue(dest1.es_procesado)
        self.assertEqual(dest1.id_via, 2905)
        self.assertEqual(dest1.num_via, "520")
        self.assertIsNone(dest1.id_zona)

        # Estructura 2: Zona + Mz/Lt puro (Sin Vía)
        rec2 = DireccionOrigen(id_licencia=102, emp_direccion="SAN JUAN DE DIOS - MZA. E LOTE 23")
        dest2 = self.parser.parse(rec2)
        self.assertTrue(dest2.es_procesado)
        self.assertIsNone(dest2.id_via)
        self.assertEqual(dest2.id_zona, 298)
        self.assertEqual(dest2.manzana, "E")
        self.assertEqual(dest2.lote, "23")

        # Estructura 3: Zona + Vía Interior + Número (Sin Mz/Lt)
        rec3 = DireccionOrigen(id_licencia=103, emp_direccion="SAN NICOLAS - LAS AMERICAS 705")
        dest3 = self.parser.parse(rec3)
        self.assertTrue(dest3.es_procesado)
        self.assertIn(dest3.id_via, (869, 2910))
        self.assertEqual(dest3.id_zona, 136)
        self.assertEqual(dest3.num_via, "705")

    def test_remigio_silva_tomas_gutierrez_id_1253(self):
        """Verifica que 'REMIGIO SILVA-TOMAS GUTIERREZ00370' resuelva Thomas Gutiérrez (ID 648) y Remigio Silva (ID 92)."""
        # Subcaso A: Ollama extrae zona como nom_via y calle en referencia con número pegado
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            nom_via="REMIGIO SILVA",
            referencia="TOMAS GUTIERREZ00370",
            num_via=None,
        )
        rec_a = DireccionOrigen(id_licencia=1253, emp_direccion="REMIGIO SILVA-TOMAS GUTIERREZ00370")
        dest_a = self.parser.parse(rec_a)
        self.assertTrue(dest_a.es_procesado)
        self.assertEqual(dest_a.id_via, 648)
        self.assertEqual(dest_a.nom_via, "THOMAS GUTIERREZ")
        self.assertEqual(dest_a.id_zona, 92)
        self.assertEqual(dest_a.nom_zona, "REMIGIO B. SILVA")
        self.assertEqual(dest_a.num_via, "370")
        self.assertIsNone(dest_a.observacion)

        # Subcaso B: Heurística pura (Ollama desconectado)
        self.mock_ollama.parse_address_with_ai.return_value = None
        rec_b = DireccionOrigen(id_licencia=1253, emp_direccion="REMIGIO SILVA-TOMAS GUTIERREZ00370")
        dest_b = self.parser.parse(rec_b)
        self.assertTrue(dest_b.es_procesado)
        self.assertEqual(dest_b.id_via, 648)
        self.assertEqual(dest_b.nom_via, "THOMAS GUTIERREZ")
        self.assertEqual(dest_b.id_zona, 92)
        self.assertEqual(dest_b.nom_zona, "REMIGIO B. SILVA")
        self.assertEqual(dest_b.num_via, "370")
        self.assertIsNone(dest_b.observacion)

    def test_permutative_structures_via_first_and_zone_first(self):
        """Verifica que tanto VIA - ZONA como ZONA - VIA resuelvan idénticamente."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        # Orden 1: Vía con número primero, luego Zona
        rec1 = DireccionOrigen(id_licencia=201, emp_direccion="LAS AMERICAS 705 - SAN NICOLAS")
        dest1 = self.parser.parse(rec1)
        self.assertTrue(dest1.es_procesado)
        self.assertIn(dest1.id_via, (869, 2910))
        self.assertEqual(dest1.id_zona, 136)
        self.assertEqual(dest1.num_via, "705")

        # Orden 2: Zona primero, luego Vía con número
        rec2 = DireccionOrigen(id_licencia=202, emp_direccion="SAN NICOLAS - LAS AMERICAS 705")
        dest2 = self.parser.parse(rec2)
        self.assertTrue(dest2.es_procesado)
        self.assertIn(dest2.id_via, (869, 2910))
        self.assertEqual(dest2.id_zona, 136)
        self.assertEqual(dest2.num_via, "705")

    def test_mixed_manzana_lote_and_via_number(self):
        """Verifica que direcciones con Mz/Lt y número de vía simultáneos conserven ambos."""
        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="TOMAS GUTIERREZ",
            num_via="370",
            tipo_zona_detectada="URBANIZACION",
            nom_zona="REMIGIO SILVA",
            manzana="B",
            lote="14",
        )
        rec = DireccionOrigen(id_licencia=301, emp_direccion="URB. REMIGIO SILVA MZ. B LT. 14 CA. TOMAS GUTIERREZ 370")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 648)
        self.assertEqual(dest.id_zona, 92)
        self.assertEqual(dest.num_via, "370")
        self.assertEqual(dest.manzana, "B")
        self.assertEqual(dest.lote, "14")

    def test_patazca_porcuya_synonym_resolution(self):
        """Verifica que 'PATAZCA-PORCUYA00330' normalice a Porculla (ID 285) y Patazca (ID 40)."""
        self.mock_ollama.parse_address_with_ai.return_value = None
        rec = DireccionOrigen(id_licencia=1321, emp_direccion="PATAZCA-PORCUYA00330")
        dest = self.parser.parse(rec)
        self.assertTrue(dest.es_procesado)
        self.assertEqual(dest.id_via, 285)
        self.assertEqual(dest.id_zona, 40)
        self.assertEqual(dest.num_via, "330")


if __name__ == "__main__":
    unittest.main()
