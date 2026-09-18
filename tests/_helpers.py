"""SOLVI - Utilidades compartidas para aserciones de pruebas y validación de texto visible."""

import re
import unittest


def extract_visible_html_text(html: str) -> str:
    """Extrae el texto que ve el usuario final eliminando comentarios, scripts, estilos y tags HTML."""
    if not html:
        return ""
    # Remover comentarios HTML
    cleaned = re.sub(r"<!--[\s\S]*?-->", " ", html)
    # Remover bloques de script y style
    cleaned = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Remover tags y atributos
    visible = re.sub(r"<[^>]+>", " ", cleaned)
    # Normalizar espacios
    return re.sub(r"\s+", " ", visible).strip()


def extract_visible_js_strings(js_code: str) -> list[str]:
    """Extrae literales de texto dirigidos al usuario en código JavaScript (toasts, placeholders, títulos, etc.)."""
    if not js_code:
        return []
    strings: list[str] = []
    strings += re.findall(r'toast\s*\(\s*["\']([^"\']+)["\']', js_code)
    strings += re.findall(r'placeholder\s*=\s*["\']([^"\']+)["\']', js_code)
    strings += re.findall(r'title\s*=\s*["\']([^"\']+)["\']', js_code)
    strings += re.findall(r'alert\s*\(\s*["\']([^"\']+)["\']', js_code)
    return strings


def assert_no_visible_ai(test_case: unittest.TestCase, text: str, context: str = "texto"):
    """Verifica de forma estricta que no existan menciones visibles de 'IA', 'AI' o 'Inteligencia Artificial'."""
    test_case.assertNotRegex(
        text,
        r"\bInteligencia\s+Artificial\b",
        f"Violación de regla estricta: 'Inteligencia Artificial' encontrada en {context}"
    )
    test_case.assertNotRegex(
        text,
        r"\b(?:IA|AI)\b",
        f"Violación de regla estricta: mención visible de 'IA' o 'AI' en {context}"
    )
