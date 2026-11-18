"""Pruebas unitarias y de integración para JG Inmobiliaria.

Ejecutar con:
    cd backend && python3 -m unittest tests -v
"""

import hashlib
import hmac
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

# Asegurar que los módulos locales se importan correctamente
sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import (
    PBKDF2_ITERATIONS,
    _b64_decode,
    _b64_encode,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)
from config import Settings, load_dotenv


# ──────────────────────────────────────────────────────────────
# Constantes de prueba
# ──────────────────────────────────────────────────────────────
TEST_USER = "testadmin"
TEST_PASS = "TestP@ss123"
TEST_SECRET = "super-secret-test-key-42"

SAMPLE_PROPERTY = {
    "title": "Test Apartamento Unit",
    "operation": "venta",
    "property_type": "apartamento",
    "city": "medellin",
    "neighborhood": "El Poblado Test",
    "address": "Calle Test #1-23",
    "price": 500000000,
    "separation_fee": 5000000,
    "admin_fee": 800000,
    "area_m2": 120,
    "bedrooms": 3,
    "bathrooms": 2,
    "parking": 2,
    "stratum": 5,
    "description": "Inmueble de prueba para tests unitarios.",
    "amenities": ["Piscina", "Gimnasio"],
    "image_url": "https://example.com/test.jpg",
    "featured": True,
    "status": "disponible",
}


# ══════════════════════════════════════════════════════════════
# A) Tests de auth.py
# ══════════════════════════════════════════════════════════════
class TestHashPassword(unittest.TestCase):
    """Pruebas para hash_password()."""

    def test_format_salt_colon_digest(self):
        """El hash debe tener formato 'salt_hex:digest_hex'."""
        result = hash_password("mi_clave")
        self.assertIn(":", result)
        salt_hex, digest_hex = result.split(":", 1)
        # Sal de 16 bytes = 32 caracteres hex
        self.assertEqual(len(salt_hex), 32)
        # Digest SHA-256 = 32 bytes = 64 caracteres hex
        self.assertEqual(len(digest_hex), 64)
        # Ambos deben ser hex válidos
        bytes.fromhex(salt_hex)
        bytes.fromhex(digest_hex)

    def test_different_salts_produce_different_hashes(self):
        """Dos llamadas con la misma contraseña generan hashes distintos."""
        h1 = hash_password("misma_clave")
        h2 = hash_password("misma_clave")
        self.assertNotEqual(h1, h2)

    def test_explicit_salt_produces_deterministic_hash(self):
        """Con la misma sal explícita, el resultado debe ser idéntico."""
        salt = b"\x00" * 16
        h1 = hash_password("test", salt=salt)
        h2 = hash_password("test", salt=salt)
        self.assertEqual(h1, h2)


class TestVerifyPassword(unittest.TestCase):
    """Pruebas para verify_password()."""

    def test_correct_password(self):
        """Contraseña correcta devuelve True."""
        stored = hash_password("clave_secreta")
        self.assertTrue(verify_password("clave_secreta", stored))

    def test_wrong_password(self):
        """Contraseña incorrecta devuelve False."""
        stored = hash_password("clave_secreta")
        self.assertFalse(verify_password("otra_clave", stored))

    def test_malformed_no_colon(self):
        """Hash sin ':' devuelve False."""
        self.assertFalse(verify_password("test", "sincolon"))

    def test_malformed_bad_hex(self):
        """Hash con sal no-hex devuelve False."""
        self.assertFalse(verify_password("test", "ZZZZ:abcdef0123456789"))

    def test_empty_hash(self):
        """Hash vacío devuelve False."""
        self.assertFalse(verify_password("test", ""))


class TestSessionToken(unittest.TestCase):
    """Pruebas para create_session_token() y verify_session_token()."""

    def test_token_format_payload_dot_signature(self):
        """El token tiene formato 'payload.signature'."""
        token = create_session_token("admin", TEST_SECRET)
        self.assertIn(".", token)
        parts = token.split(".")
        self.assertEqual(len(parts), 2)
        # Ambas partes deben ser base64url decodificables
        _b64_decode(parts[0])
        _b64_decode(parts[1])

    def test_roundtrip_create_verify(self):
        """Crear un token y verificarlo devuelve el usuario correcto."""
        token = create_session_token("juanito", TEST_SECRET, ttl_seconds=60)
        result = verify_session_token(token, TEST_SECRET)
        self.assertEqual(result, "juanito")

    def test_expired_token(self):
        """Un token con TTL=0 ya expiró y devuelve None."""
        token = create_session_token("admin", TEST_SECRET, ttl_seconds=0)
        time.sleep(1.1)
        result = verify_session_token(token, TEST_SECRET)
        self.assertIsNone(result)

    def test_tampered_payload(self):
        """Modificar el payload invalida la firma → None."""
        token = create_session_token("admin", TEST_SECRET)
        payload_b64, sig_b64 = token.split(".", 1)
        # Alterar un carácter en el payload
        tampered = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
        result = verify_session_token(f"{tampered}.{sig_b64}", TEST_SECRET)
        self.assertIsNone(result)

    def test_wrong_secret(self):
        """Verificar con un secreto diferente devuelve None."""
        token = create_session_token("admin", TEST_SECRET)
        result = verify_session_token(token, "secreto-equivocado")
        self.assertIsNone(result)

    def test_empty_token(self):
        """Token vacío devuelve None."""
        self.assertIsNone(verify_session_token("", TEST_SECRET))

    def test_none_token(self):
        """Token None devuelve None."""
        self.assertIsNone(verify_session_token(None, TEST_SECRET))

    def test_no_dot_token(self):
        """Token sin punto devuelve None."""
        self.assertIsNone(verify_session_token("sindottoken", TEST_SECRET))


