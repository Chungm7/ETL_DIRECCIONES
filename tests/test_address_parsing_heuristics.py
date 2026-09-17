"""Pruebas unitarias para la heurística y normalización de direcciones complejas de Chiclayo."""

import unittest
from unittest.mock import MagicMock

from src.models.direccion_origen import DireccionOrigen
from src.transformers.text_cleaner import TextCleaner
from src.transformers.ai_parser import AIAddressParser


class TestAddressParsingHeuristics(unittest.TestCase):
    """Verifica que casos con ciudades pegadas, interiores y referencias entre paréntesis se normalicen."""

    def setUp(self):
        # Mock de OllamaService para simular o evaluar la capa de heurística
        self.mock_ollama = MagicMock()
        self.parser = AIAddressParser(self.mock_ollama)

    def test_text_cleaner_separates_glued_city(self):
        """Verifica que TextCleaner separe CHICLAYOALFREDO -> CHICLAYO ALFREDO."""
        raw = "CHICLAYOALFREDO LAPOINT 882  INT- I"
        cleaned = TextCleaner.sanitize(raw)
        self.assertIn("CHICLAYO ALFREDO", cleaned)
        self.assertIn("INT-I", cleaned)

    def test_parse_alfredo_lapoint_with_fallback(self):
        """Verifica que 'CHICLAYOALFREDO LAPOINT 882  INT- I' extraiga la vía, número e interior."""
        # Supongamos que Ollama no respondió o devolvió nulos
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(id_licencia=1, emp_direccion="CHICLAYOALFREDO LAPOINT 882  INT- I")
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 1)
        self.assertEqual(destino.tipo_via, 2)  # CALLE = 2
        self.assertEqual(destino.nom_via, "ALFREDO LAPOINT")
        self.assertIn("882", destino.num_via)
        self.assertEqual(destino.slote, "INT-I")
        self.assertEqual(destino.tipo_zona, 8)  # CERCADO = 8

    def test_parse_fitzcarral_airport_with_fallback(self):
        """Verifica que 'AV. FITZCARRAL S/N (AEREOPUERTO...) - CHICLAYO' extraiga avenida y nombre."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=2,
            emp_direccion="AV. FITZCARRAL S/N (AEREOPUERTO JOSÉ ABELARDO QUIÑONES GONZALES) - CHICLAYO ",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 2)
        self.assertEqual(destino.tipo_via, 1)  # AVENIDA = 1
        self.assertEqual(destino.nom_via, "FITZCARRAL")
        self.assertIn("S/N", destino.num_via)
        self.assertIn("AEREOPUERTO", destino.nom_zona)

    def test_parse_reference_cerca_al_senati(self):
        """Verifica el caso de usuario: 'Calle trindiad 128, Urbanizacion el paraiso, cerca al senati'."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=3,
            emp_direccion="Calle trindiad 128, Urbanizacion el paraiso, cerca al senati",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 3)
        self.assertEqual(destino.tipo_via, 2)  # CALLE = 2
        self.assertEqual(destino.nom_via, "TRINDIAD")
        self.assertEqual(destino.num_via, "128")
        self.assertEqual(destino.tipo_zona, 6)  # URBANIZACION = 6
        self.assertEqual(destino.nom_zona, "EL PARAISO")
        self.assertEqual(destino.referencia, "CERCA AL SENATI")

    def test_parse_reference_frente_al_parque(self):
        """Verifica que referencias espaciales no contaminen la vía o la zona."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=4,
            emp_direccion="AV. BALTA 520 URB. LOS FICUS, FRENTE AL PARQUE PRINCIPAL",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.tipo_via, 1)
        self.assertIn("BALTA", destino.nom_via)
        self.assertEqual(destino.num_via, "520")
        self.assertEqual(destino.tipo_zona, 6)
        self.assertEqual(destino.nom_zona, "LOS FICUS")
        self.assertEqual(destino.referencia, "FRENTE AL PARQUE PRINCIPAL")

    def test_parse_7_de_enero_street_with_number(self):
        """Verifica que 'Ca. 7 de enero N129' NO tome el 7 como num_via y homologue la vía física."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=10,
            emp_direccion="Ca. 7 de enero N129",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 10)
        self.assertEqual(destino.tipo_via, 2)  # CALLE
        self.assertIn("7 DE ENERO", destino.nom_via)
        self.assertEqual(destino.num_via, "129")  # Debe ser 129, NUNCA 7
        self.assertIsNotNone(destino.id_via)

    def test_parse_salaverry_urb_colibri_master_tables(self):
        """Verifica que 'AV. SALAVERRY 450 URB. COLIBRI' enlace con id_via e id_zona."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=20,
            emp_direccion="AV. SALAVERRY 450 URB. COLIBRI",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 20)
        self.assertEqual(destino.tipo_via, 1)  # AVENIDA
        self.assertIn("SALAVERRY", destino.nom_via)
        self.assertEqual(destino.num_via, "450")
        self.assertEqual(destino.tipo_zona, 6)  # URBANIZACION
        self.assertEqual(destino.nom_zona, "COLIBRI")
        self.assertEqual(destino.id_via, 2862)  # FELIPE SANTIAGO SALAVERRY
        self.assertEqual(destino.id_zona, 461)   # COLIBRI

    def test_parse_reference_with_ai_extraction(self):
        """Verifica que la referencia proveniente de Ollama sea respetada fielmente."""
        from src.models.llm_schemas import OllamaAddressExtraction

        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="TRINIDAD",
            num_via="128",
            tipo_zona_detectada="URBANIZACION",
            nom_zona="EL PARAISO",
            referencia="CERCA AL SENATI",
        )

        record = DireccionOrigen(
            id_licencia=5,
            emp_direccion="Calle trindiad 128, Urbanizacion el paraiso, cerca al senati",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.referencia, "CERCA AL SENATI")
        self.assertEqual(destino.nom_zona, "EL PARAISO")
        self.assertEqual(destino.nom_via, "TRINIDAD")


if __name__ == "__main__":
    unittest.main()
