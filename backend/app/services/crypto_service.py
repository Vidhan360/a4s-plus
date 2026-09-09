"""Authenticated Encryption Demonstration.

Scope and honest framing
------------------------
This module exists to *demonstrate* authenticated encryption interactively. It
uses AES-256-GCM from the ``cryptography`` library (which wraps OpenSSL). No
cryptographic primitive is implemented by hand.

It is explicitly **not**:

* the mechanism protecting data in this application (that is TLS in transit and
  PostgreSQL at rest);
* "military-grade encryption" — that phrase is marketing, not a specification,
  and is deliberately not used anywhere in this project;
* a key-management system. Demo keys are derived per request or per session and
  are never persisted.

Three separate concerns are kept distinct in this codebase:

1. **Application authentication** — ``app/core/security.py`` (Argon2id + JWT).
2. **Transport security** — TLS, terminated by the deployment's reverse proxy.
3. **Demonstration encryption** — this module, for the Security Monitor UI.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.errors import ValidationError

ALGORITHM = "AES-256-GCM"
KEY_BYTES = 32  # 256-bit key
NONCE_BYTES = 12  # 96-bit nonce, the GCM-recommended size
MAX_PLAINTEXT_BYTES = 4096

DEMO_LABEL = "Authenticated Encryption Demonstration"
DEMO_NOTICE = (
    "This panel demonstrates AES-256-GCM authenticated encryption using the "
    "'cryptography' library. It is a teaching aid: keys are ephemeral and are "
    "never persisted. Application data is protected by TLS in transit, not by "
    "this demonstration."
)


@dataclass
class EncryptionResult:
    algorithm: str
    ciphertext_b64: str
    nonce_b64: str
    key_b64: str
    aad: str | None
    plaintext_length: int
    ciphertext_length: int
    #: GCM appends a 16-byte authentication tag to the ciphertext.
    tag_bytes: int = 16

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "label": DEMO_LABEL,
            "notice": DEMO_NOTICE,
            "ciphertext_b64": self.ciphertext_b64,
            "nonce_b64": self.nonce_b64,
            "key_b64": self.key_b64,
            "aad": self.aad,
            "plaintext_length": self.plaintext_length,
            "ciphertext_length": self.ciphertext_length,
            "tag_bytes": self.tag_bytes,
            "key_bits": KEY_BYTES * 8,
            "nonce_bits": NONCE_BYTES * 8,
        }


def derive_demo_key(passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    """Derive a demo key from a passphrase with HKDF-SHA256.

    HKDF is appropriate here because the demo passphrase is treated as
    already-high-entropy input for illustration. Real password-based key
    derivation would use Argon2id or scrypt with a high work factor; that
    distinction is stated in the UI rather than glossed over.
    """
    salt = salt or os.urandom(16)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=salt,
        info=b"a4s-plus-encryption-demonstration",
    ).derive(passphrase.encode("utf-8"))
    return key, salt


class CryptoDemoService:
    """Stateless AES-256-GCM encrypt/decrypt for the Security Monitor demo."""

    @staticmethod
    def encrypt(plaintext: str, aad: str | None = None) -> EncryptionResult:
        if not plaintext:
            raise ValidationError("Provide a message to encrypt.")
        data = plaintext.encode("utf-8")
        if len(data) > MAX_PLAINTEXT_BYTES:
            raise ValidationError(
                f"The demonstration accepts at most {MAX_PLAINTEXT_BYTES} bytes; "
                f"received {len(data)}."
            )
        key = AESGCM.generate_key(bit_length=KEY_BYTES * 8)
        nonce = os.urandom(NONCE_BYTES)
        aad_bytes = aad.encode("utf-8") if aad else None
        ciphertext = AESGCM(key).encrypt(nonce, data, aad_bytes)
        return EncryptionResult(
            algorithm=ALGORITHM,
            ciphertext_b64=base64.b64encode(ciphertext).decode(),
            nonce_b64=base64.b64encode(nonce).decode(),
            key_b64=base64.b64encode(key).decode(),
            aad=aad,
            plaintext_length=len(data),
            ciphertext_length=len(ciphertext),
        )

    @staticmethod
    def decrypt(ciphertext_b64: str, nonce_b64: str, key_b64: str, aad: str | None = None) -> str:
        try:
            ciphertext = base64.b64decode(ciphertext_b64, validate=True)
            nonce = base64.b64decode(nonce_b64, validate=True)
            key = base64.b64decode(key_b64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValidationError("ciphertext, nonce and key must all be valid base64.") from exc
        if len(key) != KEY_BYTES:
            raise ValidationError(
                f"The key must be exactly {KEY_BYTES} bytes ({KEY_BYTES * 8} bits)."
            )
        if len(nonce) != NONCE_BYTES:
            raise ValidationError(f"The nonce must be exactly {NONCE_BYTES} bytes.")
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8") if aad else None)
        except InvalidTag as exc:
            raise ValidationError(
                "Authentication failed: the ciphertext, nonce, key or "
                "associated data does not match. This is exactly the "
                "tamper-detection property that AES-GCM provides — an "
                "authenticated cipher refuses to return altered plaintext."
            ) from exc
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                "Decryption succeeded but the plaintext is not valid UTF-8."
            ) from exc

    @staticmethod
    def roundtrip(plaintext: str, aad: str | None = None) -> dict[str, Any]:
        """Encrypt then decrypt, and additionally demonstrate tamper detection."""
        result = CryptoDemoService.encrypt(plaintext, aad)
        decrypted = CryptoDemoService.decrypt(
            result.ciphertext_b64, result.nonce_b64, result.key_b64, aad
        )
        # Flip one bit in the ciphertext to show authentication catching it.
        raw = bytearray(base64.b64decode(result.ciphertext_b64))
        raw[0] ^= 0x01
        tampered_b64 = base64.b64encode(bytes(raw)).decode()
        try:
            CryptoDemoService.decrypt(tampered_b64, result.nonce_b64, result.key_b64, aad)
            tamper_detected = False
            tamper_message = "Unexpected: tampering was not detected."
        except ValidationError:
            tamper_detected = True
            tamper_message = (
                "A single flipped ciphertext bit caused authentication to fail, "
                "so no altered plaintext was returned."
            )
        return {
            **result.as_dict(),
            "decrypted": decrypted,
            "roundtrip_ok": decrypted == plaintext,
            "tamper_test": {
                "tampered_ciphertext_b64": tampered_b64,
                "detected": tamper_detected,
                "message": tamper_message,
            },
        }
