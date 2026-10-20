"""Unit tests for the PII guardrail (semente/guardrails/pii_gate.py).

They cover the deterministic detectors, format-based RG detection, the intent
layer, the orchestrator, masking, and the false-positive regressions on
geographic coordinates and CAR codes. Fully deterministic — no LLM/network.
"""

import random

import pytest

from semente.guardrails.pii_gate import (
    detecta_cpf, detecta_cnpj, detecta_cartao, detecta_email, detecta_rg,
    check_pii, mascarar_pii, redigir_pii, remover_escopo_conhecido,
)


# --- CPF ---
def test_cpf_valid_formatted():
    assert detecta_cpf("my cpf is 006.819.915-50")

def test_cpf_valid_raw():
    assert detecta_cpf("00681991550")

def test_cpf_invalid_check_digit():
    assert not detecta_cpf("111.444.777-00")

def test_cpf_not_confused_with_phone():
    assert not detecta_cpf("my phone is 62999998888")

def test_cpf_repeated():
    assert not detecta_cpf("111.111.111-11")


# --- CNPJ ---
def test_cnpj_valid():
    assert detecta_cnpj("CNPJ 27.486.358/0001-22")

def test_cnpj_valid_raw():
    assert detecta_cnpj("27486358000122")

def test_cnpj_invalid():
    assert not detecta_cnpj("11.222.333/0001-00")


# --- Card ---
def test_card_valid_luhn():
    assert detecta_cartao("card 4570 7318 2800 8591")

def test_card_invalid_luhn():
    assert not detecta_cartao("4570 7318 2800 8592")

def test_card_too_short():
    assert not detecta_cartao("the year is 2024")


# --- Email ---
def test_email_valid():
    assert detecta_email("reach me at joao.silva@gmail.com")

def test_email_without_at():
    assert not detecta_email("loose at sign without email")


# --- RG (punctuated format) ---
def test_rg_formatted():
    assert detecta_rg("my rg is 12.345.678-9")

def test_rg_raw_not_caught():
    assert not detecta_rg("I have 123456789 head of cattle")


# --- Intent (catches a fake number when the document is mentioned) ---
def test_intent_fake_cpf():
    assert "CPF" in check_pii("my cpf is 322443")

def test_intent_number_first():
    assert "CPF" in check_pii("321312 and my cpf")

def test_intent_card():
    assert "card" in check_pii("my card is 1234")

def test_intent_distant_number_not_caught():
    assert check_pii("my cpf is on file, I have 500 head") == []


# --- Orchestrator ---
def test_check_pii_multiple():
    types = check_pii("cpf 006.819.915-50 and email joao@gmail.com")
    assert "CPF" in types and "email" in types

def test_check_pii_clean():
    assert check_pii("I want to see the map of my farm") == []


# --- Masking ---
def test_masking_hides_pii():
    masked = mascarar_pii("my cpf is 006.819.915-50")
    assert "006.819.915-50" not in masked and "[hidden]" in masked

# =====================================================================
# Regression: domain identifiers are not documents
# =====================================================================
# Context (measured, not assumed):
#   - check digit of the CPF  → 1 in 103 sequences of 11 digits passes
#   - check digit of the CNPJ → 1 in 100 sequences of 14 digits passes
#   - card Luhn               → 1 in 9 sequences of 16 digits passes
#
# In other words, the validator is almost a coin flip. Any long identifier
# (high-precision coordinate, CAR code) contains, sooner or later, a stretch
# that "validates" by chance. Before the boundary guards and Layer 0:
#   - 21.6% of location pins were being blocked
#   -  0.8% of CAR codes were being blocked

# Real cases reported in the field, on CAR selection.
COORD_ONE_PROPERTY = "47,1798509°W 19,5350942°S"
COORD_TWO_PROPERTIES = "42,1343264°W 17,3386047°S"
COORD_THREE_CARS = "-52.50857591629029, -5.935149162520979"

# CAR codes that used to be false positives before Layer 0.
CAR_FALSE_POSITIVE = [
    "BA-3287819-4845970474100364E5587A1F37A75AC3",   # matched as card
    "RO-1708070-D811A2AC67B370794126616945A35974",   # matched as card
    "TO-5367207-8E7A3510FBBC929BBBB32361861437E8",   # matched as CPF
    "MS-3779009-B2F7F7C7F16D4B5BC89965149090355B",   # matched as CNPJ
    "MT-4750161-C69210318617B554911562D859B399AE",   # matched as CPF
    "GO-4237547-A56925079940F78341EA1054FF4F40B5",   # matched as CPF
]

