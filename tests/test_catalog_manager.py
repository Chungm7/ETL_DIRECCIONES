"""Pruebas unitarias para el gestor dinámico de catálogos y diccionarios JSON (CatalogManager)."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher
from src.utils.prompts import get_system_prompt_address_parser


class TestCatalogManager(unittest.TestCase):
    """Verifica la carga, diccionarios, heurísticas y adición dinámica de vías y zonas."""

    def setUp(self):
        CatalogManager.reload()
        CatalogMatcher.reset_defaults()

    def tearDown(self):
        CatalogManager.reload()
        CatalogMatcher.reset_defaults()

    def test_load_default_catalogs(self):
        """Valida que los archivos JSON maestros contengan los 12 tipos de vía y 28 de zona por defecto."""
        vias = CatalogManager.get_vias_catalog()
        zonas = CatalogManager.get_zonas_catalog()

        self.assertGreaterEqual(len(vias), 12)
        self.assertGreaterEqual(len(zonas), 28)

        # Verificar primer registro de vías (AVENIDA)
        via_1 = vias[0]
        self.assertEqual(via_1["id"], 1)
        self.assertEqual(via_1["nombre"], "AVENIDA")
        self.assertEqual(via_1["abreviatura"], "AV.")
        self.assertIn("AV.", via_1["sinonimos"])

        # Verificar primer registro de zonas (ASENTAMIENTO HUMANO)
        zona_1 = zonas[0]
        self.assertEqual(zona_1["id"], 1)
        self.assertEqual(zona_1["nombre"], "ASENTAMIENTO HUMANO")
        self.assertEqual(zona_1["abreviatura"], "A.H.")
        self.assertIn("A.H.", zona_1["sinonimos"])

    def test_tuples_for_database_service(self):
        """Valida que get_official_vias_tuples y get_official_zonas_tuples retornen las tuplas esperadas por BD."""
        via_tuples = CatalogManager.get_official_vias_tuples()
        zona_tuples = CatalogManager.get_official_zonas_tuples()

        self.assertIsInstance(via_tuples, list)
        self.assertIsInstance(zona_tuples, list)

        # Cada elemento debe ser una tupla (id, nombre, abreviatura)
        for vid, vname, vabrev in via_tuples:
            self.assertIsInstance(vid, int)
            self.assertIsInstance(vname, str)
            self.assertIsInstance(vabrev, str)

        for zid, zname, zabrev in zona_tuples:
            self.assertIsInstance(zid, int)
            self.assertIsInstance(zname, str)
            self.assertIsInstance(zabrev, str)

    def test_default_mappings_generation(self):
        """Valida que los diccionarios generados mapeen correctamente términos y sinónimos a sus IDs."""
        vias_map = CatalogManager.get_default_vias_mapping()
        zonas_map = CatalogManager.get_default_zonas_mapping()

        # Vías
        self.assertEqual(vias_map["AVENIDA"], 1)
        self.assertEqual(vias_map["AV."], 1)
        self.assertEqual(vias_map["AV"], 1)
        self.assertEqual(vias_map["CALLE"], 2)
        self.assertEqual(vias_map["CA."], 2)
        self.assertEqual(vias_map["JIRON"], 3)
        self.assertEqual(vias_map["JR."], 3)

        # Zonas
        self.assertEqual(zonas_map["ASENTAMIENTO HUMANO"], 1)
        self.assertEqual(zonas_map["A.H."], 1)
        self.assertEqual(zonas_map["PUEBLO JOVEN"], 5)
        self.assertEqual(zonas_map["P.J."], 5)
        self.assertEqual(zonas_map["URBANIZACION"], 6)
        self.assertEqual(zonas_map["URB."], 6)

    def test_format_for_prompt_and_system_prompt_integration(self):
        """Valida que los métodos de formato generen texto con la cantidad exacta de vías y zonas para el LLM."""
        vias_str = CatalogManager.format_vias_for_prompt()
        zonas_str = CatalogManager.format_zonas_for_prompt()

        self.assertIn("AVENIDA (AV.)", vias_str)
        self.assertIn("CALLE (CA.)", vias_str)
        self.assertIn("URBANIZACION (URB.)", zonas_str)

        prompt = get_system_prompt_address_parser()
        self.assertIn("### Catálogo de Tipos de Vía válidos", prompt)
        self.assertIn("### Catálogo de Tipos de Zona válidos", prompt)
        self.assertIn(vias_str, prompt)
        self.assertIn(zonas_str, prompt)

    def test_get_via_prefix_regex_str(self):
        """Valida que el generador de regex de prefijos arme una expresión válida."""
        regex_str = CatalogManager.get_via_prefix_regex_str()
        self.assertIsInstance(regex_str, str)
        self.assertTrue(regex_str.startswith("(?:"))
        self.assertTrue(regex_str.endswith(")"))
        self.assertIn("AV", regex_str)
        self.assertIn("CALLE", regex_str)

    def test_add_tipo_zona_mock_save(self):
        """Valida la adición dinámica de una zona (ej. número 29) sin afectar archivos reales."""
        fake_zonas = [
            {"id": 1, "nombre": "ASENTAMIENTO HUMANO", "abreviatura": "A.H.", "sinonimos": ["A.H."]},
            {"id": 2, "nombre": "URBANIZACION", "abreviatura": "URB.", "sinonimos": ["URB."]},
        ]

        with patch.object(CatalogManager, "get_zonas_catalog", return_value=fake_zonas):
            with patch.object(CatalogManager, "_save_json", return_value=True) as mock_save:
                res = CatalogManager.add_tipo_zona(
                    nombre="PARQUE INDUSTRIAL",
                    abreviatura="P.I.",
                    sinonimos=["PARQUE INDUSTRIAL", "P.I.", "PARQ.IND."],
                )

                self.assertTrue(res["success"])
                self.assertEqual(res["entry"]["id"], 3)  # max_id (2) + 1
                self.assertEqual(res["entry"]["nombre"], "PARQUE INDUSTRIAL")
                self.assertEqual(res["entry"]["abreviatura"], "P.I.")
                self.assertIn("PARQ.IND.", res["entry"]["sinonimos"])
                mock_save.assert_called_once()

    def test_add_tipo_via_duplicate_prevention(self):
        """Valida que no se dupliquen vías ya existentes."""
        res = CatalogManager.add_tipo_via(nombre="CALLE")
        self.assertFalse(res["success"])
        self.assertIn("ya existe", res["message"])

    def test_add_tipo_zona_duplicate_prevention(self):
        """Valida que no se dupliquen zonas ya existentes."""
        res = CatalogManager.add_tipo_zona(nombre="URBANIZACION")
        self.assertFalse(res["success"])
        self.assertIn("ya existe", res["message"])

    def test_adding_new_zone_propagates_to_database_and_matcher(self):
        """Valida que al agregar una nueva zona (ej. la 29), CatalogMatcher y DatabaseService la incorporen sin romper nada."""
        from src.services.db_service import DatabaseService

        fake_zonas = list(CatalogManager.get_zonas_catalog())
        new_zone = {
            "id": 29,
            "nombre": "PARQUE INDUSTRIAL",
            "abreviatura": "P.I.",
            "sinonimos": ["PARQUE INDUSTRIAL", "P.I.", "PARQ.IND."],
            "patron_regex": r"\b(?:PARQUE\s+INDUSTRIAL|P\.I\.)\b",
        }
        fake_zonas.append(new_zone)

        with patch.object(CatalogManager, "get_zonas_catalog", return_value=fake_zonas):
            CatalogMatcher.reset_defaults()
            self.assertEqual(CatalogMatcher.match_tipo_zona("PARQUE INDUSTRIAL"), 29)
            self.assertEqual(CatalogMatcher.match_tipo_zona("P.I."), 29)
            self.assertEqual(CatalogMatcher.match_tipo_zona("PARQ.IND."), 29)
            self.assertEqual(CatalogMatcher.get_zona_name(29), "PARQUE INDUSTRIAL")

            # Verificar que DatabaseService.ensure_catalogs_exist detecte las 29 zonas
            service = DatabaseService()
            service._engine = MagicMock()

            mock_session = MagicMock()
            # Simula que existen las 28 zonas oficiales en la BD
            existing_28_rows = [(v[0], v[1]) for v in CatalogManager.get_official_zonas_tuples()[:28]]

            def mock_execute_side_effect(sql_stmt, params=None):

                sql_str = str(sql_stmt)
                mock_res = MagicMock()
                if "information_schema.tables" in sql_str:
                    mock_res.scalar.return_value = 1
                elif "column_name = 'abreviatura'" in sql_str:
                    mock_res.scalar.return_value = 1
                elif "tipos_zona" in sql_str:
                    mock_res.fetchall.return_value = existing_28_rows
                elif "tipos_via" in sql_str:
                    mock_res.fetchall.return_value = [(1, "AVENIDA"), (2, "CALLE")]
                else:
                    mock_res.fetchall.return_value = []
                    mock_res.scalar.return_value = None
                return mock_res

            mock_session.execute.side_effect = mock_execute_side_effect

            with patch.object(service, "get_session") as mock_get_session:
                mock_get_session.return_value.__enter__.return_value = mock_session
                status = service.ensure_catalogs_exist(schema="test_schema")

                # Debería haber 28 existentes y 1 agregada (la 29) -> total 29
                self.assertEqual(status["tipos_zona"]["existing_records"], 28)
                self.assertEqual(status["tipos_zona"]["added_records"], 1)
                self.assertEqual(status["tipos_zona"]["total_records"], 29)

    def test_physical_vias_and_zonas_catalogs_loading(self):
        """Valida que los catálogos maestros físicos de Chiclayo carguen correctamente."""
        vias = CatalogManager.get_vias_chiclayo_catalog()
        zonas = CatalogManager.get_zonas_chiclayo_catalog()

        self.assertEqual(len(vias), 3024)
        self.assertEqual(len(zonas), 461)

        v_tuples = CatalogManager.get_official_physical_vias_tuples()
        z_tuples = CatalogManager.get_official_physical_zonas_tuples()
        self.assertEqual(len(v_tuples), 3024)
        self.assertEqual(len(z_tuples), 461)

    def test_physical_vias_and_zonas_matching(self):
        """Valida que CatalogMatcher homologue vías y zonas físicas de Chiclayo."""
        v1 = CatalogMatcher.match_physical_via("7 DE ENERO")
        self.assertIsNotNone(v1)
        self.assertEqual(v1["id"], 2279)
        self.assertEqual(v1["nom_via"], "7 DE ENERO SUR")

        v2 = CatalogMatcher.match_physical_via("AV. SALAVERRY")
        self.assertIsNotNone(v2)
        self.assertEqual(v2["id"], 2862)
        self.assertEqual(v2["nom_via"], "FELIPE SANTIAGO SALAVERRY")

        z1 = CatalogMatcher.match_physical_zona("URB. COLIBRI")
        self.assertIsNotNone(z1)
        self.assertEqual(z1["id"], 461)
        self.assertEqual(z1["nom_zona"], "COLIBRI")

        z2 = CatalogMatcher.match_physical_zona("SANTA VICTORIA")
        self.assertIsNotNone(z2)
        self.assertEqual(z2["id"], 1)
        self.assertEqual(z2["nom_zona"], "SANTA VICTORIA")


if __name__ == "__main__":
    unittest.main()

