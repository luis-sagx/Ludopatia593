# Desplegar en Railway — Guía fácil paso a paso

> Guía **simple** para dejar la app corriendo en Railway desde cero, aunque sea tu primera vez.
> Si quieres el detalle técnico y la justificación de seguridad de cada variable, mira `Despliegue-Railway.md` (runbook completo). Esta guía es el "hazlo así y funciona".
>
> _Última actualización: 2026-07-19._

---

## Lo que vas a montar

4 piezas dentro de **un mismo proyecto** de Railway:

```
┌─────────────────────────────────────────┐
│  Proyecto Railway "ludopatia593"         │
│                                          │
│   Postgres ──┐         ┌── Redis         │
│              │         │                 │
│           backend (FastAPI, carpeta backend/)
│              │                           │
│           frontend (Next.js, carpeta frontend/)
└─────────────────────────────────────────┘
```

- **Postgres** y **Redis**: te los da Railway ya hechos (add-ons). No construyes nada.
- **backend** y **frontend**: se construyen solos con el `Dockerfile` de cada carpeta.

---

## Antes de empezar (5 minutos)

1. **Cuenta Railway** en <https://railway.com> — entra con **GitHub** (esto también te da el "Full Trial": sin verificar GitHub caes en "Limited Trial" con la salida de red y puertos restringidos).
2. Ten el repo subido a GitHub.
3. Ten `openssl` a mano para generar el secreto (en Linux/Mac ya viene). Genera **ahora** tu `JWT_SECRET` y guárdalo en un bloc de notas privado:
   ```bash
   openssl rand -hex 32
   ```
4. **Ojo con el plan gratis:** el Trial da **$5 una vez** y dura **30 días**. Cubre de sobra la presentación. Cuando el Trial acabe, el plan Free solo deja **3 servicios** (tú tienes 4) — si quieres que siga vivo pasado el Trial, sube a **Hobby ($5/mes)**.

---

## Paso 1 — Crear el proyecto y las bases de datos

1. Railway → **New Project** → ponle nombre (ej. `ludopatia593`).
2. Dentro del proyecto: **+ New** → **Database** → **Add PostgreSQL**. Espera unos segundos.
3. Otra vez **+ New** → **Database** → **Add Redis**.

✅ Ya tienes Postgres y Redis. Railway crea solo sus variables `DATABASE_URL` y `REDIS_URL`.

---

## Paso 2 — Servicio backend

1. **+ New** → **GitHub Repo** → elige tu repo.
2. Se crea un servicio. Ábrelo → pestaña **Settings**:
   - **Root Directory** → escribe `backend`
   - Railway detecta solo `backend/railway.toml` (usa el Dockerfile y el healthcheck `/health`). No toques nada más aquí.
3. Ve a la pestaña **Variables** del backend y añade **exactamente** estas:

   | Variable | Valor |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `JWT_SECRET` | *(el que generaste con `openssl rand -hex 32`)* |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
   | `REDIS_URL` | `${{Redis.REDIS_URL}}` |
   | `ADMIN_EMAIL` | `admin@tudominio.com` |
   | `ADMIN_PASSWORD` | *(una contraseña fuerte tuya)* |
   | `CORS_ORIGINS` | *(se rellena en el Paso 4 — déjala pendiente)* |

   > Las de `${{Postgres...}}` y `${{Redis...}}` se autocompletan al escribirlas: Railway las referencia sin que copies el secreto a mano.
   >
   > ⚠️ **NO** definas `DEMO_PASSWORD` ni `NEXT_PUBLIC_DEMO_ACCOUNTS`. Dejarlas fuera mantiene ocultas las cuentas demo (es lo seguro).

4. Deja que despliegue. El primer arranque **entrena el modelo y siembra la base**, tarda unos segundos. Espera a que el healthcheck `/health` quede en verde.

---

## Paso 3 — Servicio frontend

1. **+ New** → **GitHub Repo** → el **mismo** repo otra vez.
2. Ábrelo → **Settings** → **Root Directory** → `frontend`.
3. Pestaña **Variables** → añade:

   | Variable | Valor |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | *(la URL pública del backend — la tienes en el Paso 4)* |

   > ⚠️ **Importante:** `NEXT_PUBLIC_API_URL` se "hornea" en el momento del build. Si la cambias después, hay que **volver a desplegar con rebuild** para que tenga efecto.

