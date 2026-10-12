from __future__ import annotations

import re
import unicodedata


WHITESPACE = re.compile(r"\s+")
LATEX_COMMAND = re.compile(r"\\(?:operatorname|mathrm|text)\s*\{([^{}]+)\}")
DECORATIVE_LATEX = re.compile(r"[${}^_\\]")


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u2019", "'").replace("\u2013", "-")
    return WHITESPACE.sub(" ", normalized).strip()


def formula_key(value: str) -> str:
    normalized = normalize_text(value).casefold()
    normalized = LATEX_COMMAND.sub(r"\1", normalized)
    normalized = DECORATIVE_LATEX.sub("", normalized)
    normalized = normalized.replace(" ", "")
    replacements = {
        "π": "pi",
        "∞": "infinity",
        "×": "*",
        "·": "*",
        "−": "-",
        "–": "-",
        "＝": "=",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def latex_to_unicode(value: str) -> str:
    replacements = {
        r"\alpha": "α",
        r"\beta": "β",
        r"\gamma": "γ",
        r"\delta": "δ",
        r"\epsilon": "ε",
        r"\theta": "θ",
        r"\lambda": "λ",
        r"\mu": "μ",
        r"\pi": "π",
        r"\sigma": "σ",
        r"\phi": "φ",
        r"\omega": "ω",
        r"\infty": "∞",
        r"\sum": "Σ",
        r"\prod": "Π",
        r"\int": "∫",
        r"\times": "×",
        r"\cdot": "·",
        r"\pm": "±",
        r"\leq": "≤",
        r"\geq": "≥",
        r"\neq": "≠",
        r"\approx": "≈",
        r"\to": "→",
        r"\rightarrow": "→",
        r"\in": "∈",
        r"\subset": "⊂",
        r"\partial": "∂",
        r"\nabla": "∇",
    }
    output = normalize_text(value).replace("$", "")
    for source, target in replacements.items():
        output = output.replace(source, target)
    output = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", output)
    output = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", output)
    output = re.sub(r"\\(?:left|right|displaystyle|,|;|!)", "", output)
    output = re.sub(r"\^\{([^{}]+)\}", r"^(\1)", output)
    output = re.sub(r"_\{([^{}]+)\}", r"_(\1)", output)
    output = output.replace("{", "").replace("}", "")
    return output

def latex_to_ascii(value: str) -> str:
    replacements = {
        "α": "alpha",
        "β": "beta",
        "γ": "gamma",
        "δ": "delta",
        "ε": "epsilon",
        "θ": "theta",
        "λ": "lambda",
        "μ": "mu",
        "π": "pi",
        "σ": "sigma",
        "φ": "phi",
        "ω": "omega",
        "∞": "infinity",
        "×": "x",
        "·": "*",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "≈": "~=",
        "→": "->",
        "∈": " in ",
        "∂": "partial",
        "∇": "nabla",
    }
    output = latex_to_unicode(value)
    for source, target in replacements.items():
        output = output.replace(source, target)
    return output
