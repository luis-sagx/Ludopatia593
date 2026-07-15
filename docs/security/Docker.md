# Hardening Docker en producción — Ludopatia593 (Sección 04 del hardening plan)

> Como en la sección 03, acá casi nada estaba implementado: sin segmentación de red, sin `cap_drop`/`read_only`, sin límites de recursos, sin healthcheck de `backend`/`frontend`, Redis sin `--requirepass`, y — hallazgo nuevo encontrado al verificar, no estaba ni en el plan original — el usuario de Postgres resultó ser superusuario. Todo lo de abajo se implementó y se probó en Docker, no solo se documentó.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| Solo `8080`/`3000` publicados, `db`/`redis` sin `ports:` | ✅ Ya estaba bien, sin cambios | — |
| `redis-cli ping` sin password → `NOAUTH` | ✅ **Implementado y verificado** | `docker exec redis redis-cli ping` → `NOAUTH Authentication required.`; con password → `PONG`. |
| `docker inspect ... User` no vacío/root en ningún servicio | ✅ Ya estaba bien (Dockerfiles), sin cambios | — |
| `\du` confirma que el usuario de la app no es superusuario | ✅ **Implementado y verificado** (con un giro, ver abajo) | `app_runtime` (nuevo rol, el que ahora usa `DATABASE_URL`) sale sin ningún atributo elevado en `\du`. |
| Restauración de backup probada, con fecha registrada | ⏳ **Pendiente — requiere producción** | No verificable desde código/Docker local; es un procedimiento operativo contra el backup gestionado de Railway. |
| `trivy image` sin `CRITICAL` sin parche | ⏳ **Pendiente — requiere `trivy` instalado o CI** | No ejecutado; no hay pipeline (`.github/workflows` no existe, confirmado en `ListaActivos.md`). |

## Qué se implementó, por bloque

### Puertos — segmentación de red

`docker-compose.yml` ahora define dos redes en vez de la red default compartida:

```yaml
networks:
  backend-net:   # db, redis, backend
  public-net:    # backend, frontend
```

`frontend` ya no comparte red con `db`/`redis` — antes los cuatro servicios estaban en la misma red bridge por default, así que el frontend podía alcanzar la base de datos directamente aunque nunca lo hiciera por código.

**Verificado:**
```
db networks:      ludopatia593_backend-net
redis networks:   ludopatia593_backend-net
backend networks: ludopatia593_backend-net ludopatia593_public-net
```

### Aplicación — `cap_drop`, `read_only`, límites, healthcheck

```yaml
backend:
  cap_drop: [ALL]
  security_opt: ["no-new-privileges:true"]
  read_only: true
  tmpfs: [/tmp]
  volumes:
    - model-data:/app/data   # ver nota de diseño abajo
  deploy:
    resources:
      limits: {cpus: "1.0", memory: 512M}
  healthcheck:
    test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8000/health', timeout=3)"]
    ...

frontend:
  cap_drop: [ALL]
  security_opt: ["no-new-privileges:true"]
  deploy:
    resources:
      limits: {cpus: "1.0", memory: 512M}
  healthcheck:
    test: ["CMD", "node", "-e", "..."]
```

**Nota de diseño — por qué `backend` necesita un volumen a pesar de `read_only: true`:** `backend/app/ml/train.py:93` escribe `data/model.json` en **cada arranque** del contenedor (`start.sh` corre `python -m app.ml.train` antes de levantar uvicorn). Un filesystem completamente read-only rompe el arranque. La solución no es abandonar `read_only` — es acotar la excepción a la única carpeta que de verdad necesita escribirse (`/app/data`), dejando el resto de la imagen (código, dependencias) inmutable.

**Decisión deliberada — `frontend` sin `read_only`:** a diferencia del backend, no confirmé si `next start` necesita escribir en `.next/cache` en este proyecto (depende de si se usa ISR/optimización de imágenes). Preferí no aplicarlo sin probarlo a fondo primero — aplicar `cap_drop`/límites/healthcheck ahora (de bajo riesgo, ya verificado) y dejar `read_only` para una iteración siguiente con más tiempo de prueba, en vez de arriesgar un `EROFS` en producción por apurar el cierre del checklist.

### Base de datos — el hallazgo no estaba en el plan original

Al correr `\du` contra el proyecto real (no contra un ejemplo), encontré que el usuario `app` (el que usaba `DATABASE_URL`) **es superusuario**:

```
 Role name |                         Attributes
-----------+------------------------------------------------------------
 app       | Superuser, Create role, Create DB, Replication, Bypass RLS
```

Esto pasa porque la imagen oficial de Postgres convierte automáticamente a `POSTGRES_USER` en el usuario bootstrap (superusuario) al inicializar el volumen — no es una configuración nuestra, es el comportamiento por defecto de `postgres:16-alpine`.

**Intento 1 (fallido):** un script SQL en `docker-entrypoint-initdb.d/` que hiciera `ALTER ROLE app WITH NOSUPERUSER` — Postgres lo rechaza explícitamente: *"the bootstrap user must have the SUPERUSER attribute"*. No se puede auto-degradar.

