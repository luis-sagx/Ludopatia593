# Runbook de despliegue en Railway — Ludopatia593

> Documento operativo para **quien hace el despliegue**. Objetivo: dejar la app en producción en Railway de forma segura, con todos los controles de `docs/security/` activos. Lee esto completo antes de tocar Railway.
>
> _Última actualización: 2026-07-19._

---

## 0. Antes de nada: ¿esto tiene CI/CD?

- **CD (entrega continua): sí, parcial.** Railway redepliega automáticamente cada vez que se hace *push* a la rama conectada (usa `backend/railway.toml` y `frontend/railway.toml`, builder = Dockerfile). No hay que desplegar a mano tras el setup inicial.
- **CI (integración continua): sí, implementado** en `.github/workflows/ci.yml`. En cada push/PR corre: (1) **pytest con cobertura** (gate 80%, config en `backend/pytest.ini`), (2) **build** de ambas imágenes Docker, (3) **Trivy** escaneando ambas imágenes (falla ante vulns HIGH/CRITICAL con parche). Los resultados de Trivy suben a la pestaña *Security* del repo.
- **Implicación práctica:** la CI es la primera puerta de calidad. Aun así, antes de un push conviene correr los tests localmente:
  ```bash
  # suite completa con cobertura (sin Docker; usa SQLite)
  cd backend && ./.venv/bin/python -m pytest
  # build de las dos imágenes
  docker compose build
  ```

---

## 1. Arquitectura de servicios en Railway

Cuatro servicios dentro de un mismo proyecto Railway:

| Servicio | Tipo | Origen | Puerto interno |
|---|---|---|---|
| `db` | Postgres 16 (plugin gestionado de Railway) | Railway Add-on | 5432 |
| `redis` | Redis 7 (plugin gestionado de Railway) | Railway Add-on | 6379 |
| `backend` | FastAPI (Docker) | carpeta `backend/` (root dir del servicio) | 8000 |
| `frontend` | Next.js (Docker) | carpeta `frontend/` (root dir del servicio) | 3000 |

> El `docker-compose.yml` del repo es **solo para local**. En Railway cada servicio se despliega por separado; Postgres y Redis son add-ons gestionados, no los contenedores del compose.

---

## 2. Prerrequisitos

- Cuenta en Railway con acceso al proyecto.
- Repo conectado a Railway (GitHub).
- `openssl` disponible para generar secretos.
- Acceso para definir variables en cada servicio (Settings → Variables).

---

## 3. Paso a paso

### 3.1 Crear el proyecto y los add-ons de datos
1. Crear un proyecto nuevo en Railway.
2. Añadir add-on **PostgreSQL** → Railway crea la variable `DATABASE_URL` en ese servicio.
3. Añadir add-on **Redis** → Railway crea `REDIS_URL` (incluye contraseña).

### 3.2 Servicio backend
1. New Service → Deploy from repo → seleccionar el repo.
2. Settings → **Root Directory** = `backend`.
3. Railway detecta `backend/railway.toml` (builder Dockerfile, healthcheck `/health`).
4. Definir variables (sección 4.1).
5. **Reference variables** para no copiar secretos a mano: en Railway puedes referenciar `${{Postgres.DATABASE_URL}}` y `${{Redis.REDIS_URL}}` desde el servicio backend.

### 3.3 Servicio frontend
1. New Service → Deploy from repo → mismo repo.
2. Settings → **Root Directory** = `frontend`.
3. Railway detecta `frontend/railway.toml` (Dockerfile, healthcheck `/`).
4. Definir variables (sección 4.2).
5. **Importante:** `NEXT_PUBLIC_API_URL` es **build-time** (se hornea en el bundle). Debe existir *antes* del build; si la cambias luego, hay que **redeploy con rebuild**.