# ══════════════════════════════════════════════════════════════
# B) Tests de config.py
# ══════════════════════════════════════════════════════════════
class TestLoadDotenv(unittest.TestCase):
    """Pruebas para load_dotenv()."""

    def setUp(self):
        self._saved_env = {}

    def tearDown(self):
        # Limpiar variables que el test pudo haber puesto
        for key in ("_TEST_VAR_A", "_TEST_VAR_B", "_TEST_VAR_EXISTING"):
            if key in self._saved_env:
                os.environ[key] = self._saved_env[key]
            else:
                os.environ.pop(key, None)

    def test_loads_variables(self):
        """Carga pares CLAVE=VALOR desde un archivo .env temporal."""
        os.environ.pop("_TEST_VAR_A", None)
        os.environ.pop("_TEST_VAR_B", None)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('_TEST_VAR_A=valor_a\n_TEST_VAR_B="valor_b"\n')
            f.flush()
            path = Path(f.name)
        try:
            load_dotenv(path)
            self.assertEqual(os.environ.get("_TEST_VAR_A"), "valor_a")
            self.assertEqual(os.environ.get("_TEST_VAR_B"), "valor_b")
        finally:
            path.unlink(missing_ok=True)
            os.environ.pop("_TEST_VAR_A", None)
            os.environ.pop("_TEST_VAR_B", None)

    def test_does_not_overwrite_existing(self):
        """Si la variable ya existe en os.environ, no la sobrescribe."""
        os.environ["_TEST_VAR_EXISTING"] = "original"
        self._saved_env["_TEST_VAR_EXISTING"] = "original"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("_TEST_VAR_EXISTING=nuevo\n")
            f.flush()
            path = Path(f.name)
        try:
            load_dotenv(path)
            self.assertEqual(os.environ["_TEST_VAR_EXISTING"], "original")
        finally:
            path.unlink(missing_ok=True)

    def test_missing_file(self):
        """Archivo inexistente no lanza error."""
        load_dotenv(Path("/tmp/__no_existe_jg__.env"))  # no debe lanzar


class TestGetSettings(unittest.TestCase):
    """Pruebas para get_settings()."""

    def setUp(self):
        self._orig = {}
        for k in ("ADMIN_USER", "ADMIN_PASSWORD", "SESSION_SECRET", "DB_PATH", "PORT"):
            self._orig[k] = os.environ.get(k)

    def tearDown(self):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_missing_vars_raises(self):
        """Sin ADMIN_USER/PASSWORD/SECRET lanza RuntimeError."""
        os.environ.pop("ADMIN_USER", None)
        os.environ.pop("ADMIN_PASSWORD", None)
        os.environ.pop("SESSION_SECRET", None)
        from config import get_settings
        with self.assertRaises(RuntimeError) as ctx:
            # Evitar que cargue el .env real
            os.environ["ADMIN_USER"] = ""
            os.environ["ADMIN_PASSWORD"] = ""
            os.environ["SESSION_SECRET"] = ""
            get_settings()
        self.assertIn("ADMIN_USER", str(ctx.exception))

    def test_valid_settings(self):
        """Con variables válidas devuelve un Settings correcto."""
        os.environ["ADMIN_USER"] = "admin_test"
        os.environ["ADMIN_PASSWORD"] = "pass_test"
        os.environ["SESSION_SECRET"] = "secret_test"
        os.environ["DB_PATH"] = "/tmp/test_jg.db"
        os.environ["PORT"] = "9090"
        from config import get_settings
        s = get_settings()
        self.assertEqual(s.admin_user, "admin_test")
        self.assertEqual(s.admin_password, "pass_test")
        self.assertEqual(s.session_secret, "secret_test")
        self.assertEqual(s.port, 9090)
        self.assertEqual(s.db_path, Path("/tmp/test_jg.db"))


