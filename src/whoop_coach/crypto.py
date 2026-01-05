"""Cryptographic utilities for token encryption."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet

from whoop_coach.config import get_settings


def get_fernet_key(secret: str) -> bytes:
    """Derive a 32-byte Fernet key from secret using SHA256."""
    key_bytes = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(key_bytes)


def get_fernet() -> Fernet:
    """Get Fernet instance with derived key."""
    settings = get_settings()
    key = get_fernet_key(settings.SECRET_KEY)
    return Fernet(key)


def encrypt_tokens(tokens: dict) -> str:
    """Encrypt tokens dictionary to string."""
    fernet = get_fernet()
    json_bytes = json.dumps(tokens).encode()
    encrypted = fernet.encrypt(json_bytes)
    return encrypted.decode()


def decrypt_tokens(encrypted: str) -> dict:
    """Decrypt tokens string to dictionary."""
    fernet = get_fernet()
    decrypted = fernet.decrypt(encrypted.encode())
    return json.loads(decrypted.decode())
