# Plan de acción de hardening — Ludopatia593

> Documento vivo. Deriva de una auditoría estática realizada el 2026-07-09 sobre el estado del repo en la rama `main` (commit `871ac01`). Cada sección indica **qué buscar/hallar**, la **acción concreta** a ejecutar y la **evidencia de cierre** (Definition of Done) que demuestra que el control quedó aplicado, no solo planeado.

## Contexto del proyecto (para quien no lo conoce)

- **Qué es**: plataforma de predicciones del Mundial 2026 con **puntos virtuales** (sin dinero real). Backend FastAPI (Python 3.12), frontend Next.js, Postgres 16 + Redis 7, todo sobre Docker (`docker-compose.yml` en local, despliegue en Railway vía `railway.toml` + `Dockerfile` en `backend/` y `frontend/`).
- **Autenticación**: Argon2id para passwords, JWT de acceso corto (15 min) + refresh rotatorio (7 días) con revocación por `jti`.
- **RBAC**: roles `user`/`admin`, rutas admin segregadas en `backend/app/api/admin.py` vía `require_admin`.
- **Integración externa**: football-data.org (`backend/app/services/api_football.py`) para sincronizar fixtures reales.
- **Estado previo**: ya existen controles sólidos (Argon2id, CORS restringido, rate limit global, no-root en contenedores, headers de seguridad). El trabajo de este plan es cerrar las brechas concretas identificadas, no partir de cero.

## Cómo usar este documento

Cada apartado sigue el mismo patrón:

1. **Qué buscar / hallar** — comandos y ubicaciones exactas para verificar el estado actual antes de tocar nada.
2. **Acciones concretas** — pasos ejecutables, con archivo/línea cuando aplica.
3. **Evidencia de cierre** — checklist verificable (comando, respuesta esperada), no una opinión de "ya quedó listo".

Al final hay un **prompt reutilizable** para que otra persona (o un asistente de IA) retome el análisis con el contexto completo, sin tener que reconstruirlo desde cero.

---

## ⚠️ Importante: controles condicionados al entorno (`dev` vs `production`)

Varios controles **solo se activan cuando `ENVIRONMENT=production`** (o cualquier valor distinto de `dev`). En un `docker compose up` local, que corre en `dev` por defecto, están **apagados a propósito** — esto es diseño, no un control faltante. Verificar en local (dev) y concluir "no está implementado" es un error de método: hay que probar con `ENVIRONMENT=production`.

| Control | En `dev` (local) | En `production` | Dónde |
|---|---|---|---|
| HSTS (`Strict-Transport-Security`) | ausente | presente | `main.py` (`environment != "dev"`) |
| `/docs`, `/redoc`, `/openapi.json` | **200** (accesibles) | **404** | `main.py` (`docs_url=... if _is_dev else None`) |
| Cookies de sesión `Secure` + `SameSite=None` | `secure=False`, `Lax` | `secure=True`, `None` | `auth.py::_cookie_flags` |
| Fail-fast de `JWT_SECRET` débil | permitido (default dev) | **rechaza el arranque** | `config.py::reject_weak_secret` |

Controles que **sí** están activos también en `dev` (no dependen del entorno): header `Server: ludopatia593`, `X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`, rate limiting, Redis con `--requirepass`, rol `app_runtime` no-superusuario, `cap_drop`/`read_only`/`no-new-privileges`, logging estructurado, CSRF.

### Cómo verificar en modo producción localmente

```bash
export ENVIRONMENT=production JWT_SECRET=$(openssl rand -hex 32)
docker compose up -d backend
curl -sS -D - -o /dev/null http://localhost:8080/health | grep -i strict-transport   # presente
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/docs                    # 404
docker compose up -d backend   # (sin los exports) para volver a modo dev
```

**Verificación en runtime ejecutada — 2026-07-19:** se levantó el backend con `ENVIRONMENT=production` y se confirmó empíricamente: HSTS presente; `/docs`=`/redoc`=`/openapi.json`=404; `Server: ludopatia593` (sin `uvicorn`); fail-fast del `JWT_SECRET` débil (`ValidationError`, el contenedor no arranca); Redis responde `NOAUTH Authentication required.` sin contraseña; rate limit de login corta en el 6.º intento (`401 x5` → `429`). Todos los controles descritos en las secciones 02–07 quedaron verificados también en ejecución, no solo por lectura de código.

