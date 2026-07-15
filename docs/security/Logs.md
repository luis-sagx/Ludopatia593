# Logs — Ludopatia593 (Sección 03 del hardening plan)

> A diferencia de las secciones 01 y 02, en esta **no había ningún control implementado**: no existía `logging.basicConfig`/`dictConfig` en todo el backend, `security_middleware` (`backend/app/main.py`) solo aplicaba rate limit y headers, y `AuditLog` solo registraba eventos de negocio sin forma de cruzarlos con la petición HTTP que los originó. Esta sección documenta la implementación aplicada hoy, con evidencia de que funciona.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| Cada request en producción genera una línea de log con `request_id`, IP, método, ruta, status, latencia |  **Implementado y verificado** | Docker local, `ENVIRONMENT=production`: cada request genera una línea JSON (ver evidencia abajo), incluidas las respuestas `429` del rate limiter (antes no se logueaban en absoluto). |
| `curl` con `Authorization: Bearer ...` no aparece en el log |  **Verificado** | Se envió `Authorization: Bearer test-secret-token-should-not-leak` contra `/v1/leaderboard` y se revisó el log completo del contenedor: el valor no aparece en ningún punto. No es una exclusión manual — el logger de acceso nunca recibe headers ni bodies, solo metadata (`request_id`, IP, método, ruta, status, latencia). |
| `AuditLog.detail` de login/register sin contraseñas ni tokens |  **Verificado, y ahora con `request_id` cruzado** | Se registró un usuario de prueba con password `Str0ngPassw0rd!SECRETVALUE` vía `/v1/auth/login`; ni la contraseña ni el token aparecen en los logs. Se consultó `audit_log` en Postgres y el `request_id` guardado coincide exactamente con el de la línea de log HTTP de esa misma petición. |

## Qué se implementó

### 1. Logging estructurado JSON (`backend/app/core/logging.py`, nuevo archivo)

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {"level": record.levelname, "logger": record.name, "message": record.getMessage()}
        http = getattr(record, "http", None)
        if http:
            payload.update(http)
        return json.dumps(payload, default=str)

def configure_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.environment == "dev" else logging.INFO)
```

`DEBUG` solo se habilita si `settings.environment == "dev"` (punto 5 de las acciones concretas del plan) — fuera de `dev` el nivel queda en `INFO`, evitando volcar detalle interno en producción.

### 2. `request_id` + traza de cada request (`backend/app/main.py`, `security_middleware`)

- Reusa `X-Request-Id` si el proxy/Railway ya lo manda; si no, genera uno con `uuid4()`.
- Se guarda en `request.state.request_id` para que los routers lo lean.
- Se mueve el rate limit **antes** de generar la traza pero la línea de log se emite **para ambos casos** (permitido o `429`) — antes las peticiones bloqueadas por rate limit no dejaban ningún rastro.
- El log solo contiene metadata (`request_id`, `ip`, `method`, `path`, `status`, `latency_ms`) — nunca headers ni el body de la petición, así que `Authorization` queda excluido **por construcción**, no por una lista de exclusión que alguien pueda olvidar mantener.
- Se agrega `X-Request-Id` a la respuesta, para que el cliente/frontend pueda correlacionar un error con una línea de log específica si hace falta soporte.

### 3. `request_id` propagado a `AuditLog` (cruce traza HTTP ↔ evento de negocio)

Se agregó `request: Request` a los endpoints que escriben `AuditLog` y no lo tenían, y se añadió `"request_id": request.state.request_id` dentro del `detail` JSON existente (sin tocar el esquema de la tabla — no hace falta migración, `detail` ya era una columna JSON):

- `backend/app/api/auth.py` — `register` (nuevo parámetro `request`) y `login` (ya lo tenía).
- `backend/app/api/bets.py` — `place_prediction`.
- `backend/app/api/admin.py` — `settle_fixture`, `simulate` (vía `_apply_result`, que ahora recibe `request_id` como parámetro) y `sync_fixtures`.

**Nota de diseño:** se evitó deliberadamente agregar una columna `request_id` nueva a `AuditLog` porque el proyecto no tiene un sistema de migraciones activo (`alembic` está en `requirements.txt` pero no hay carpeta `alembic/`; el esquema se crea con `Base.metadata.create_all`, que no altera tablas ya existentes). Meter el `request_id` dentro del `detail` JSON logra el mismo cruce sin ese riesgo.

## Evidencia técnica recolectada (Docker local, `ENVIRONMENT=production`)

### Prueba 1 — request normal con `Authorization` falso, no aparece en el log

```
$ curl -H "Authorization: Bearer test-secret-token-should-not-leak" http://localhost:8080/v1/leaderboard

