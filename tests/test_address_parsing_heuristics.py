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
        """Verifica que 'CHICLAYOJOSE BALTA 882  INT- I' extraiga la vía, número e interior."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(id_licencia=1, emp_direccion="CHICLAYOJOSE BALTA 882  INT- I")
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 1)
        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2905)  # JOSE BALTA
        self.assertIn("882", destino.num_via)
        self.assertEqual(destino.slote, "INT-I")
        self.assertIsNone(destino.id_zona)  # CHICLAYO es la ciudad, no forzar CERCADO

    def test_parse_fitzcarral_airport_with_fallback(self):
        """Verifica que 'AV. FITZCARRAL S/N (AEREOPUERTO...) - CHICLAYO' extraiga avenida y nombre."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=2,
            emp_direccion="AV. FITZCARRAL S/N (AEREOPUERTO JOSÉ ABELARDO QUIÑONES GONZALES) - CHICLAYO ",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 2)
        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2855)  # AV. FITZCARRAL
        self.assertIn("S/N", destino.num_via)
        self.assertIn("AEREOPUERTO", destino.referencia)

    def test_parse_reference_cerca_al_senati_observed(self):
        """Verifica que 'Calle trindiad 128...' quede como OBSERVADA por no existir TRINDIAD en vias."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=3,
            emp_direccion="Calle trindiad 128, Urbanizacion el paraiso, cerca al senati",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 3)
        self.assertFalse(destino.es_procesado)
        self.assertIsNone(destino.id_via)
        self.assertIsNone(destino.num_via)
        self.assertIsNone(destino.id_zona)
        self.assertIsNone(destino.referencia)
        self.assertIn("TRINDIAD", destino.observacion)

    def test_parse_reference_frente_al_parque(self):
        """Verifica que referencias espaciales no contaminen la vía o la zona y se validen con catastro."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=4,
            emp_direccion="AV. BALTA 520 URB. SANTA VICTORIA, FRENTE AL PARQUE PRINCIPAL",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2905)    # JOSE BALTA
        self.assertEqual(destino.id_zona, 1)    # SANTA VICTORIA
        self.assertEqual(destino.num_via, "520")
        self.assertEqual(destino.referencia, "FRENTE AL PARQUE PRINCIPAL")

    def test_parse_7_de_enero_street_with_number(self):
        """Verifica que 'Av. 9 de Octubre N129' NO tome el 9 como num_via y homologue la vía física."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=10,
            emp_direccion="Av. 9 de Octubre N129",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 10)
        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2882)    # AV. 9 DE OCTUBRE
        self.assertEqual(destino.num_via, "129")  # Debe ser 129, NUNCA 9
        self.assertIsNone(destino.observacion)

    def test_parse_salaverry_urb_colibri_master_tables(self):
        """Verifica que 'AV. SALAVERRY 450 URB. SANTA VICTORIA' enlace con id_via e id_zona."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=20,
            emp_direccion="AV. SALAVERRY 450 URB. SANTA VICTORIA",
        )
        destino = self.parser.parse(record)

        self.assertEqual(destino.id_licencia, 20)
        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.num_via, "450")
        self.assertEqual(destino.id_via, 2862)    # FELIPE SANTIAGO SALAVERRY
        self.assertEqual(destino.id_zona, 1)    # SANTA VICTORIA
        self.assertIsNone(destino.observacion)

    def test_parse_reference_with_ai_extraction_valid(self):
        """Verifica que la referencia proveniente de Ollama sea respetada fielmente en caso válido."""
        from src.models.llm_schemas import OllamaAddressExtraction

        self.mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="BALTA",
            num_via="128",
            tipo_zona_detectada="URBANIZACION",
            nom_zona="EL PARAISO",
            referencia="CERCA AL SENATI",
        )

        record = DireccionOrigen(
            id_licencia=5,
            emp_direccion="Calle balta 128, Urbanizacion el paraiso, cerca al senati",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.referencia, "CERCA AL SENATI")
        self.assertEqual(destino.id_via, 2905)
        self.assertEqual(destino.id_zona, 18)

    def test_parse_remigio_silva_generic_maps_to_remigio_b_silva(self):
        """Verifica que 'URB REMIGIO SILVA MZ A LT 12' se homologue a REMIGIO B. SILVA (ID 92)."""
        self.mock_ollama.parse_address_with_ai.return_value = None
        self.mock_ollama.disambiguate_candidate.return_value = None

        record = DireccionOrigen(
            id_licencia=10,
            emp_direccion="URB REMIGIO SILVA MZ A LT 12",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_zona, 92)  # REMIGIO B. SILVA
        self.assertEqual(destino.nom_zona, "REMIGIO B. SILVA")
        self.assertEqual(destino.manzana, "A")
        self.assertEqual(destino.lote, "12")
        self.assertIsNone(destino.observacion)

    def test_parse_remigio_silva_etapa_1_maps_to_primera_etapa(self):
        """Verifica que 'URB REMIGIO SILVA ETAPA 1 MZ B LT 4' resuelva a REMIGIO B. SILVA PRIMERA ETAPA (ID 90)."""
        self.mock_ollama.parse_address_with_ai.return_value = None
        self.mock_ollama.disambiguate_candidate.return_value = None

        record = DireccionOrigen(
            id_licencia=11,
            emp_direccion="URB REMIGIO SILVA ETAPA 1 MZ B LT 4",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_zona, 90)  # REMIGIO B. SILVA SUBPROGRAMA II PRIMERA ETAPA
        self.assertIn("PRIMERA ETAPA", destino.nom_zona)
        self.assertEqual(destino.manzana, "B")
        self.assertEqual(destino.lote, "4")
        self.assertIsNone(destino.observacion)

    def test_parse_remigio_silva_ai_disambiguation(self):
        """Verifica que si la IA desambigua un candidato específico, se respete su selección."""
        from src.models.llm_schemas import OllamaCandidateDisambiguation

        self.mock_ollama.parse_address_with_ai.return_value = None
        self.mock_ollama.disambiguate_candidate.return_value = OllamaCandidateDisambiguation(
            id_seleccionado=94,
            nombre_oficial="REMIGIO B. SILVA II ETAPA",
            motivo="La dirección se refiere a la Segunda Etapa de Remigio B. Silva.",
        )

        record = DireccionOrigen(
            id_licencia=12,
            emp_direccion="URB REMIGIO SILVA SECTOR 2 MZ C LT 1",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_zona, 94)
        self.assertEqual(destino.nom_zona, "REMIGIO B. SILVA II ETAPA")
        self.assertIsNone(destino.observacion)

    def test_parse_carretera_pimentel_remains_observed(self):
        """Verifica que carreteras o zonas inexistentes permanezcan en observación con campos en NULL."""
        self.mock_ollama.parse_address_with_ai.return_value = None
        self.mock_ollama.disambiguate_candidate.return_value = None

        record = DireccionOrigen(
            id_licencia=13,
            emp_direccion="CARRETERA PIMENTEL KM 5 FUNDO LA ESPERANZA",
        )
        destino = self.parser.parse(record)

        self.assertFalse(destino.es_procesado)
        self.assertIsNone(destino.id_via)
        self.assertIsNone(destino.id_zona)
        self.assertIsNotNone(destino.observacion)
        self.assertIn("PIMENTEL", destino.observacion)

    def test_parse_san_nicolas_las_americas_hyphen_and_attached_number(self):
        """Verifica que 'SAN NICOLAS-LAS AMERICAS705' despegue el guion y número y homologue vía y zona."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(id_licencia=1199, emp_direccion="SAN NICOLAS-LAS AMERICAS705")
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2910)  # AV. LAS AMERICAS
        self.assertEqual(destino.id_zona, 136)  # A.H. SAN NICOLÁS
        self.assertEqual(destino.num_via, "705")
        self.assertIsNone(destino.observacion)

    def test_parse_chiclayo_luis_gonzales_hyphen_zeros_and_floors(self):
        """Verifica que 'CHICLAYO-LUIS GONZALES00839 - 2DO. Y 3ER. PISO' limpie la ciudad, ceros y extraiga piso."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=1201,
            emp_direccion="CHICLAYO-LUIS GONZALES00839 - 2DO. Y 3ER. PISO",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 2913)   # AV. LUIS GONZALES
        self.assertEqual(destino.num_via, "839")  # Limpio sin 00 iniciales
        self.assertIn("2DO. Y 3ER. PISO", destino.referencia)
        self.assertIsNone(destino.observacion)

    def test_parse_san_juan_de_dios_lot_without_street(self):
        """Verifica que 'SAN JUAN DE DIOS-MZA. E LOTE 23' procese predio catastral sin vía con zona, Mz y Lt."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=1202,
            emp_direccion="SAN JUAN DE DIOS-MZA. E LOTE 23",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertIsNone(destino.id_via)
        self.assertEqual(destino.id_zona, 298)  # A.H. SAN JUAN DE DIOS
        self.assertEqual(destino.manzana, "E")
        self.assertEqual(destino.lote, "23")
        self.assertIsNone(destino.observacion)

    def test_parse_san_juan_oriente_zeros_processed(self):
        """Verifica que 'SAN JUAN-ORIENTE00261' homologue la vía oficial ORIENTE (ID 780) y zona SAN JUAN."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(id_licencia=1200, emp_direccion="SAN JUAN-ORIENTE00261")
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 780)  # ORIENTE
        self.assertEqual(destino.nom_via, "ORIENTE")
        self.assertEqual(destino.num_via, "261")
        self.assertEqual(destino.id_zona, 444)  # SAN JUAN
        self.assertEqual(destino.nom_zona, "SAN JUAN")

    def test_parse_chiclayo_torres_paz_processed_with_exact_street(self):
        """Verifica que 'CHICLAYO-TORRES PAZ00651 3ER. PISO' homologue la vía oficial TORRES PAZ (ID 874)."""
        self.mock_ollama.parse_address_with_ai.return_value = None

        record = DireccionOrigen(
            id_licencia=1203,
            emp_direccion="CHICLAYO-TORRES PAZ00651 3ER. PISO",
        )
        destino = self.parser.parse(record)

        self.assertTrue(destino.es_procesado)
        self.assertEqual(destino.id_via, 874)  # TORRES PAZ
        self.assertEqual(destino.nom_via, "TORRES PAZ")
        self.assertEqual(destino.num_via, "651")
        self.assertEqual(destino.referencia, "3ER. PISO")


if __name__ == "__main__":
    unittest.main()