SHOULD_NOT_BLOCK = [
    COORD_ONE_PROPERTY,
    COORD_TWO_PROPERTIES,
    COORD_THREE_CARS,
    "I want to register my property at coordinates Lat: -5.935149162520979 Long: -52.50857591629029.",
    "my farm is at -16.3107, -43.8839",
    "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "go-5212303-27057d4194f64ce3a498b90bfac2e5f9",
    "I want to merge GO-5205703-5B18B6DF441C4B7FA9444DDC127CF6C0 and GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9",
    "I have 1.234,56 hectares of pasture",
    "the total area is 1.234.567,89 hectares",
    "I produced 12345678901234 kg of silage",
    "my plot is the 987654321098765",
    "the bank slip is 34191790010104351004791020150008291070026000",
    "I bought 250 head at 2.850,00 each",
    "it rained 120 130 140 15 mm",
    "my phone is 62 99999-8888",
    "I want to see the map of my farm",
]

SHOULD_BLOCK = [
    ("my cpf is 710.768.971-18", "CPF"),
    ("71076897118", "CPF"),
    ("my cpf is 71076897118.", "CPF"),
    ("710 768 971 18", "CPF"),
    ("CNPJ 27.486.358/0001-22", "CNPJ"),
    ("27486358000122", "CNPJ"),
    ("27 486 358 0001 22", "CNPJ"),
    ("my rg is 12.345.678-9", "RG"),
    ("card 4570 7318 2800 8591", "card"),
    ("4111111111111111", "card"),
    ("reach me at joao.silva@gmail.com", "email"),
    ("my cpf is 322443", "CPF"),
]


@pytest.mark.parametrize("text", SHOULD_NOT_BLOCK)
def test_should_not_block(text):
    assert check_pii(text) == [], f"false positive in: {text}"


@pytest.mark.parametrize("text,kind", SHOULD_BLOCK)
def test_should_block(text, kind):
    assert kind in check_pii(text), f"false negative in: {text}"


@pytest.mark.parametrize("car", CAR_FALSE_POSITIVE)
def test_car_not_blocked(car):
    """Each of these was blocked before Layer 0."""
    assert check_pii(car) == []


# --- Boundary guard: a document is a whole token, not a fragment ---
def test_cpf_with_sentence_final_period():
    """The trailing sentence period must not be mistaken for a decimal separator."""
    assert detecta_cpf("my cpf is 71076897118.")


def test_cpf_inside_larger_number_not_caught():
    assert not detecta_cpf("9971076897118")


def test_cnpj_inside_larger_number_not_caught():
    assert not detecta_cnpj("123456780001957")
    assert not detecta_cnpj("9927486358000122")


def test_raw_card_without_brand_not_caught():
    """13-16 digits + Luhn is noise: 1 in 9 passes by chance."""
    assert not detecta_cartao("50857591629029")


def test_card_with_real_brand_caught():
    assert detecta_cartao("4111111111111111")


# --- Spaced format (the CPF used to be caught only by the intent layer) ---
def test_cpf_spaced_caught_without_keyword():
    assert detecta_cpf("710 768 971 18")
    assert detecta_cpf("my document is 710 768 971 18")


def test_cnpj_spaced_caught_without_keyword():
    assert detecta_cnpj("27 486 358 0001 22")


def test_spaced_invalid_not_caught():
    """One wrong digit turns it from a document into a bare number."""
    assert not detecta_cpf("710 768 971 19")


# --- Layer 0 ---
def test_layer_zero_does_not_swallow_document():
    """Removing known scope must not swallow real PII."""
    assert check_pii(remover_escopo_conhecido("my cpf is 710.768.971-18")) == ["CPF"]


def test_layer_zero_preserves_text_without_car():
    text = "I want to see the biomass of my farm"
    assert remover_escopo_conhecido(text) == text


def test_car_and_cpf_in_same_message():
    """The CAR is excluded from the scan, the CPF is still caught."""
    text = "register GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9 and my cpf is 710.768.971-18"
    assert "CPF" in check_pii(text)


# --- Statistical tests: the false positive was probabilistic ---
def test_false_positive_in_coordinates():
    """No location pin in Brazil may ever be blocked."""
    rng = random.Random(7)
    blocked = [
        t for _ in range(5000)
        for t in [f"Lat: {rng.uniform(-33.0, 5.0)} Long: {rng.uniform(-74.0, -34.0)}"]
        if check_pii(t)
    ]
    assert not blocked, f"{len(blocked)} blocked, e.g.: {blocked[:3]}"


