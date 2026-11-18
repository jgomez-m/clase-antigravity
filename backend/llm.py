"""Módulo de integración con proveedores de LLM para el agente conversacional.

Soporta: OpenAI, Anthropic (Claude), Google Gemini y OpenRouter.
Todas las llamadas se hacen con urllib.request (sin pip).
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import ssl
import subprocess
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Any


# ══════════════════════════════════════════════════════════════
# Configuración de proveedores
# ══════════════════════════════════════════════════════════════
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "url": "https://api.openai.com/v1/chat/completions",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "name": "Anthropic (Claude)",
        "url": "https://api.anthropic.com/v1/messages",
        "models": [
            "claude-sonnet-4-20250514",
            "claude-3-5-haiku-20241022",
            "claude-opus-4-20250514",
        ],
        "default_model": "claude-sonnet-4-20250514",
    },
    "gemini": {
        "name": "Google (Gemini)",
        "url_template": (
            "https://generativelanguage.googleapis.com"
            "/v1beta/models/{model}:generateContent"
        ),
        "models": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "default_model": "gemini-2.0-flash",
    },
    "openrouter": {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": [
            "meta-llama/llama-3.1-70b-instruct",
            "google/gemini-flash-1.5",
            "anthropic/claude-3.5-sonnet",
        ],
        "default_model": "meta-llama/llama-3.1-70b-instruct",
    },
}

DEFAULT_SYSTEM_PROMPT = (
    "Eres el asistente virtual de JG Inmobiliaria, una empresa de bienes raíces "
    "en Medellín y Bogotá, Colombia.\n"
    "Tu objetivo es ayudar a los clientes a encontrar su inmueble ideal, responder "
    "preguntas sobre el catálogo, precios, ubicaciones, proceso de separación y requisitos.\n\n"
    "Reglas:\n"
    "- Responde siempre en español de manera amable y profesional.\n"
    "- Basa tus respuestas ÚNICAMENTE en la información del catálogo y la base de conocimiento.\n"
    "- Si no tienes la información, sugiere contactar al equipo por WhatsApp o email.\n"
    "- Nunca inventes precios, direcciones o datos que no estén en el contexto.\n"
    "- Puedes recomendar inmuebles según las preferencias del cliente "
    "(ciudad, presupuesto, habitaciones)."
)


# ══════════════════════════════════════════════════════════════
# Cifrado / descifrado de API keys
# ══════════════════════════════════════════════════════════════
_KDF_SALT = b"jg-inmobiliaria-llm-key-v1"
_KDF_ITERATIONS = 100_000
_NONCE_SIZE = 16
_TAG_SIZE = 32


def _derive_key(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _KDF_SALT, _KDF_ITERATIONS)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Genera un flujo pseudoaleatorio HMAC-SHA256 en modo contador."""
    blocks = []
    for counter in range((length + 31) // 32):
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
    return b"".join(blocks)[:length]


def encrypt_api_key(api_key: str, secret: str) -> str:
    """Cifra la API key (nonce aleatorio + keystream HMAC + etiqueta de integridad)."""
    key = _derive_key(secret)
    nonce = secrets.token_bytes(_NONCE_SIZE)
    plain = api_key.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(plain, _keystream(key, nonce, len(plain))))
    tag = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")


