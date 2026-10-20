"""PII (personal data) detection at the ingestion layer.

Brings together deterministic detectors (regex + check-digit validation)
and an intent layer. Instead of blocking the whole message, the sensitive
data is replaced with a marker — the rest of the user's request goes through.

External interface:
    detecta_cpf(text)        -- True if the text contains a valid CPF.
    detecta_cnpj(text)       -- True if the text contains a valid CNPJ.
    detecta_cartao(text)     -- True if the text contains a valid card number.
    detecta_email(text)      -- True if the text contains an e-mail address.
    detecta_rg(text)         -- True if the text contains an RG in the punctuated format.
    check_pii(text)          -- list of the PII types found (empty if clean).
    redigir_pii(text)        -- replaces personal data with markers.
    mascarar_pii(text)       -- replaces PII with [hidden], for safe logs.
"""

import re
from typing import Callable, Dict, List, Tuple

# =====================================================================
# Layer 0 — Exclusion of known scope
# =====================================================================
# Before scanning for PII, we remove from the text the identifiers that
# belong to the system itself.
#
# Reason: the check digit is a weak signal — about 1 in every 100 random
# sequences of 11 or 14 digits passes by chance (and 1 in 9 on the card
# Luhn). So any long identifier, such as the CAR with its 32 hexadecimal
# characters, sooner or later contains a stretch that looks like a valid
# document. Measured: 1 in ~3,000 CAR codes was being blocked wrongly.
#
# Hardening the regex does not solve this class of problem — it only
# reduces the frequency. Removing the stretch before the scan, the
# detector never gets to see it.

# CAR (Rural Environmental Registry): state (UF) code + municipality code + identifier.
# E.g.: GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9
# Domain-flavored, but engine-safe: domains may extend _KNOWN_SCOPE
# with their own long identifiers.
_CAR_RE = re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9]{32}\b", re.IGNORECASE)
_KNOWN_SCOPE = [
    _CAR_RE,
]


def remover_escopo_conhecido(text: str) -> str:
    """Removes the system's own identifiers before the PII scan.

    Replaces with a space (and not with an empty string) on purpose: without
    that, whatever was on both sides glues together and can form a number
    that did not exist in the original text.
    """
    for rx in _KNOWN_SCOPE:
        text = rx.sub(" ", text)
    return text

_NB_L = r"(?<!\d)(?<!\d[.,])"
_NB_R = r"(?!\d)(?![.,]\d)"

# --- CPF ---
# Three accepted forms, always complete — never half of it:
#   dotted   123.456.789-01
#   spaced   123 456 789 01
#   raw      12345678901
# The spaced form exists because that's how many people type, and without
# it the CPF was only caught by the intent layer (it depended on the word
# "cpf" being nearby).
_CPF_RE = re.compile(
    _NB_L
    + r"(?:\d{3}\.\d{3}\.\d{3}-\d{2}|\d{3} \d{3} \d{3} \d{2}|\d{11})"
    + _NB_R
)


def _valid_cpf(digits: str) -> bool:
    """Validates the two check digits of a CPF (receives digits only)."""
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    # 1st check digit: weights 10..2 over the first 9 digits.
    total = sum(int(digits[i]) * (10 - i) for i in range(9))
    remainder = (total * 10) % 11
    if remainder == 10:
        remainder = 0
    if remainder != int(digits[9]):
        return False

    # 2nd check digit: weights 11..2 over the first 10 digits.
    total = sum(int(digits[i]) * (11 - i) for i in range(10))
    remainder = (total * 10) % 11
    if remainder == 10:
        remainder = 0
    return remainder == int(digits[10])


def detecta_cpf(text: str) -> bool:
    """Returns True if the text contains at least one valid CPF."""
    for candidate in _CPF_RE.findall(text):
        digits = re.sub(r"\D", "", candidate)
        if _valid_cpf(digits):
            return True
    return False

