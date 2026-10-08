import pytest
from pydantic import ValidationError

from semente.manifest import Manifest
from semente.guardrails.pii_gate import sanitize_json_pii
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
        "user_query": "meu email é teste@teste.com e o cpf 123.456.789-09",
        "nested_data": [
            {"id": 1, "text": "cpf falso 000.000.000-00"},
            {"id": 2, "text": "cartão 4111 1111 1111 1111"}
        ],
        "is_active": True,
        "count": 42
    }
    
    sanitized = sanitize_json_pii(raw_data)
    
    assert "teste@teste.com" not in sanitized["user_query"]
    assert "[EMAIL_OCULTO]" in sanitized["user_query"]
    assert "123.456.789-09" not in sanitized["user_query"]
    assert "[CPF_OCULTO]" in sanitized["user_query"]
    
    # Valida que o CPF falso (sem dígito verificador real) não é alterado, preservando o comportamento da gate
    assert sanitized["nested_data"][0]["text"] == "cpf falso 000.000.000-00"
    
    assert "4111 1111 1111 1111" not in sanitized["nested_data"][1]["text"]
    assert "[CARTAO_OCULTO]" in sanitized["nested_data"][1]["text"]
    
    # Valida que booleanos e inteiros foram preservados sem corromper o JSON
    assert sanitized["is_active"] is True
    assert sanitized["count"] == 42


def test_fine_tuning_export_schemas():
    valid_sft = {
        "messages": [
            {"role": "user", "content": "Quero solicitar um serviço."},
            {"role": "assistant", "content": "Como posso ajudar?"}
        ]
    }
    sft_row = SFTDatasetRow.model_validate(valid_sft)
    assert len(sft_row.messages) == 2
    assert sft_row.messages[0].role == "user"
    
    valid_dpo = {
        "prompt": "Quero solicitar um serviço.",
        "chosen": "Como posso ajudar?",
        "rejected": "Não faço isso."
    }
    dpo_row = DPODatasetRow.model_validate(valid_dpo)
    assert dpo_row.prompt == "Quero solicitar um serviço."
    assert dpo_row.chosen == "Como posso ajudar?"
    
    # Valida a restrição de tamanho mínimo da lista de mensagens (min_length=1)
    with pytest.raises(ValidationError):
        SFTDatasetRow.model_validate({"messages": []})