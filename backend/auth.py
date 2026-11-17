"""Utilidades de autenticación y sesiones firmadas para el administrador."""

import base64
import hashlib
import hmac
import json
import secrets
import time


PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Genera un hash PBKDF2-SHA256 seguro con sal aleatoria."""
    actual_salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        actual_salt,
        PBKDF2_ITERATIONS,
    )
    return f"{actual_salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica una contraseña contra su hash almacenado en tiempo constante."""
    if ":" not in stored_hash:
        return False
    salt_hex, expected_hex = stored_hash.split(":", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hash_password(password, salt).split(":", 1)[1]
    return hmac.compare_digest(candidate, expected_hex)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_session_token(username: str, secret: str, ttl_seconds: int = 86_400) -> str:
    """Crea un token de sesión firmado con HMAC-SHA256 y expiración."""
    payload = {
        "sub": username,
        "exp": int(time.time()) + ttl_seconds,
    }
    encoded_payload = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_b64_encode(signature)}"


def verify_session_token(token: str, secret: str) -> str | None:
    """Valida firma y expiración del token; devuelve el usuario o None."""
    if not token or "." not in token:
        return None
    encoded_payload, encoded_sig = token.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_sig = _b64_decode(encoded_sig)
    except Exception:
        return None
    if not hmac.compare_digest(actual_sig, expected_sig):
        return None
    try:
        payload = json.loads(_b64_decode(encoded_payload).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload.get("sub")

