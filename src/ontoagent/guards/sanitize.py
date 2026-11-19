"""Prompt injection and untrusted input sanitization.

Purpose:
    Multi-layered prompt-injection defenses (Threats T1, T2, T3).
    Implements heuristic rule scanning, score weighting, and strict XML-style
    untrusted data boundary wrapping.
"""

from dataclasses import dataclass
import re
from typing import List


@dataclass
class ScanResult:
    """Outcome of scanning text for prompt injection patterns."""
    score: float
    matches: List[str]
    flagged: bool


RULES = [
    (r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+(?:instructions|rules)", 0.7, "IGNORE_INSTRUCTIONS"),
    (r"disregard\s+.*(?:instructions|policy|rules)", 0.7, "DISREGARD_POLICY"),
    (r"you\s+are\s+now", 0.5, "JAILBREAK_ROLEPLAY"),
    (r"pretend\s+you\s+(?:are|can)", 0.5, "JAILBREAK_PRETEND"),
    (r"(?:developer|debug)\s+mode", 0.5, "JAILBREAK_DEVELOPER_MODE"),
    (r"(?:database|api|secret|credential|password)s?", 0.3, "CREDENTIAL_PROBE"),
    (r"system\s*[:\-]\s*.*|system\s+(?:notice|prompt|message|override|directive)", 0.6, "SYSTEM_DIRECTIVE"),
    (r"(?:assistant|ai|llm)s?:", 0.5, "AGENT_IMPERSONATION"),
    (r"do\s+not\s+(?:tell|mention|reveal|disclose)", 0.4, "SECRECY_COERCION"),
    (r"(?:approve|issue|execute|call|run)\s+.*(?:refund|tool|payment|ticket)", 0.7, "UNAUTHORIZED_ACTION_TRIGGER"),
    (r"<\|?(?:im_start|system|im_end)\|?>", 0.8, "SPECIAL_TOKEN_INJECTION"),
    (r"(?:[A-Za-z0-9+/]{40,}={0,2})", 0.4, "BASE64_BLOB"),
    (r"[\u200B-\u200D\uFEFF]", 0.5, "ZERO_WIDTH_CHARS"),
    (r"<!--[\s\S]*?-->|<style[\s\S]*?>[\s\S]*?<\/style>", 0.4, "HIDDEN_MARKUP"),
    (r"<\/?untrusted_data[^>]*>", 0.6, "DELIMITER_TAMPERING"),
]


def scan_untrusted_text(text: str) -> ScanResult:
    """Scan natural language or untrusted retrieved text for prompt injection heuristics.

    Args:
        text: Input string to inspect.

    Returns:
        ScanResult with combined risk score [0, 1], match tags, and boolean flag (>= 0.5).
    """
    if not text:
        return ScanResult(score=0.0, matches=[], flagged=False)

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    total_score = 0.0
    matches: List[str] = []

    for pattern, weight, tag in RULES:
        if re.search(pattern, normalized, re.IGNORECASE):
            total_score += weight
            matches.append(tag)

    clamped_score = min(round(total_score, 2), 1.0)
    flagged = clamped_score >= 0.5
    return ScanResult(score=clamped_score, matches=matches, flagged=flagged)


def wrap_untrusted_data(text: str, source: str, item_id: str) -> str:
    """Wrap untrusted database or retrieved KB text in isolation tags.

    Neutralizes delimiter breakouts by removing literal closing and opening tags.
    """
    sanitized = re.sub(r"<\/?untrusted_data[^>]*>", "", text)
    return f'<untrusted_data source="{source}" id="{item_id}">\n{sanitized}\n</untrusted_data>'


def sanitize_untrusted(text: str, max_length: int = 500) -> str:
    """Sanitize free-text database comments before prompt inclusion."""
    if not text:
        return ""
    # Strip dangerous characters, delimiter tags, and limit length
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    cleaned = re.sub(r"<\/?untrusted_data[^>]*>", "", cleaned)
    return cleaned[:max_length]
