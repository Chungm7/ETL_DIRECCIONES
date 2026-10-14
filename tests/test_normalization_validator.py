"""Pruebas unitarias para el validador de certeza catastral y similitud post-normalización."""

import pytest
from unittest.mock import MagicMock

from src.models.direccion_destino import DireccionDestino
from src.models.direccion_origen import DireccionOrigen
from src.models.llm_schemas import OllamaAddressExtraction
from src.transformers.ai_parser import AIAddressParser
from src.transformers.normalization_validator import AddressNormalizationValidator
from src.catalogs.catalog_manager import CatalogManager
from src.transformers.catalog_matcher import CatalogMatcher


@pytest.fixture(autouse=True)
def setup_catalogs():
    CatalogManager.reload()
    CatalogMatcher.reset_defaults()


class TestNormalizationValidator:
    """Verifica el cálculo de similitud y cobertura entre texto crudo y resultado normalizado."""

    def test_validator_approves_clean_standard_address(self):
        """Verifica que una dirección limpia y bien normalizada obtenga score superior al umbral y sea aprobada."""
        dest = DireccionDestino(
            id_licencia=101,
            nom_via="JOSE BALTA",
            tipo_via=1,
            num_via="500",
            modulos=[{"timo_nombre": "DEPARTAMENTO", "ditm_nombre": "101"}],
            componentes=[{"codi_nombre": "PISO", "diti_nombre": "3"}],
            es_procesado=True,
        )
        res = AddressNormalizationValidator.validate(
            raw_text="AV. BALTA 500 DPTO 101 PISO 3 - CHICLAYO",
            destino=dest,
            threshold=0.85,
        )
        assert res.is_valid is True
        assert res.score >= 0.85
        assert res.token_coverage >= 0.90
        assert res.unmatched_tokens == []
        assert res.rejection_reason is None

    def test_validator_approves_manzana_lote_urbanizacion(self):
        """Verifica que combinaciones prediales Mz/Lt en urbanización homologada alcancen 100% de acierto."""
        dest = DireccionDestino(
            id_licencia=102,
            nom_via="SAN JOSE",
            tipo_via=2,
            num_via="120",
            manzana="B",
            lote="5",
            nom_zona="CENTRO",
            tipo_zona=6,  # URBANIZACION
            es_procesado=True,
        )
        res = AddressNormalizationValidator.validate(
            raw_text="CALLE SAN JOSE 120 MZ B LT 5 URB. CENTRO - CHICLAYO",
            destino=dest,
            threshold=0.85,
        )
        assert res.is_valid is True
        assert res.score >= 0.85
        assert res.token_coverage == 1.0

    def test_validator_rejects_severe_omissions(self):
        """Verifica que si la IA omitió partes críticas de la dirección cruda, sea vetada con es_procesado = False."""
        dest_incompleto = DireccionDestino(
            id_licencia=103,
            nom_via="JOSE BALTA",
            tipo_via=1,
            num_via="500",
            es_procesado=True,
        )
        raw_complejo = "AV. BALTA 500 CON ESQ. SAN JOSE Y SAENZ PEÑA FRENTE AL PARQUE PRINCIPAL MZ A LT 14 DPTO 301 PISO 3"
        res = AddressNormalizationValidator.validate(
            raw_text=raw_complejo,
            destino=dest_incompleto,
            threshold=0.85,
        )
        assert res.is_valid is False
        assert res.score < 0.60
        assert res.token_coverage < 0.50
        assert "SIMILITUD_INSUFICIENTE" in res.rejection_reason
        # Comprobar que detecta los tokens ignorados por la IA
        for token in ["SAN", "SAENZ", "PARQUE", "MANZANA", "DEPARTAMENTO"]:
            assert token in res.unmatched_tokens

    def test_validator_approves_multi_via_corner(self):
        """Verifica que esquinas con ambas vías extraídas reconozcan conectores de esquina sin penalizar."""
        dest_esquina = DireccionDestino(
            id_licencia=104,
            vias=[
                {"via_nombre": "SAENZ PEÑA", "tipo_via_name": "AVENIDA", "divi_numero": "106"},
                {"via_nombre": "GARCILAZO DE LA VEGA", "tipo_via_name": "CALLE", "divi_numero": "905"},
            ],
            es_procesado=True,
        )
        res = AddressNormalizationValidator.validate(
            raw_text="AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905 - CHICLAYO",
            destino=dest_esquina,
            threshold=0.85,
        )
        assert res.is_valid is True
        assert res.score >= 0.85
        assert res.token_coverage == 1.0

    def test_validator_rejects_when_corner_via_is_missed(self):
        """Verifica que si el texto crudo describe una esquina pero la IA solo extrajo una vía, se rechace."""
        dest_single_via = DireccionDestino(
            id_licencia=105,
            vias=[
                {"via_nombre": "SAENZ PEÑA", "tipo_via_name": "AVENIDA", "divi_numero": "106"},
            ],
            es_procesado=True,
        )
        res = AddressNormalizationValidator.validate(
            raw_text="AV. SAENZ PEÑA N 106 - ESQ. GARCILAZO DE LA VEGA N 905 - CHICLAYO",
            destino=dest_single_via,
            threshold=0.85,
        )
        assert res.is_valid is False
        assert res.score < 0.70
        assert "GARCILAZO" in res.unmatched_tokens
        assert "VEGA" in res.unmatched_tokens

    def test_validator_handles_abbreviations_and_stopwords(self):
        """Verifica que abreviaturas como CA, AV, MZ, LT, DPTO mapeen canónicamente y las stopwords no penalicen."""
        dest = DireccionDestino(
            id_licencia=106,
            nom_via="ALFREDO LAPOINT",
            tipo_via=2,
            num_via="838",
            modulos=[
                {"timo_nombre": "INTERIOR", "ditm_nombre": "B"},
                {"timo_nombre": "INTERIOR", "ditm_nombre": "C"},
            ],
            es_procesado=True,
        )
        res = AddressNormalizationValidator.validate(
            raw_text="CA. ALFREDO LAPOINT N 838 INT. B-C - CHICLAYO",
            destino=dest,
            threshold=0.85,
        )
        assert res.is_valid is True
        assert res.score >= 0.90
        assert res.token_coverage == 1.0