def test_false_positive_in_car_codes():
    """Before Layer 0, ~1 in every 3,000 CARs was blocked."""
    rng = random.Random(42)
    states = ["GO", "MT", "MS", "MG", "BA", "PA", "TO", "SP", "PR", "RO"]
    blocked = []
    for _ in range(5000):
        car = (
            f"{rng.choice(states)}-{rng.randint(1000000, 9999999)}-"
            + "".join(rng.choice("0123456789ABCDEF") for _ in range(32))
        )
        if check_pii(car):
            blocked.append(car)
    assert not blocked, f"{len(blocked)} blocked, e.g.: {blocked[:3]}"


# --- Masking stays deliberately permissive ---
def test_masking_still_aggressive():
    """In logs, over-masking is cheap; under-masking is a leak."""
    assert "[hidden]" in mascarar_pii("27486358000122")
    assert "[hidden]" in mascarar_pii("my cpf is 006.819.915-50")


# --- Redaction (redigir_pii) ---
def test_redaction_cpf_keeps_the_request():
    """The request made in the same message must survive."""
    clean, types = redigir_pii("my cpf is 710.768.971-18, what is the system version?")
    assert clean == "my cpf is [CPF_HIDDEN], what is the system version?"
    assert types == ["CPF"]


def test_redaction_raw_cpf():
    clean, types = redigir_pii("71076897118")
    assert clean == "[CPF_HIDDEN]" and types == ["CPF"]


def test_redaction_multiple_pieces_in_same_message():
    clean, types = redigir_pii("cpf 006.819.915-50 and email joao@gmail.com")
    assert clean == "cpf [CPF_HIDDEN] and email [EMAIL_HIDDEN]"
    assert types == ["CPF", "email"]


def test_redaction_clean_text_returns_original():
    text = "I want to see the map of my farm"
    assert redigir_pii(text) == (text, [])


def test_redaction_empty_text():
    assert redigir_pii("") == ("", [])


def test_redaction_invalid_cpf_keeps_text():
    """With no matching check digit, it is not a document — intent is check_pii's job."""
    text = "my cpf is 111.444.777-00"
    assert redigir_pii(text) == (text, [])


def test_redaction_car_protected():
    """The CAR may by chance contain a sequence that validates — it is untouchable."""
    for car in CAR_FALSE_POSITIVE:
        assert redigir_pii(car) == (car, [])


def test_redaction_car_and_cpf_in_same_message():
    text = "register GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9 and my cpf is 710.768.971-18"
    clean, types = redigir_pii(text)
    assert "GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9" in clean
    assert "my cpf is [CPF_HIDDEN]" in clean
    assert types == ["CPF"]


def test_redaction_location_pin_untouched():
    """Behavioral regression: a high-precision coordinate is not PII."""
    text = "Lat: -5.935149162520979 Long: -52.50857591629029"
    assert redigir_pii(text) == (text, [])


def test_redaction_spaced_format():
    clean, types = redigir_pii("my document is 710 768 971 18")
    assert clean == "my document is [CPF_HIDDEN]" and types == ["CPF"]


def test_redaction_rg_and_card():
    clean, types = redigir_pii("my rg is 12.345.678-9 and the card 4570 7318 2800 8591")
    assert clean == "my rg is [RG_HIDDEN] and the card [CARD_HIDDEN]"
    assert types == ["RG", "card"]


def test_redaction_streamlit_demo_text_survives():
    """The Streamlit demo coordinate sentence is not PII and must not be altered."""
    text = """My coordinates are 2°46'32.94"S 48°31'41.74"W."""
    assert redigir_pii(text) == (text, [])


@pytest.mark.parametrize("text", SHOULD_NOT_BLOCK)
def test_should_not_redact_anything(text):
    """Nothing in the non-blocking corpus may be altered by redaction."""
    assert redigir_pii(text) == (text, [])


@pytest.mark.parametrize("text,kind", SHOULD_BLOCK)
def test_should_redact(text, kind):
    """Everything check_pii detects as real PII (valid number) is redacted."""
    clean, types = redigir_pii(text)
    if text in ("my cpf is 322443",):  # intent without a valid number: covered only by check_pii
        assert redigir_pii(text) == (text, [])
        return
    assert kind in types, f"false negative in redaction of: {text}"
    assert "[hidden]" not in clean