---

## 01 · Lista de activos

### Qué buscar / hallar
```bash
# Todas las variables sensibles referenciadas en el backend
grep -rn "jwt_secret\|password\|SECRET\|_KEY\|TOKEN" backend/app/core/config.py

# Confirmar que ningún secreto está hardcodeado fuera de defaults de dev
grep -rniE "(secret|password|api_key)\s*=\s*[\"'][a-z0-9]" backend/app --include="*.py" | grep -v "dev-only-insecure"

# Todos los modelos de datos (activos de información)
cat backend/app/db/models.py | grep "^class\|Mapped\["

# Todas las integraciones externas
grep -rln "httpx\|requests\." backend/app/services/
```

### Acciones concretas
1. Ejecutar los tres comandos anteriores y confirmar 0 resultados de secretos hardcodeados fuera de `dev-only-insecure-change-me` (el default explícito de `config.py:18`, que solo debe sobrevivir en entorno `dev`).
2. Completar la tabla de activos (heredada de la auditoría) con dos columnas nuevas: **dueño responsable** y **clasificación C/I/D** (Confidencialidad / Integridad / Disponibilidad).
3. Guardar la tabla como `docs/security/asset-inventory.md`, versionada junto al código.
4. Vincular cada activo crítico a la sección de este plan que lo controla (ej. `JWT_SECRET` → sección 02; `points_balance` → sección 04/07).

### Evidencia de cierre
- [ ] `docs/security/asset-inventory.md` existe y está commiteado.
- [ ] 0 coincidencias de secretos hardcodeados en el grep anterior.
- [ ] Cada fila de la tabla tiene dueño y clasificación C/I/D asignados.

---

## 02 · Criptografía

### Qué buscar / hallar
```bash
# Único punto de uso del secreto JWT (debe ser solo core/security.py y config.py)
grep -rn "jwt_secret" backend/app

# Confirmar que el default inseguro no llega a producción
grep -n "dev-only-insecure-change-me" backend/app/core/config.py

# Verificar TLS y redirect forzado en el dominio de producción
curl -I https://<dominio-prod>
curl -I http://<dominio-prod>   # debe responder 301/308 hacia https
```

### Acciones concretas
1. Generar un secreto fuerte: `openssl rand -hex 32`.
2. Cargarlo como variable gestionada en Railway (Settings → Variables), **nunca** en un `.env` commiteado — `.env` ya está en `.gitignore`, mantenerlo así.
3. Documentar el procedimiento de rotación: como el access token dura 15 min y el refresh 7 días, rotar `JWT_SECRET` invalida todas las sesiones activas — usarlo también como respuesta ante sospecha de fuga.
4. Confirmar con `curl -I` que el dominio de producción fuerza HTTPS y devuelve `Strict-Transport-Security`.
5. Confirmar en el panel del proveedor de Postgres que el volumen y los backups están cifrados en reposo.
6. Dejar constancia explícita de lo que **ya está bien** (Argon2id, refresh rotatorio) en el inventario de la sección 01, para no re-auditarlo cada vez.

### Evidencia de cierre
- [ ] `JWT_SECRET` en producción es distinto del default de `config.py:18`.
- [ ] `curl -I http://<dominio-prod>` redirige a `https`.
- [ ] Respuesta HTTPS incluye `Strict-Transport-Security`.
- [ ] Cifrado en reposo confirmado en el panel del proveedor (captura o confirmación escrita).

---

## 03 · Logs

### Qué buscar / hallar
```bash
# Todo uso de print()/logging en la ruta de request (no en scripts CLI)
grep -rn "print(\|logging\." backend/app/api backend/app/core backend/app/main.py

# Qué guarda hoy cada AuditLog (para no romper la disciplina actual de "sin secretos")
grep -rn "AuditLog(" backend/app/api

# Confirmar que Authorization nunca se loguea
grep -rn "Authorization" backend/app
```

### Acciones concretas
1. Implementar logging estructurado JSON dentro de `security_middleware` (`backend/app/main.py:37-54`): `request_id`, IP, método, ruta, status, latencia_ms.
2. Generar `request_id` con `uuid4()` si no llega ya en un header del proxy (`X-Request-Id`).
3. Excluir explícitamente el header `Authorization` y los bodies de `/v1/auth/login`, `/v1/auth/register`, `/v1/auth/refresh` del log — como función reutilizable, no criterio manual por endpoint.
4. Propagar el mismo `request_id` hacia las escrituras de `AuditLog` para poder cruzar traza HTTP ↔ evento de negocio.
5. Fijar nivel de log por entorno: `DEBUG` solo si `settings.environment == "dev"`.