### 3.4 Dominios
1. En backend → Settings → Networking → generar dominio público (`https://<backend>.up.railway.app`).
2. En frontend → igual (`https://<frontend>.up.railway.app`).
3. Con esas dos URLs completas, volver a la sección 4 y fijar `CORS_ORIGINS` (backend) y `NEXT_PUBLIC_API_URL` (frontend).

---

## 4. Variables de entorno (exactas)

### 4.1 Backend

| Variable | Valor | Obligatoria | Nota de seguridad |
|---|---|---|---|
| `ENVIRONMENT` | `production` | ✅ | **Imprescindible.** Activa HSTS, oculta `/docs`/`/redoc`/`/openapi`, fuerza cookies `Secure`, y el fail-fast del `JWT_SECRET`. |
| `JWT_SECRET` | salida de `openssl rand -hex 32` | ✅ | Nunca pegarlo en chat/commit. Si es el default o <32 chars, el backend **no arranca**. |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | ✅ | El código normaliza `postgres://` → driver psycopg2 automáticamente. |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` | ✅ | Incluye contraseña (Railway Redis la trae). |
| `CORS_ORIGINS` | `https://<frontend>.up.railway.app` | ✅ | Dominio **exacto** del frontend, sin `*`. Admite lista separada por comas. |
| `ADMIN_EMAIL` | ej. `admin@tudominio.com` | ✅ | Cuenta admin sembrada al arranque. |
| `ADMIN_PASSWORD` | contraseña fuerte | ✅ | Sin ella el `seed` aborta (`SystemExit`). |
| `FOOTBALL_DATA_API_KEY` | tu API key | ⬜ | Opcional; vacío → usa dataset local. |
| `DEMO_PASSWORD` | **NO definir** | ⬜ | Si se define, siembra 7 cuentas demo con credencial compartida (AST-11). Dejar sin definir en producción. |

### 4.2 Frontend

| Variable | Valor | Obligatoria | Nota |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://<backend>.up.railway.app` | ✅ | **Build-time.** URL pública del backend (el navegador la llama directo). Cambiarla exige rebuild. |
| `NEXT_PUBLIC_DEMO_ACCOUNTS` | **NO definir** | ⬜ | Default `0` → login sin credenciales visibles. Definir `1` solo expondría cuentas demo. |

---

## 5. Nota importante sobre el rol de Postgres (`app_runtime`)

En **local con compose**, la app se conecta con un rol sin privilegios elevados (`app_runtime`, creado por `backend/db-init/10-create-app-runtime-role.sh`). Ese script **solo corre en el contenedor Postgres del compose** — en el **Postgres gestionado de Railway NO se ejecuta**.

En Railway, `DATABASE_URL` usa el usuario que provee el add-on, que es **dueño de la base** pero no superusuario del clúster compartido — aceptable para este proyecto. Si se quiere replicar el hardening de mínimo privilegio, es una acción **manual opcional**:

1. Railway → Postgres → Query / Data → ejecutar el SQL equivalente al del script (`CREATE ROLE app_runtime ... NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION` + grants).
2. Cambiar `DATABASE_URL` del backend para usar `app_runtime`.

No es bloqueante para el despliegue; documentarlo como deuda si no se hace.

---

## 6. Orden de despliegue

1. Postgres y Redis primero (add-ons; quedan listos casi al instante).
2. Backend (espera a que el healthcheck `/health` pase; el arranque entrena el modelo + siembra la DB, tarda unos segundos).
3. Frontend (necesita `NEXT_PUBLIC_API_URL` apuntando al backend ya con dominio).

> **Esquema de BD:** el modelo usa `Base.metadata.create_all` (sin migraciones Alembic activas). En una base **vacía** crea todo bien. Si la base ya existía de un deploy anterior con esquema viejo (p.ej. sin la columna `round_order`), hay que **recrearla** (borrar y dejar que el seed la regenere) — `create_all` no altera tablas existentes.

---

## 7. Verificación de seguridad post-deploy (obligatoria)