class TestAIParserPostValidationIntegration:
    """Verifica que AIAddressParser utilice la validación cruzada para vetar normalizaciones dudosas."""

    def test_ai_parser_vetoes_incomplete_normalization_to_observed(self):
        """Simula una respuesta de IA que ignora más de la mitad del texto crudo y verifica que se marque es_procesado = False."""
        mock_ollama = MagicMock()
        # El LLM solo extrae Balta 500, ignorando el resto del texto
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="CALLE",
            nom_via="SAN JOSE",
            num_via="340",
            confianza=0.95,
        )

        parser = AIAddressParser(
            ollama_service=mock_ollama,
            filter_high_complexity=False,  # Para que pase a validación post-normalización
            min_similarity_threshold=0.85,
        )

        raw = "CALLE SAN JOSE 340 SECTOR INDUSTRIAL MOLINERO ALMACEN CENTRAL DEPOSITO SUR CHICLAYO"
        rec = DireccionOrigen(id_licencia=5001, emp_direccion=raw)
        dest = parser.parse(rec)

        # 1. Debe ser vetado a OBSERVADO (es_procesado = False)
        assert dest.es_procesado is False
        # 2. Las relaciones relacionales deben quedar limpias
        assert dest.vias == []
        assert dest.componentes == []
        assert dest.modulos == []
        assert dest.zona_id is None
        # 3. La observación en BD queda limpia (None)
        assert dest.observacion is None
        # 4. El método de normalización documenta la razón técnica
        assert "Similitud insuficiente" in dest.metodo_normalizacion

    def test_instantiable_custom_similarity_threshold(self):
        """Verifica que el umbral de similitud sea instanciable y configurable directamente en la clase."""
        mock_ollama = MagicMock()
        mock_ollama.parse_address_with_ai.return_value = OllamaAddressExtraction(
            tipo_via_detectado="AVENIDA",
            nom_via="BALTA",
            num_via="500",
            confianza=0.90,
        )

        # Instanciar con umbral estricto de 0.99
        strict_parser = AIAddressParser(
            ollama_service=mock_ollama,
            filter_high_complexity=False,
            min_similarity_threshold=0.99,
        )
        assert strict_parser.min_similarity_threshold == 0.99

        # Con umbral estándar
        default_parser = AIAddressParser(ollama_service=mock_ollama)
        assert default_parser.min_similarity_threshold == 0.85