# ══════════════════════════════════════════════════════════════
# C) Tests de db.py
# ══════════════════════════════════════════════════════════════
class TestDatabase(unittest.TestCase):
    """Pruebas para init_db() y serialize_property()."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="jg_test_db_")
        cls._db_path = Path(cls._tmpdir) / "test.db"
        cls._settings = Settings(
            port=0,
            db_path=cls._db_path,
            admin_user=TEST_USER,
            admin_password=TEST_PASS,
            session_secret=TEST_SECRET,
            contact_email="test@test.com",
            whatsapp_number="573000000000",
            whatsapp_display="+57 300 000 0000",
        )
        from db import init_db
        init_db(cls._settings)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _conn(self):
        from db import get_connection
        return get_connection(self._db_path)

    def test_tables_exist(self):
        """Las 6 tablas deben existir después de init_db."""
        expected = {"admins", "properties", "reservations", "reservation_items",
                    "page_visits", "inquiries"}
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        actual = {r["name"] for r in rows}
        self.assertTrue(expected.issubset(actual),
                        f"Faltan tablas: {expected - actual}")

    def test_seed_properties_count(self):
        """Deben existir exactamente 6 propiedades semilla."""
        with self._conn() as conn:
            cnt = conn.execute("SELECT COUNT(*) AS c FROM properties").fetchone()["c"]
        self.assertEqual(cnt, 6)

    def test_admin_user_created(self):
        """El usuario admin debe existir en la tabla admins."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT username FROM admins WHERE username = ?", (TEST_USER,)
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["username"], TEST_USER)

    def test_admin_password_verifies(self):
        """La contraseña del admin debe verificar correctamente."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT password_hash FROM admins WHERE username = ?", (TEST_USER,)
            ).fetchone()
        self.assertTrue(verify_password(TEST_PASS, row["password_hash"]))

    def test_serialize_property(self):
        """serialize_property convierte amenities y featured correctamente."""
        from db import serialize_property
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM properties LIMIT 1").fetchone()
        data = serialize_property(row)
        self.assertIsInstance(data["amenities"], list)
        self.assertIsInstance(data["featured"], bool)
        self.assertIn("title", data)
        self.assertIn("city", data)

    def test_property_types_valid(self):
        """Todas las propiedades semilla son 'apartamento' o 'casa'."""
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT property_type FROM properties").fetchall()
        types = {r["property_type"] for r in rows}
        self.assertTrue(types.issubset({"apartamento", "casa"}))

    def test_property_cities_valid(self):
        """Todas las propiedades semilla son de 'medellin' o 'bogota'."""
        with self._conn() as conn:
            rows = conn.execute("SELECT DISTINCT city FROM properties").fetchall()
        cities = {r["city"] for r in rows}
        self.assertTrue(cities.issubset({"medellin", "bogota"}))


# ══════════════════════════════════════════════════════════════
# D) Tests de integración E2E (server.py)
# ══════════════════════════════════════════════════════════════
class TestServerIntegration(unittest.TestCase):
    """Tests E2E contra el servidor HTTP corriendo en un puerto aleatorio."""

    @classmethod
    def setUpClass(cls):
        # Configurar entorno de prueba
        cls._tmpdir = tempfile.mkdtemp(prefix="jg_e2e_")
        cls._db_path = Path(cls._tmpdir) / "e2e.db"

        os.environ["ADMIN_USER"] = TEST_USER
        os.environ["ADMIN_PASSWORD"] = TEST_PASS
        os.environ["SESSION_SECRET"] = TEST_SECRET
        os.environ["DB_PATH"] = str(cls._db_path)

        cls._settings = Settings(
            port=0,
            db_path=cls._db_path,
            admin_user=TEST_USER,
            admin_password=TEST_PASS,
            session_secret=TEST_SECRET,
            contact_email="test@jginmobiliaria.com",
            whatsapp_number="573114436916",
            whatsapp_display="+57 311 443 6916",
        )

        from db import init_db
        init_db(cls._settings)

        # Importar handler y configurar settings
        from server import JGRequestHandler

        class TestHandler(JGRequestHandler):
            pass
        TestHandler.settings = cls._settings

        # Levantar servidor en un puerto aleatorio
        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        cls._port = cls._server.server_address[1]
        cls._base = f"http://127.0.0.1:{cls._port}"
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

        # Opener sin proxy (evita que el proxy del sistema intercepte loopback)
        cls._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ── Helpers ──────────────────────────────────────────────
    def _request(self, method, path, data=None, headers=None, expect_json=True):
        """Hace una petición HTTP y devuelve (status_code, body_dict, response_headers)."""
        url = f"{self._base}{path}"
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            resp = self._opener.open(req, timeout=10)
            status = resp.status
            raw = resp.read()
            resp_headers = dict(resp.headers)
        except urllib.error.HTTPError as e:
            status = e.code
            raw = e.read()
            resp_headers = dict(e.headers)
        if expect_json and raw:
            return status, json.loads(raw.decode("utf-8")), resp_headers
        return status, raw, resp_headers

    def _admin_login(self):
        """Hace login y devuelve el cookie header."""
        status, body, headers = self._request("POST", "/api/admin/login", {
            "username": TEST_USER,
            "password": TEST_PASS,
        })
        self.assertEqual(status, 200)
        cookie = headers.get("Set-Cookie", "")
        # Extraer solo la parte nombre=valor
        return cookie.split(";")[0] if cookie else ""

    # ── Tests públicos ──────────────────────────────────────
    def test_01_health(self):
        """GET /api/health → 200 con status ok."""
        status, body, _ = self._request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "jg-inmobiliaria")

    def test_02_index_page(self):
        """GET / → 200 con contenido HTML."""
        status, raw, headers = self._request("GET", "/", expect_json=False)
        self.assertEqual(status, 200)
        self.assertIn(b"JG", raw.upper())

    def test_03_admin_page(self):
        """GET /admin → 200 con contenido HTML del panel."""
        status, raw, headers = self._request("GET", "/admin", expect_json=False)
        self.assertEqual(status, 200)
        self.assertIn(b"admin", raw.lower())

    def test_04_config(self):
        """GET /api/config → datos de contacto correctos."""
        status, body, _ = self._request("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertIn("contact_email", body)
        self.assertIn("whatsapp_number", body)
        self.assertTrue(body["only_housing"])

    def test_05_list_properties(self):
        """GET /api/properties → 6 propiedades semilla."""
        status, body, _ = self._request("GET", "/api/properties")
        self.assertEqual(status, 200)
        self.assertIn("properties", body)
        self.assertEqual(len(body["properties"]), 6)

    def test_06_get_property(self):
        """GET /api/properties/1 → inmueble válido."""
        status, body, _ = self._request("GET", "/api/properties/1")
        self.assertEqual(status, 200)
        self.assertIn("property", body)
        self.assertIn("title", body["property"])

    def test_07_get_property_not_found(self):
        """GET /api/properties/9999 → 404."""
        status, body, _ = self._request("GET", "/api/properties/9999")
        self.assertEqual(status, 404)

    def test_08_get_property_invalid_id(self):
        """GET /api/properties/abc → 400."""
        status, body, _ = self._request("GET", "/api/properties/abc")
        self.assertEqual(status, 400)

    # ── Tests de autenticación admin ────────────────────────
    def test_10_login_wrong_password(self):
        """Login con contraseña incorrecta → 401."""
        status, body, _ = self._request("POST", "/api/admin/login", {
            "username": TEST_USER,
            "password": "clave_incorrecta",
        })
        self.assertEqual(status, 401)
        self.assertIn("error", body)

    def test_11_login_correct(self):
        """Login correcto → 200 + cookie de sesión."""
        status, body, headers = self._request("POST", "/api/admin/login", {
            "username": TEST_USER,
            "password": TEST_PASS,
        })
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["username"], TEST_USER)
        self.assertIn("Set-Cookie", headers)
        self.assertIn("jg_admin_session", headers["Set-Cookie"])

    def test_12_login_empty_fields(self):
        """Login sin campos → 400."""
        status, body, _ = self._request("POST", "/api/admin/login", {
            "username": "",
            "password": "",
        })
        self.assertEqual(status, 400)

    def test_13_admin_me_no_auth(self):
        """GET /api/admin/me sin cookie → 401."""
        status, body, _ = self._request("GET", "/api/admin/me")
        self.assertEqual(status, 401)

    def test_14_admin_me_with_auth(self):
        """GET /api/admin/me con cookie válida → 200."""
        cookie = self._admin_login()
        status, body, _ = self._request("GET", "/api/admin/me",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(body["username"], TEST_USER)

    # ── Tests del dashboard ─────────────────────────────────
    def test_20_dashboard_no_auth(self):
        """Dashboard sin autenticación → 401."""
        status, body, _ = self._request("GET", "/api/admin/dashboard")
        self.assertEqual(status, 401)

    def test_21_dashboard_with_auth(self):
        """Dashboard autenticado → 200 con stats y charts."""
        cookie = self._admin_login()
        status, body, _ = self._request("GET", "/api/admin/dashboard",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        # Verificar estructura de stats
        self.assertIn("stats", body)
        stats = body["stats"]
        self.assertIn("total_properties", stats)
        self.assertIn("total_income_cop", stats)
        self.assertIn("conversion_rate", stats)
        self.assertIn("average_ticket", stats)
        # Verificar charts
        self.assertIn("charts", body)
        charts = body["charts"]
        self.assertIn("monthly_income", charts)
        self.assertIn("operation_distribution", charts)
        self.assertIn("city_distribution", charts)
        self.assertIn("top_properties", charts)
        # monthly_income tiene formato {labels, values}
        self.assertIn("labels", charts["monthly_income"])
        self.assertIn("values", charts["monthly_income"])

    def test_22_dashboard_date_filter(self):
        """Dashboard con filtro de fecha funciona sin error."""
        cookie = self._admin_login()
        status, body, _ = self._request(
            "GET", "/api/admin/dashboard?from=2026-01-01&to=2026-12-31",
            headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("stats", body)

    # ── Tests de cotizaciones (reservaciones) ───────────────
    def test_30_create_reservation(self):
        """Crear una reserva válida → 201 con order_code."""
        # Obtener un property_id válido
        status, body, _ = self._request("GET", "/api/properties")
        prop_id = body["properties"][0]["id"]

        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Juan Test",
            "customer_doc": "1234567890",
            "customer_email": "juan@test.com",
            "customer_phone": "3001234567",
            "customer_city": "Medellín",
            "payment_method": "transferencia",
            "property_ids": [prop_id],
        })
        self.assertEqual(status, 201)
        self.assertIn("reservation", body)
        self.assertIn("order_code", body["reservation"])
        self.assertTrue(body["reservation"]["order_code"].startswith("JG-"))
        self.assertIn("whatsapp_url", body["reservation"])
        self._order_code = body["reservation"]["order_code"]

    def test_31_create_reservation_missing_fields(self):
        """Reserva sin campos requeridos → 400."""
        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "",
            "customer_doc": "",
            "customer_email": "",
            "customer_phone": "",
            "customer_city": "",
            "payment_method": "transferencia",
            "property_ids": [1],
        })
        self.assertEqual(status, 400)

    def test_32_create_reservation_invalid_email(self):
        """Reserva con email inválido → 400."""
        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Test",
            "customer_doc": "123",
            "customer_email": "noesunemail",
            "customer_phone": "300123",
            "customer_city": "Bogotá",
            "payment_method": "tarjeta",
            "property_ids": [1],
        })
        self.assertEqual(status, 400)

    def test_33_create_reservation_invalid_payment(self):
        """Reserva con método de pago inválido → 400."""
        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Test",
            "customer_doc": "123",
            "customer_email": "test@x.com",
            "customer_phone": "300123",
            "customer_city": "Bogotá",
            "payment_method": "bitcoin",
            "property_ids": [1],
        })
        self.assertEqual(status, 400)

    def test_34_create_reservation_no_properties(self):
        """Reserva sin propiedades → 400."""
        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Test",
            "customer_doc": "123",
            "customer_email": "test@x.com",
            "customer_phone": "300123",
            "customer_city": "Bogotá",
            "payment_method": "tarjeta",
            "property_ids": [],
        })
        self.assertEqual(status, 400)

    def test_35_create_reservation_nonexistent_property(self):
        """Reserva con property_id inexistente → 404."""
        status, body, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Test",
            "customer_doc": "123",
            "customer_email": "test@x.com",
            "customer_phone": "300123",
            "customer_city": "Bogotá",
            "payment_method": "tarjeta",
            "property_ids": [99999],
        })
        self.assertEqual(status, 404)

    # ── Tests de mensajes (inquiries) ───────────────────────
    def test_40_create_inquiry(self):
        """Crear un mensaje de contacto → 201."""
        status, body, _ = self._request("POST", "/api/inquiries", {
            "name": "María Test",
            "phone": "3109876543",
            "email": "maria@test.com",
            "city": "Medellín",
            "message": "Estoy interesada en el penthouse.",
            "source": "contacto",
        })
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])

    def test_41_create_inquiry_missing_fields(self):
        """Mensaje sin nombre ni teléfono → 400."""
        status, body, _ = self._request("POST", "/api/inquiries", {
            "name": "",
            "phone": "",
        })
        self.assertEqual(status, 400)

    # ── Tests CRUD admin de propiedades ─────────────────────
    def test_50_admin_create_property(self):
        """Admin crea un inmueble → 201."""
        cookie = self._admin_login()
        status, body, _ = self._request("POST", "/api/admin/properties",
                                        data=SAMPLE_PROPERTY,
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 201)
        self.assertIn("property", body)
        self.__class__._created_prop_id = body["property"]["id"]
        self.assertEqual(body["property"]["title"], SAMPLE_PROPERTY["title"])

    def test_51_admin_create_property_no_auth(self):
        """Crear inmueble sin auth → 401."""
        status, body, _ = self._request("POST", "/api/admin/properties",
                                        data=SAMPLE_PROPERTY)
        self.assertEqual(status, 401)

    def test_52_admin_update_property(self):
        """Admin actualiza un inmueble → 200."""
        cookie = self._admin_login()
        prop_id = getattr(self.__class__, "_created_prop_id", 1)
        updated = dict(SAMPLE_PROPERTY)
        updated["title"] = "Inmueble Actualizado Test"
        updated["price"] = 600000000
        status, body, _ = self._request("PUT", f"/api/admin/properties/{prop_id}",
                                        data=updated,
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(body["property"]["title"], "Inmueble Actualizado Test")

    def test_53_admin_update_property_not_found(self):
        """Actualizar inmueble inexistente → 404."""
        cookie = self._admin_login()
        updated = dict(SAMPLE_PROPERTY)
        status, body, _ = self._request("PUT", "/api/admin/properties/99999",
                                        data=updated,
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 404)

    def test_54_admin_delete_property(self):
        """Admin elimina un inmueble → 200."""
        cookie = self._admin_login()
        prop_id = getattr(self.__class__, "_created_prop_id", None)
        if prop_id is None:
            self.skipTest("No hay inmueble creado por test_50")
        status, body, _ = self._request("DELETE", f"/api/admin/properties/{prop_id}",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_55_admin_delete_not_found(self):
        """Eliminar inmueble inexistente → 404."""
        cookie = self._admin_login()
        status, body, _ = self._request("DELETE", "/api/admin/properties/99999",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 404)

    def test_56_admin_create_property_invalid(self):
        """Crear inmueble con datos inválidos → 400."""
        cookie = self._admin_login()
        status, body, _ = self._request("POST", "/api/admin/properties",
                                        data={"title": ""},
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 400)

    # ── Tests de cotizaciones admin ─────────────────────────
    def test_60_admin_reservations_list(self):
        """Admin lista cotizaciones → 200."""
        cookie = self._admin_login()
        status, body, _ = self._request("GET", "/api/admin/reservations",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("reservations", body)
        self.assertIsInstance(body["reservations"], list)

    def test_61_admin_update_reservation_status(self):
        """Admin actualiza estado de cotización."""
        cookie = self._admin_login()
        # Primero crear una reserva
        status, props, _ = self._request("GET", "/api/properties")
        prop_id = props["properties"][0]["id"]
        status, res, _ = self._request("POST", "/api/reservations", {
            "customer_name": "Test Status",
            "customer_doc": "999",
            "customer_email": "status@test.com",
            "customer_phone": "300999",
            "customer_city": "Bogotá",
            "payment_method": "whatsapp",
            "property_ids": [prop_id],
        })
        # Buscar el ID de la reserva
        status, all_res, _ = self._request("GET", "/api/admin/reservations",
                                           headers={"Cookie": cookie})
        res_id = all_res["reservations"][0]["id"]
        # Actualizar a aprobado
        status, body, _ = self._request("PATCH", f"/api/admin/reservations/{res_id}",
                                        data={"status": "aprobado"},
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "aprobado")

    # ── Tests de bandeja de mensajes admin ──────────────────
    def test_65_admin_inquiries_list(self):
        """Admin lista mensajes → 200."""
        cookie = self._admin_login()
        status, body, _ = self._request("GET", "/api/admin/inquiries",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("inquiries", body)

    def test_66_admin_update_inquiry_status(self):
        """Admin marca mensaje como atendido."""
        cookie = self._admin_login()
        # Crear un inquiry primero
        self._request("POST", "/api/inquiries", {
            "name": "Test Inquiry",
            "phone": "300111",
            "message": "Consulta test",
        })
        # Obtener lista
        status, body, _ = self._request("GET", "/api/admin/inquiries",
                                        headers={"Cookie": cookie})
        inq_id = body["inquiries"][0]["id"]
        # Marcar como atendido
        status, body, _ = self._request("PATCH", f"/api/admin/inquiries/{inq_id}",
                                        data={"status": "atendido"},
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    # ── Tests de visitas ────────────────────────────────────
    def test_70_track_visit(self):
        """POST /api/visits → 201."""
        status, body, _ = self._request("POST", "/api/visits", {
            "page": "/",
            "referrer": "https://google.com",
        })
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])

    def test_71_admin_visits(self):
        """Admin ve métricas de visitas → 200."""
        cookie = self._admin_login()
        # Registrar otra visita primero
        self._request("POST", "/api/visits", {"page": "/admin", "referrer": ""})
        status, body, _ = self._request("GET", "/api/admin/visits",
                                        headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("total_visits", body)
        self.assertGreaterEqual(body["total_visits"], 1)
        self.assertIn("by_page", body)
        self.assertIn("by_device", body)

    # ── Tests del reporte CSV ───────────────────────────────
    def test_80_admin_csv_export(self):
        """Admin exporta CSV → 200 con content-type text/csv."""
        cookie = self._admin_login()
        status, raw, headers = self._request(
            "GET", "/api/admin/reports/csv",
            headers={"Cookie": cookie}, expect_json=False)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", headers.get("Content-Type", ""))
        self.assertIn("Content-Disposition", headers)
        # Verificar que el CSV tiene el encabezado correcto
        lines = raw.decode("utf-8-sig").strip().splitlines()
        self.assertGreaterEqual(len(lines), 1)
        self.assertIn("Código", lines[0])

    def test_81_admin_csv_no_auth(self):
        """CSV sin autenticación → 401."""
        status, body, _ = self._request("GET", "/api/admin/reports/csv")
        self.assertEqual(status, 401)

    # ── Tests de logout ─────────────────────────────────────
    def test_90_logout(self):
        """POST /api/admin/logout → 200 y borra cookie."""
        status, body, headers = self._request("POST", "/api/admin/logout")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("Max-Age=0", headers.get("Set-Cookie", ""))

    # ── Tests de rutas no encontradas ───────────────────────
    def test_95_post_unknown_route(self):
        """POST a ruta inexistente → 404."""
        status, body, _ = self._request("POST", "/api/unknown_route", {"foo": "bar"})
        self.assertEqual(status, 404)


# ══════════════════════════════════════════════════════════════
# E) Tests de llm.py
# ══════════════════════════════════════════════════════════════
def _minimal_pdf(text: str) -> bytes:
    """PDF de una página con un stream de texto sin comprimir."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2a1"
    "78a70000000049454e44ae426082"
)


