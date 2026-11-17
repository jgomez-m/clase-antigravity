"""Servidor HTTP y API REST para el e-commerce JG Inmobiliaria."""

from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

# Asegura importaciones locales aunque se ejecute desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import create_session_token, verify_password, verify_session_token
from config import BASE_DIR, Settings, get_settings
from db import get_connection, init_db, serialize_property


FRONTEND_DIR = BASE_DIR / "frontend"
SESSION_COOKIE_NAME = "jg_admin_session"
VALID_OPERATIONS = {"venta", "arriendo"}
VALID_TYPES = {"apartamento", "casa"}
VALID_CITIES = {"medellin", "bogota"}
VALID_PROP_STATUSES = {"disponible", "reservado", "arrendado", "vendido"}
VALID_PAYMENT_METHODS = {"transferencia", "tarjeta", "whatsapp"}
VALID_RES_STATUSES = {"pendiente", "en_revision", "aprobado", "cerrado", "cancelado"}


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

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Encabezado Content-Length inválido."})
            return None
        if length <= 0 or length > 1_000_000:
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

        # Rutas protegidas de administración
        if path == "/api/admin/me":
            user = self._require_admin()
            if user:
                self._send_json(200, {"username": user})
            return

        if path == "/api/admin/dashboard":
            if not self._require_admin():
                return
            self._handle_admin_dashboard()
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

    def _handle_admin_dashboard(self) -> None:
        with get_connection(self.settings.db_path) as conn:
            total_props = conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]
            avail_props = conn.execute("SELECT COUNT(*) FROM properties WHERE status = 'disponible'").fetchone()[0]
            pending_res = conn.execute(
                "SELECT COUNT(*) FROM reservations WHERE status IN ('pendiente', 'en_revision')"
            ).fetchone()[0]
            total_res_amount = conn.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM reservations WHERE status != 'cancelado'"
            ).fetchone()[0]
            new_inquiries = conn.execute("SELECT COUNT(*) FROM inquiries WHERE status = 'nuevo'").fetchone()[0]

        self._send_json(
            200,
            {
                "stats": {
                    "total_properties": total_props,
                    "available_properties": avail_props,
                    "pending_reservations": pending_res,
                    "total_reserved_cop": total_res_amount,
                    "new_inquiries": new_inquiries,
                }
            },
        )

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
