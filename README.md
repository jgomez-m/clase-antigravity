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

## Agente conversacional IA
1. En el panel administrador abre **Agente IA**, elige el proveedor (OpenAI, Anthropic, Gemini u OpenRouter), pega tu API key y guarda.
2. Prueba el agente en el **Chat de prueba** y, cuando responda bien, marca **Agente activo en la web pública**.
3. Alimenta la **Base de conocimiento** con textos, PDFs o imágenes con descripción. El inventario disponible se incluye automáticamente.

- La API key se guarda cifrada con `SESSION_SECRET`; si cambias esa variable debes volver a ingresar la key.
- Para extraer mejor el texto de los PDFs instala `pdftotext` (`brew install poppler`); sin él se usa un extractor básico.
- Los archivos subidos quedan en `backend/uploads/` (excluido de git).

## Pruebas
```bash
cd backend && python3 -m unittest tests -v
```


## Estilos de la tienda (Tailwind)
La tienda usa `frontend/css/tailwind.css`, ya compilado y versionado (no depende de ningún CDN). Si agregas clases nuevas en `index.html` o `app.js`, recompílalo:
```bash
cd tailwind && npm i tailwindcss@3 @tailwindcss/forms @tailwindcss/container-queries && npx tailwindcss -c tailwind.config.js -i input.css -o ../frontend/css/tailwind.css --minify
```
