"""Servidor HTTP y API REST para el e-commerce JG Inmobiliaria."""

import base64
import binascii
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

# Asegura importaciones locales aunque se ejecute desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import create_session_token, verify_password, verify_session_token
from config import BASE_DIR, Settings, get_settings
from db import get_connection, init_db, serialize_property
import llm


FRONTEND_DIR = BASE_DIR / "frontend"
SESSION_COOKIE_NAME = "jg_admin_session"
VALID_OPERATIONS = {"venta", "arriendo"}
VALID_TYPES = {"apartamento", "casa"}
VALID_CITIES = {"medellin", "bogota"}
VALID_PROP_STATUSES = {"disponible", "reservado", "arrendado", "vendido"}
VALID_PAYMENT_METHODS = {"transferencia", "tarjeta", "whatsapp"}
VALID_RES_STATUSES = {"pendiente", "en_revision", "aprobado", "cerrado", "cancelado"}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_UPLOAD_BODY = 12 * 1024 * 1024  # base64 infla el archivo ~33%
UPLOAD_TYPES = {
    "application/pdf": ("pdf", ".pdf"),
    "image/png": ("image", ".png"),
    "image/jpeg": ("image", ".jpg"),
    "image/webp": ("image", ".webp"),
    "image/gif": ("image", ".gif"),
}
CHAT_MAX_MESSAGE_CHARS = 1000
CHAT_HISTORY_LIMIT = 12
CHAT_RATE_LIMIT = 20
CHAT_RATE_WINDOW_SECONDS = 300
SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}")

_chat_rate_lock = threading.Lock()
_chat_rate_hits: dict[str, list[float]] = {}


def chat_rate_limited(client_key: str) -> bool:
    """Ventana deslizante en memoria para frenar abuso del endpoint público de chat."""
    now = time.monotonic()
    with _chat_rate_lock:
        hits = [t for t in _chat_rate_hits.get(client_key, []) if now - t < CHAT_RATE_WINDOW_SECONDS]
        if len(hits) >= CHAT_RATE_LIMIT:
            _chat_rate_hits[client_key] = hits
            return True
        hits.append(now)
        _chat_rate_hits[client_key] = hits
        return False


