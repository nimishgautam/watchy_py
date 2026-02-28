"""Application-level AES-256-CBC encryption for BLE protocol.

Key derived from AUTH_TOKEN via SHA-256. Used when BLE pairing is
disabled — encrypts all message payloads before chunking.
"""

import os

try:
    from ucryptolib import aes
except ImportError:
    from cryptolib import aes  # type: ignore[import-not-found]

import uhashlib

_AES_BLOCK = 16
_MODE_CBC = 2


def derive_key(auth_token: str) -> bytes:
    """Derive 32-byte AES-256 key from AUTH_TOKEN."""
    return uhashlib.sha256(auth_token.encode("utf-8")).digest()


def _pkcs7_pad(data: bytes) -> bytes:
    """PKCS7 pad data to AES block boundary."""
    pad_len = _AES_BLOCK - (len(data) % _AES_BLOCK)
    if pad_len == 0:
        pad_len = _AES_BLOCK
    return data + bytes([pad_len] * pad_len)


def _pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    if len(data) < _AES_BLOCK:
        raise ValueError("ciphertext too short")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > _AES_BLOCK:
        raise ValueError("invalid padding")
    for i in range(pad_len):
        if data[-(i + 1)] != pad_len:
            raise ValueError("invalid padding")
    return data[:-pad_len]


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt plaintext with AES-256-CBC. Returns IV || ciphertext."""
    iv = os.urandom(_AES_BLOCK)
    padded = _pkcs7_pad(plaintext)
    cipher = aes(key, _MODE_CBC, iv)
    ciphertext = cipher.encrypt(padded)
    return iv + ciphertext


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    """Decrypt IV || ciphertext. Returns plaintext."""
    if len(ciphertext) < _AES_BLOCK * 2:
        raise ValueError("ciphertext too short for IV + at least one block")
    iv = ciphertext[:_AES_BLOCK]
    ct = ciphertext[_AES_BLOCK:]
    cipher = aes(key, _MODE_CBC, iv)
    padded = cipher.decrypt(ct)
    return _pkcs7_unpad(padded)
