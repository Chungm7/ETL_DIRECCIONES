"""Estructura de limpieza y normalización léxica de direcciones."""

import re
import unicodedata
from typing import Optional


class TextCleaner:
    """Provee rutinas de saneamiento y normalización de cadenas de texto antes de la inferencia."""

    @staticmethod
    def sanitize(text: Optional[str]) -> str:
        """Limpia caracteres extraños, separa palabras pegadas y normaliza a mayúsculas."""
        if not text:
            return ""

        # 1. Eliminar caracteres no imprimibles y normalizar espacios iniciales
        clean = "".join(ch for ch in text if ch.isprintable())
        clean = re.sub(r"\s+", " ", clean).strip().upper()

        # 2. Despegar guiones entre palabras y números (ej. 'SAN NICOLAS-LAS AMERICAS' -> 'SAN NICOLAS - LAS AMERICAS')
        clean = re.sub(r"([A-ZÁÉÍÓÚÑ0-9])\-([A-ZÁÉÍÓÚÑ0-9])", r"\1 - \2", clean)

        # 3. Despegar nombres de ciudades o distritos unidos a nombres de calles (ej. CHICLAYOALFREDO -> CHICLAYO ALFREDO)
        clean = re.sub(
            r"^(CHICLAYO|LAMBAYEQUE|FERRENAFE|PIMENTEL|LA VICTORIA|JLO|REQUE|MONSEFU)([A-ZÁÉÍÓÚ])",
            r"\1 \2",
            clean,
        )

        # 4. Despegar letras pegadas a números al final de palabras (ej. 'AMERICAS705' -> 'AMERICAS 705', 'ORIENTE00261' -> 'ORIENTE 261')
        def _sep_num(m):
            pfx = m.group(1)
            num = m.group(2)
            if pfx in ("MZ", "MZA", "LT", "LOTE", "INT", "DPTO", "KM", "CDRA", "CUADRA"):
                return f"{pfx} {num}"
            # Quitar ceros sobrantes a la izquierda en la numeración (ej. 00261 -> 261, 00839 -> 839)
            num_clean = str(int(num)) if num.isdigit() and int(num) > 0 else num
            return f"{pfx} {num_clean}"

        clean = re.sub(r"\b([A-ZÁÉÍÓÚÑ]{2,})(\d{1,6})\b", _sep_num, clean)

        # 5. Normalizar interiores y departamentos (ej. 'INT - I', 'INT - 2' -> 'INT-I', 'INT-2')
        clean = re.sub(r"\bINT\s*[-–.]\s*([A-Z0-9]+)", r"INT-\1", clean)
        clean = re.sub(r"\bDPTO\s*[-–.]\s*([A-Z0-9]+)", r"DPTO-\1", clean)

        # 6. Normalizar números y prefijos N°
        clean = re.sub(r"\bN\s*°?\s*(\d+)", r"N° \1", clean)
        clean = re.sub(r"\bNUM\s*°?\s*(\d+)", r"N° \1", clean)

        # 7. Normalizar tipos de vía abreviados sin punto al inicio
        clean = re.sub(r"^AV\s+([A-Z])", r"AV. \1", clean)
        clean = re.sub(r"^CA\s+([A-Z])", r"CA. \1", clean)
        clean = re.sub(r"^JR\s+([A-Z])", r"JR. \1", clean)
        clean = re.sub(r"^PJE\s+([A-Z])", r"PJE. \1", clean)

        # 8. Limpieza de guiones dobles o sobrantes al inicio o final y espacios redundantes
        clean = re.sub(r"^\s*-\s*", "", clean)
        clean = re.sub(r"\s*-\s*$", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        return clean

    @staticmethod
    def remove_accents(text: str) -> str:
        """Elimina tildes y diacríticos para facilitar búsquedas y homologación."""
        nfkd_form = unicodedata.normalize("NFKD", text)
        return "".join([c for c in nfkd_form if not unicodedata.combining(c)])
