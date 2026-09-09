"""AES-256-GCM Authenticated Encryption Demonstration.

The product deliberately calls this a *demonstration*: it shows a standard
authenticated cipher round-tripping and detecting tampering. It does not
implement key management, key rotation, HSM custody or transport security, and
nothing in the codebase may describe it as "military-grade".
"""

from __future__ import annotations

import base64

import pytest

from app.core.errors import ValidationError
from app.services.crypto_service import (
    ALGORITHM,
    DEMO_LABEL,
    DEMO_NOTICE,
    KEY_BYTES,
    NONCE_BYTES,
    CryptoDemoService,
    derive_demo_key,
)


def test_algorithm_and_parameter_sizes_are_the_documented_ones() -> None:
    assert ALGORITHM == "AES-256-GCM"
    assert KEY_BYTES == 32
    assert NONCE_BYTES == 12


def test_demo_is_labelled_honestly_and_never_as_military_grade() -> None:
    assert DEMO_LABEL == "Authenticated Encryption Demonstration"
    combined = f"{DEMO_LABEL} {DEMO_NOTICE}".lower()
    assert "military-grade" not in combined
    assert "military grade" not in combined
    assert "demonstration" in combined


def test_round_trip_recovers_the_plaintext() -> None:
    result = CryptoDemoService.encrypt("Casualty at grid 34/51, evac requested.")
    recovered = CryptoDemoService.decrypt(result.ciphertext_b64, result.nonce_b64, result.key_b64)
    assert recovered == "Casualty at grid 34/51, evac requested."


def test_ciphertext_carries_the_16_byte_gcm_tag() -> None:
    result = CryptoDemoService.encrypt("abcdefghij")
    assert result.plaintext_length == 10
    assert result.ciphertext_length == 10 + 16
    assert result.tag_bytes == 16


def test_key_and_nonce_are_the_right_length() -> None:
    result = CryptoDemoService.encrypt("hello")
    assert len(base64.b64decode(result.key_b64)) == KEY_BYTES
    assert len(base64.b64decode(result.nonce_b64)) == NONCE_BYTES


def test_nonces_are_never_reused_across_calls() -> None:
    nonces = {CryptoDemoService.encrypt("same message").nonce_b64 for _ in range(50)}
    assert len(nonces) == 50


def test_identical_plaintext_yields_different_ciphertext() -> None:
    a = CryptoDemoService.encrypt("identical")
    b = CryptoDemoService.encrypt("identical")
    assert a.ciphertext_b64 != b.ciphertext_b64


def test_unicode_survives_the_round_trip() -> None:
    message = "Alerte: SpO₂ 78 % — évacuation immédiate ❄"
    result = CryptoDemoService.encrypt(message)
    assert (
        CryptoDemoService.decrypt(result.ciphertext_b64, result.nonce_b64, result.key_b64)
        == message
    )


def test_associated_data_is_authenticated() -> None:
    result = CryptoDemoService.encrypt("payload", aad="personnel:SNOWCAT-14")
    assert (
        CryptoDemoService.decrypt(
            result.ciphertext_b64, result.nonce_b64, result.key_b64, "personnel:SNOWCAT-14"
        )
        == "payload"
    )
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt(
            result.ciphertext_b64, result.nonce_b64, result.key_b64, "personnel:OTHER"
        )


def test_tampered_ciphertext_is_rejected() -> None:
    result = CryptoDemoService.encrypt("do not alter this")
    raw = bytearray(base64.b64decode(result.ciphertext_b64))
    raw[3] ^= 0xFF
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt(
            base64.b64encode(bytes(raw)).decode(), result.nonce_b64, result.key_b64
        )


def test_wrong_key_is_rejected() -> None:
    result = CryptoDemoService.encrypt("secret")
    other = CryptoDemoService.encrypt("secret")
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt(result.ciphertext_b64, result.nonce_b64, other.key_b64)


def test_wrong_nonce_is_rejected() -> None:
    result = CryptoDemoService.encrypt("secret")
    other = CryptoDemoService.encrypt("secret")
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt(result.ciphertext_b64, other.nonce_b64, result.key_b64)


@pytest.mark.parametrize(
    ("key_b64", "nonce_b64"),
    [
        (base64.b64encode(b"short").decode(), base64.b64encode(b"0" * 12).decode()),
        (base64.b64encode(b"0" * 32).decode(), base64.b64encode(b"bad").decode()),
    ],
)
def test_malformed_key_or_nonce_sizes_are_rejected(key_b64: str, nonce_b64: str) -> None:
    result = CryptoDemoService.encrypt("secret")
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt(result.ciphertext_b64, nonce_b64, key_b64)


def test_non_base64_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CryptoDemoService.decrypt("not base64!!", "also not", "nope")


def test_empty_plaintext_is_rejected_with_a_helpful_message() -> None:
    with pytest.raises(ValidationError):
        CryptoDemoService.encrypt("")


def test_oversized_plaintext_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CryptoDemoService.encrypt("x" * 100_000)


def test_roundtrip_helper_reports_measured_results() -> None:
    payload = CryptoDemoService.roundtrip("Third Eye status: nominal")
    assert payload["roundtrip_ok"] is True
    assert payload["tamper_test"]["detected"] is True
    assert payload["ciphertext_length"] > 0
    assert payload["key_b64"]
    assert payload["tag_bytes"] == 16


def test_key_derivation_is_deterministic_for_a_given_salt() -> None:
    key_a, salt = derive_demo_key("a-demo-passphrase")
    key_b, _ = derive_demo_key("a-demo-passphrase", salt)
    assert key_a == key_b
    assert len(key_a) == KEY_BYTES
    key_c, _ = derive_demo_key("a-different-passphrase", salt)
    assert key_c != key_a
