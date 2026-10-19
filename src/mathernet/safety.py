from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import RefusalError
from .models import RefusalReason
from .normalization import normalize_text


ASSESSMENT_PATTERNS = (
    r"\b(midterm|final\s+exam|exam\s+question|homework|assignment|quiz|test\s+question)\b",
    r"(期中|期末|考试题|测验题|作业题|作业|试卷|quiz|assignment)",
)
FABRICATION_PATTERNS = (
    r"\b(ignore\s+(?:the\s+)?sources?|fabricat\w*|invent\s+(?:a\s+)?(?:derivation|proof|source)|make\s+the\s+derivation\s+look\s+correct)\b",
    r"(忽略来源|编造|伪造|虚构).{0,12}(推导|证明|来源|公式)",
    r"(推导|证明|来源).{0,12}(编造|伪造|虚构|看起来正确)",
)
NON_FORMULA_PATTERNS = (
    r"\b(write|compose)\s+(?:me\s+)?a\s+(?:poem|song|story|essay)\b",
    r"\b(recipe|weather\s+forecast|stock\s+price)\b",
    r"(写一首诗|写诗|写歌|菜谱|天气预报)",
)


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    reason_code: RefusalReason | None = None
    message: str = ""


def _matches(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def assess_request(request: str) -> SafetyDecision:
    normalized = normalize_text(request)
    if not normalized:
        return SafetyDecision(
            False,
            RefusalReason.NON_FORMULA,
            "Please provide a formula name, plain-language expression, or LaTeX string.",
        )
    if _matches(FABRICATION_PATTERNS, normalized):
        return SafetyDecision(
            False,
            RefusalReason.FABRICATION,
            "Mathernet cannot fabricate or alter a derivation to make it look correct. It will preserve source integrity.",
        )
    if _matches(ASSESSMENT_PATTERNS, normalized):
        return SafetyDecision(
            False,
            RefusalReason.ASSESSMENT,
            "Mathernet cannot solve or answer real exams, homework, quizzes, or other assessed work. You may ask about a formula for study instead.",
        )
    if _matches(NON_FORMULA_PATTERNS, normalized):
        return SafetyDecision(
            False,
            RefusalReason.NON_FORMULA,
            "Mathernet only supports mathematical formula learning requests.",
        )
    return SafetyDecision(True)


def enforce_request_safety(request: str) -> None:
    decision = assess_request(request)
    if not decision.allowed:
        raise RefusalError(decision.message, decision.reason_code.value)
