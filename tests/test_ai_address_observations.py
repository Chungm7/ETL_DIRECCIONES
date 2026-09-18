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
        self.assertEqual(dest.num_via, "00260")

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


if __name__ == "__main__":
    unittest.main()
