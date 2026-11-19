"""Unit tests for PII masking and HMAC pseudonymization (Threat T6)."""

from ontoagent.guards.pii import mask_rows, mask_text, pseudonymize_id


def test_mask_emails_and_phones():
    text = "Please reach out to alice@example.com or call +55 11 98765-4321 regarding the refund."
    res = mask_text(text)
    assert "[EMAIL_1]" in res.text
    assert "alice@example.com" not in res.text
    assert "[PHONE_1]" in res.text
    assert "98765-4321" not in res.text


def test_mask_cpf():
    text = "Customer CPF registration number is 123.456.789-00."
    res = mask_text(text)
    assert "[CPF_1]" in res.text
    assert "123.456.789-00" not in res.text


def test_pseudonymization_is_deterministic():
    id_1 = "cust_abc_123"
    token_a = pseudonymize_id(id_1)
    token_b = pseudonymize_id(id_1)
    assert token_a == token_b
    assert token_a.startswith("CUST_")

    id_2 = "cust_xyz_999"
    token_c = pseudonymize_id(id_2)
    assert token_a != token_c


def test_mask_rows(ontology):
    rows = [
        {
            "customer_id": "cust_111",
            "email": "secret@victim.com",
            "phone": "11988887777",
            "city": "Sao Paulo",
            "order_value": "150.00"
        }
    ]
    masked = mask_rows(rows, onto=ontology, role="analyst")
    assert len(masked) == 1
    assert masked[0]["customer_id"].startswith("CUST_")
    assert masked[0]["email"] == "[EMAIL_MASKED]"
    assert masked[0]["city"] == "Sao Paulo"
