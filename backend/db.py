"""Base de datos SQLite y datos iniciales para JG Inmobiliaria."""

import json
from pathlib import Path
import sqlite3
from typing import Any

from auth import hash_password
from config import Settings
from llm import DEFAULT_SYSTEM_PROMPT, PROVIDERS


SEED_PROPERTIES = [
    {
        "title": "Penthouse Skyview Poblado",
        "slug": "penthouse-skyview-poblado",
        "operation": "venta",
        "property_type": "apartamento",
        "city": "medellin",
        "neighborhood": "El Poblado",
        "address": "Loma de Los Balsos, El Poblado, Medellín",
        "price": 2650000000,
        "separation_fee": 15000000,
        "admin_fee": 1350000,
        "area_m2": 245,
        "bedrooms": 3,
        "bathrooms": 4,
        "parking": 3,
        "stratum": 6,
        "description": "Pisos en madera natural, terraza 360° con vista panorámica al Valle de Aburrá y ascensor privado de acceso directo.",
        "amenities": ["Ascensor privado", "Terraza 360°", "Domótica", "Vigilancia 24/7", "Turco y gimnasio"],
        "image_url": "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=1200&q=80",
        "featured": 1,
        "status": "disponible",
    },
    {
        "title": "Villa Campestre Llanogrande",
        "slug": "villa-campestre-llanogrande",
        "operation": "venta",
        "property_type": "casa",
        "city": "medellin",
        "neighborhood": "Llanogrande, Rionegro",
        "address": "Sector La Fe, Llanogrande, Oriente Antioqueño",
        "price": 4800000000,
        "separation_fee": 25000000,
        "admin_fee": 1800000,
        "area_m2": 480,
        "bedrooms": 4,
        "bathrooms": 5,
        "parking": 4,
        "stratum": 6,
        "description": "Lote independiente de 2.200 m², piscina sin fin climatizada y arquitectura bioclimática en un solo nivel.",
        "amenities": ["Piscina climatizada", "Lote 2.200 m²", "Pérgola BBQ", "Casa de huéspedes", "Sendero ecológico"],
        "image_url": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=1200&q=80",
        "featured": 1,
        "status": "disponible",
    },
    {
        "title": "Residencia Alto Rosales",
        "slug": "residencia-alto-rosales",
        "operation": "arriendo",
        "property_type": "apartamento",
        "city": "bogota",
        "neighborhood": "Rosales",
        "address": "Carrera 4 # 72-40, Rosales, Bogotá D.C.",
        "price": 14500000,
        "separation_fee": 3500000,
        "admin_fee": 1450000,
        "area_m2": 165,
        "bedrooms": 2,
        "bathrooms": 3,
        "parking": 2,
        "stratum": 6,
        "description": "Chimenea de gas europea, acabados en mármol y carpintería artesanal con vista directa a los cerros orientales.",
        "amenities": ["Chimenea europea", "Vista a los cerros", "Calefacción", "Salón social", "Planta eléctrica total"],
        "image_url": "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1200&q=80",
        "featured": 1,
        "status": "disponible",
    },
    {
        "title": "Townhouse Chicó Reservado",
        "slug": "townhouse-chico-reservado",
        "operation": "venta",
        "property_type": "casa",
        "city": "bogota",
        "neighborhood": "Chicó Reservado",
        "address": "Calle 94 # 11A-28, Chicó Reservado, Bogotá D.C.",
        "price": 3900000000,
        "separation_fee": 20000000,
        "admin_fee": 1600000,
        "area_m2": 320,
        "bedrooms": 4,
        "bathrooms": 4,
        "parking": 3,
        "stratum": 6,
        "description": "Residencia urbana de cuatro niveles con jardín privado zen, terraza BBQ y automatización domótica integral.",
        "amenities": ["Jardín zen privado", "Terraza BBQ", "Domótica integral", "3 parqueaderos", "Estudio independiente"],
        "image_url": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1200&q=80",
        "featured": 1,
        "status": "disponible",
    },
    {
        "title": "Apartamento Provenza Terrace",
        "slug": "apartamento-provenza-terrace",
        "operation": "arriendo",
        "property_type": "apartamento",
        "city": "medellin",
        "neighborhood": "Provenza, El Poblado",
        "address": "Calle 10A # 36-18, Provenza, Medellín",
        "price": 11800000,
        "separation_fee": 2500000,
        "admin_fee": 980000,
        "area_m2": 138,
        "bedrooms": 2,
        "bathrooms": 3,
        "parking": 2,
        "stratum": 6,
        "description": "Apartamento amoblado de diseño contemporáneo a pasos de restaurantes y zonas verdes, ideal para ejecutivos.",
        "amenities": ["Balcón amplio", "Cocina abierta", "Coworking en edificio", "Gimnasio", "Portería 24/7"],
        "image_url": "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?auto=format&fit=crop&w=1200&q=80",
        "featured": 0,
        "status": "disponible",
    },
    {
        "title": "Casa Jardín Santa Ana Oriental",
        "slug": "casa-jardin-santa-ana-oriental",
        "operation": "arriendo",
        "property_type": "casa",
        "city": "bogota",
        "neighborhood": "Santa Ana Oriental",
        "address": "Transversal 2 # 109-35, Usaquén, Bogotá D.C.",
        "price": 18500000,
        "separation_fee": 4000000,
        "admin_fee": 1950000,
        "area_m2": 295,
        "bedrooms": 3,
        "bathrooms": 4,
        "parking": 3,
        "stratum": 6,
        "description": "Casa familiar en conjunto cerrado con vigilancia armada, patio interior cubierto y sala con doble altura.",
        "amenities": ["Conjunto cerrado", "Doble altura", "Cuarto de servicio", "Cancha de tenis", "Zona infantil"],
        "image_url": "https://images.unsplash.com/photo-1613490493576-7fde63acd811?auto=format&fit=crop&w=1200&q=80",
        "featured": 0,
        "status": "disponible",
    },
]


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Abre una conexión SQLite con filas tipo diccionario y llaves foráneas activas."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(settings: Settings) -> None:
    """Crea tablas si no existen y carga el usuario admin y propiedades iniciales."""
    with get_connection(settings.db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                operation TEXT NOT NULL CHECK (operation IN ('venta', 'arriendo')),
                property_type TEXT NOT NULL CHECK (property_type IN ('apartamento', 'casa')),
                city TEXT NOT NULL CHECK (city IN ('medellin', 'bogota')),
                neighborhood TEXT NOT NULL,
                address TEXT NOT NULL DEFAULT '',
                price INTEGER NOT NULL,
                separation_fee INTEGER NOT NULL,
                admin_fee INTEGER NOT NULL DEFAULT 0,
                area_m2 REAL NOT NULL,
                bedrooms INTEGER NOT NULL,
                bathrooms INTEGER NOT NULL,
                parking INTEGER NOT NULL DEFAULT 1,
                stratum INTEGER NOT NULL DEFAULT 6,
                description TEXT NOT NULL,
                amenities TEXT NOT NULL DEFAULT '[]',
                image_url TEXT NOT NULL DEFAULT '',
                featured INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'disponible'
                    CHECK (status IN ('disponible', 'reservado', 'arrendado', 'vendido')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT NOT NULL UNIQUE,
                customer_name TEXT NOT NULL,
                customer_doc TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_city TEXT NOT NULL,
                payment_method TEXT NOT NULL CHECK (payment_method IN ('transferencia', 'tarjeta', 'whatsapp')),
                payment_reference TEXT NOT NULL DEFAULT '',
                total_amount INTEGER NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (status IN ('pendiente', 'en_revision', 'aprobado', 'cerrado', 'cancelado')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS reservation_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reservation_id INTEGER NOT NULL,
                property_id INTEGER,
                property_title TEXT NOT NULL,
                operation TEXT NOT NULL,
                separation_fee INTEGER NOT NULL,
                FOREIGN KEY (reservation_id) REFERENCES reservations(id) ON DELETE CASCADE,
                FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS page_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                page TEXT NOT NULL DEFAULT '/',
                referrer TEXT NOT NULL DEFAULT '',
                device TEXT NOT NULL DEFAULT 'desktop',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                city TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'contacto',
                status TEXT NOT NULL DEFAULT 'nuevo' CHECK (status IN ('nuevo', 'atendido')),
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS agent_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                provider TEXT NOT NULL DEFAULT 'openai'
                    CHECK (provider IN ('openai', 'anthropic', 'gemini', 'openrouter')),
                api_key_encrypted TEXT NOT NULL DEFAULT '',
                api_key_hint TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                system_prompt TEXT NOT NULL DEFAULT '',
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 1024,
                active INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS knowledge_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                entry_type TEXT NOT NULL CHECK (entry_type IN ('text', 'pdf', 'image')),
                content TEXT NOT NULL DEFAULT '',
                file_path TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO agent_config (id, provider, model, system_prompt)
            VALUES (1, 'openai', ?, ?)
            """,
            (PROVIDERS["openai"]["default_model"], DEFAULT_SYSTEM_PROMPT),
        )

        # Sincronizar administrador principal desde variables de entorno
        pw_hash = hash_password(settings.admin_password)
        existing_admin = conn.execute(
            "SELECT id FROM admins WHERE username = ?",
            (settings.admin_user,),
        ).fetchone()
        if existing_admin:
            conn.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (pw_hash, existing_admin["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                (settings.admin_user, pw_hash),
            )

        # Cargar propiedades iniciales solo si la tabla está vacía
        count = conn.execute("SELECT COUNT(*) AS cnt FROM properties").fetchone()["cnt"]
        if count == 0:
            for item in SEED_PROPERTIES:
                conn.execute(
                    """
                    INSERT INTO properties (
                        title, slug, operation, property_type, city, neighborhood, address,
                        price, separation_fee, admin_fee, area_m2, bedrooms, bathrooms,
                        parking, stratum, description, amenities, image_url, featured, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["title"],
                        item["slug"],
                        item["operation"],
                        item["property_type"],
                        item["city"],
                        item["neighborhood"],
                        item["address"],
                        item["price"],
                        item["separation_fee"],
                        item["admin_fee"],
                        item["area_m2"],
                        item["bedrooms"],
                        item["bathrooms"],
                        item["parking"],
                        item["stratum"],
                        item["description"],
                        json.dumps(item["amenities"], ensure_ascii=False),
                        item["image_url"],
                        item["featured"],
                        item["status"],
                    ),
                )
        conn.commit()


def serialize_property(row: sqlite3.Row) -> dict[str, Any]:
    """Convierte una fila de inmueble a diccionario listo para JSON."""
    data = dict(row)
    try:
        data["amenities"] = json.loads(data.get("amenities") or "[]")
    except json.JSONDecodeError:
        data["amenities"] = []
    data["featured"] = bool(data.get("featured"))
    return data

