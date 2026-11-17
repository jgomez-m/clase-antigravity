"""Carga y validación de variables de entorno para JG Inmobiliaria."""

from dataclasses import dataclass
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(env_path: Path) -> None:
    """Lee pares CLAVE=VALOR desde un archivo .env sin sobrescribir variables ya definidas."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    """Configuración validada de la aplicación."""

    port: int
    db_path: Path
    admin_user: str
    admin_password: str
    session_secret: str
    contact_email: str
    whatsapp_number: str
    whatsapp_display: str


def get_settings() -> Settings:
    """Carga variables de entorno y valida que las credenciales obligatorias existan."""
    load_dotenv(BASE_DIR / ".env")

    admin_user = os.environ.get("ADMIN_USER", "").strip()
    admin_password = os.environ.get("ADMIN_PASSWORD", "").strip()
    session_secret = os.environ.get("SESSION_SECRET", "").strip()

    missing = [
        name
        for name, val in (
            ("ADMIN_USER", admin_user),
            ("ADMIN_PASSWORD", admin_password),
            ("SESSION_SECRET", session_secret),
        )
        if not val
    ]
    if missing:
        raise RuntimeError(
            "Faltan variables de entorno obligatorias: "
            + ", ".join(missing)
            + ". Copia .env.example a .env y configúralas."
        )

    raw_db = os.environ.get("DB_PATH", "backend/jginmobiliaria.db").strip()
    db_path = Path(raw_db)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path

    return Settings(
        port=int(os.environ.get("PORT", "8080")),
        db_path=db_path,
        admin_user=admin_user,
        admin_password=admin_password,
        session_secret=session_secret,
        contact_email=os.environ.get("CONTACT_EMAIL", "admin@jginmobiliaria.com").strip(),
        whatsapp_number=os.environ.get("WHATSAPP_NUMBER", "573114436916").strip(),
        whatsapp_display=os.environ.get("WHATSAPP_DISPLAY", "+57 3114436916").strip(),
    )

