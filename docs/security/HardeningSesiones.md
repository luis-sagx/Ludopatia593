# Hardening de sesiones — Ludopatia593 (Sección 07 del hardening plan)

> Última sección del plan. El propio código ya documentaba el pendiente: `frontend/lib/api.ts:3-5` decía literalmente *"Token en localStorage para demo... en producción, refresh token debería ir en cookie HttpOnly"*. Esta sección ejecuta esa nota. Es el cambio de mayor superficie de todo el plan (backend + frontend a la vez), y el que más se benefició de probarse en un navegador real en vez de solo con `curl` — dos bugs reales solo aparecieron ahí.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| `POST /v1/auth/login` responde con `Set-Cookie` `HttpOnly; Secure; SameSite=...` y ya no trae `refresh_token` en el body | ✅ **Implementado y verificado** | `curl -D -` muestra `Set-Cookie: refresh_token=...; HttpOnly; ...; Secure` y el body solo trae `{"access_token":"...","token_type":"bearer"}`. |
| DevTools → Local Storage sin `refresh_token` | ✅ **Verificado en navegador real** | `Object.keys(localStorage)` → `[]` antes y después de loguearse. |
| `GET /v1/auth/sessions` devuelve las sesiones activas | ✅ **Implementado y verificado** | Devuelve `[{jti, created_at, expires_at}, ...]` de las sesiones no revocadas del usuario autenticado. |
| Petición CSRF simulada contra `/v1/auth/refresh` es rechazada | ✅ **Implementado y verificado** | Sin header `X-CSRF-Token` → `403`. Con header que no matchea la cookie → `403`. Con header correcto → `200`. |

## Qué se implementó

### 1. Refresh token en cookie HttpOnly (`backend/app/api/auth.py`)

`login`, `refresh` y `logout` ahora reciben `response: Response` y usan `_set_session_cookies`/`_clear_session_cookies` en vez de devolver el refresh token en el body:

```python
def _set_session_cookies(response: Response, refresh_token: str) -> None:
    flags = _cookie_flags()  # secure+samesite según entorno, ver punto 3
    response.set_cookie("refresh_token", refresh_token, httponly=True,
                         path="/v1/auth", max_age=..., **flags)
    response.set_cookie("csrf_token", secrets.token_urlsafe(32), httponly=False,
                         path="/", max_age=..., **flags)
```

`TokenOut` (`schemas.py`) perdió el campo `refresh_token`; `RefreshIn` se eliminó por completo (ya no hace falta un body para `refresh`/`logout`, se lee la cookie).

### 2. CSRF por doble-envío (`_verify_csrf`, `auth.py`)

Solo `/v1/auth/refresh` y `/v1/auth/logout` la necesitan — son las dos únicas rutas que dependen de la cookie de sesión; el resto de la API sigue usando el access token vía header `Authorization`, que no viaja cross-site solo:

```python
def _verify_csrf(request: Request) -> None:
    cookie_val = request.cookies.get("csrf_token")
    header_val = request.headers.get("x-csrf-token")
    if not cookie_val or not header_val or not secrets.compare_digest(cookie_val, header_val):
        raise HTTPException(403, "csrf inválido")
```

### 3. Flags de cookie por entorno

```python
def _cookie_flags() -> dict:
    if settings.environment == "dev":
        return {"secure": False, "samesite": "lax"}
    return {"secure": True, "samesite": "none"}
```
`SameSite=None` (no `Lax`/`Strict`) fuera de `dev` porque backend y frontend son **servicios separados en Railway** (dominios `*.up.railway.app` distintos) — no comparten "site" a menos que se configure un dominio propio unificado. `SameSite=None` exige `Secure`, así que va siempre junto.

### 4. Endpoints de sesiones (nuevo)

```
GET    /v1/auth/sessions          -> lista jti/created_at/expires_at del usuario autenticado
DELETE /v1/auth/sessions/{jti}    -> revoca una sesión propia (filtra por user_id -- anti-IDOR)
```

### 5. Frontend: access token en memoria, nunca localStorage

- **Nuevo** `frontend/lib/session.ts`: singleton en memoria + `useSyncExternalStore` para reactividad, `refreshSession()` (llama a `/v1/auth/refresh` con la cookie + header CSRF), y `<SessionBootstrap />` (se monta una vez en `layout.tsx`, intenta recuperar sesión al cargar la app).
- `frontend/lib/api.ts`: reescrito. `credentials: "include"` en todo fetch; si un request autenticado responde `401` (access token vencido a los 15 min), reintenta **una vez** tras un `refreshSession()` silencioso antes de rendirse.
- `Nav.tsx`, `BetSlip.tsx`, `betslip.tsx`, `bets/page.tsx`: reemplazado `getToken()`/`localStorage` por `useSession()`. Los componentes que redirigen si no hay sesión (`bets/page.tsx`) ahora esperan a que termine el bootstrap (`initializing`) antes de decidir -- si no, una recarga de página mandaría al usuario a `/login` por una fracción de segundo antes de que el refresh silencioso confirme que sí tiene sesión.

## Dos bugs reales, encontrados solo al probar en navegador (no con `curl`)

`curl` no respeta el *scoping* de cookies por `Path` de la misma forma que `document.cookie` en un navegador, así que ambos bugs pasaron mis pruebas de `curl` sin problema y solo aparecieron al probar el flujo completo en Chrome.

