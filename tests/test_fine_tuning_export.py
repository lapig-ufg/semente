import pytest
from pydantic import ValidationError

from semente.manifest import Manifest
from semente.guardrails import CardGuardrail, EmailGuardrail, GuardrailChain
from semente.schemas.fine_tuning import SFTDatasetRow, DPODatasetRow


def test_manifest_feedback_config(tmp_path):
    manifest_file = tmp_path / "semente.yaml"
    
    manifest_file.write_text("name: test-app\nfeatures:\n  feedback: true", encoding="utf-8")
    m1 = Manifest.load(manifest_file)
    assert m1.features["feedback"].enable is True
    assert m1.features["feedback"].window_size == 5

    manifest_file.write_text("name: test-app\nfeatures:\n  feedback:\n    enable: true\n    window_size: 10", encoding="utf-8")
    m2 = Manifest.load(manifest_file)
    assert m2.features["feedback"].enable is True
    assert m2.features["feedback"].window_size == 10


def test_json_pii_sanitizer():
    raw_data = {
        "user_query": "my email is teste@teste.com and card 4111 1111 1111 1111",
        "nested_data": [
            {"id": 1, "text": "fake cpf 000.000.000-00"},
            {"id": 2, "text": "card 4570 7318 2800 8591"}
        ],
        "is_active": True,
        "count": 42
    }

    sanitized = GuardrailChain([EmailGuardrail(), CardGuardrail()]).sanitize_json(raw_data)

    assert "teste@teste.com" not in sanitized["user_query"]
    assert "[EMAIL_HIDDEN]" in sanitized["user_query"]

    # Validates that a bare number is not changed — the universal guards cover
    # e-mail and Luhn-valid cards only (documents are domain guardrails).
    assert sanitized["nested_data"][0]["text"] == "fake cpf 000.000.000-00"

    assert "4111 1111 1111 1111" not in sanitized["user_query"]
    assert "[CARD_HIDDEN]" in sanitized["nested_data"][1]["text"]

    # Validates that booleans and integers were preserved without corrupting the JSON
    assert sanitized["is_active"] is True
    assert sanitized["count"] == 42


def test_fine_tuning_export_schemas():
    valid_sft = {
        "messages": [
            {"role": "user", "content": "I want to request a service."},
            {"role": "assistant", "content": "How can I help?"}
        ]
    }
    sft_row = SFTDatasetRow.model_validate(valid_sft)
    assert len(sft_row.messages) == 2
    assert sft_row.messages[0].role == "user"
    
    valid_dpo = {
        "prompt": "I want to request a service.",
        "chosen": "How can I help?",
        "rejected": "I don't do that."
    }
    dpo_row = DPODatasetRow.model_validate(valid_dpo)
    assert dpo_row.prompt == "I want to request a service."
    assert dpo_row.chosen == "How can I help?"
    
    # Validates the minimum-length constraint of the messages list (min_length=1)
    with pytest.raises(ValidationError):
        SFTDatasetRow.model_validate({"messages": []})