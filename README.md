# JG Inmobiliaria — Plataforma E-Commerce de Viviendas

Plataforma web (frontend + backend + panel administrador) para la administración, venta y arriendo de viviendas en Medellín y Bogotá, basada en el sistema de diseño del mockup incluido.

## Requisitos
- Python 3.10 o superior (usa únicamente la librería estándar, incluyendo SQLite).

## Configuración de variables de entorno
1. Copia `.env.example` como `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edita `.env` y asigna tu usuario administrador (`ADMIN_USER`), contraseña (`ADMIN_PASSWORD`) y una clave secreta larga (`SESSION_SECRET`).
   - El archivo `.env` y la base de datos `*.db` están incluidos en `.gitignore` para no subirse nunca a GitHub.

## Ejecución
```bash
python3 backend/server.py
```

- Tienda pública: `http://localhost:8080`
- Panel administrador: `http://localhost:8080/admin`

