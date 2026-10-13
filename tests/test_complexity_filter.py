"""Pruebas unitarias para el evaluador de alta complejidad y la derivación a Observados (Tri-State FALSE)."""

import pytest
from unittest.mock import MagicMock
from src.transformers.complexity_evaluator import AddressComplexityEvaluator
from src.transformers.ai_parser import AIAddressParser
from src.models.direccion_origen import DireccionOrigen
from src.models.direccion_destino import DireccionDestino
from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher


@pytest.fixture(autouse=True)
def setup_catalogs():
    CatalogManager.reload()
    CatalogMatcher.reset_defaults()


class TestComplexityFilter:
    """Valida la detección de direcciones sobrecargadas y su derivación a es_procesado = FALSE."""

    def test_evaluator_detects_historical_via_alias(self):
        """Verifica que alias viales históricos 'EX-' sean detectados como hard trigger."""
        addr1 = "AV. SAN JOSEMARÍA ESCRIVÁ DE BALAGUER S/N (EX PANAMERICANA N° 639), TIENDA 120/220 - C.C. MALL AVENTURA - CHICLAYO"
        res1 = AddressComplexityEvaluator.evaluate(addr1)
        assert res1.is_too_complex is True
        assert "ALIAS_VIA_HISTORICA" in res1.triggers
        assert res1.score >= 65.0

        addr2 = "MZ. W LT. 24, P.J. FANNY ABANTO CALLE / AV. AMAUTA DE LA NACIÓN GUILLERMO BACA AGUINAGA N° 2715 (EX. CA. PEDRO RUIZ)"
        res2 = AddressComplexityEvaluator.evaluate(addr2)
        assert res2.is_too_complex is True
        assert "ALIAS_VIA_HISTORICA" in res2.triggers

    def test_evaluator_detects_dual_street_with_slash(self):
        """Verifica que vías compuestas con barra 'CALLE / AV' disparen trigger de alta complejidad."""
        addr = "CALLE / AV. AMAUTA DE LA NACION GUILLERMO BACA AGUINAGA N° 2715"
        res = AddressComplexityEvaluator.evaluate(addr)
        assert res.is_too_complex is True
        assert "DOBLE_VIA_DISYUNTIVA" in res.triggers

    def test_evaluator_detects_massive_modules(self):
        """Verifica que listas de 3 o más módulos concatenados sean catalogadas como alta complejidad."""
        addr = "AV. SAN JOSEMARÍA ESCRIVÁ DE BALAGUER S/N, C.C. MALL AVENTURA - 1° PISO, MÓDULOS 3, 4, 5 Y 6 (FRENTE A PROMART)"
        res = AddressComplexityEvaluator.evaluate(addr)
        assert res.is_too_complex is True
        assert "MODULOS_MASIVOS_EN_LISTA" in res.triggers

    def test_evaluator_detects_complex_rural_structure(self):
        """Verifica que estructuras rústicas complejas con unidades catastrales U.C. sean derivadas."""
        addr = "PARCELA AGRICOLA DE TERRENO RUSTICO SECTOR SAN PEDRO N° 7, FUNDO MARIA CRUZ Y ANEXOS (QUE PERTENECE A U.C. N° 12057)"
        res = AddressComplexityEvaluator.evaluate(addr)
        assert res.is_too_complex is True
        assert "PREDIO_RUSTICO_COMPLEJO" in res.triggers

    def test_evaluator_permits_clean_standard_addresses(self):
        """Verifica que direcciones estándar y limpias NUNCA sean catalogadas como alta complejidad."""
        standard_addresses = [
            "CALLE ARICA N 1364 - CHICLAYO",
            "AV. AUGUSTO B. LEGUÍA N 187 - CHICLAYO",
            "CA. LOS DULANTOS N 119 URB. SANTA VICTORIA - CHICLAYO",
            "CA. FRANCISCO DE PAULA VIGIL S/N CONJ.RES. DIEGO FERRE MZ. 18 LT. 12",
            "AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905 - CHICLAYO",
            "CA. ALFREDO LAPOINT N 838 INT. B-C - CHICLAYO",
            "AV. JOSÉ BALTA N 1400 - INT. 17-19 2 PISO - CHICLAYO",
        ]
        for raw in standard_addresses:
            res = AddressComplexityEvaluator.evaluate(raw)
            assert res.is_too_complex is False, f"Falso positivo en dirección estándar: '{raw}' (Score: {res.score})"
            assert len(res.triggers) == 0

    def test_ai_parser_derives_complex_address_to_observed_false(self):
        """Verifica que AIAddressParser marque una dirección compleja directamente como es_procesado = FALSE."""
        raw = "AV. SAN JOSEMARÍA ESCRIVÁ DE BALAGUER S/N (EX PANAMERICANA N° 639), TIENDA 120/220 - C.C. MALL AVENTURA - CHICLAYO"
        rec = DireccionOrigen(id_licencia=36370, emp_direccion=raw)
        
        mock_ollama = MagicMock()
        parser = AIAddressParser(
            ollama_service=mock_ollama,
            filter_high_complexity=True,
            complexity_threshold=65.0,
        )

        dest = parser.parse(rec)

        # 1. Debe ser Observado (Tri-State FALSE)
        assert dest.es_procesado is False
        # 2. No debe asociar zona_id ni relaciones hijas
        assert dest.zona_id is None
        assert dest.dire_referencia is None
        assert dest.vias == []
        assert dest.componentes == []
        assert dest.modulos == []
        # 3. La observación de base de datos permanece limpia (None)
        assert dest.observacion is None
        # 4. El método de normalización documenta la razón técnica
        assert "Alta Complejidad" in dest.metodo_normalizacion
        # 5. La IA no debe ser invocada innecesariamente ante un hard trigger temprano
        mock_ollama.parse_address_with_ai.assert_not_called()

    def test_ai_parser_respects_filter_toggle(self):
        """Verifica que si filter_high_complexity es False, el parser intente el flujo regular."""
        raw = "AV. SAN JOSEMARÍA ESCRIVÁ DE BALAGUER S/N (EX PANAMERICANA N° 639)"
        rec = DireccionOrigen(id_licencia=9999, emp_direccion=raw)
        
        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = None
        parser = AIAddressParser(
            ollama_service=mock_ollama,
            filter_high_complexity=False,
        )

        dest = parser.parse(rec)
        # La IA fue llamada porque el filtro estaba desactivado
        mock_ollama.parse_address_with_ai.assert_called_once()