class TestLLMCrypto(unittest.TestCase):
    """Cifrado y enmascarado de API keys."""

    def test_roundtrip(self):
        import llm
        key = "sk-proj-" + "x" * 120
        enc = llm.encrypt_api_key(key, TEST_SECRET)
        self.assertNotIn("sk-proj", enc)
        self.assertEqual(llm.decrypt_api_key(enc, TEST_SECRET), key)

    def test_random_nonce(self):
        import llm
        self.assertNotEqual(llm.encrypt_api_key("abc", TEST_SECRET),
                            llm.encrypt_api_key("abc", TEST_SECRET))

    def test_wrong_secret_raises(self):
        import llm
        enc = llm.encrypt_api_key("sk-secret", TEST_SECRET)
        with self.assertRaises(ValueError):
            llm.decrypt_api_key(enc, "otro-secret")

    def test_tampered_raises(self):
        import base64
        import llm
        raw = bytearray(base64.urlsafe_b64decode(llm.encrypt_api_key("sk-secret", TEST_SECRET)))
        raw[20] ^= 0x01
        with self.assertRaises(ValueError):
            llm.decrypt_api_key(base64.urlsafe_b64encode(bytes(raw)).decode(), TEST_SECRET)

    def test_garbage_raises(self):
        import llm
        with self.assertRaises(ValueError):
            llm.decrypt_api_key("no-es-base64!!", TEST_SECRET)

    def test_mask(self):
        import llm
        self.assertEqual(llm.mask_api_key("sk-123456789"), "••••6789")
        self.assertEqual(llm.mask_api_key("abc"), "••••")


