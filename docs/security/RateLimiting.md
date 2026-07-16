# Rate limiting — Ludopatia593 (Sección 06 del hardening plan)

> Precondición del propio plan: "confirmar que Redis ya tiene auth antes de endurecer límites — si no, el limitador es de acceso libre". Ya cerrado en la sección 04 (`--requirepass`), así que esta sección parte de una base sólida.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| `POST /v1/auth/register` con límite propio | ✅ **Implementado y verificado** | Loop de 10 peticiones: `201 x8` luego `429 x2` — 429 antes de la iteración 10, tal como pide el checklist. |
| `POST /v1/bets` con límite propio distinto del global | ✅ **Implementado y verificado** | Loop de 25 peticiones autenticadas: `201 x20` luego `429 x5`. Límite propio (20/min) dispara mucho antes que el global (60/min) — confirma que es independiente. |
| `/v1/admin/*` con límite reforzado (defensa en profundidad) | ✅ **Implementado y verificado** | Loop de 35 peticiones a `/v1/admin/audit` con token admin: `200 x30` luego `429 x5`. |
| Redis con auth antes de endurecer límites | ✅ Ya cerrado en sección 04 | — |
| Deuda técnica de ventana fija documentada | ✅ Documentado (no se resuelve en esta pasada) | Ver abajo. |

## Qué se implementó

### 1. Dependencia reusable `rate_limit_dep` (`backend/app/core/ratelimit.py`)

Antes, el único patrón para aplicar un límite era llamar `allow()` a mano dentro del cuerpo de cada endpoint (así estaba hecho en `login`). Para los tres nuevos límites se agregó una fábrica de dependencias FastAPI, así el límite se declara en la firma de la ruta en vez de mezclarse con la lógica de negocio:

```python
def rate_limit_dep(key_prefix: str, limit: int) -> Callable[[Request], None]:
    def _dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not allow(f"{key_prefix}:{ip}", limit):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "demasiadas peticiones")
    return _dep
```

### 2. Límites nuevos (`backend/app/core/config.py`)

```python
register_rate_limit_per_min: int = 8
bets_rate_limit_per_min: int = 20
admin_rate_limit_per_min: int = 30
```

Los tres son configurables por entorno (igual que `rate_limit_per_min`/`login_rate_limit_per_min` ya existentes), sin tocar código para ajustarlos.

### 3. Aplicación por ruta

- **`POST /v1/auth/register`** (`auth.py`) — límite en el decorador de la ruta:
  ```python
  @router.post("/register", ..., dependencies=[Depends(rate_limit_dep("register", settings.register_rate_limit_per_min))])
  ```
- **`POST /v1/bets`** (`bets.py`) — mismo patrón, prefijo `"bets"`.
- **`/v1/admin/*`** (`admin.py`) — a diferencia de los dos anteriores, se aplicó **a nivel de router**, no por endpoint:
  ```python
  router = APIRouter(prefix="/v1/admin", tags=["admin"],
                      dependencies=[Depends(rate_limit_dep("admin", settings.admin_rate_limit_per_min))])
  ```
  Esto cubre `settle_fixture`, `simulate`, `model/reload`, `audit`, `fixtures/sync` con una sola línea — y cualquier ruta admin que se agregue después queda cubierta automáticamente, sin tener que acordarse de repetir el `Depends(...)` en cada una.

## Evidencia técnica recolectada (Docker local, `ENVIRONMENT=production`)

### `POST /v1/auth/register` — límite 8/min

```
$ for i in $(seq 1 10); do curl -X POST /v1/auth/register -d '{"email":"ratelimitN@demo.io",...}'; done
201 201 201 201 201 201 201 201 429 429
```

### `POST /v1/bets` (autenticado, con `idempotency_key` distinta por intento) — límite 20/min

```
$ for i in $(seq 1 25); do curl -X POST /v1/bets -H "Authorization: Bearer $TOKEN" -d '{...}'; done
201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 201 429 429 429 429 429
```
20 apuestas aceptadas, después `429` — confirma que el límite de `/v1/bets` es propio y bastante más estricto que el global (60/min): sin este cambio, las 25 peticiones habrían pasado todas.

### `GET /v1/admin/audit` (token admin) — límite 30/min

```
$ for i in $(seq 1 35); do curl /v1/admin/audit -H "Authorization: Bearer $ADMIN_TOKEN"; done
200 (x30) 429 (x5)
```
Confirma que el límite a nivel de router funciona sin tener que declararlo en cada endpoint individual.

## Deuda técnica documentada (no se resuelve en esta pasada)

`core/ratelimit.py` usa **ventana fija** (`bucket = f"rl:{key}:{int(now // window_sec)}"`), no deslizante. Esto significa que un cliente puede, en el peor caso, hacer hasta ~2× el límite nominal si concentra peticiones justo en el borde entre dos ventanas (ej. la mitad al final del minuto N, la mitad al inicio del minuto N+1) — cada mitad cuenta contra un bucket distinto. Aceptable para el volumen actual del proyecto (académico, sin tráfico real de producción); si el tráfico lo justifica más adelante, migrar a ventana deslizante (ej. sorted set de Redis con timestamps y `ZREMRANGEBYSCORE`). Quedó documentado directamente en el docstring de `ratelimit.py`, no solo acá, para que sea visible sin tener que buscar en `docs/`.

## Archivos modificados

- `backend/app/core/ratelimit.py` — `rate_limit_dep()` (dependencia reusable) + docstring con la deuda técnica de ventana fija.
- `backend/app/core/config.py` — `register_rate_limit_per_min`, `bets_rate_limit_per_min`, `admin_rate_limit_per_min`.
- `backend/app/api/auth.py` — límite en `POST /register`.
- `backend/app/api/bets.py` — límite en `POST /v1/bets`.
- `backend/app/api/admin.py` — límite a nivel de router, cubre todo `/v1/admin/*`.

## Historial de revisiones

- **2026-07-15** — Implementación de límites propios para `register`, `bets` y `admin/*`, con `rate_limit_dep` como dependencia reusable. Verificado en Docker local con las mismas pruebas de loop que pide el checklist del plan (10 intentos a `register`, y una prueba equivalente ampliada a `bets` y `admin`). Deuda de ventana fija documentada, no resuelta (fuera de alcance por volumen de tráfico actual).