# --- CNPJ ---
# Same three forms as the CPF:
#   dotted   12.345.678/0001-90
#   spaced   12 345 678 0001 90
#   raw      12345678000190
_CNPJ_RE = re.compile(
    _NB_L
    + r"(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{2} \d{3} \d{3} \d{4} \d{2}|\d{14})"
    + _NB_R
)

# Official weights for computing the CNPJ check digits.
_CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_WEIGHTS_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def _valid_cnpj(digits: str) -> bool:
    """Validates the two check digits of a CNPJ (receives digits only)."""
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    # 1st check digit: weighted sum of the first 12 digits.
    total = sum(int(digits[i]) * _CNPJ_WEIGHTS_1[i] for i in range(12))
    remainder = total % 11
    dv1 = 0 if remainder < 2 else 11 - remainder
    if dv1 != int(digits[12]):
        return False

    # 2nd check digit: weighted sum of the first 13 digits.
    total = sum(int(digits[i]) * _CNPJ_WEIGHTS_2[i] for i in range(13))
    remainder = total % 11
    dv2 = 0 if remainder < 2 else 11 - remainder
    return dv2 == int(digits[13])


def detecta_cnpj(text: str) -> bool:
    """Returns True if the text contains at least one valid CNPJ."""
    for candidate in _CNPJ_RE.findall(text):
        digits = re.sub(r"\D", "", candidate)
        if _valid_cnpj(digits):
            return True
    return False

# --- Credit card ---
# Two forms, always complete: visual grouping (4-4-4-1..4, with space or
# dash) OR a real brand prefix (4x Visa, 5[1-5]x Mastercard, 3[47]x
# Amex, 6(011|5xx) Discover). A raw 13-16 digit number + Luhn is noise —
# no longer detected (1 in 9 sequences passes by chance).
_CARTAO_RE = re.compile(
    _NB_L
    + r"(?:"
    r"\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}"
    r"|4\d{12}(?:\d{3})?"
    r"|5[1-5]\d{14}"
    r"|3[47]\d{13}"
    r"|6(?:011|5\d{2})\d{12}"
    r")"
    + _NB_R
)