def slugify(text: str) -> str:
    """Convierte un título en un identificador amigable para URL."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s-]", "", text.lower().strip())
    return re.sub(r"[\s-]+", "-", cleaned).strip("-") or f"inmueble-{secrets.token_hex(3)}"


def format_cop(amount: int) -> str:
    return "$" + f"{amount:,}".replace(",", ".") + " COP"


class JGRequestHandler(BaseHTTPRequestHandler):
    """Manejador de rutas API y archivos estáticos."""

    settings: Settings  # Inyectado en la clase por run_server()

    def log_message(self, format: str, *args: Any) -> None:
        # Formato limpio en consola
        sys.stderr.write(f"[JG-API] {self.address_string()} - {format % args}\n")

    def _send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self, max_bytes: int = 1_000_000) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Encabezado Content-Length inválido."})
            return None
        if length <= 0 or length > max_bytes:
            self._send_json(400, {"error": "Cuerpo de solicitud vacío o demasiado grande."})
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON debe ser un objeto")
            return data
        except Exception:
            self._send_json(400, {"error": "Formato JSON inválido."})
            return None

    def _get_admin_username(self) -> str | None:
        raw_cookie = self.headers.get("Cookie", "")
        if not raw_cookie:
            return None
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw_cookie)
        except Exception:
            return None
        morsel = jar.get(SESSION_COOKIE_NAME)
        if not morsel:
            return None
        return verify_session_token(morsel.value, self.settings.session_secret)

    def _require_admin(self) -> str | None:
        user = self._get_admin_username()
        if not user:
            self._send_json(401, {"error": "Acceso no autorizado. Inicia sesión como administrador."})
            return None
        return user

    def _serve_static(self, rel_path: str) -> None:
        target = (FRONTEND_DIR / rel_path.lstrip("/")).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.is_file():
            self._send_json(404, {"error": "Recurso no encontrado."})
            return
        mime, _ = mimetypes.guess_type(str(target))
        if mime is None:
            mime = "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") or mime == "application/javascript" else mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------------
    # GET
    # ------------------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._send_json(200, {"status": "ok", "service": "jg-inmobiliaria"})
            return

        if path == "/api/config":
            self._send_json(
                200,
                {
                    "contact_email": self.settings.contact_email,
                    "whatsapp_number": self.settings.whatsapp_number,
                    "whatsapp_display": self.settings.whatsapp_display,
                    "only_housing": True,
                },
            )
            return

        if path == "/api/properties":
            self._handle_list_properties(query, include_all=False)
            return

        if path.startswith("/api/properties/"):
            prop_id = path.removeprefix("/api/properties/")
            self._handle_get_property(prop_id)
            return

        if path.startswith("/api/reservations/"):
            order_code = path.removeprefix("/api/reservations/").strip().upper()
            self._handle_get_reservation_status(order_code)
            return

        if path == "/api/agent/status":
            self._handle_agent_status()
            return

        # Rutas protegidas de administración
        if path == "/api/admin/me":
            user = self._require_admin()
            if user:
                self._send_json(200, {"username": user})
            return

        if path == "/api/admin/dashboard":
            if not self._require_admin():
                return
            self._handle_admin_dashboard(query)
            return

        if path == "/api/admin/properties":
            if not self._require_admin():
                return
            self._handle_list_properties(query, include_all=True)
            return

        if path == "/api/admin/reservations":
            if not self._require_admin():
                return
            self._handle_admin_reservations()
            return

        if path == "/api/admin/inquiries":
            if not self._require_admin():
                return
            self._handle_admin_inquiries()
            return

        if path == "/api/admin/visits":
            if not self._require_admin():
                return
            self._handle_admin_visits(query)
            return

        if path == "/api/admin/reports/csv":
            if not self._require_admin():
                return
            self._handle_admin_csv_report(query)
            return

        if path == "/api/admin/agent-config":
            if not self._require_admin():
                return
            self._handle_get_agent_config()
            return

        if path == "/api/admin/knowledge":
            if not self._require_admin():
                return
            self._handle_list_knowledge()
            return

        knowledge_file = re.fullmatch(r"/api/admin/knowledge/(\d+)/file", path)
        if knowledge_file:
            if not self._require_admin():
                return
            self._handle_get_knowledge_file(int(knowledge_file.group(1)))
            return

        # Páginas y archivos estáticos del frontend
        if path == "/" or path == "/index.html":
            self._serve_static("index.html")
            return
        if path == "/admin" or path == "/admin/":
            self._serve_static("admin.html")
            return
        self._serve_static(path)

    # ------------------------------------------------------------------
    # POST
    # ------------------------------------------------------------------
    def do_POST(self) -> None:
        path = unquote(urlparse(self.path).path)

        if path == "/api/reservations":
            self._handle_create_reservation()
            return

        if path == "/api/inquiries":
            self._handle_create_inquiry()
            return

        if path == "/api/admin/login":
            self._handle_admin_login()
            return

        if path == "/api/admin/logout":
            self._send_json(
                200,
                {"ok": True},
                {"Set-Cookie": f"{SESSION_COOKIE_NAME}=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"},
            )
            return

        if path == "/api/admin/properties":
            if not self._require_admin():
                return
            self._handle_create_property()
            return

        if path == "/api/visits":
            self._handle_track_visit()
            return

        if path == "/api/chat":
            self._handle_public_chat()
            return

        if path == "/api/admin/knowledge":
            if not self._require_admin():
                return
            self._handle_create_knowledge_text()
            return

        if path == "/api/admin/knowledge/upload":
            if not self._require_admin():
                return
            self._handle_upload_knowledge()
            return

        if path == "/api/admin/agent-test":
            if not self._require_admin():
                return
            self._handle_agent_test()
            return

        self._send_json(404, {"error": "Ruta no encontrada."})

    # ------------------------------------------------------------------
    # PUT / PATCH / DELETE
    # ------------------------------------------------------------------
    def do_PUT(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/admin/properties/"):
            if not self._require_admin():
                return
            prop_id = path.removeprefix("/api/admin/properties/")
            self._handle_update_property(prop_id)
            return
        if path == "/api/admin/agent-config":
            if not self._require_admin():
                return
            self._handle_update_agent_config()
            return
        if path.startswith("/api/admin/knowledge/"):
            if not self._require_admin():
                return
            self._handle_update_knowledge(path.removeprefix("/api/admin/knowledge/"))
            return
        self._send_json(404, {"error": "Ruta no encontrada."})

    def do_PATCH(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/admin/reservations/"):
            if not self._require_admin():
                return
            res_id = path.removeprefix("/api/admin/reservations/")
            self._handle_update_reservation_status(res_id)
            return
        if path.startswith("/api/admin/inquiries/"):
            if not self._require_admin():
                return
            inq_id = path.removeprefix("/api/admin/inquiries/")
            self._handle_update_inquiry_status(inq_id)
            return
        self._send_json(404, {"error": "Ruta no encontrada."})

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/admin/properties/"):
            if not self._require_admin():
                return
            prop_id = path.removeprefix("/api/admin/properties/")
            self._handle_delete_property(prop_id)
            return
        if path.startswith("/api/admin/knowledge/"):
            if not self._require_admin():
                return
            self._handle_delete_knowledge(path.removeprefix("/api/admin/knowledge/"))
            return
        self._send_json(404, {"error": "Ruta no encontrada."})

    # ------------------------------------------------------------------
    # HANDLERS PÚBLICOS
    # ------------------------------------------------------------------
    def _handle_list_properties(self, query: dict[str, list[str]], include_all: bool) -> None:
        tx = (query.get("transaction", ["all"])[0] or "all").lower()
        ptype = (query.get("type", ["all"])[0] or "all").lower()
        city = (query.get("city", ["all"])[0] or "all").lower()
        budget = (query.get("budget", ["all"])[0] or "all").lower()
        search = (query.get("search", [""])[0] or "").strip().lower()

        clauses = []
        params: list[Any] = []

        if not include_all:
            clauses.append("status IN ('disponible', 'reservado')")
        if tx in VALID_OPERATIONS:
            clauses.append("operation = ?")
            params.append(tx)
        if ptype in VALID_TYPES:
            clauses.append("property_type = ?")
            params.append(ptype)
        if city in VALID_CITIES:
            clauses.append("city = ?")
            params.append(city)
        if budget == "under-2b":
            clauses.append("price < 2000000000")
        elif budget == "2b-4b":
            clauses.append("price BETWEEN 2000000000 AND 4000000000")
        elif budget == "over-4b":
            clauses.append("price > 4000000000")
        if search:
            clauses.append(
                "(LOWER(title) LIKE ? OR LOWER(neighborhood) LIKE ? OR LOWER(description) LIKE ? OR LOWER(city) LIKE ?)"
            )
            like = f"%{search}%"
            params.extend([like, like, like, like])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM properties {where_sql} ORDER BY featured DESC, id ASC"

        with get_connection(self.settings.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        self._send_json(200, {"properties": [serialize_property(r) for r in rows]})

    def _handle_get_property(self, prop_id: str) -> None:
        if not prop_id.isdigit():
            self._send_json(400, {"error": "Identificador de inmueble inválido."})
            return
        with get_connection(self.settings.db_path) as conn:
            row = conn.execute("SELECT * FROM properties WHERE id = ?", (int(prop_id),)).fetchone()
        if not row:
            self._send_json(404, {"error": "Inmueble no encontrado."})
            return
        self._send_json(200, {"property": serialize_property(row)})

    def _handle_create_reservation(self) -> None:
        data = self._read_json()
        if data is None:
            return

        customer_name = str(data.get("customer_name", "")).strip()
        customer_doc = str(data.get("customer_doc", "")).strip()
        customer_email = str(data.get("customer_email", "")).strip()
        customer_phone = str(data.get("customer_phone", "")).strip()
        customer_city = str(data.get("customer_city", "")).strip()
        payment_method = str(data.get("payment_method", "")).strip().lower()
        payment_reference = str(data.get("payment_reference", "")).strip()
        notes = str(data.get("notes", "")).strip()
        raw_ids = data.get("property_ids")

        if not all([customer_name, customer_doc, customer_email, customer_phone, customer_city]):
            self._send_json(400, {"error": "Por favor completa todos los datos de contacto y ciudad."})
            return
        if "@" not in customer_email or "." not in customer_email:
            self._send_json(400, {"error": "Ingresa un correo electrónico válido."})
            return
        if payment_method not in VALID_PAYMENT_METHODS:
            self._send_json(400, {"error": "Método de pago no válido."})
            return
        if not isinstance(raw_ids, list) or len(raw_ids) == 0:
            self._send_json(400, {"error": "Debes seleccionar al menos un inmueble para separar."})
            return

        try:
            prop_ids = list(dict.fromkeys(int(x) for x in raw_ids))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "Lista de inmuebles inválida."})
            return

        with get_connection(self.settings.db_path) as conn:
            placeholders = ",".join("?" for _ in prop_ids)
            rows = conn.execute(
                f"SELECT id, title, operation, separation_fee, status FROM properties WHERE id IN ({placeholders})",
                prop_ids,
            ).fetchall()

            if len(rows) != len(prop_ids):
                self._send_json(404, {"error": "Uno o más inmuebles seleccionados ya no existen."})
                return

            unavailable = [r["title"] for r in rows if r["status"] != "disponible"]
            if unavailable:
                self._send_json(
                    409,
                    {
                        "error": "Los siguientes inmuebles ya no están disponibles para separar: "
                        + ", ".join(unavailable)
                    },
                )
                return

            total_amount = sum(int(r["separation_fee"]) for r in rows)
            order_code = f"JG-{secrets.randbelow(900000) + 100000}"

            if payment_method == "tarjeta" and not payment_reference:
                payment_reference = f"PREAUTH-{secrets.token_hex(3).upper()}"
            elif payment_method == "transferencia" and not payment_reference:
                payment_reference = "PENDIENTE-COMPROBANTE"
            elif payment_method == "whatsapp" and not payment_reference:
                payment_reference = "CONFIRMACION-WHATSAPP"

            initial_status = "en_revision" if payment_method in {"transferencia", "tarjeta"} else "pendiente"

            cursor = conn.execute(
                """
                INSERT INTO reservations (
                    order_code, customer_name, customer_doc, customer_email, customer_phone,
                    customer_city, payment_method, payment_reference, total_amount, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_code,
                    customer_name,
                    customer_doc,
                    customer_email,
                    customer_phone,
                    customer_city,
                    payment_method,
                    payment_reference,
                    total_amount,
                    notes,
                    initial_status,
                ),
            )
            reservation_id = cursor.lastrowid

            items_out = []
            for r in rows:
                conn.execute(
                    """
                    INSERT INTO reservation_items (reservation_id, property_id, property_title, operation, separation_fee)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (reservation_id, r["id"], r["title"], r["operation"], r["separation_fee"]),
                )
                items_out.append(
                    {
                        "property_id": r["id"],
                        "property_title": r["title"],
                        "operation": r["operation"],
                        "separation_fee": r["separation_fee"],
                    }
                )

            conn.commit()

        prop_names = ", ".join(i["property_title"] for i in items_out)
        wa_text = (
            f"Hola JG Inmobiliaria, acabo de registrar la reserva {order_code} "
            f"por {prop_names}. Total separación: {format_cop(total_amount)}. "
            f"Método: {payment_method}. Mi nombre es {customer_name} ({customer_phone})."
        )
        whatsapp_url = f"https://wa.me/{self.settings.whatsapp_number}?text={quote(wa_text)}"

        self._send_json(
            201,
            {
                "reservation": {
                    "order_code": order_code,
                    "status": initial_status,
                    "total_amount": total_amount,
                    "payment_method": payment_method,
                    "payment_reference": payment_reference,
                    "items": items_out,
                    "whatsapp_url": whatsapp_url,
                }
            },
        )

    def _handle_get_reservation_status(self, order_code: str) -> None:
        if not re.fullmatch(r"JG-\d{6}", order_code):
            self._send_json(400, {"error": "El código debe tener el formato JG-123456."})
            return
        with get_connection(self.settings.db_path) as conn:
            row = conn.execute(
                """
                SELECT order_code, customer_name, customer_city, payment_method,
                       payment_reference, total_amount, status, created_at
                FROM reservations
                WHERE order_code = ?
                """,
                (order_code,),
            ).fetchone()
            if not row:
                self._send_json(404, {"error": "No encontramos ninguna reserva con ese código."})
                return
            items = conn.execute(
                """
                SELECT property_title, operation, separation_fee
                FROM reservation_items
                WHERE reservation_id = (SELECT id FROM reservations WHERE order_code = ?)
                """,
                (order_code,),
            ).fetchall()

        res = dict(row)
        # Enmascarar apellido para proteger privacidad en consulta pública
        first_name = res["customer_name"].split()[0]
        res["customer_name"] = f"{first_name} ***"
        res["items"] = [dict(i) for i in items]
        self._send_json(200, {"reservation": res})

    def _handle_create_inquiry(self) -> None:
        data = self._read_json()
        if data is None:
            return
        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        email = str(data.get("email", "")).strip()
        city = str(data.get("city", "")).strip()
        message = str(data.get("message", "")).strip()
        source = str(data.get("source", "contacto")).strip()[:30]

        if not name or not phone:
            self._send_json(400, {"error": "Por favor ingresa tu nombre y teléfono o WhatsApp."})
            return

        with get_connection(self.settings.db_path) as conn:
            conn.execute(
                """
                INSERT INTO inquiries (name, phone, email, city, message, source)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, phone, email, city, message, source),
            )
            conn.commit()

        self._send_json(201, {"ok": True, "message": "Solicitud registrada correctamente."})

    # ------------------------------------------------------------------
    # HANDLERS DE ADMINISTRADOR
    # ------------------------------------------------------------------
    def _handle_admin_login(self) -> None:
        data = self._read_json()
        if data is None:
            return
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))

        if not username or not password:
            self._send_json(400, {"error": "Ingresa usuario y contraseña."})
            return

        with get_connection(self.settings.db_path) as conn:
            row = conn.execute(
                "SELECT username, password_hash FROM admins WHERE username = ?",
                (username,),
            ).fetchone()

        if not row or not verify_password(password, row["password_hash"]):
            self._send_json(401, {"error": "Usuario o contraseña incorrectos."})
            return

        token = create_session_token(row["username"], self.settings.session_secret)
        cookie_val = f"{SESSION_COOKIE_NAME}={token}; HttpOnly; Path=/; Max-Age=86400; SameSite=Lax"
        self._send_json(
            200,
            {"ok": True, "username": row["username"]},
            {"Set-Cookie": cookie_val},
        )

    def _handle_admin_dashboard(self, query: dict[str, list[str]] | None = None) -> None:
        if query is None:
            query = {}
        date_from = (query.get("from", [""])[0] or "").strip()
        date_to = (query.get("to", [""])[0] or "").strip()

        with get_connection(self.settings.db_path) as conn:
            # KPIs generales de catálogo
            total_props = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
            avail_props = conn.execute("SELECT COUNT(*) FROM properties WHERE status = 'disponible'").fetchone()[0]
            reserved_props = conn.execute("SELECT COUNT(*) FROM properties WHERE status = 'reservado'").fetchone()[0]
            closed_props = conn.execute("SELECT COUNT(*) FROM properties WHERE status IN ('vendido','arrendado')").fetchone()[0]
            new_inquiries = conn.execute("SELECT COUNT(*) FROM inquiries WHERE status = 'nuevo'").fetchone()[0]

            # Filtros de fecha para reservas
            date_params: list[Any] = []
            date_clause = ""
            if date_from and date_to:
                date_clause = "WHERE DATE(created_at) BETWEEN ? AND ?"
                date_params = [date_from, date_to]
            elif date_from:
                date_clause = "WHERE DATE(created_at) >= ?"
                date_params = [date_from]
            elif date_to:
                date_clause = "WHERE DATE(created_at) <= ?"
                date_params = [date_to]

            total_res = conn.execute(
                f"SELECT COUNT(*) FROM reservations {date_clause}", date_params
            ).fetchone()[0]
            pending_res = conn.execute(
                f"SELECT COUNT(*) FROM reservations {date_clause + (' AND' if date_clause else 'WHERE')} status IN ('pendiente','en_revision')",
                date_params
            ).fetchone()[0]
            approved_res = conn.execute(
                f"SELECT COUNT(*) FROM reservations {date_clause + (' AND' if date_clause else 'WHERE')} status IN ('aprobado','cerrado')",
                date_params
            ).fetchone()[0]
            total_income = conn.execute(
                f"SELECT COALESCE(SUM(total_amount),0) FROM reservations {date_clause + (' AND' if date_clause else 'WHERE')} status IN ('aprobado','cerrado')",
                date_params
            ).fetchone()[0]

            conversion_rate = round((approved_res / total_res * 100) if total_res > 0 else 0, 1)
            average_ticket = round(total_income / approved_res) if approved_res > 0 else 0

            # Gráfica 1: Ingresos por mes (últimos 6 meses o periodo)
            m_clause = date_clause if date_clause else "WHERE created_at >= date('now', '-6 months')"
            m_params = date_params if date_clause else []
            monthly_income = conn.execute(f"""
                SELECT strftime('%Y-%m', created_at) AS month,
                       COALESCE(SUM(total_amount), 0) AS total
                FROM reservations
                {m_clause + (' AND' if m_clause else 'WHERE')} status IN ('aprobado','cerrado')
                GROUP BY month ORDER BY month ASC
            """, m_params).fetchall()

            # Gráfica 2: Distribución venta vs arriendo
            r_prefix_clause = ""
            if date_from and date_to:
                r_prefix_clause = "WHERE DATE(r.created_at) BETWEEN ? AND ?"
            elif date_from:
                r_prefix_clause = "WHERE DATE(r.created_at) >= ?"
            elif date_to:
                r_prefix_clause = "WHERE DATE(r.created_at) <= ?"

            dist_venta = conn.execute(
                f"""SELECT COUNT(*) FROM reservations r
                   JOIN reservation_items ri ON ri.reservation_id = r.id
                   {r_prefix_clause + (' AND' if r_prefix_clause else 'WHERE')} ri.operation = 'venta'""",
                date_params
            ).fetchone()[0]
            dist_arriendo = conn.execute(
                f"""SELECT COUNT(*) FROM reservations r
                   JOIN reservation_items ri ON ri.reservation_id = r.id
                   {r_prefix_clause + (' AND' if r_prefix_clause else 'WHERE')} ri.operation = 'arriendo'""",
                date_params
            ).fetchone()[0]

            # Gráfica 3: Demanda y Ventas por Ciudad (Medellín vs Bogotá)
            city_rows = conn.execute(f"""
                SELECT p.city, COUNT(DISTINCT r.id) AS cnt,
                       COALESCE(SUM(CASE WHEN r.status IN ('aprobado','cerrado') THEN r.total_amount ELSE 0 END), 0) AS total_val
                FROM reservations r
                JOIN reservation_items ri ON ri.reservation_id = r.id
                JOIN properties p ON p.id = ri.property_id
                {r_prefix_clause}
                GROUP BY p.city
            """, date_params).fetchall()

            med_count = sum(r["cnt"] for r in city_rows if "medell" in str(r["city"]).lower())
            bog_count = sum(r["cnt"] for r in city_rows if "bogot" in str(r["city"]).lower())
            med_income = sum(r["total_val"] for r in city_rows if "medell" in str(r["city"]).lower())
            bog_income = sum(r["total_val"] for r in city_rows if "bogot" in str(r["city"]).lower())

            # Gráfica 4: Top inmuebles más demandados
            top_props = conn.execute(f"""
                SELECT p.title, COUNT(ri.id) AS cnt
                FROM reservation_items ri
                JOIN properties p ON p.id = ri.property_id
                JOIN reservations r ON r.id = ri.reservation_id
                {r_prefix_clause}
                GROUP BY ri.property_id
                ORDER BY cnt DESC LIMIT 5
            """, date_params).fetchall()

            # Gráfica 5: Cotizaciones por semana
            w_clause = date_clause if date_clause else "WHERE created_at >= date('now', '-56 days')"
            w_params = date_params if date_clause else []
            weekly_res = conn.execute(f"""
                SELECT strftime('%Y-W%W', created_at) AS week,
                       COUNT(*) AS total
                FROM reservations
                {w_clause}
                GROUP BY week ORDER BY week ASC
            """, w_params).fetchall()

        charts_data = {
            "monthly_income": {
                "labels": [r["month"] for r in monthly_income],
                "values": [r["total"] for r in monthly_income],
            },
            "operation_distribution": {
                "venta": dist_venta,
                "arriendo": dist_arriendo,
            },
            "operation_dist": {
                "venta": dist_venta,
                "arriendo": dist_arriendo,
            },
            "city_distribution": {
                "labels": ["Medellín", "Bogotá"],
                "values": [med_count, bog_count],
                "income": [med_income, bog_income],
            },
            "top_properties": {
                "labels": [r["title"] for r in top_props],
                "values": [r["cnt"] for r in top_props],
            },
            "weekly_reservations": {
                "labels": [r["week"] for r in weekly_res],
                "values": [r["total"] for r in weekly_res],
            },
        }

        stats_data = {
            "total_properties": total_props,
            "available_properties": avail_props,
            "reserved_properties": reserved_props,
            "closed_properties": closed_props,
            "total_reservations": total_res,
            "pending_reservations": pending_res,
            "approved_reservations": approved_res,
            "total_income_cop": total_income,
            "total_income": total_income,
            "average_ticket": average_ticket,
            "conversion_rate": conversion_rate,
            "new_inquiries": new_inquiries,
        }

        response_payload = dict(stats_data)
        response_payload["stats"] = stats_data
        response_payload["charts"] = charts_data

        self._send_json(200, response_payload)

    def _validate_property_payload(self, data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        title = str(data.get("title", "")).strip()
        operation = str(data.get("operation", "")).strip().lower()
        property_type = str(data.get("property_type", "")).strip().lower()
        city = str(data.get("city", "")).strip().lower()
        neighborhood = str(data.get("neighborhood", "")).strip()
        address = str(data.get("address", "")).strip()
        description = str(data.get("description", "")).strip()
        image_url = str(data.get("image_url", "")).strip()
        status = str(data.get("status", "disponible")).strip().lower()

        if not title or not neighborhood or not description:
            return None, "Título, sector y descripción son obligatorios."
        if operation not in VALID_OPERATIONS:
            return None, "La operación debe ser 'venta' o 'arriendo'."
        if property_type not in VALID_TYPES:
            return None, "Solo se permiten viviendas ('apartamento' o 'casa')."
        if city not in VALID_CITIES:
            return None, "La ciudad debe ser 'medellin' o 'bogota'."
        if status not in VALID_PROP_STATUSES:
            return None, "Estado de inmueble inválido."

        try:
            price = int(float(data.get("price", 0)))
            separation_fee = int(float(data.get("separation_fee", 0)))
            admin_fee = int(float(data.get("admin_fee", 0)))
            area_m2 = float(data.get("area_m2", 0))
            bedrooms = int(data.get("bedrooms", 0))
            bathrooms = int(data.get("bathrooms", 0))
            parking = int(data.get("parking", 1))
            stratum = int(data.get("stratum", 6))
        except (TypeError, ValueError):
            return None, "Verifica que precios, área y habitaciones sean números válidos."

        if price <= 0 or separation_fee <= 0 or area_m2 <= 0 or bedrooms <= 0 or bathrooms <= 0:
            return None, "Precio, valor de separación, área, habitaciones y baños deben ser mayores a cero."

        raw_amenities = data.get("amenities", [])
        if isinstance(raw_amenities, str):
            amenities = [a.strip() for a in raw_amenities.split(",") if a.strip()]
        elif isinstance(raw_amenities, list):
            amenities = [str(a).strip() for a in raw_amenities if str(a).strip()]
        else:
            amenities = []

        return {
            "title": title,
            "operation": operation,
            "property_type": property_type,
            "city": city,
            "neighborhood": neighborhood,
            "address": address,
            "price": price,
            "separation_fee": separation_fee,
            "admin_fee": max(0, admin_fee),
            "area_m2": area_m2,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "parking": max(0, parking),
            "stratum": max(1, min(6, stratum)),
            "description": description,
            "amenities": json.dumps(amenities, ensure_ascii=False),
            "image_url": image_url,
            "featured": 1 if data.get("featured") else 0,
            "status": status,
        }, None

    def _handle_create_property(self) -> None:
        data = self._read_json()
        if data is None:
            return
        parsed, error = self._validate_property_payload(data)
        if error or parsed is None:
            self._send_json(400, {"error": error})
            return

        base_slug = slugify(parsed["title"])
        slug = base_slug
        with get_connection(self.settings.db_path) as conn:
            if conn.execute("SELECT 1 FROM properties WHERE slug = ?", (slug,)).fetchone():
                slug = f"{base_slug}-{secrets.token_hex(2)}"
            cursor = conn.execute(
                """
                INSERT INTO properties (
                    title, slug, operation, property_type, city, neighborhood, address,
                    price, separation_fee, admin_fee, area_m2, bedrooms, bathrooms,
                    parking, stratum, description, amenities, image_url, featured, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parsed["title"],
                    slug,
                    parsed["operation"],
                    parsed["property_type"],
                    parsed["city"],
                    parsed["neighborhood"],
                    parsed["address"],
                    parsed["price"],
                    parsed["separation_fee"],
                    parsed["admin_fee"],
                    parsed["area_m2"],
                    parsed["bedrooms"],
                    parsed["bathrooms"],
                    parsed["parking"],
                    parsed["stratum"],
                    parsed["description"],
                    parsed["amenities"],
                    parsed["image_url"],
                    parsed["featured"],
                    parsed["status"],
                ),
            )
            new_id = cursor.lastrowid
            conn.commit()
            row = conn.execute("SELECT * FROM properties WHERE id = ?", (new_id,)).fetchone()

        self._send_json(201, {"property": serialize_property(row)})

    def _handle_update_property(self, prop_id: str) -> None:
        if not prop_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        data = self._read_json()
        if data is None:
            return
        parsed, error = self._validate_property_payload(data)
        if error or parsed is None:
            self._send_json(400, {"error": error})
            return

        with get_connection(self.settings.db_path) as conn:
            existing = conn.execute("SELECT id FROM properties WHERE id = ?", (int(prop_id),)).fetchone()
            if not existing:
                self._send_json(404, {"error": "Inmueble no encontrado."})
                return
            conn.execute(
                """
                UPDATE properties
                SET title = ?, operation = ?, property_type = ?, city = ?, neighborhood = ?, address = ?,
                    price = ?, separation_fee = ?, admin_fee = ?, area_m2 = ?, bedrooms = ?, bathrooms = ?,
                    parking = ?, stratum = ?, description = ?, amenities = ?, image_url = ?,
                    featured = ?, status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    parsed["title"],
                    parsed["operation"],
                    parsed["property_type"],
                    parsed["city"],
                    parsed["neighborhood"],
                    parsed["address"],
                    parsed["price"],
                    parsed["separation_fee"],
                    parsed["admin_fee"],
                    parsed["area_m2"],
                    parsed["bedrooms"],
                    parsed["bathrooms"],
                    parsed["parking"],
                    parsed["stratum"],
                    parsed["description"],
                    parsed["amenities"],
                    parsed["image_url"],
                    parsed["featured"],
                    parsed["status"],
                    int(prop_id),
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM properties WHERE id = ?", (int(prop_id),)).fetchone()

        self._send_json(200, {"property": serialize_property(row)})

    def _handle_delete_property(self, prop_id: str) -> None:
        if not prop_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        with get_connection(self.settings.db_path) as conn:
            cursor = conn.execute("DELETE FROM properties WHERE id = ?", (int(prop_id),))
            conn.commit()
        if cursor.rowcount == 0:
            self._send_json(404, {"error": "Inmueble no encontrado."})
            return
        self._send_json(200, {"ok": True})

    def _handle_admin_reservations(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            res_rows = conn.execute(
                "SELECT * FROM reservations ORDER BY id DESC"
            ).fetchall()
            item_rows = conn.execute(
                "SELECT * FROM reservation_items"
            ).fetchall()

        items_by_res: dict[int, list[dict[str, Any]]] = {}
        for item in item_rows:
            items_by_res.setdefault(item["reservation_id"], []).append(dict(item))

        reservations = []
        for r in res_rows:
            obj = dict(r)
            obj["items"] = items_by_res.get(r["id"], [])
            reservations.append(obj)

        self._send_json(200, {"reservations": reservations})

    def _handle_update_reservation_status(self, res_id: str) -> None:
        if not res_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        data = self._read_json()
        if data is None:
            return
        status = str(data.get("status", "")).strip().lower()
        prop_status = str(data.get("property_status", "")).strip().lower()

        if status not in VALID_RES_STATUSES:
            self._send_json(400, {"error": "Estado de reserva no válido."})
            return
        if prop_status and prop_status not in VALID_PROP_STATUSES:
            self._send_json(400, {"error": "Estado de inmueble no válido."})
            return

        with get_connection(self.settings.db_path) as conn:
            row = conn.execute("SELECT id FROM reservations WHERE id = ?", (int(res_id),)).fetchone()
            if not row:
                self._send_json(404, {"error": "Reserva no encontrada."})
                return
            conn.execute(
                "UPDATE reservations SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, int(res_id)),
            )
            if prop_status:
                conn.execute(
                    """
                    UPDATE properties
                    SET status = ?, updated_at = datetime('now')
                    WHERE id IN (
                        SELECT property_id FROM reservation_items
                        WHERE reservation_id = ? AND property_id IS NOT NULL
                    )
                    """,
                    (prop_status, int(res_id)),
                )
            conn.commit()

        self._send_json(200, {"ok": True, "status": status})

    def _handle_admin_inquiries(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM inquiries ORDER BY id DESC").fetchall()
        self._send_json(200, {"inquiries": [dict(r) for r in rows]})

    def _handle_update_inquiry_status(self, inq_id: str) -> None:
        if not inq_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        data = self._read_json()
        if data is None:
            return
        status = str(data.get("status", "")).strip().lower()
        if status not in {"nuevo", "atendido"}:
            self._send_json(400, {"error": "Estado inválido."})
            return
        with get_connection(self.settings.db_path) as conn:
            cursor = conn.execute("UPDATE inquiries SET status = ? WHERE id = ?", (status, int(inq_id)))
            conn.commit()
        if cursor.rowcount == 0:
            self._send_json(404, {"error": "Solicitud no encontrada."})
            return
        self._send_json(200, {"ok": True})


    def _handle_admin_visits(self, query: dict[str, list[str]]) -> None:
        date_from = (query.get("from", [""])[0] or "").strip()
        date_to = (query.get("to", [""])[0] or "").strip()

        date_params: list[Any] = []
        date_clause = ""
        if date_from and date_to:
            date_clause = "WHERE DATE(created_at) BETWEEN ? AND ?"
            date_params = [date_from, date_to]
        elif date_from:
            date_clause = "WHERE DATE(created_at) >= ?"
            date_params = [date_from]
        elif date_to:
            date_clause = "WHERE DATE(created_at) <= ?"
            date_params = [date_to]

        with get_connection(self.settings.db_path) as conn:
            total_visits = conn.execute(
                f"SELECT COUNT(*) FROM page_visits {date_clause}", date_params
            ).fetchone()[0]

            by_page = conn.execute(f"""
                SELECT page, COUNT(*) AS cnt FROM page_visits {date_clause}
                GROUP BY page ORDER BY cnt DESC LIMIT 10
            """, date_params).fetchall()

            by_device = conn.execute(f"""
                SELECT device, COUNT(*) AS cnt FROM page_visits {date_clause}
                GROUP BY device ORDER BY cnt DESC
            """, date_params).fetchall()

            daily = conn.execute(f"""
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM page_visits {date_clause}
                GROUP BY day ORDER BY day ASC LIMIT 30
            """, date_params).fetchall()

        by_device_dict = {r["device"]: r["cnt"] for r in by_device}

        self._send_json(200, {
            "total_visits": total_visits,
            "total": total_visits,
            "by_page": [{"page": r["page"], "count": r["cnt"]} for r in by_page],
            "by_device": by_device_dict,
            "devices_list": [{"device": r["device"], "count": r["cnt"]} for r in by_device],
            "daily": [{"day": r["day"], "count": r["cnt"]} for r in daily],
        })

    def _handle_track_visit(self) -> None:
        data = self._read_json()
        if data is None:
            return
        page = str(data.get("page", "/")).strip()[:200]
        referrer = str(data.get("referrer", "")).strip()[:500]
        ua = self.headers.get("User-Agent", "").lower()
        if any(x in ua for x in ["mobile", "android", "iphone", "ipad"]):
            device = "mobile"
        elif "tablet" in ua:
            device = "tablet"
        else:
            device = "desktop"
        with get_connection(self.settings.db_path) as conn:
            conn.execute(
                "INSERT INTO page_visits (page, referrer, device) VALUES (?, ?, ?)",
                (page, referrer, device)
            )
            conn.commit()
        self._send_json(201, {"ok": True})

    def _handle_admin_csv_report(self, query: dict[str, list[str]]) -> None:
        date_from = (query.get("from", [""])[0] or "").strip()
        date_to = (query.get("to", [""])[0] or "").strip()

        date_params: list[Any] = []
        date_clause = ""
        if date_from and date_to:
            date_clause = "WHERE DATE(r.created_at) BETWEEN ? AND ?"
            date_params = [date_from, date_to]
        elif date_from:
            date_clause = "WHERE DATE(r.created_at) >= ?"
            date_params = [date_from]
        elif date_to:
            date_clause = "WHERE DATE(r.created_at) <= ?"
            date_params = [date_to]

        with get_connection(self.settings.db_path) as conn:
            rows = conn.execute(f"""
                SELECT r.order_code, r.customer_name, r.customer_email, r.customer_phone,
                       r.customer_city, r.payment_method, r.total_amount, r.status,
                       r.created_at,
                       GROUP_CONCAT(ri.property_title, ' | ') AS properties
                FROM reservations r
                LEFT JOIN reservation_items ri ON ri.reservation_id = r.id
                {date_clause}
                GROUP BY r.id ORDER BY r.id DESC
            """, date_params).fetchall()

        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Código", "Cliente", "Email", "Teléfono", "Ciudad",
                         "Pago", "Monto", "Estado", "Fecha", "Inmuebles"])
        for r in rows:
            writer.writerow([
                r["order_code"], r["customer_name"], r["customer_email"],
                r["customer_phone"], r["customer_city"], r["payment_method"],
                r["total_amount"], r["status"], r["created_at"], r["properties"] or ""
            ])
        csv_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"cotizaciones_{date_from or 'todo'}_{date_to or 'todo'}.csv"
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(csv_bytes)))
        self.end_headers()
        self.wfile.write(csv_bytes)

    # ------------------------------------------------------------------
    # AGENTE IA
    # ------------------------------------------------------------------
    def _uploads_dir(self) -> Path:
        return self.settings.db_path.parent / "uploads" / "knowledge"

    @staticmethod
    def _load_agent_config(conn: Any) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM agent_config WHERE id = 1").fetchone()
        if row:
            return dict(row)
        return {
            "provider": "openai",
            "api_key_encrypted": "",
            "api_key_hint": "",
            "model": llm.PROVIDERS["openai"]["default_model"],
            "system_prompt": llm.DEFAULT_SYSTEM_PROMPT,
            "temperature": 0.7,
            "max_tokens": 1024,
            "active": 0,
            "updated_at": "",
        }

    def _build_agent_system_message(self, conn: Any, cfg: dict[str, Any]) -> str:
        knowledge = [dict(r) for r in conn.execute(
            "SELECT title, content FROM knowledge_entries ORDER BY id ASC"
        ).fetchall()]
        properties = [serialize_property(r) for r in conn.execute(
            "SELECT * FROM properties WHERE status IN ('disponible', 'reservado') "
            "ORDER BY featured DESC, id ASC"
        ).fetchall()]
        contact = {
            "WhatsApp": self.settings.whatsapp_display,
            "Email": self.settings.contact_email,
        }
        return llm.build_system_message(cfg["system_prompt"], knowledge, properties, contact)

    def _call_agent(self, cfg: dict[str, Any], system_message: str,
                    history: list[dict[str, str]]) -> tuple[str | None, str | None]:
        """Llama al LLM configurado. Devuelve (respuesta, error_para_usuario)."""
        if not cfg.get("api_key_encrypted"):
            return None, "Configura primero la API key del proveedor."
        try:
            api_key = llm.decrypt_api_key(cfg["api_key_encrypted"], self.settings.session_secret)
        except ValueError as exc:
            return None, str(exc)
        model = cfg.get("model") or llm.PROVIDERS[cfg["provider"]]["default_model"]
        messages = [{"role": "system", "content": system_message}, *history]
        try:
            reply = llm.chat(
                cfg["provider"], api_key, model, messages,
                temperature=float(cfg["temperature"]), max_tokens=int(cfg["max_tokens"]),
            )
        except (RuntimeError, ValueError) as exc:
            sys.stderr.write(f"[JG-AGENT] Error del proveedor: {exc}\n")
            return None, str(exc)
        if not reply:
            return None, "El modelo devolvió una respuesta vacía."
        return reply, None

    def _handle_agent_status(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            cfg = self._load_agent_config(conn)
        active = bool(cfg["active"]) and bool(cfg["api_key_encrypted"])
        self._send_json(200, {"active": active})

    def _handle_public_chat(self) -> None:
        client_key = self.client_address[0] if self.client_address else "unknown"
        if chat_rate_limited(client_key):
            self._send_json(429, {"error": "Has enviado muchos mensajes. Intenta de nuevo en unos minutos."})
            return
        data = self._read_json()
        if data is None:
            return
        session_key = str(data.get("session_id", "")).strip()
        message = str(data.get("message", "")).strip()
        if not SESSION_ID_RE.fullmatch(session_key):
            self._send_json(400, {"error": "Identificador de sesión inválido."})
            return
        if not message:
            self._send_json(400, {"error": "Escribe un mensaje."})
            return
        if len(message) > CHAT_MAX_MESSAGE_CHARS:
            self._send_json(400, {"error": f"El mensaje no puede superar {CHAT_MAX_MESSAGE_CHARS} caracteres."})
            return

        with get_connection(self.settings.db_path) as conn:
            cfg = self._load_agent_config(conn)
            if not cfg["active"] or not cfg["api_key_encrypted"]:
                self._send_json(503, {"error": "El asistente virtual no está disponible en este momento."})
                return
            conn.execute("INSERT OR IGNORE INTO chat_sessions (session_id) VALUES (?)", (session_key,))
            conn.commit()
            session_row_id = conn.execute(
                "SELECT id FROM chat_sessions WHERE session_id = ?", (session_key,)
            ).fetchone()["id"]
            past = conn.execute(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM chat_messages
                    WHERE session_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_row_id, CHAT_HISTORY_LIMIT),
            ).fetchall()
            system_message = self._build_agent_system_message(conn, cfg)

        history = [{"role": r["role"], "content": r["content"]} for r in past]
        # Algunos proveedores exigen que la conversación empiece con el usuario
        while history and history[0]["role"] != "user":
            history.pop(0)
        history.append({"role": "user", "content": message})

        reply, error = self._call_agent(cfg, system_message, history)
        if error or reply is None:
            self._send_json(502, {"error": "El asistente no pudo responder. Escríbenos por WhatsApp mientras tanto."})
            return

        with get_connection(self.settings.db_path) as conn:
            conn.executemany(
                "INSERT INTO chat_messages (session_id, role, content) VALUES (?, ?, ?)",
                [(session_row_id, "user", message), (session_row_id, "assistant", reply)],
            )
            conn.commit()

        self._send_json(200, {"reply": reply})

    def _handle_get_agent_config(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            cfg = self._load_agent_config(conn)
        providers = {
            key: {"name": p["name"], "models": p["models"], "default_model": p["default_model"]}
            for key, p in llm.PROVIDERS.items()
        }
        self._send_json(200, {
            "config": {
                "provider": cfg["provider"],
                "model": cfg["model"],
                "system_prompt": cfg["system_prompt"],
                "temperature": cfg["temperature"],
                "max_tokens": cfg["max_tokens"],
                "active": bool(cfg["active"]),
                "has_api_key": bool(cfg["api_key_encrypted"]),
                "api_key_masked": cfg["api_key_hint"],
                "updated_at": cfg["updated_at"],
            },
            "providers": providers,
            "default_system_prompt": llm.DEFAULT_SYSTEM_PROMPT,
        })

    def _handle_update_agent_config(self) -> None:
        data = self._read_json()
        if data is None:
            return
        provider = str(data.get("provider", "")).strip().lower()
        if provider not in llm.PROVIDERS:
            self._send_json(400, {"error": "Proveedor de LLM no soportado."})
            return
        model = str(data.get("model", "")).strip() or llm.PROVIDERS[provider]["default_model"]
        if len(model) > 120 or not re.fullmatch(r"[A-Za-z0-9._:/@-]+", model):
            self._send_json(400, {"error": "Nombre de modelo inválido."})
            return
        system_prompt = str(data.get("system_prompt", "")).strip() or llm.DEFAULT_SYSTEM_PROMPT
        if len(system_prompt) > 8000:
            self._send_json(400, {"error": "El prompt de sistema no puede superar 8.000 caracteres."})
            return
        try:
            temperature = float(data.get("temperature", 0.7))
            max_tokens = int(data.get("max_tokens", 1024))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "Temperatura y máximo de tokens deben ser numéricos."})
            return
        if not 0.0 <= temperature <= 1.0:
            self._send_json(400, {"error": "La temperatura debe estar entre 0.0 y 1.0."})
            return
        if not 64 <= max_tokens <= 8192:
            self._send_json(400, {"error": "El máximo de tokens debe estar entre 64 y 8192."})
            return
        new_key = str(data.get("api_key", "") or "").strip()
        clear_key = bool(data.get("clear_api_key"))
        active = 1 if data.get("active") else 0

        with get_connection(self.settings.db_path) as conn:
            cfg = self._load_agent_config(conn)
            encrypted, hint = cfg["api_key_encrypted"], cfg["api_key_hint"]
            if clear_key:
                encrypted, hint = "", ""
            if new_key:
                if len(new_key) > 500:
                    self._send_json(400, {"error": "API key demasiado larga."})
                    return
                encrypted = llm.encrypt_api_key(new_key, self.settings.session_secret)
                hint = llm.mask_api_key(new_key)
            if active and not encrypted:
                self._send_json(400, {"error": "Agrega una API key antes de activar el agente."})
                return
            conn.execute(
                """
                INSERT INTO agent_config (id, provider, api_key_encrypted, api_key_hint, model,
                                          system_prompt, temperature, max_tokens, active, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    provider = excluded.provider,
                    api_key_encrypted = excluded.api_key_encrypted,
                    api_key_hint = excluded.api_key_hint,
                    model = excluded.model,
                    system_prompt = excluded.system_prompt,
                    temperature = excluded.temperature,
                    max_tokens = excluded.max_tokens,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (provider, encrypted, hint, model, system_prompt, temperature, max_tokens, active),
            )
            conn.commit()
        self._handle_get_agent_config()

    def _handle_agent_test(self) -> None:
        data = self._read_json()
        if data is None:
            return
        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list) or not raw_messages:
            self._send_json(400, {"error": "Envía al menos un mensaje de prueba."})
            return
        history: list[dict[str, str]] = []
        for item in raw_messages[-CHAT_HISTORY_LIMIT:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()[:CHAT_MAX_MESSAGE_CHARS]
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content})
        while history and history[0]["role"] != "user":
            history.pop(0)
        if not history or history[-1]["role"] != "user":
            self._send_json(400, {"error": "El último mensaje de prueba debe ser del usuario."})
            return

        with get_connection(self.settings.db_path) as conn:
            cfg = self._load_agent_config(conn)
            system_message = self._build_agent_system_message(conn, cfg)

        reply, error = self._call_agent(cfg, system_message, history)
        if error or reply is None:
            self._send_json(502, {"error": error or "El agente no respondió."})
            return
        self._send_json(200, {"reply": reply})

    @staticmethod
    def _serialize_knowledge(row: Any) -> dict[str, Any]:
        data = dict(row)
        data["has_file"] = bool(data.pop("file_path", ""))
        data["content_length"] = len(data.get("content") or "")
        return data

    def _handle_list_knowledge(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            rows = conn.execute("SELECT * FROM knowledge_entries ORDER BY id DESC").fetchall()
        self._send_json(200, {"entries": [self._serialize_knowledge(r) for r in rows]})

    def _handle_create_knowledge_text(self) -> None:
        data = self._read_json()
        if data is None:
            return
        title = str(data.get("title", "")).strip()[:200]
        content = str(data.get("content", "")).strip()
        if not title or not content:
            self._send_json(400, {"error": "Título y contenido son obligatorios."})
            return
        with get_connection(self.settings.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO knowledge_entries (title, entry_type, content) VALUES (?, 'text', ?)",
                (title, content),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM knowledge_entries WHERE id = ?", (cursor.lastrowid,)).fetchone()
        self._send_json(201, {"entry": self._serialize_knowledge(row)})

    def _handle_upload_knowledge(self) -> None:
        data = self._read_json(max_bytes=MAX_UPLOAD_BODY)
        if data is None:
            return
        title = str(data.get("title", "")).strip()[:200]
        filename = Path(str(data.get("filename", "")).strip()).name[:200]
        mime_type = str(data.get("mime_type", "")).strip().lower()
        description = str(data.get("description", "")).strip()
        if mime_type not in UPLOAD_TYPES:
            self._send_json(400, {"error": "Solo se permiten archivos PDF o imágenes (PNG, JPG, WEBP, GIF)."})
            return
        try:
            file_bytes = base64.b64decode(str(data.get("data", "")), validate=True)
        except (binascii.Error, ValueError):
            self._send_json(400, {"error": "El archivo no está codificado correctamente."})
            return
        if not file_bytes:
            self._send_json(400, {"error": "El archivo está vacío."})
            return
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            self._send_json(400, {"error": "El archivo supera el máximo de 8 MB."})
            return

        entry_type, ext = UPLOAD_TYPES[mime_type]
        signatures = {
            ".pdf": [b"%PDF"],
            ".png": [b"\x89PNG"],
            ".jpg": [b"\xff\xd8\xff"],
            ".gif": [b"GIF87a", b"GIF89a"],
        }
        valid_signature = (
            file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP"
            if ext == ".webp"
            else any(file_bytes.startswith(sig) for sig in signatures[ext])
        )
        if not valid_signature:
            self._send_json(400, {"error": "El contenido del archivo no coincide con su tipo."})
            return

        uploads = self._uploads_dir()
        uploads.mkdir(parents=True, exist_ok=True)
        stored_name = f"{secrets.token_hex(12)}{ext}"
        target = uploads / stored_name
        target.write_bytes(file_bytes)

        warning = None
        if entry_type == "pdf":
            extracted = llm.extract_pdf_text(target)
            content = "\n\n".join(part for part in (description, extracted) if part)
            if not extracted:
                warning = ("No se pudo extraer texto del PDF. Pega el contenido manualmente "
                           "editando la entrada para que el agente lo use.")
        else:
            content = description
            if not description:
                warning = ("Agrega una descripción a la imagen: el agente solo usa el texto "
                           "descriptivo de las imágenes.")

        with get_connection(self.settings.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_entries (title, entry_type, content, file_path, original_filename)
                VALUES (?, ?, ?, ?, ?)
                """,
                (title or filename or "Archivo sin título", entry_type, content, stored_name, filename),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM knowledge_entries WHERE id = ?", (cursor.lastrowid,)).fetchone()

        payload: dict[str, Any] = {"entry": self._serialize_knowledge(row)}
        if warning:
            payload["warning"] = warning
        self._send_json(201, payload)

    def _handle_update_knowledge(self, entry_id: str) -> None:
        if not entry_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        data = self._read_json()
        if data is None:
            return
        title = str(data.get("title", "")).strip()[:200]
        content = str(data.get("content", "")).strip()
        if not title:
            self._send_json(400, {"error": "El título es obligatorio."})
            return
        with get_connection(self.settings.db_path) as conn:
            cursor = conn.execute(
                "UPDATE knowledge_entries SET title = ?, content = ? WHERE id = ?",
                (title, content, int(entry_id)),
            )
            conn.commit()
            if cursor.rowcount == 0:
                self._send_json(404, {"error": "Entrada no encontrada."})
                return
            row = conn.execute("SELECT * FROM knowledge_entries WHERE id = ?", (int(entry_id),)).fetchone()
        self._send_json(200, {"entry": self._serialize_knowledge(row)})

    def _knowledge_file_path(self, stored_name: str) -> Path | None:
        if not stored_name:
            return None
        uploads = self._uploads_dir().resolve()
        target = (uploads / stored_name).resolve()
        if target.parent != uploads:
            return None
        return target

    def _handle_delete_knowledge(self, entry_id: str) -> None:
        if not entry_id.isdigit():
            self._send_json(400, {"error": "Identificador inválido."})
            return
        with get_connection(self.settings.db_path) as conn:
            row = conn.execute(
                "SELECT file_path FROM knowledge_entries WHERE id = ?", (int(entry_id),)
            ).fetchone()
            if not row:
                self._send_json(404, {"error": "Entrada no encontrada."})
                return
            conn.execute("DELETE FROM knowledge_entries WHERE id = ?", (int(entry_id),))
            conn.commit()
        target = self._knowledge_file_path(row["file_path"])
        if target and target.is_file():
            target.unlink()
        self._send_json(200, {"ok": True})

    def _handle_get_knowledge_file(self, entry_id: int) -> None:
        with get_connection(self.settings.db_path) as conn:
            row = conn.execute(
                "SELECT file_path, original_filename FROM knowledge_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        target = self._knowledge_file_path(row["file_path"]) if row else None
        if not target or not target.is_file():
            self._send_json(404, {"error": "Archivo no encontrado."})
            return
        mime, _ = mimetypes.guess_type(str(target))
        file_bytes = target.read_bytes()
        safe_name = re.sub(r"[^A-Za-z0-9._\- ]", "_", row["original_filename"] or target.name)
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(file_bytes)))
        self.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(file_bytes)


def run_server() -> None:
    settings = get_settings()
    init_db(settings)

    class ConfiguredHandler(JGRequestHandler):
        pass

    ConfiguredHandler.settings = settings
    host = os.environ.get("HOST", "127.0.0.1").strip() or "127.0.0.1"
    server = ThreadingHTTPServer((host, settings.port), ConfiguredHandler)
    print(f"JG Inmobiliaria activo en http://{host}:{settings.port}")
    print(f"Panel administrador en http://{host}:{settings.port}/admin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
        server.server_close()


if __name__ == "__main__":
    run_server()
