"""Deterministic synthetic PII generator.

Purpose:
    Generates realistic Brazilian Portuguese PII (email, phone, CPF)
    seeded deterministically from customer_unique_id.
    Ensures identical fake attributes across runs for reproducible testing.
"""

import hashlib
import random
from typing import Dict
from faker import Faker

_FAKER = Faker("pt_BR")


def generate_synthetic_pii(customer_unique_id: str) -> Dict[str, str]:
    """Generate deterministic synthetic CPF, phone, and email for a customer.

    Args:
        customer_unique_id: Canonical person identifier.

    Returns:
        Dict with keys: 'email', 'phone', 'cpf'.
    """
    # Create stable integer seed from sha256 of customer_unique_id
    seed_int = int(hashlib.sha256(customer_unique_id.encode("utf-8")).hexdigest(), 16) % (2**32)
    random.seed(seed_int)
    _FAKER.seed_instance(seed_int)

    # Generate fake CPF, phone, email
    cpf = _FAKER.cpf()
    phone = _FAKER.phone_number()
    clean_id = customer_unique_id[:8]
    email = f"user_{clean_id}@{_FAKER.free_email_domain()}"

    return {
        "cpf": cpf,
        "phone": phone,
        "email": email,
    }