def _luhn(digits: str) -> bool:
    """Validates a card number using the Luhn algorithm (receives digits only)."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:          # doubles alternating digits, right to left
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def detecta_cartao(text: str) -> bool:
    """Returns True if the text contains a valid card number (Luhn)."""
    for candidate in _CARTAO_RE.findall(text):
        digits = re.sub(r"\D", "", candidate)
        if 13 <= len(digits) <= 16 and _luhn(digits):
            return True
    return False

# --- E-mail ---
# Standard format: user@domain.extension
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def detecta_email(text: str) -> bool:
    """Returns True if the text contains an e-mail address."""
    return bool(_EMAIL_RE.search(text))


# --- RG (punctuated format) ---
# RG has no national pattern, so we only cover the clearly written format
# (12.345.678-9). A raw number is NOT included, to avoid needlessly blocking
# values/amounts.
_RG_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}-[\dxX]\b")


def detecta_rg(text: str) -> bool:
    """Returns True if the text contains an RG in the punctuated format (e.g.: 12.345.678-9)."""
    return bool(_RG_RE.search(text))


# --- Document intent (catches a fake/invalid number too) ---
# If the user mentions the document and appends a number (e.g.: "my cpf is 322443"),
# we detect it even if the number is not valid — the intent is already to send the data.
_INTENT_RE = {
    "CPF":    re.compile(r"\bcpf\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\bcpf\b", re.IGNORECASE),
    "CNPJ":   re.compile(r"\bcnpj\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\bcnpj\b", re.IGNORECASE),
    "RG":     re.compile(r"\brg\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\brg\b", re.IGNORECASE),
    "card":   re.compile(r"\b(?:card|cart[ãa]o)\b.{0,12}?\d{3,}|\d{3,}.{0,12}?\b(?:card|cart[ãa]o)\b", re.IGNORECASE),
}

# --- Orchestrator ---

_DETECTORS: Dict[str, Callable[[str], bool]] = {
    "CPF": detecta_cpf,
    "CNPJ": detecta_cnpj,
    "card": detecta_cartao,
    "email": detecta_email,
    "RG": detecta_rg,
}


def check_pii(text: str) -> List[str]:
    """PII types present in the text: valid documents + clear intent to send a document."""

    text = remover_escopo_conhecido(text)

    types = [kind for kind, detector in _DETECTORS.items() if detector(text)]

    # Intent layer: mentioned "cpf/cnpj/rg" and appended a number → catches invalid ones too.
    for kind, rx in _INTENT_RE.items():
        if kind not in types and rx.search(text):
            types.append(kind)
    return types

# --- Redaction ---
# Instead of refusing the whole message, replaces only the sensitive data
# with a marker and lets the rest go through. That way the user doesn't
# lose the requests made alongside, and the data never reaches the agent
# or the database.
_MARKERS = {
    "CPF": "[CPF_HIDDEN]",
    "CNPJ": "[CNPJ_HIDDEN]",
    "card": "[CARD_HIDDEN]",
    "RG": "[RG_HIDDEN]",
    "email": "[EMAIL_HIDDEN]",
}


def redigir_pii(text: str) -> Tuple[str, List[str]]:
    """Replaces personal data with markers.

    Returns (redacted_text, removed_types). If nothing was found, returns
    the original text and an empty list.
    """
    if not text:
        return text, []

    # Known-scope spans (CAR) are untouchable: a CAR may contain, by chance,
    # a sequence that validates as a document.
    protected_spans = [mt.span() for rx in _KNOWN_SCOPE for mt in rx.finditer(text)]

    def _is_protected(start: int, end: int) -> bool:
        return any(start < p_end and end > p_start for p_start, p_end in protected_spans)

    findings = []  # (start, end, type)
    for kind, rx in (
        ("CPF", _CPF_RE),
        ("CNPJ", _CNPJ_RE),
        ("card", _CARTAO_RE),
        ("RG", _RG_RE),
        ("email", _EMAIL_RE),
    ):
        for mt in rx.finditer(text):
            start, end = mt.span()
            if _is_protected(start, end):
                continue
            digits = re.sub(r"\D", "", mt.group())
            # CPF, CNPJ and card only count if the check digit matches.
            # RG and email have no check digit: the format itself is the evidence.
            if kind == "CPF" and not _valid_cpf(digits):
                continue
            if kind == "CNPJ" and not _valid_cnpj(digits):
                continue
            if kind == "card" and not (13 <= len(digits) <= 16 and _luhn(digits)):
                continue
            findings.append((start, end, kind))

    if not findings:
        return text, []

    # Replace back to front so the indexes don't shift,
    # discarding overlaps between detectors.
    findings.sort(key=lambda a: a[0])
    clean, types, last_start = text, [], len(text)
    for start, end, kind in reversed(findings):
        if end > last_start:
            continue
        clean = clean[:start] + _MARKERS[kind] + clean[end:]
        types.append(kind)
        last_start = start

    return clean, sorted(set(types))


# --- Masking (for safe logs) ---

_MASKING_RES = [_CPF_RE, _CNPJ_RE, _CARTAO_RE, _EMAIL_RE, _RG_RE] + list(_INTENT_RE.values())


def mascarar_pii(text: str) -> str:
    """Replaces any span that looks like PII with [hidden] — for safe logs."""
    for rx in _MASKING_RES:
        text = rx.sub("[hidden]", text)
    return text

def sanitize_json_pii(data):
    """
    Recursively sanitizes string values within JSON-like structures (dicts, lists)
    using the redigir_pii function, preserving the original data structure.
    """
    if isinstance(data, dict):
        return {key: sanitize_json_pii(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [sanitize_json_pii(item) for item in data]
    elif isinstance(data, str):
        sanitized_text, _ = redigir_pii(data)
        return sanitized_text
    return data