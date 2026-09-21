"""Pruebas unitarias para el refinamiento de IA, erradicación de alucinaciones
y blindaje de inversiones basado en la auditoría del reporte de 100 registros.
"""

import unittest
from unittest.mock import MagicMock
from src.transformers.text_cleaner import TextCleaner
from src.transformers.catalog_matcher import CatalogMatcher
from src.catalogs.catalog_manager import CatalogManager
from src.transformers.ai_parser import AIAddressParser
from src.models.llm_schemas import OllamaAddressExtraction
from src.models.direccion_origen import DireccionOrigen


class TestAIRefinementReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        CatalogManager.reload()
        CatalogMatcher.reset_defaults()

    def setUp(self):
        self.mock_ollama = MagicMock()
        self.mock_ollama.is_available.return_value = True
        self.mock_ollama.model_name = "mock-model"
        self.parser = AIAddressParser(ollama_service=self.mock_ollama)

    def test_id_250_mcdo_sanitization_no_mcdonalds_hallucination(self):
        """Caso ID 250: 'MCDO. MOSHOQUEQUE EXT. PTOS. 11 Y 12 CDRA. 02'
        Debe transformar MCDO. en MERCADO, no en MCDONALD'S.
        El mercado debe ser tratado como referencia y no vía pública municipal.
        """
        raw = "MCDO. MOSHOQUEQUE EXT. PTOS. 11 Y 12 CDRA. 02"
        clean = TextCleaner.sanitize(raw)
        self.assertIn("MERCADO", clean)
        self.assertNotIn("MCDONALD", clean)
        self.assertNotIn("MCDO", clean)

        # Simular extracción donde nom_via capturó 'MERCADO MOSHOQUEQUE'
        extraction = OllamaAddressExtraction(
            tipo_via_detectado=None,
            nom_via="MERCADO MOSHOQUEQUE",
            num_via="2",
            tipo_zona_detectada=None,
            nom_zona=None,
            manzana=None,
            lote=None,
            slote=None,
            referencia="PTOS. 11 Y 12",
            observaciones=None,
        )
        self.mock_ollama.parse_address_with_ai.return_value = extraction
        record = DireccionOrigen(id_licencia=250, emp_direccion=raw)
        res = self.parser.parse(record)

        # Debe observarse con claridad al ser un puesto de mercado sin calle pública
        self.assertFalse(res.es_procesado)
        self.assertIsNotNone(res.observacion)
        self.assertNotIn("MCDONALD", res.observacion.upper())

    def test_id_240_elvira_garcia_y_garcia_no_two_vias_conflict(self):
        """Caso ID 240: 'AV. ELVIRA GARCIA Y GARCIA N 418'
        No debe disparar falso 'Conflicto de vías' por la conjunción 'Y'.
        Debe homologar correctamente a la vía oficial ID 2901.
        """
        raw = "AV. ELVIRA GARCIA Y GARCIA N 418"
        clean = TextCleaner.sanitize(raw)
        extraction = OllamaAddressExtraction(
            tipo_via_detectado="AVENIDA",
            nom_via="ELVIRA GARCIA Y GARCIA",
            num_via="418",
            tipo_zona_detectada=None,
            nom_zona=None,
            manzana=None,
            lote=None,
            slote=None,
            referencia=None,
            observaciones=None,
        )
        self.mock_ollama.parse_address_with_ai.return_value = extraction
        record = DireccionOrigen(id_licencia=240, emp_direccion=raw)
        res = self.parser.parse(record)

        self.assertTrue(res.es_procesado, f"Error: observacion={res.observacion}")
        self.assertEqual(res.id_via, 2901)
        self.assertEqual(res.num_via, "418")
        self.assertIsNone(res.observacion)

    def test_id_209_urb_jose_quinones_gonzales_catalog_resolution(self):
        """Caso ID 209: 'URB. JOSÉ QUIÑONES GONZALES MZ. B LT. 15'
        Debe resolver al catálogo de zonas (ID 62) sin ser reportado como zona inexistente.
        """
        match_z = CatalogMatcher.match_physical_zona("JOSÉ QUIÑONES GONZALES")
        self.assertIsNotNone(match_z)
        self.assertEqual(match_z["id"], 62)

    def test_id_220_porcuya_synonym_resolution(self):
        """Caso ID 220: 'CA. PORCUYA N 140'
        Debe resolver a 'PORCULLA' mediante el diccionario de sinónimos canónicos.
        """
        match_v = CatalogMatcher.match_physical_via("PORCUYA")
        self.assertIsNotNone(match_v)
        self.assertEqual(match_v["nom_via"], "PORCULLA")

    def test_id_252_manuel_gervacio_arizola_synonym_resolution(self):
        """Caso ID 252: 'MANUEL GERVACIO ARIZOLA N 340'
        Debe resolver a 'ARIZOLA' (ID 59) mediante el diccionario de sinónimos canónicos.
        """
        match_v = CatalogMatcher.match_physical_via("MANUEL GERVACIO ARIZOLA")
        self.assertIsNotNone(match_v)
        self.assertEqual(match_v["nom_via"], "ARIZOLA")

    def test_id_244_anti_swap_protection_santa_victoria_buenos_aires(self):
        """Caso ID 244: 'AV. SANTA VICTORIA / PP.JJ. BUENOS AIRES'
        Ambos componentes tienen prefijos tipográficos explícitos ('AV.' y 'PP.JJ.').
        Bajo ninguna circunstancia deben invertirse.
        AV. SANTA VICTORIA debe resolver a SESQUICENTENARIO (ID 2926).
        PP.JJ. BUENOS AIRES debe resolver a P.J. BUENOS AIRES (ID 17).
        """
        raw = "AV. SANTA VICTORIA / PP.JJ. BUENOS AIRES"
        extraction = OllamaAddressExtraction(
            tipo_via_detectado="AVENIDA",
            nom_via="SANTA VICTORIA",
            num_via=None,
            tipo_zona_detectada="PUEBLO JOVEN",
            nom_zona="BUENOS AIRES",
            manzana=None,
            lote=None,
            slote=None,
            referencia=None,
            observaciones=None,
        )
        self.mock_ollama.parse_address_with_ai.return_value = extraction
        record = DireccionOrigen(id_licencia=244, emp_direccion=raw)
        res = self.parser.parse(record)

        self.assertTrue(res.es_procesado, f"Error de normalización: {res.observacion}")
        self.assertEqual(res.id_via, 2926)  # Sesquicentenario
        self.assertEqual(res.nom_zona, "BUENOS AIRES")

    def test_id_283_cross_streets_not_misidentified_as_urban_zone(self):
        """Caso ID 283: 'CA. ARICA N 1028 - HEROES CIVILES N 178'
        Intersección de dos vías con números.
        'HEROES CIVILES' no debe reportarse como zona inexistente;
        debe ser tratada como calle transversal / esquina en 'referencia'.
        """
        raw = "CA. ARICA N 1028 - HEROES CIVILES N 178"
        extraction = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="ARICA",
            num_via="1028",
            tipo_zona_detectada=None,
            nom_zona="HEROES CIVILES",
            manzana=None,
            lote=None,
            slote=None,
            referencia="178",
            observaciones=None,
        )
        self.mock_ollama.parse_address_with_ai.return_value = extraction
        record = DireccionOrigen(id_licencia=283, emp_direccion=raw)
        res = self.parser.parse(record)

        self.assertTrue(res.es_procesado, f"Observación inesperada: {res.observacion}")
        self.assertEqual(res.id_via, 233)  # Calle Arica
        self.assertEqual(res.num_via, "1028")
        self.assertIsNotNone(res.referencia)
        self.assertIn("HEROES CIVILES", res.referencia)

    def test_id_232_haya_de_la_torre_does_not_extract_tower_building(self):
        """Caso ID 232/298: 'HAYA DE LA TORRE N 111'
        No debe extraer 'TORRE N 111' como un Block/Torre residencial en la referencia.
        """
        raw = "HAYA DE LA TORRE N 111"
        extraction = OllamaAddressExtraction(
            tipo_via_detectado="AVENIDA",
            nom_via="HAYA DE LA TORRE",
            num_via="111",
            tipo_zona_detectada=None,
            nom_zona=None,
            manzana=None,
            lote=None,
            slote=None,
            referencia=None,
            observaciones=None,
        )
        self.mock_ollama.parse_address_with_ai.return_value = extraction
        record = DireccionOrigen(id_licencia=232, emp_direccion=raw)
        res = self.parser.parse(record)

        self.assertTrue(res.es_procesado, f"Error: observacion={res.observacion}")
        self.assertEqual(res.num_via, "111")
        # Asegurar que referencia no capturó TORRE N 111
        if res.referencia:
            self.assertNotIn("TORRE", res.referencia)


if __name__ == "__main__":
    unittest.main()