### Bug 1 — `csrf_token` con `Path=/v1/auth` era invisible para el frontend

Primer intento: puse **ambas** cookies (`refresh_token` y `csrf_token`) con `Path=/v1/auth`, pensando "solo las necesitan las rutas de auth". Pero `csrf_token` la tiene que leer `document.cookie` desde **el frontend** (`/fixtures`, `/bets`, `/login`...) — páginas que nunca están bajo `/v1/auth`. Un navegador solo expone a `document.cookie` las cookies cuyo `Path` es prefijo de la página actual, así que `getCsrfToken()` devolvía `null` siempre, y cada intento de refresh fallaba con `403` en la práctica (aunque mis pruebas con `curl -b cookies.txt` sí "veían" la cookie, porque el cookie-jar de curl no aplica esa restricción de lectura).

**Fix:** `csrf_token` pasa a `Path=/` (visible en todo el frontend); `refresh_token` se queda en `Path=/v1/auth` (el navegador la adjunta a esas requests sin importar desde qué página del frontend salga la petición — el `Path` de una cookie se compara contra la URL de destino, no contra la página que hace el fetch).

### Bug 2 — el logout no borraba `csrf_token` en el navegador

`_clear_session_cookies` llamaba `response.delete_cookie(...)` sin repetir `secure`/`samesite`. Los navegadores aplican la regla *"Leave Secure Cookies Alone"*: un `Set-Cookie` de borrado que no incluya `Secure` no puede pisar una cookie que sí se creó con `Secure` -- el navegador simplemente ignora ese intento de borrado, aunque el `Path`/nombre coincidan. Resultado: tras "cerrar sesión", `csrf_token` seguía viva en el navegador (verificado con `document.cookie.includes("csrf_token=")` → `true` después del logout).

**Fix:** pasar `**_cookie_flags()` también a los `delete_cookie(...)`, para que el borrado matchee exactamente los flags con los que se creó la cookie.

## Evidencia end-to-end en navegador real (Chrome, vía Docker)

1. Login con `sess1@demo.io` → redirige a `/fixtures`, balance `1000 pts` visible en el nav.
2. `document.cookie.includes("csrf_token=")` → `true`; `.includes("refresh_token=")` → `false` (HttpOnly); `Object.keys(localStorage)` → `[]`.
3. Apuesta de 100 pts sobre Mexico → balance baja a `900 pts`, aparece en "Mis apuestas".
4. **Recarga completa de la página** (`F5` equivalente, borra todo el estado de memoria de React) → el usuario sigue autenticado, balance `900 pts` se mantiene — confirma que `SessionBootstrap` recupera la sesión vía la cookie HttpOnly sin pedir credenciales de nuevo.
5. Logout → redirige a `/login`, nav muestra "Entrar". `csrf_token` ya no está en `document.cookie`. Recargar de nuevo **no** restaura la sesión (el refresh token quedó revocado server-side).

## Qué queda fuera de esta implementación (documentado, no resuelto)

- **Requisito de diseño para cuando exista cambio de contraseña** (no existe ese endpoint hoy, se revisó `auth.py` completo): debe revocar todos los `RefreshToken` del usuario en la misma transacción que el cambio de password. Documentado tal cual lo pide el plan, sin implementar un endpoint especulativo que no se necesita todavía.
- **Sin UI dedicada de "gestionar sesiones"** en el frontend (listar/revocar desde pantalla): el plan solo exige que el endpoint exista y funcione (verificable por API/DevTools), no una pantalla. `api.sessions()`/`api.revokeSession(jti)` ya están en `lib/api.ts`, listos para una pantalla futura si hace falta.
- **`SameSite=None` en producción depende de que Railway sirva ambos servicios sobre HTTPS** (ya lo hace por defecto) -- si en algún momento backend y frontend pasan a compartir dominio raíz, conviene apretar a `SameSite=Lax` como defensa adicional (hoy no es posible porque son subdominios `*.up.railway.app` distintos, tratados como sitios distintos).

## Archivos modificados

**Backend:**
- `backend/app/api/auth.py` — reescrito: cookies, CSRF, `sessions`/`sessions/{jti}`.
- `backend/app/schemas/schemas.py` — `TokenOut` sin `refresh_token`; `RefreshIn` eliminado; `SessionOut` nuevo.
- `backend/app/main.py` — CORS: `allow_headers` con `X-CSRF-Token`, `allow_methods` con `DELETE`.

**Frontend:**
- **Nuevo** `frontend/lib/session.ts`.
- `frontend/lib/api.ts` — reescrito (memoria en vez de localStorage, `credentials: include`, reintento silencioso en 401).
- `frontend/app/layout.tsx`, `components/Nav.tsx`, `components/BetSlip.tsx`, `lib/betslip.tsx`, `app/bets/page.tsx` — migrados a `useSession()`.

## Historial de revisiones

- **2026-07-16** — Implementación completa de la sección 07. Verificado end-to-end en Docker + Chrome real (no solo `curl`): login/logout/refresh silencioso/apuesta autenticada/IDOR en revocación de sesiones. Dos bugs de cookies (Path del CSRF token, borrado de cookies Secure) encontrados y corregidos durante la verificación en navegador — no se habrían detectado solo con pruebas de API.