Ejecutar y **guardar la salida** como evidencia:

```bash
BACK=https://<backend>.up.railway.app
FRONT=https://<frontend>.up.railway.app

# 1. Redirección a HTTPS + HSTS
curl -I http://${BACK#https://}                 # espera 301/308 -> https
curl -sI $BACK/health | grep -i strict-transport-security   # presente

# 2. Ofuscación de versiones
curl -s -o /dev/null -w "docs=%{http_code}\n"     $BACK/docs          # 404
curl -s -o /dev/null -w "openapi=%{http_code}\n"  $BACK/openapi.json  # 404
curl -sI $BACK/health | grep -i '^server:'                            # server: ludopatia593 (sin uvicorn)
curl -sI $FRONT | grep -i x-powered-by                                # ausente

# 3. Rate limiting (login, límite 5/min)
for i in $(seq 1 8); do curl -s -o /dev/null -w "%{http_code} " \
  -X POST $BACK/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"x@x.com","password":"nope12345"}'; done; echo   # ...401 x5 -> 429

# 4. Cuentas demo ocultas en el login
curl -s $FRONT/login | grep -c "demo.io"        # 0

# 5. CORS restringido (origen no permitido no recibe ACAO)
curl -sI -H "Origin: https://evil.example" $BACK/health | grep -i access-control-allow-origin  # vacío
```

Checklist de cierre:
- [ ] HTTP redirige a HTTPS y responde `Strict-Transport-Security`.
- [ ] `/docs`, `/openapi.json`, `/redoc` → 404.
- [ ] `Server: ludopatia593`, sin `X-Powered-By` en el frontend.
- [ ] Login corta con `429` antes del 6.º intento.
- [ ] `/login` no muestra cuentas demo (0 coincidencias).
- [ ] Origen no permitido no recibe cabecera CORS.

---

## 8. Rotación de secretos y rollback

- **Rotar `JWT_SECRET`:** generar `openssl rand -hex 32`, reemplazar la variable en Railway, redeploy. Efecto: **invalida todas las sesiones** (access 15 min + refresh 7 días) — es la defensa ante sospecha de fuga, no un efecto a evitar. Ver `docs/security/Criptografia.md`.
- **Rollback:** Railway → servicio → Deployments → "Redeploy" sobre un deployment anterior sano.
- **Cambio de personal con acceso:** rotar `JWT_SECRET` y `ADMIN_PASSWORD`.

---

## 9. Pendientes operativos (no de código, requieren el panel)

- [ ] Confirmar **cifrado en reposo** del volumen de Postgres y de los backups (panel de Railway).
- [ ] **Probar una restauración** de backup al menos una vez y registrar la fecha (un backup no probado no cuenta).
- [ ] Confirmar que Postgres/Redis gestionados **no** exponen dominio público (solo red privada del proyecto).
- [ ] (Opcional) `trivy image` sobre ambas imágenes y fijar digest de las imágenes base.
- [ ] (Opcional) Enrutar los logs JSON (stdout) a un colector para buscar por `request_id`.

---

## Apéndice A — CI (ya implementado)

El pipeline vive en `.github/workflows/ci.yml` y corre en cada push/PR con tres jobs:

1. **`backend-tests`** — `pip install -r backend/requirements-dev.txt` + `pytest` con cobertura (gate 80%, definido en `backend/pytest.ini`).
2. **`docker-build`** — construye las imágenes backend y frontend y las exporta como artefacto.
3. **`trivy-scan`** — carga cada imagen y la escanea con Trivy (severidad HIGH/CRITICAL, `ignore-unfixed`); falla el build ante vulns con parche y sube el SARIF a la pestaña *Security*.

Ver el archivo para el detalle; no hace falta reproducirlo aquí.

> Es una **recomendación**, no está implementado. Si se decide adoptarlo, añadir además un job de `trivy image` para cerrar el pendiente de escaneo de vulnerabilidades de la sección 04.