class TestLLMProviders(unittest.TestCase):
    """Formato de las peticiones a cada proveedor (sin red)."""

    MESSAGES = [
        {"role": "system", "content": "Eres un asistente."},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "¿En qué te ayudo?"},
        {"role": "user", "content": "Busco apartamento"},
    ]

    def _capture(self, provider, response):
        import llm
        from unittest import mock
        with mock.patch("llm._make_request", return_value=response) as m:
            reply = llm.chat(provider, "KEY123", "modelo-x", self.MESSAGES, 0.5, 256)
        url, headers, body = m.call_args.args
        return reply, url, headers, body

    def test_openai(self):
        reply, url, headers, body = self._capture(
            "openai", {"choices": [{"message": {"content": " Respuesta "}}]})
        self.assertEqual(reply, "Respuesta")
        self.assertIn("api.openai.com", url)
        self.assertEqual(headers["Authorization"], "Bearer KEY123")
        self.assertEqual(body["messages"], self.MESSAGES)
        self.assertEqual(body["max_tokens"], 256)

    def test_anthropic_separates_system(self):
        reply, url, headers, body = self._capture(
            "anthropic", {"content": [{"text": "Hola desde Claude"}]})
        self.assertEqual(reply, "Hola desde Claude")
        self.assertEqual(headers["x-api-key"], "KEY123")
        self.assertEqual(body["system"], "Eres un asistente.")
        self.assertTrue(all(m["role"] != "system" for m in body["messages"]))

    def test_gemini_key_in_header_not_url(self):
        reply, url, headers, body = self._capture(
            "gemini", {"candidates": [{"content": {"parts": [{"text": "Hola Gemini"}]}}]})
        self.assertEqual(reply, "Hola Gemini")
        self.assertNotIn("KEY123", url)
        self.assertIn("modelo-x:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "KEY123")
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Eres un asistente.")

    def test_openrouter(self):
        reply, url, headers, body = self._capture(
            "openrouter", {"choices": [{"message": {"content": "OR"}}]})
        self.assertEqual(reply, "OR")
        self.assertIn("openrouter.ai", url)
        self.assertEqual(headers["Authorization"], "Bearer KEY123")

    def test_unknown_provider(self):
        import llm
        with self.assertRaises(ValueError):
            llm.chat("desconocido", "k", "m", self.MESSAGES)

    def test_unexpected_response_format(self):
        import llm
        from unittest import mock
        with mock.patch("llm._make_request", return_value={"inesperado": True}):
            with self.assertRaises(RuntimeError):
                llm.chat("openai", "k", "m", self.MESSAGES)


class TestLLMContext(unittest.TestCase):
    """Construcción del mensaje de sistema y extracción de PDFs."""

    PROPERTY = {
        "id": 7, "title": "Penthouse Test", "operation": "venta", "property_type": "apartamento",
        "city": "medellin", "neighborhood": "El Poblado", "price": 2650000000,
        "separation_fee": 15000000, "admin_fee": 1350000, "area_m2": 245, "bedrooms": 3,
        "bathrooms": 4, "parking": 3, "stratum": 6, "status": "disponible",
        "description": "Vista panorámica", "amenities": ["Terraza", "Gimnasio"],
    }

    def test_includes_inventory_knowledge_contact(self):
        import llm
        msg = llm.build_system_message(
            "Prompt base",
            [{"title": "Horarios", "content": "Lunes a sábado de 8 a 6."}],
            [self.PROPERTY],
            {"WhatsApp": "+57 300"},
        )
        self.assertTrue(msg.startswith("Prompt base"))
        self.assertIn("Penthouse Test", msg)
        self.assertIn("$2.650.000.000 COP", msg)
        self.assertIn("Medellín", msg)
        self.assertIn("Terraza, Gimnasio", msg)
        self.assertIn("Lunes a sábado", msg)
        self.assertIn("+57 300", msg)

    def test_empty_prompt_uses_default_and_no_inventory(self):
        import llm
        msg = llm.build_system_message("", [], [])
        self.assertIn("JG Inmobiliaria", msg)
        self.assertIn("No hay inmuebles disponibles", msg)

    def test_knowledge_truncated(self):
        import llm
        huge = [{"title": f"Doc {i}", "content": "x" * 10_000} for i in range(10)]
        msg = llm.build_system_message("P", huge, [])
        self.assertLess(len(msg), llm.MAX_KNOWLEDGE_CHARS + 1_000)

    def test_extract_pdf_text(self):
        import llm
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.pdf"
            path.write_bytes(_minimal_pdf("Requisitos de arriendo JG"))
            self.assertIn("Requisitos de arriendo JG", llm.extract_pdf_text(path))

    def test_extract_pdf_text_invalid_file(self):
        import llm
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roto.pdf"
            path.write_bytes(b"no es un pdf")
            self.assertEqual(llm.extract_pdf_text(path), "")


class TestChatRateLimit(unittest.TestCase):
    def test_blocks_after_limit(self):
        import server
        key = f"rate-test-{time.time()}"
        for _ in range(server.CHAT_RATE_LIMIT):
            self.assertFalse(server.chat_rate_limited(key))
        self.assertTrue(server.chat_rate_limited(key))


# ══════════════════════════════════════════════════════════════
# F) Tests de integración del Agente IA
# ══════════════════════════════════════════════════════════════
class TestAgentIntegration(unittest.TestCase):
    """Endpoints del agente con el LLM simulado."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="jg_agent_")
        cls._db_path = Path(cls._tmpdir) / "agent.db"
        cls._settings = Settings(
            port=0,
            db_path=cls._db_path,
            admin_user=TEST_USER,
            admin_password=TEST_PASS,
            session_secret=TEST_SECRET,
            contact_email="test@jginmobiliaria.com",
            whatsapp_number="573114436916",
            whatsapp_display="+57 311 443 6916",
        )
        from db import init_db
        init_db(cls._settings)

        import server
        server._chat_rate_hits.clear()

        class TestHandler(server.JGRequestHandler):
            pass
        TestHandler.settings = cls._settings

        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        cls._base = f"http://127.0.0.1:{cls._server.server_address[1]}"
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls._server.shutdown()
        cls._server.server_close()
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    _request = TestServerIntegration._request
    _admin_login = TestServerIntegration._admin_login

    def _admin(self, method, path, data=None, **kw):
        return self._request(method, path, data, headers={"Cookie": self._admin_login()}, **kw)

    def _conn(self):
        from db import get_connection
        return get_connection(self._db_path)

    def _activate(self, provider="openai"):
        status, body, _ = self._admin("PUT", "/api/admin/agent-config", {
            "provider": provider, "model": "", "api_key": "sk-test-secret-9876",
            "temperature": 0.3, "max_tokens": 512, "system_prompt": "Prompt de prueba", "active": True,
        })
        self.assertEqual(status, 200, body)
        return body

    def _deactivate(self):
        self._admin("PUT", "/api/admin/agent-config", {
            "provider": "openai", "clear_api_key": True, "active": False,
        })

    def tearDown(self):
        self._deactivate()

    # ── Esquema ──────────────────────────────────────────────
    def test_tables_and_default_config(self):
        with self._conn() as conn:
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            cfg = conn.execute("SELECT * FROM agent_config WHERE id = 1").fetchone()
        self.assertTrue({"agent_config", "knowledge_entries", "chat_sessions", "chat_messages"} <= tables)
        self.assertEqual(cfg["provider"], "openai")

    # ── Estado público ───────────────────────────────────────
    def test_status_inactive_and_chat_503(self):
        status, body, _ = self._request("GET", "/api/agent/status")
        self.assertEqual(status, 200)
        self.assertFalse(body["active"])
        status, body, _ = self._request("POST", "/api/chat", {"session_id": "sesion-12345", "message": "Hola"})
        self.assertEqual(status, 503)

    # ── Autenticación ────────────────────────────────────────
    def test_admin_endpoints_require_auth(self):
        for method, path, data in [
            ("GET", "/api/admin/agent-config", None),
            ("PUT", "/api/admin/agent-config", {"provider": "openai"}),
            ("GET", "/api/admin/knowledge", None),
            ("POST", "/api/admin/knowledge", {"title": "a", "content": "b"}),
            ("POST", "/api/admin/knowledge/upload", {"x": 1}),
            ("PUT", "/api/admin/knowledge/1", {"title": "a"}),
            ("DELETE", "/api/admin/knowledge/1", None),
            ("GET", "/api/admin/knowledge/1/file", None),
            ("POST", "/api/admin/agent-test", {"messages": []}),
        ]:
            status, _, _ = self._request(method, path, data)
            self.assertEqual(status, 401, f"{method} {path}")

    # ── Configuración ────────────────────────────────────────
    def test_get_default_config(self):
        status, body, _ = self._admin("GET", "/api/admin/agent-config")
        self.assertEqual(status, 200)
        self.assertEqual(set(body["providers"]), {"openai", "anthropic", "gemini", "openrouter"})
        self.assertFalse(body["config"]["has_api_key"])
        self.assertNotIn("api_key_encrypted", body["config"])

    def test_activate_without_key_rejected(self):
        status, body, _ = self._admin("PUT", "/api/admin/agent-config", {"provider": "openai", "active": True})
        self.assertEqual(status, 400)

    def test_invalid_config_values(self):
        for payload in [
            {"provider": "skynet"},
            {"provider": "openai", "temperature": 1.5},
            {"provider": "openai", "max_tokens": 10},
            {"provider": "openai", "model": "modelo con espacios"},
        ]:
            status, _, _ = self._admin("PUT", "/api/admin/agent-config", payload)
            self.assertEqual(status, 400, payload)

    def test_save_config_masks_and_encrypts_key(self):
        body = self._activate(provider="gemini")
        cfg = body["config"]
        self.assertTrue(cfg["active"])
        self.assertEqual(cfg["api_key_masked"], "••••9876")
        self.assertEqual(cfg["model"], "gemini-2.0-flash")
        self.assertNotIn("sk-test-secret-9876", json.dumps(body))
        with self._conn() as conn:
            row = conn.execute("SELECT api_key_encrypted FROM agent_config").fetchone()
        self.assertNotIn("sk-test", row["api_key_encrypted"])
        import llm
        self.assertEqual(llm.decrypt_api_key(row["api_key_encrypted"], TEST_SECRET), "sk-test-secret-9876")

        # Guardar sin api_key conserva la clave existente
        status, body, _ = self._admin("PUT", "/api/admin/agent-config", {
            "provider": "gemini", "active": True, "temperature": 0.9})
        self.assertEqual(status, 200)
        self.assertTrue(body["config"]["has_api_key"])
        status, body, _ = self._request("GET", "/api/agent/status")
        self.assertTrue(body["active"])

    # ── Base de conocimiento ─────────────────────────────────
    def test_knowledge_text_crud(self):
        status, body, _ = self._admin("POST", "/api/admin/knowledge", {"title": "FAQ", "content": "Respuesta 1"})
        self.assertEqual(status, 201)
        entry_id = body["entry"]["id"]
        self.assertEqual(body["entry"]["entry_type"], "text")

        status, body, _ = self._admin("PUT", f"/api/admin/knowledge/{entry_id}",
                                      {"title": "FAQ editada", "content": "Respuesta 2"})
        self.assertEqual(status, 200)
        self.assertEqual(body["entry"]["content"], "Respuesta 2")

        status, body, _ = self._admin("GET", "/api/admin/knowledge")
        self.assertIn(entry_id, [e["id"] for e in body["entries"]])

        status, _, _ = self._admin("DELETE", f"/api/admin/knowledge/{entry_id}")
        self.assertEqual(status, 200)
        status, _, _ = self._admin("DELETE", f"/api/admin/knowledge/{entry_id}")
        self.assertEqual(status, 404)

    def test_knowledge_text_requires_fields(self):
        status, _, _ = self._admin("POST", "/api/admin/knowledge", {"title": "", "content": "x"})
        self.assertEqual(status, 400)

    def test_upload_pdf_extracts_text_and_serves_file(self):
        import base64
        pdf = _minimal_pdf("Politica de mascotas permitidas")
        status, body, _ = self._admin("POST", "/api/admin/knowledge/upload", {
            "title": "Políticas", "filename": "politicas.pdf", "mime_type": "application/pdf",
            "data": base64.b64encode(pdf).decode(),
        })
        self.assertEqual(status, 201, body)
        entry = body["entry"]
        self.assertEqual(entry["entry_type"], "pdf")
        self.assertTrue(entry["has_file"])
        self.assertIn("mascotas", entry["content"])
        self.assertNotIn("warning", body)

        status, raw, headers = self._admin("GET", f"/api/admin/knowledge/{entry['id']}/file", expect_json=False)
        self.assertEqual(status, 200)
        self.assertEqual(raw, pdf)
        self.assertIn("application/pdf", headers.get("Content-Type", ""))

        stored = list((self._db_path.parent / "uploads" / "knowledge").iterdir())
        self.assertEqual(len(stored), 1)
        self._admin("DELETE", f"/api/admin/knowledge/{entry['id']}")
        self.assertFalse(stored[0].exists())

    def test_upload_image_without_description_warns(self):
        import base64
        status, body, _ = self._admin("POST", "/api/admin/knowledge/upload", {
            "title": "Fachada", "filename": "fachada.png", "mime_type": "image/png",
            "data": base64.b64encode(PNG_1PX).decode(),
        })
        self.assertEqual(status, 201)
        self.assertEqual(body["entry"]["entry_type"], "image")
        self.assertIn("warning", body)
        self._admin("DELETE", f"/api/admin/knowledge/{body['entry']['id']}")

    def test_upload_rejects_bad_files(self):
        import base64
        cases = [
            {"mime_type": "application/x-msdownload", "data": base64.b64encode(b"MZ...").decode()},
            {"mime_type": "image/png", "data": base64.b64encode(b"<script>").decode()},
            {"mime_type": "application/pdf", "data": "@@no-base64@@"},
            {"mime_type": "application/pdf", "data": ""},
        ]
        for case in cases:
            status, _, _ = self._admin("POST", "/api/admin/knowledge/upload",
                                       {"title": "x", "filename": "x", **case})
            self.assertEqual(status, 400, case["mime_type"])

    # ── Chat público ─────────────────────────────────────────
    def test_chat_validation(self):
        self._activate()
        status, _, _ = self._request("POST", "/api/chat", {"session_id": "corto", "message": "Hola"})
        self.assertEqual(status, 400)
        status, _, _ = self._request("POST", "/api/chat", {"session_id": "sesion-valida-1", "message": ""})
        self.assertEqual(status, 400)
        status, _, _ = self._request("POST", "/api/chat",
                                     {"session_id": "sesion-valida-1", "message": "x" * 1001})
        self.assertEqual(status, 400)

    def test_chat_uses_context_and_history(self):
        from unittest import mock
        self._activate(provider="anthropic")
        self._admin("POST", "/api/admin/knowledge", {"title": "Horario", "content": "Atendemos sábados."})

        with mock.patch("llm.chat", side_effect=["Primera respuesta", "Segunda respuesta"]) as fake:
            status, body, _ = self._request("POST", "/api/chat",
                                            {"session_id": "sesion-historial-1", "message": "Hola"})
            self.assertEqual(status, 200)
            self.assertEqual(body["reply"], "Primera respuesta")
            status, body, _ = self._request("POST", "/api/chat",
                                            {"session_id": "sesion-historial-1", "message": "¿Abren sábados?"})
            self.assertEqual(body["reply"], "Segunda respuesta")

        provider, api_key, model, messages = fake.call_args.args
        self.assertEqual(provider, "anthropic")
        self.assertEqual(api_key, "sk-test-secret-9876")
        self.assertEqual(model, "claude-sonnet-4-20250514")
        self.assertEqual(fake.call_args.kwargs["temperature"], 0.3)
        system = messages[0]["content"]
        self.assertIn("Prompt de prueba", system)
        self.assertIn("Penthouse Skyview Poblado", system)
        self.assertIn("Atendemos sábados.", system)
        self.assertEqual([m["role"] for m in messages[1:]], ["user", "assistant", "user"])

        with self._conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
                "WHERE s.session_id = 'sesion-historial-1'").fetchone()[0]
        self.assertEqual(count, 4)

    def test_chat_provider_error_returns_502(self):
        from unittest import mock
        self._activate()
        with mock.patch("llm.chat", side_effect=RuntimeError("Error 401 del proveedor LLM")):
            status, body, _ = self._request("POST", "/api/chat",
                                            {"session_id": "sesion-error-1", "message": "Hola"})
        self.assertEqual(status, 502)
        self.assertNotIn("401", body["error"])
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
                "WHERE s.session_id = 'sesion-error-1'").fetchone()
        self.assertEqual(row[0], 0)

    # ── Chat de prueba (admin) ───────────────────────────────
    def test_agent_test_without_key(self):
        status, body, _ = self._admin("POST", "/api/admin/agent-test",
                                      {"messages": [{"role": "user", "content": "Hola"}]})
        self.assertEqual(status, 502)
        self.assertIn("API key", body["error"])

    def test_agent_test_replies_when_inactive(self):
        from unittest import mock
        self._activate()
        self._admin("PUT", "/api/admin/agent-config", {"provider": "openai", "active": False})
        with mock.patch("llm.chat", return_value="Respuesta de prueba"):
            status, body, _ = self._admin("POST", "/api/admin/agent-test", {"messages": [
                {"role": "user", "content": "Hola"},
                {"role": "assistant", "content": "¡Hola!"},
                {"role": "user", "content": "¿Qué tienen en Bogotá?"},
            ]})
        self.assertEqual(status, 200)
        self.assertEqual(body["reply"], "Respuesta de prueba")

    def test_agent_test_requires_user_last(self):
        status, _, _ = self._admin("POST", "/api/admin/agent-test",
                                   {"messages": [{"role": "assistant", "content": "Hola"}]})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