### Evidencia de cierre
- [ ] Cada request en producción genera una línea de log con `request_id`, IP, método, ruta, status, latencia.
- [ ] Prueba manual: hacer `curl` con header `Authorization: Bearer test` contra cualquier ruta y confirmar que **no aparece** en el log generado.
- [ ] `AuditLog.detail` de login/register sigue sin contener contraseñas ni tokens (revisión de las últimas 20 filas).

---

## 04 · Hardening en producción (Docker)

> El proyecto ya está construido sobre Docker (compose local + Dockerfile en Railway). Se recomienda continuar por esa vía en vez de migrar a máquina propia: el aislamiento por contenedor, las imágenes inmutables y el usuario no-root ya están resueltos por el propio Dockerfile.

### Qué buscar / hallar
```bash
# Puertos publicados
grep -n "ports:" -A2 docker-compose.yml

# Comando de arranque de Redis (¿tiene --requirepass?)
grep -n "redis-server" docker-compose.yml

# Usuario en tiempo de ejecución de cada contenedor
docker inspect ludopatia593_backend_1  --format '{{.Config.User}}'
docker inspect ludopatia593_frontend_1 --format '{{.Config.User}}'

# Grants del usuario de Postgres
docker compose exec db psql -U app -d predictor -c "\du"

# Vulnerabilidades conocidas en las imágenes
trivy image ludopatia593-backend:latest
trivy image ludopatia593-frontend:latest
```

### Acciones concretas — Puertos
1. Confirmar que `db` y `redis` siguen **sin** bloque `ports:` en `docker-compose.yml` (hoy correcto).
2. Añadir `networks:` explícitas: una red `backend-net` (backend + db + redis) separada de la red pública del frontend.
3. En Railway, confirmar que Postgres/Redis gestionados no tienen dominio público habilitado.

### Acciones concretas — Aplicación
1. Confirmar ausencia de `--reload` en `backend/start.sh` (hoy correcto) — dejarlo como check de CI.
2. Añadir `cap_drop: [ALL]`, `read_only: true` (donde el proceso no escriba en el filesystem) y `security_opt: [no-new-privileges:true]` a los servicios `backend`/`frontend` en compose.
3. Definir `deploy.resources.limits` (cpu/mem) por contenedor.
4. Añadir `healthcheck` para `backend` (`GET /health`) y `frontend`, igual que ya existe para `db`/`redis`.

### Acciones concretas — Base de datos
1. Ejecutar `\du` en psql y confirmar que el usuario `app` **no** es superusuario.
2. Automatizar backup del volumen `pgdata` (o usar el backup gestionado de Railway) y **ejecutar una restauración de prueba** — un backup nunca probado no cuenta como control.

### Acciones concretas — Periféricos (servicios auxiliares)
1. **Redis sin autenticación** (`docker-compose.yml:16-18`) — hallazgo activo, corregir:
   ```yaml
   redis:
     image: redis:7-alpine
     command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?}", "--save", "60", "1"]
   ```
   y actualizar `REDIS_URL` del backend a `redis://:${REDIS_PASSWORD}@redis:6379/0`.
2. Confirmar que no hay paneles de administración (pgAdmin, RedisInsight) desplegados de forma persistente en producción.
3. Fijar las imágenes base a un digest concreto (no solo el tag) y correr `trivy image` en CI antes de publicar.

### Evidencia de cierre
- [ ] `docker compose ps` / `docker port` muestran únicamente `8000` y `3000` publicados.
- [ ] `redis-cli -h redis ping` sin contraseña responde `NOAUTH Authentication required`.
- [ ] `docker inspect ... --format '{{.Config.User}}'` no devuelve vacío ni `root` en ningún servicio propio.
- [ ] `\du` confirma que `app` no tiene `Superuser`.
- [ ] Restauración de backup probada al menos una vez, con fecha registrada.
- [ ] `trivy image` sin vulnerabilidades `CRITICAL` sin parche disponible.

---

## 05 · Ofuscación de versiones de tecnología

