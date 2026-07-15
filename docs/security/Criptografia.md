# Criptografía — Ludopatia593 (Sección 02 del hardening plan)

> Ámbito de esta sección (según `docs/security/hardening-plan.md`): fortaleza y gestión de `JWT_SECRET`, TLS/HSTS en producción, y cifrado en reposo de Postgres. El hashing de contraseñas (Argon2id) ya está evaluado como control adecuado en `AST-04` de `ListaActivos.md` y no se re-audita aquí.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| `JWT_SECRET` en producción distinto del default |  **Cerrado a nivel de aplicación** | Prueba en Docker local (ver abajo): el backend **rechaza arrancar** si el secreto es el default o mide <32 caracteres fuera de `dev`. Ya no depende de que alguien recuerde cambiarlo — el sistema falla rápido en vez de arrancar inseguro. |
| `curl -I http://<dominio-prod>` redirige a `https` |  **Pendiente — no verificable hoy** | El despliegue actual en Railway está desactualizado (no refleja el código de esta rama). No tiene sentido auditar TLS contra una versión vieja. Queda documentado el comando exacto para correr apenas se redepliegue. |
| Respuesta HTTPS incluye `Strict-Transport-Security` |  **Verificado a nivel de aplicación** ( falta confirmar en el dominio real) | Docker local con `ENVIRONMENT=production`: el header se envía correctamente (ver evidencia abajo). La terminación TLS real la hace Railway, no la app — falta la confirmación contra el dominio una vez actualizado el deploy. |
| Cifrado en reposo confirmado (Postgres + backups) |  **Pendiente — fuera del alcance del código** | Requiere entrar al panel de Railway (Settings del servicio Postgres). No es verificable desde el repo ni desde Docker local. |

## Evidencia técnica recolectada (Docker local, `ENVIRONMENT=production`)

Se levantó el stack (`db`, `redis`, `backend`) con `ENVIRONMENT=production` y un `JWT_SECRET` generado con `openssl rand -hex 32`, simulando las condiciones de producción sin depender del deploy desactualizado de Railway.

### 1. Headers de seguridad y HSTS

```
$ curl -s -D - -o /dev/null http://localhost:8080/health

HTTP/1.1 200 OK
x-content-type-options: nosniff
x-frame-options: DENY
referrer-policy: no-referrer
content-security-policy: default-src 'self'
strict-transport-security: max-age=31536000; includeSubDomains
```

`Strict-Transport-Security` solo aparece cuando `settings.environment != "dev"` (`backend/app/main.py:68-69`) — confirmado que se activa correctamente en modo producción.

**Hallazgo lateral (no es de esta sección, es de la 05):** el header `server: uvicorn` sigue presente en la respuesta — no se sobrescribe en `security_middleware`. Lo anoto aquí porque apareció en la misma prueba; la corrección corresponde a la sección 05 (ofuscación de versiones), no a esta.

### 2. `/docs`, `/redoc`, `/openapi.json` ocultos fuera de `dev`

```
$ curl -o /dev/null -w "status=%{http_code}\n" http://localhost:8080/docs
status=404
$ curl -o /dev/null -w "status=%{http_code}\n" http://localhost:8080/openapi.json
status=404
$ curl -o /dev/null -w "status=%{http_code}\n" http://localhost:8080/redoc
status=404
```

### 3. Fail-fast del `JWT_SECRET` débil (`config.py:61-72`)

**Caso A — default inseguro en `production`:**
```
JWT_SECRET=dev-only-insecure-change-me ENVIRONMENT=production ...
```
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
jwt_secret
  Value error, JWT_SECRET inseguro o ausente en entorno no-dev
  (usa 'openssl rand -hex 32')
```
Contenedor termina con `Exited (1)` — la aplicación **nunca llega a exponer un puerto**.

**Caso B — secreto corto (<32 caracteres) en `production`:**
```
JWT_SECRET=short123 ENVIRONMENT=production ...
```
Mismo resultado: `ValidationError`, contenedor no arranca.

**Caso C — secreto fuerte (64 caracteres, `openssl rand -hex 32`) en `production`:**
Arranca correctamente, health check en `200 OK` (evidencia usada en los puntos 1 y 2 arriba).

Esto confirma que el control descrito en `ListaActivos.md` (AST-01) funciona en la práctica, no solo en el código: es imposible desplegar en modo producción con el secreto por defecto o uno demasiado corto.

## Qué falta hacer (acciones concretas)

1. **Generar el secreto real de producción** con `openssl rand -hex 32` y cargarlo en Railway → Settings → Variables como `JWT_SECRET`. El valor **nunca** debe pegarse en un chat, commit o documento — solo el procedimiento se documenta, no el secreto en sí.
2. **Actualizar el deploy de Railway** con el código actual antes de repetir las pruebas de red contra el dominio real (el deploy vigente no refleja ni el fail-fast del `JWT_SECRET` ni el resto de mejoras recientes).
3. Tras el redeploy, ejecutar y registrar el resultado:
   ```bash
   curl -I http://<dominio-prod>     # esperado: 301/308 -> https
   curl -I https://<dominio-prod>    # esperado: incluye strict-transport-security
   ```
4. Confirmar en el panel de Railway que el volumen de Postgres y los backups están cifrados en reposo (captura de pantalla o confirmación escrita, adjuntar a este documento).
5. Seguir el procedimiento de rotación (abajo) la primera vez que se cargue el secreto real — no reutilizar ningún valor usado durante pruebas/desarrollo.

## Procedimiento de rotación de `JWT_SECRET`

**Por qué importa documentarlo:** `create_access_token`, `create_refresh_token` y `decode_token` (`backend/app/core/security.py:52-84`) usan el **mismo** `settings.jwt_secret` para firmar y validar tanto el access token (15 min) como el refresh token (7 días). Rotar el secreto invalida **ambos de inmediato** — no es un cambio silencioso, es un evento que desloguea a todos los usuarios activos. Por eso se documenta como procedimiento, no como acción improvisada.

**Cuándo rotar:**
- Sospecha o confirmación de fuga del secreto (ej. expuesto en un log, un repo, una captura compartida).
- Cambio de personal con acceso a las variables de Railway.
- Rotación preventiva periódica (recomendado cada 90 días si el proyecto pasa a operar con datos reales).

**Pasos:**
1. Generar el nuevo valor: `openssl rand -hex 32`.
2. Railway → proyecto backend → Settings → Variables → `JWT_SECRET` → reemplazar el valor.
3. Redeploy del servicio (Railway lo aplica al reiniciar el proceso; no hay hot-reload de variables de entorno).
4. Efecto inmediato y esperado: todo access/refresh token firmado con el secreto anterior deja de pasar `decode_token` (`JWTError` → 401) tan pronto el proceso nuevo esté sirviendo tráfico. **Todos los usuarios deben volver a iniciar sesión** — esto es la defensa, no un efecto secundario a evitar.
5. Si la rotación es por sospecha de fuga, comunicarlo como incidente (quién, cuándo, por qué) — el `AuditLog` de la app no cubre este evento porque es de infraestructura, no una acción de negocio; registrar la rotación en la sección "Historial" de este documento.