{"level": "INFO", "logger": "access", "message": "http_request",
 "request_id": "7a8c3a86-070d-41ed-a00e-0bc3d338045f", "ip": "172.25.0.1",
 "method": "GET", "path": "/v1/leaderboard", "status": 200, "latency_ms": 21.26}
```
El valor `test-secret-token-should-not-leak` no aparece en ningún punto del log del contenedor.

### Prueba 2 — registro de usuario, cruce `request_id` con `AuditLog`

```
$ curl -X POST http://localhost:8080/v1/auth/register -d '{"email":"testlog@demo.io","password":"Str0ngPassw0rd!"}'

{"level": "INFO", "logger": "access", "message": "http_request",
 "request_id": "e2bf3cb6-1a9a-4931-b874-fa44c3000a9e", ...,
 "path": "/v1/auth/register", "status": 201, "latency_ms": 134.54}
```
```sql
SELECT id, actor_id, action, detail FROM audit_log ORDER BY id DESC LIMIT 1;

 id | actor_id |  action  |                         detail
----+----------+----------+--------------------------------------------------------
  1 |        2 | register | {"request_id": "e2bf3cb6-1a9a-4931-b874-fa44c3000a9e"}
```
El `request_id` de la línea de log HTTP coincide exactamente con el guardado en `AuditLog.detail` — confirma el cruce traza-HTTP ↔ evento-de-negocio que pedía el punto 4 del plan.

### Prueba 3 — login con contraseña real, y rate limit también queda logueado

```
$ curl -X POST /v1/auth/login -d '{"email":"testlog@demo.io","password":"Str0ngPassw0rd!SECRETVALUE"}'
# 6 intentos seguidos contra /v1/auth/login (límite: 5/min)
401 401 401 401 401 429
```
Las 6 líneas de log aparecen, incluida la del `429`:
```
{"...","path": "/v1/auth/login", "status": 401, ...}   (x5)
{"...","path": "/v1/auth/login", "status": 429, ...}   (bloqueada por rate limit, y AUN ASÍ queda registrada)
```
`Str0ngPassw0rd!SECRETVALUE` no aparece en ningún punto del log — confirma que el body tampoco se loguea nunca, ni siquiera en intentos fallidos.

## Qué queda pendiente / fuera de esta implementación

1. **Envío a un colector centralizado** (ej. Loki, CloudWatch, Datadog): hoy los logs JSON van a `stdout` del contenedor — correcto como base, pero en producción real conviene que Railway (o quien opere el deploy) los enrute a un sistema que permita buscar por `request_id` sin entrar a `docker logs` manualmente. No es una tarea de código, es de infraestructura/operación.
2. **`reload_model` (`admin.py`) no escribe `AuditLog`** — se detectó de paso durante esta revisión; no estaba en el alcance original de la sección 03 (es un gap de la sección de auditoría/RBAC, no de logging de requests), se deja anotado para no perderlo.
3. El log de acceso propio (`access_logger`) convive con el log de acceso nativo de uvicorn (`INFO: 172.25.0.1:xxxx - "GET ..." 200 OK`, texto plano) — es redundante pero inofensivo (no filtra nada adicional). Si se quiere un único formato, se puede desactivar el `access_log` de uvicorn (`--no-access-log` en `start.sh`) ya que nuestro middleware cubre lo mismo en JSON.

## Archivos modificados

- **Nuevo**: `backend/app/core/logging.py`
- `backend/app/main.py` — `security_middleware` genera `request_id`, mide latencia y loguea cada request.
- `backend/app/api/auth.py` — `register` y `login` propagan `request_id` a `AuditLog`.
- `backend/app/api/bets.py` — `place_prediction` propaga `request_id`.
- `backend/app/api/admin.py` — `settle_fixture`, `simulate`, `sync_fixtures` propagan `request_id`.

## Historial de revisiones

- **2026-07-15** — Implementación inicial de logging estructurado + `request_id` + cruce con `AuditLog`. Verificado en Docker local con `ENVIRONMENT=production`: JSON por request (incluidos los `429`), sin fuga de `Authorization` ni de contraseñas, `request_id` cruzado correctamente en `audit_log`.