def decrypt_api_key(encrypted: str, secret: str) -> str:
    """Descifra la API key. Lanza ValueError si el dato fue alterado o el secret cambió."""
    key = _derive_key(secret)
    try:
        raw = base64.urlsafe_b64decode(encrypted.encode("ascii"))
    except Exception as exc:
        raise ValueError("API key cifrada con formato inválido.") from exc
    if len(raw) < _NONCE_SIZE + _TAG_SIZE:
        raise ValueError("API key cifrada con formato inválido.")
    nonce, cipher, tag = raw[:_NONCE_SIZE], raw[_NONCE_SIZE:-_TAG_SIZE], raw[-_TAG_SIZE:]
    expected = hmac.new(key, nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("No se pudo descifrar la API key (¿cambió SESSION_SECRET?).")
    plain = bytes(a ^ b for a, b in zip(cipher, _keystream(key, nonce, len(cipher))))
    return plain.decode("utf-8")


def mask_api_key(api_key: str) -> str:
    """Muestra solo los últimos 4 caracteres de la key."""
    if len(api_key) <= 4:
        return "••••"
    return "••••" + api_key[-4:]


# ══════════════════════════════════════════════════════════════
# Extracción de texto de PDFs (sin pip)
# ══════════════════════════════════════════════════════════════
def extract_pdf_text(filepath: str | Path) -> str:
    """Intenta extraer texto de un PDF usando herramientas del sistema o regex."""
    filepath = str(filepath)

    # 1. Intentar con pdftotext (poppler) si está instalado
    try:
        result = subprocess.run(
            ["pdftotext", filepath, "-"],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0:
            text = result.stdout.decode("utf-8", errors="replace").strip()
            if text:
                return text
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 2. Fallback: extracción básica de streams de texto del PDF
    try:
        with open(filepath, "rb") as f:
            data = f.read()

        text_parts: list[str] = []

        # Buscar streams comprimidos y descomprimir
        for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", data, re.DOTALL):
            stream_data = match.group(1)
            try:
                decompressed = zlib.decompress(stream_data)
            except zlib.error:
                decompressed = stream_data

            # Extraer operaciones de texto TJ y Tj
            for txt_match in re.finditer(rb"\(([^)]+)\)", decompressed):
                try:
                    decoded = txt_match.group(1).decode("latin-1", errors="replace")
                    if any(c.isalpha() for c in decoded) and len(decoded) > 1:
                        text_parts.append(decoded)
                except Exception:
                    pass

        if text_parts:
            return " ".join(text_parts)
    except Exception:
        pass

    return ""


# ══════════════════════════════════════════════════════════════
# Peticiones HTTP a proveedores de LLM
# ══════════════════════════════════════════════════════════════
def _make_request(url: str, headers: dict[str, str], body: dict[str, Any],
                  timeout: int = 60) -> dict[str, Any]:
    """Hace un POST JSON y devuelve la respuesta parseada."""
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    for k, v in headers.items():
        req.add_header(k, v)

    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Error {e.code} del proveedor LLM: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Error de conexión con el proveedor LLM: {e.reason}")


# ── OpenAI ───────────────────────────────────────────────────
def _chat_openai(api_key: str, model: str, messages: list[dict[str, str]],
                 temperature: float, max_tokens: int) -> str:
    url = PROVIDERS["openai"]["url"]
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    result = _make_request(url, headers, body)
    return result["choices"][0]["message"]["content"]


# ── Anthropic (Claude) ───────────────────────────────────────
def _chat_anthropic(api_key: str, model: str, messages: list[dict[str, str]],
                    temperature: float, max_tokens: int) -> str:
    url = PROVIDERS["anthropic"]["url"]
    system_parts: list[str] = []
    chat_msgs: list[dict[str, str]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            chat_msgs.append(msg)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    body: dict[str, Any] = {
        "model": model,
        "messages": chat_msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if system_parts:
        body["system"] = "\n".join(system_parts)

    result = _make_request(url, headers, body)
    return result["content"][0]["text"]


# ── Google Gemini ────────────────────────────────────────────
def _chat_gemini(api_key: str, model: str, messages: list[dict[str, str]],
                 temperature: float, max_tokens: int) -> str:
    url = PROVIDERS["gemini"]["url_template"].format(model=model)

    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        else:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

    result = _make_request(url, {"x-goog-api-key": api_key}, body)
    return result["candidates"][0]["content"]["parts"][0]["text"]


# ── OpenRouter ───────────────────────────────────────────────
def _chat_openrouter(api_key: str, model: str, messages: list[dict[str, str]],
                     temperature: float, max_tokens: int) -> str:
    url = PROVIDERS["openrouter"]["url"]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://jginmobiliaria.com",
        "X-Title": "JG Inmobiliaria Chat",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    result = _make_request(url, headers, body)
    return result["choices"][0]["message"]["content"]


# ══════════════════════════════════════════════════════════════
# Dispatcher principal
# ══════════════════════════════════════════════════════════════
_DISPATCH = {
    "openai": _chat_openai,
    "anthropic": _chat_anthropic,
    "gemini": _chat_gemini,
    "openrouter": _chat_openrouter,
}


def chat(provider: str, api_key: str, model: str,
         messages: list[dict[str, str]],
         temperature: float = 0.7, max_tokens: int = 1024) -> str:
    """Envía mensajes al proveedor seleccionado y devuelve la respuesta.

    Args:
        provider: Uno de 'openai', 'anthropic', 'gemini', 'openrouter'.
        api_key: Clave API (descifrada) del proveedor.
        model: Nombre del modelo a usar.
        messages: Lista de dicts con 'role' y 'content'.
        temperature: Creatividad (0.0 a 1.0).
        max_tokens: Máximo de tokens en la respuesta.

    Returns:
        Texto de la respuesta del LLM.
    """
    fn = _DISPATCH.get(provider)
    if fn is None:
        raise ValueError(
            f"Proveedor '{provider}' no soportado. "
            f"Usa: {', '.join(_DISPATCH)}"
        )
    try:
        reply = fn(api_key, model, messages, temperature, max_tokens)
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("El proveedor LLM devolvió una respuesta con formato inesperado.") from exc
    return (reply or "").strip()


# ══════════════════════════════════════════════════════════════
# Construcción del contexto del agente
# ══════════════════════════════════════════════════════════════
MAX_KNOWLEDGE_CHARS = 24_000

_CITY_LABELS = {"medellin": "Medellín", "bogota": "Bogotá D.C."}


def _format_cop(amount: Any) -> str:
    try:
        return "$" + f"{int(amount):,}".replace(",", ".") + " COP"
    except (TypeError, ValueError):
        return str(amount)


def format_property_line(prop: dict[str, Any]) -> str:
    """Resume un inmueble en una línea legible para el LLM."""
    amenities = prop.get("amenities") or []
    if isinstance(amenities, str):
        try:
            amenities = json.loads(amenities)
        except json.JSONDecodeError:
            amenities = [amenities]
    price_label = "Canon mensual" if prop.get("operation") == "arriendo" else "Precio"
    parts = [
        f"[ID {prop.get('id')}] {prop.get('title')}",
        f"{prop.get('property_type', '')} en {prop.get('operation', '')}",
        f"{prop.get('neighborhood', '')}, {_CITY_LABELS.get(prop.get('city', ''), prop.get('city', ''))}",
        f"{price_label}: {_format_cop(prop.get('price'))}",
        f"Separación: {_format_cop(prop.get('separation_fee'))}",
        f"Administración: {_format_cop(prop.get('admin_fee'))}",
        f"{prop.get('area_m2')} m², {prop.get('bedrooms')} hab., {prop.get('bathrooms')} baños, "
        f"{prop.get('parking')} parqueaderos, estrato {prop.get('stratum')}",
        f"Estado: {prop.get('status')}",
        f"Descripción: {prop.get('description', '')}",
    ]
    if amenities:
        parts.append("Amenidades: " + ", ".join(str(a) for a in amenities))
    return " | ".join(parts)


def build_system_message(system_prompt: str,
                         knowledge: list[dict[str, Any]],
                         properties: list[dict[str, Any]],
                         contact: dict[str, str] | None = None) -> str:
    """Une prompt, base de conocimiento, inventario y contacto en un solo mensaje de sistema."""
    sections = [system_prompt.strip() or DEFAULT_SYSTEM_PROMPT]

    if contact:
        contact_lines = [f"- {k}: {v}" for k, v in contact.items() if v]
        if contact_lines:
            sections.append("## Datos de contacto del negocio\n" + "\n".join(contact_lines))

    if properties:
        lines = "\n".join(f"- {format_property_line(p)}" for p in properties)
        sections.append(f"## Inventario actual de inmuebles ({len(properties)})\n{lines}")
    else:
        sections.append("## Inventario actual de inmuebles\nNo hay inmuebles disponibles en este momento.")

    knowledge_parts: list[str] = []
    used = 0
    for entry in knowledge:
        content = (entry.get("content") or "").strip()
        if not content:
            continue
        block = f"### {entry.get('title', 'Sin título')}\n{content}"
        remaining = MAX_KNOWLEDGE_CHARS - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining] + "…"
        knowledge_parts.append(block)
        used += len(block)
    if knowledge_parts:
        sections.append("## Base de conocimiento del negocio\n" + "\n\n".join(knowledge_parts))

    return "\n\n".join(sections)