---

## Paso 4 — Dominios (conectar las piezas)

1. **Backend** → Settings → **Networking** → **Generate Domain**. Copia la URL, algo tipo:
   `https://backend-xxxx.up.railway.app`
2. **Frontend** → Settings → **Networking** → **Generate Domain**:
   `https://frontend-xxxx.up.railway.app`
3. Ahora rellena las dos variables que quedaron pendientes:
   - Backend → `CORS_ORIGINS` = la URL **exacta del frontend** (sin `/` final, sin `*`).
   - Frontend → `NEXT_PUBLIC_API_URL` = la URL **exacta del backend**.
4. Redeploy del frontend (para que hornee la URL correcta) y del backend (para tomar el CORS).

---

## Paso 5 — Comprobar que quedó seguro (2 minutos)

Copia estas líneas en tu terminal cambiando las dos URLs. **Guarda la salida** como evidencia para la presentación:

```bash
BACK=https://backend-xxxx.up.railway.app
FRONT=https://frontend-xxxx.up.railway.app

# 1) HTTPS + HSTS
curl -sI $BACK/health | grep -i strict-transport-security        # debe aparecer

# 2) Versiones ofuscadas
curl -s -o /dev/null -w "docs=%{http_code}\n" $BACK/docs         # 404
curl -sI $BACK/health | grep -i '^server:'                       # Server: ludopatia593
curl -sI $FRONT | grep -i x-powered-by                           # (vacío)

# 3) Rate limit del login (corta en el 6.º intento)
for i in $(seq 1 8); do curl -s -o /dev/null -w "%{http_code} " \
  -X POST $BACK/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"x@x.com","password":"nope12345"}'; done; echo    # ...401 x5 -> 429

# 4) Sin cuentas demo visibles
curl -s $FRONT/login | grep -c "demo.io"                         # 0
```

**Checklist de que todo está bien:**
- [ ] `Strict-Transport-Security` presente.
- [ ] `/docs` da 404 y `Server: ludopatia593`.
- [ ] El login corta con `429` antes del 6.º intento.
- [ ] `/login` no muestra cuentas demo.

---

## Paso 6 — Cosas del panel (no del código)

Marca esto en el panel de Railway antes de dar por cerrado:
- [ ] Postgres → confirma que tiene **Backups** activados y **haz una restauración de prueba** una vez (un backup sin probar no cuenta).
- [ ] Confirma que Postgres y Redis **NO** tienen dominio público (solo red privada del proyecto — por defecto es así, solo verifícalo).

---

## CI/CD — ¿qué hace cada parte?

- **CD (despliegue continuo): lo hace Railway.** Cada vez que haces *push* a la rama conectada, Railway reconstruye y redepliega solo. No hay que hacer nada a mano tras este setup.
- **CI (integración continua): lo hace GitHub Actions** (`.github/workflows/ci.yml`). En cada push/PR corre:
  1. **Tests con cobertura** (gate 80%) — si algo se rompe o baja la cobertura, falla.
  2. **Build** de las dos imágenes Docker.
  3. **Trivy** — escanea ambas imágenes; falla si hay vulnerabilidades **HIGH/CRITICAL con parche disponible**.
- Los resultados de Trivy también quedan en la pestaña **Security** del repo en GitHub.

> Correr los tests localmente antes de un push:
> ```bash
> cd backend && pip install -r requirements-dev.txt && python -m pytest
> ```

---

## Si algo falla

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| Backend no arranca, log dice `JWT_SECRET inseguro` | Falta o es corto | Pon uno de `openssl rand -hex 32` (≥32 chars) |
| Frontend llama a `localhost` en vez del backend | `NEXT_PUBLIC_API_URL` mal o cambiada sin rebuild | Corrige la variable y **redeploy con rebuild** |
| Error de CORS en el navegador | `CORS_ORIGINS` no es la URL exacta del frontend | Copia la URL exacta (sin `/` final) y redeploy |
| Backend arranca pero da errores raros de BD | Base vieja de un deploy anterior | Recrea la base (bórrala y deja que el seed la regenere) |
| Salida de red / API externa bloqueada | Estás en "Limited Trial" | Verifica tu cuenta con GitHub para pasar a "Full Trial" |