### Qué buscar / hallar
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://<dominio-prod>/docs
curl -s -o /dev/null -w "%{http_code}\n" https://<dominio-prod>/openapi.json
curl -I https://<dominio-prod>/            # inspeccionar Server, X-Powered-By
curl -I https://<frontend-prod>/           # inspeccionar X-Powered-By
```

### Acciones concretas
1. Deshabilitar `/docs`, `/redoc`, `/openapi.json` fuera de `dev` (`backend/app/main.py:26`):
   ```python
   app = FastAPI(
       title=settings.app_name,
       version="0.1.0",
       docs_url="/docs" if settings.environment == "dev" else None,
       redoc_url="/redoc" if settings.environment == "dev" else None,
       openapi_url="/openapi.json" if settings.environment == "dev" else None,
       lifespan=lifespan,
   )
   ```
2. Quitar `X-Powered-By: Next.js` (`frontend/next.config.js`):
   ```js
   module.exports = { poweredByHeader: false };
   ```
3. Sobrescribir el header `Server` del backend dentro del middleware ya existente en `main.py`.
4. Confirmar que ningún `500` en producción devuelve stack trace (probar forzando un error y revisando la respuesta cruda).

### Evidencia de cierre
- [ ] `curl` a `/docs` y `/openapi.json` en producción responde `404`.
- [ ] `curl -I` no muestra `X-Powered-By` en el frontend.
- [ ] Header `Server` del backend no revela `uvicorn` ni versión.

---

## 06 · Limitar peticiones (rate limiting)

### Qué buscar / hallar
```bash
# Endpoints que ya usan el limitador (allow()) vs. los que dependen solo del límite global
grep -rn "allow(" backend/app/api/*.py backend/app/main.py
```

### Acciones concretas
1. Confirmar que Redis ya tiene auth (depende de sección 04) antes de endurecer límites — si no, el limitador es de acceso libre para cualquiera en la red interna.
2. Añadir límite específico a `POST /v1/auth/register` (`backend/app/api/auth.py:43`), hoy cubierto solo por el límite global de 60/min.
3. Añadir límite específico a `POST /v1/bets` (placeBet) para prevenir bot-farming de puntos.
4. Añadir límite reforzado sobre `/v1/admin/*` como defensa en profundidad, aunque ya esté protegido por RBAC.
5. Documentar como deuda técnica conocida que `core/ratelimit.py` usa ventana fija (permite hasta 2× el límite en el borde entre ventanas) — migrar a ventana deslizante si el tráfico lo justifica.

### Evidencia de cierre
- [ ] Prueba con `for i in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code} " -X POST .../v1/auth/register ...; done` muestra `429` antes de la iteración 10.
- [ ] Misma prueba contra `/v1/bets` confirma límite propio distinto del global.

---

## 07 · Hardening de sesiones

### Qué buscar / hallar
```bash
# Confirmar el uso actual de localStorage para tokens
grep -rn "localStorage" frontend/lib/api.ts

# Estructura actual de RefreshToken (ya tiene lo necesario para listar/revocar sesiones)
grep -n "class RefreshToken" -A8 backend/app/db/models.py
```
El propio código ya documenta el problema: `frontend/lib/api.ts:3-5` dice literalmente *"Token en localStorage para demo. NOTA seguridad: en producción, refresh token debería ir en cookie HttpOnly; aquí se simplifica por ser proyecto académico."* — esta sección ejecuta esa nota pendiente.

### Acciones concretas
1. Mover el refresh token a cookie `HttpOnly` + `Secure` + `SameSite` en `backend/app/api/auth.py` (`login`/`refresh`), en vez de devolverlo en el body JSON.
2. Quitar el refresh token de `localStorage` en `frontend/lib/api.ts:18-25`; mantener el access token solo en memoria de la aplicación (estado de React), no persistido.
3. Añadir protección CSRF (token de doble envío o header custom) antes de completar la migración a cookies — hoy no es necesaria porque `Authorization` header no viaja entre orígenes automáticamente, pero una cookie sí.
4. Exponer `GET /v1/auth/sessions` (lista de `RefreshToken` no revocados del usuario) y `DELETE /v1/auth/sessions/{jti}` — la tabla `RefreshToken` (`backend/app/db/models.py:54-63`) ya tiene `jti`, `user_id`, `created_at`; falta solo la ruta.
5. Dejar como requisito de diseño: cuando exista endpoint de cambio de contraseña, revocar todos los `RefreshToken` del usuario en la misma transacción.

### Evidencia de cierre
- [ ] Respuesta de `POST /v1/auth/login` incluye `Set-Cookie` con `HttpOnly; Secure; SameSite=...` y **ya no** incluye `refresh_token` en el body.
- [ ] Inspección de DevTools → Application → Local Storage confirma que `refresh_token` ya no se almacena ahí.
- [ ] `GET /v1/auth/sessions` devuelve las sesiones activas del usuario autenticado.
- [ ] Petición cross-origin simulando CSRF contra `/v1/auth/refresh` es rechazada.

---

## Prompt para continuar el análisis (otra persona / asistente de IA)

Copiar y pegar el siguiente bloque completo al iniciar una nueva sesión de análisis (con otro ingeniero, otro chat de Claude Code, o cualquier asistente de código) para que continúe exactamente donde quedó este proceso, sin perder contexto.

```
Actúa como ingeniero de seguridad revisando el proyecto "Ludopatia593": una plataforma
de predicciones del Mundial 2026 con puntos virtuales (sin dinero real). Stack: backend
FastAPI (Python 3.12, backend/app/), frontend Next.js (frontend/), Postgres 16 + Redis 7,
todo sobre Docker (docker-compose.yml local, Dockerfile + railway.toml para despliegue
en Railway).

Ya se completó un proceso de control proactivo y hardening en 3 fases:
  1. Descomposición de arquitectura -> inventario de activos con clasificación C/I/D.
  2. Auditoría de 7 apartados: (01) activos, (02) criptografía, (03) logs, (04) hardening
     de producción en Docker (puertos, aplicación, base de datos, periféricos), (05)
     ofuscación de versión de tecnología, (06) rate limiting, (07) hardening de sesiones.
  3. Plan de acción con pasos concretos y evidencia de cierre verificable por sección,
     documentado en docs/security/hardening-plan.md (léelo primero, es la fuente de verdad).

Hallazgos ya identificados y su severidad (verificar si siguen vigentes, el código pudo
haber cambiado):
  - CRÍTICO: /docs, /redoc, /openapi.json activos en todos los entornos
    (backend/app/main.py:26) -> exponen el esquema completo de la API sin autenticación.
  - ALTO: Redis sin --requirepass (docker-compose.yml) -> acceso libre dentro de la red
    docker, del cual dependen el rate limiter y futuras sesiones.
  - ALTO: refresh token en localStorage del frontend (frontend/lib/api.ts) -> vulnerable
    a robo vía XSS; el propio código ya documenta esto como simplificación pendiente.
  - ALTO: CORS_ORIGINS de producción no verificable desde el repo (depende de variable
    de entorno en Railway, no versionada).
  - MEDIO: JWT_SECRET sin gestión de secretos ni rotación documentada.
  - RESUELTO (2026-07-19): faltaba .dockerignore en frontend/ (COPY . . podía hornear
    un .env local). Añadidos frontend/.dockerignore y backend/.dockerignore que excluyen
    .env*, node_modules, .next, .venv, etc. Rebuild del frontend verificado OK.
  - MEDIO: sin logging estructurado de requests HTTP (solo existe AuditLog de negocio).
  - MEDIO: X-Powered-By: Next.js expuesto (falta poweredByHeader: false).

Tu tarea:
1. Lee docs/security/hardening-plan.md completo antes de tocar código.
2. Para cada sección (01-07), ejecuta los comandos de "Qué buscar / hallar" contra el
   estado ACTUAL del repo -- no asumas que los hallazgos anteriores siguen igual.
3. Marca en el checklist de "Evidencia de cierre" qué quedó resuelto y qué sigue abierto.
4. Si implementas un fix, indica archivo:línea exacto y el porqué del cambio (no solo el qué).
5. Nunca introduzcas backwards-compatibility shims ni flags de features para esto: son
   cambios de seguridad, se aplican directo.
6. Si algún hallazgo ya no aplica (el código cambió), dilo explícitamente en vez de
   omitirlo en silencio -- este documento debe seguir siendo la fuente de verdad.

Reporta al final: qué se cerró, qué sigue pendiente, y si apareció algún hallazgo nuevo
no cubierto en las 7 secciones originales.
```

---

_Última actualización: 2026-07-09. Mantener este archivo sincronizado con cada PR que toque autenticación, configuración de entorno, `docker-compose.yml` o los Dockerfiles._