**Solución aplicada:** crear un **segundo rol**, `app_runtime`, sin privilegios elevados, y mover `DATABASE_URL` para que la aplicación se conecte con ese — nunca con el bootstrap. Nuevo archivo `backend/db-init/10-create-app-runtime-role.sh`:

```sh
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE app_runtime WITH LOGIN PASSWORD '$POSTGRES_PASSWORD'
        NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    GRANT ALL PRIVILEGES ON DATABASE $POSTGRES_DB TO app_runtime;
    GRANT ALL ON SCHEMA public TO app_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_runtime;
EOSQL
```

```yaml
# docker-compose.yml
backend:
  environment:
    DATABASE_URL: postgresql+psycopg2://app_runtime:${DB_PASSWORD:-app}@db:5432/predictor
db:
  volumes:
    - ./backend/db-init:/docker-entrypoint-initdb.d:ro
```

**Verificado end-to-end** (proyecto Docker aislado, volumen nuevo):
```
 Role name  |                         Attributes
-------------+------------------------------------------------------------
 app         | Superuser, Create role, Create DB, Replication, Bypass RLS
 app_runtime |
```
- `app_runtime` puede `CREATE TABLE`/`INSERT`/`SELECT`/`DROP` (suficiente para que `Base.metadata.create_all` y el ORM funcionen).
- `app_runtime` **no** puede `CREATE ROLE` (`ERROR: permission denied to create role`) — la restricción es real, no cosmética.
- El backend completo (entrena modelo, siembra DB, sirve API) arrancó y respondió `200 OK` en `/health` usando exclusivamente `app_runtime`.

**⚠️ Acción pendiente en su entorno local actual:** los scripts de `docker-entrypoint-initdb.d/` solo corren la **primera vez** que se inicializa un volumen vacío. El volumen `ludopatia593_pgdata` que ya tienen fue creado antes de este cambio, así que **no** tiene el rol `app_runtime` — si levantan el stack tal cual con ese volumen viejo, el backend fallará al conectar. Hace falta correr una vez:
```bash
docker compose down -v   # borra el volumen viejo (datos de demo, se re-siembran solos)
docker compose up --build
```

### Periféricos — Redis con autenticación

```yaml
redis:
  command: ["redis-server", "--requirepass", "${REDIS_PASSWORD:?define REDIS_PASSWORD}", "--save", "60", "1"]
  healthcheck:
    test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "--no-auth-warning", "ping"]

backend:
  environment:
    REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0   # antes: redis://redis:6379/0
```

Se agregó `REDIS_PASSWORD` (obligatorio, sin default) a `.env.example`. Se verificó que solo dos archivos consumen `settings.redis_url` (`core/ratelimit.py`, `api/predictions.py`, ambos vía `get_redis()`), así que no quedó ningún punto de conexión sin actualizar.

**Verificado:**
```
$ docker exec redis redis-cli ping
NOAUTH Authentication required.
$ docker exec redis redis-cli -a <password> --no-auth-warning ping
PONG
```

**Pendiente (no ejecutado):** `trivy image` sobre ambas imágenes y fijar digest en vez de tag — necesito confirmar si tienen `trivy` disponible localmente o si esto queda para cuando exista CI.

## Evidencia técnica adicional — `docker inspect`

```
CapDrop=[ALL] | ReadonlyRootfs=true | SecurityOpt=[no-new-privileges:true] | Mem=536870912 (512MiB) | NanoCpus=1000000000 (1 CPU)
```
Confirmado sobre el contenedor `backend` real, no solo sobre el YAML.

## Archivos modificados / nuevos

- `docker-compose.yml` — networks, `cap_drop`/`read_only`/`security_opt`/límites/healthcheck en `backend` y `frontend`, `--requirepass` en `redis`, `DATABASE_URL` apuntando a `app_runtime`, volumen `model-data` nuevo.
- **Nuevo**: `backend/db-init/10-create-app-runtime-role.sh`
- `.env.example` — se agregó `REDIS_PASSWORD`.

## Qué queda pendiente

1. **Recrear el volumen `pgdata` local** (ver nota de arriba) — acción manual de una sola vez, no de código.
2. **`trivy image`** sobre `ludopatia593-backend`/`-frontend` — pendiente de confirmar herramienta disponible.
3. **Digest fijo de imágenes base** (`postgres:16-alpine@sha256:...`, `redis:7-alpine@sha256:...`) en vez de solo el tag.
4. **Prueba de restauración de backup** — requiere acceso al panel de Railway.
5. **Confirmar en Railway** que el Postgres/Redis gestionados no exponen dominio público — no verificable desde el repo.
6. **`read_only` en `frontend`** — quedó deliberadamente afuera, evaluar en una siguiente pasada si `next start` necesita escribir en `.next/cache`.

## Historial de revisiones

- **2026-07-15** — Implementación completa de la sección 04 sobre `Mateo_VerificacionAcciones`: segmentación de red, `cap_drop`/`read_only`/límites/healthcheck en `backend` y `frontend`, Redis con `--requirepass`, y separación de rol de Postgres (`app_runtime` sin privilegios elevados, hallazgo no contemplado en el plan original). Todo verificado end-to-end en un proyecto Docker aislado (`ludoptest`, volúmenes descartados al terminar) para no afectar el volumen de datos local ya existente.
