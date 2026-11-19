"""Personally Identifiable Information (PII) masking and pseudonymization.

Purpose:
    Enforces privacy controls and redactions (Threat T6).
    Applies regex masking for Brazilian CPFs, phones, emails, and Luhn credit cards.
    Provides deterministic HMAC-based pseudonymization for customer identifiers.
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import re
from typing import Any, Dict, List
from ontoagent.config import get_settings
from ontoagent.ontology.models import Ontology


@dataclass
class MaskedText:
    """Masked text along with mapping of placeholders to original tokens."""
    text: str
    redactions: Dict[str, str] = field(default_factory=dict)


EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_REGEX = re.compile(r"(?:\+55\s?)?(?:\(?\d{2}\)?\s?)?(?:9?\d{4}[-\s]?\d{4})")
CPF_REGEX = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


def is_luhn_valid(number_str: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    digits = [int(c) for c in number_str if c.isdigit()]
    if len(digits) < 13 or len(digits) > 16:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            doubled = d * 2
            checksum += doubled - 9 if doubled > 9 else doubled
        else:
            checksum += d
    return checksum % 10 == 0


def mask_text(text: str) -> MaskedText:
    """Scan and replace PII tokens (emails, phones, CPFs, cards) with numbered placeholders."""
    if not text:
        return MaskedText(text="")

    redactions: Dict[str, str] = {}
    counters = {"EMAIL": 1, "PHONE": 1, "CPF": 1, "CARD": 1}

    def replace_email(match: re.Match) -> str:
        token = f"[EMAIL_{counters['EMAIL']}]"
        counters["EMAIL"] += 1
        val = match.group(0)
        redactions[token] = val
        return token

    def replace_phone(match: re.Match) -> str:
        token = f"[PHONE_{counters['PHONE']}]"
        counters["PHONE"] += 1
        val = match.group(0)
        redactions[token] = val
        return token

    def replace_cpf(match: re.Match) -> str:
        token = f"[CPF_{counters['CPF']}]"
        counters["CPF"] += 1
        val = match.group(0)
        redactions[token] = val
        return token

    def replace_card(match: re.Match) -> str:
        val = match.group(0)
        if is_luhn_valid(val):
            token = f"[CARD_{counters['CARD']}]"
            counters["CARD"] += 1
            redactions[token] = val
            return token
        return val

    masked = EMAIL_REGEX.sub(replace_email, text)
    masked = CPF_REGEX.sub(replace_cpf, masked)
    masked = CARD_REGEX.sub(replace_card, masked)
    masked = PHONE_REGEX.sub(replace_phone, masked)

    return MaskedText(text=masked, redactions=redactions)


def pseudonymize_id(value: str, kind: str = "CUST") -> str:
    """Compute stable HMAC-based pseudonymous token for person IDs."""
    if not value:
        return ""
    secret = get_settings().pseudonym_secret.encode("utf-8")
    digest = hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return f"{kind}_{digest.upper()}"


def mask_rows(rows: List[Dict[str, Any]], onto: Ontology, role: str) -> List[Dict[str, Any]]:
    """Mask PII columns and pseudonymize customer identifiers in database results."""
    masked_rows = []
    for row in rows:
        new_row = dict(row)
        for k, v in row.items():
            if v is None:
                continue
            lower_k = k.lower()
            if "customer_id" in lower_k or "customer_unique_id" in lower_k:
                new_row[k] = pseudonymize_id(str(v), kind="CUST")
            elif lower_k in ("email", "phone", "cpf"):
                new_row[k] = f"[{k.upper()}_MASKED]"
            elif isinstance(v, str):
                # Text masking for potential embedded PII
                masked_res = mask_text(v)
                new_row[k] = masked_res.text
        masked_rows.append(new_row)
    return masked_rows
