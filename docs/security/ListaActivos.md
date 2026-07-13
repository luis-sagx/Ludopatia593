# Inventario de activos — Ludopatia593

## Metodología

Clasificación por **Confidencialidad / Integridad / Disponibilidad (C/I/D)**, cada una en `Alto/Medio/Bajo`. La **criticidad global** no es un promedio: es el máximo de las tres, ponderado por **radio de explosión** (cuántos otros activos quedan expuestos si este se compromete).

Esto separa el inventario en tres capas, que es lo que realmente determina el orden de remediación:

- **Raíces de confianza** (AST-01 a AST-03): comprometerlas anula el resto de los controles del sistema, no solo exponen su propio contenido.
- **Activos primarios** (AST-04 a AST-08): lo que efectivamente se protege — datos y lógica de negocio.
- **Activo de respuesta** (AST-09): no protege datos, protege la capacidad de investigar qué pasó con los demás.

## Resumen ejecutivo — los 5 más valiosos

| # | Activo | Por qué pesa más que su tamaño sugiere |
|---|---|---|
| 1 | `JWT_SECRET` | Raíz de confianza única (HS256 simétrico); comprometerlo = impersonar cualquier rol sin credenciales. Radio de explosión: 100% del sistema. |
| 2 | Cuenta admin (rol + credenciales) | Control operativo total: liquida apuestas, recarga el modelo, sincroniza datos. Combinado con #1, control absoluto. |
| 3 | Acceso directo a Postgres (`DB_PASSWORD`) | No tiene valor propio — es el punto de mayor concentración de valor: contiene a todos los demás activos a la vez. |
| 4 | `points_balance` / `UserPrediction` | Es el único activo de negocio real del producto (no hay dinero real); su integridad *es* la confianza del producto. |
| 5 | `AuditLog` | Activo de segundo orden: protege la capacidad de responder ante el compromiso de cualquiera de los otros cuatro. |

---

## Registro completo de activos

### Raíces de confianza

| ID | Activo | Ubicación | C/I/D | Criticidad | Justificación (impacto si se compromete) | Controles actuales | Gap → sección |
|---|---|---|---|---|---|---|---|
| AST-01 | `JWT_SECRET` (firma HS256) | `backend/app/core/config.py:18`, env | C:Alto · I:Alto · D:Medio | **Crítico** | Simétrico: quien lo obtiene firma tokens de cualquier usuario o admin sin login. Anula RBAC, rate limit por identidad y revocación de sesión (un token falsificado no tiene `jti` real en `RefreshToken`, pero el access token de 15 min no se valida contra tabla). | Requerido en arranque (`:?` en compose, falla si falta); default inseguro explícito solo en `dev`. | 02 — sin gestor de secretos ni rotación |
| AST-02 | Credenciales admin + rol `Role.admin` | `docker-compose.yml` (`ADMIN_EMAIL/PASSWORD`), `db/models.py:22-24,46` | C:Alto · I:Alto · D:Bajo | **Crítico** | Control operativo total sobre `settle_fixture`, `model/reload`, `fixtures/sync` (`backend/app/api/admin.py`). Un admin comprometido puede acreditar puntos arbitrarios o corromper resultados liquidados. | RBAC segregado vía `require_admin` (`api/deps.py:32`); `ADMIN_PASSWORD` obligatorio en arranque. | 06 — sin rate limit propio en `/v1/admin/*`; 07 — sin revocación de sesiones al detectar abuso |
| AST-03 | Acceso a Postgres (`DB_PASSWORD`, red interna) | `docker-compose.yml:6`, `DATABASE_URL` | C:Alto · I:Alto · D:Alto | **Crítico** | Contiene simultáneamente AST-04 a AST-09. No es un activo con valor propio — es el de mayor concentración: un solo compromiso expone todo lo demás a la vez. | Sin `ports:` publicado en compose (no alcanzable desde el host). | 04 — verificar grants del usuario `app` (¿superusuario?), backups cifrados y probados |

### Activos primarios

| ID | Activo | Ubicación | C/I/D | Criticidad | Justificación (impacto si se compromete) | Controles actuales | Gap → sección |
|---|---|---|---|---|---|---|---|
| AST-04 | `password_hash` de usuarios | `db/models.py:45` (`User`) | C:Alto · I:Medio · D:Bajo | Alto | El hash en sí no es reversible, pero protege contraseñas que los usuarios probablemente reutilizan en otros servicios — el impacto de una fuga trasciende esta app. | Argon2id explícito (time_cost=3, memory_cost=64MiB, parallelism=2), no defaults implícitos (`core/security.py:20`). | Sin gap abierto — control ya adecuado, mantener en revisión de sección 02. |
| AST-05 | Refresh tokens (`jti`) / sesiones activas | `db/models.py:54-63` (`RefreshToken`); `frontend/lib/api.ts:11-25` | C:Alto · I:Medio · D:Bajo | Alto | Robo = secuestro de sesión sin necesitar contraseña. Hoy persisten en `localStorage` del navegador, alcanzables por cualquier XSS. | Rotación con detección de reuso (revoca cadena completa si se reusa un token revocado, `api/auth.py:89-95`); TTL 7 días. | 07 — mover a cookie HttpOnly; sin endpoint para listar/revocar sesiones propias |
| AST-06 | `points_balance` (saldo virtual) | `db/models.py:47` (`User`) | C:Bajo · I:Alto · D:Medio | Alto | Es el único activo económico real del producto (sin dinero real detrás). Manipularlo — saldo infinito, robo de saldo ajeno — destruye la confianza que sostiene todo el producto. | Bloqueo de fila (`with_for_update`) al acreditar en `settle_fixture` (`api/admin.py:71`); previene race condition en liquidación concurrente. | Sin gap abierto directo — depende de que AST-01/02 estén cerrados (quien falsifica un token puede alterar saldo vía endpoints legítimos). |
| AST-07 | `UserPrediction` (apuestas, `idempotency_key`) | `db/models.py:90-114` | C:Bajo · I:Alto · D:Medio | Medio | Integridad transaccional: doble-submit o replay alterarían el resultado económico de una apuesta ya liquidada. | `UniqueConstraint(user_id, idempotency_key)`; estado `pending/won/lost/void` explícito. | Sin gap abierto — control ya adecuado. |
| AST-08 | `FOOTBALL_DATA_API_KEY` | `core/config.py:31`, env | C:Medio · I:Bajo · D:Medio | Medio | Credencial de terceros. Abuso o fuga puede agotar cuota o provocar bloqueo del servicio para el uso legítimo del proyecto (`services/api_football.py`). | Enviada solo vía header `X-Auth-Token` sobre HTTPS (`httpx` con verificación TLS por defecto); nunca logueada. | Sin gap abierto — bajo impacto y ya aislada en un único cliente (`FootballDataClient`). |
| AST-09b | `email` de usuario | `db/models.py:44` | C:Medio · I:Bajo · D:Bajo | Medio | PII de baja sensibilidad — no hay datos financieros reales detrás, pero sigue siendo dato personal. | Único + indexado, nunca expuesto en `AuditLog.detail`. | 02 — depende de cifrado en reposo a nivel de disco del proveedor, no de la app. |
| AST-10 | `model.json` (modelo Dixon-Coles) | `backend/data/`, `ml/train.py` | C:Bajo · I:Medio · D:Medio | Medio | Activo de IP/negocio, no de datos personales. Corromperlo afecta la integridad de las predicciones mostradas — confianza del producto, no seguridad de datos. | Recarga atómica solo vía `require_admin` (`api/admin.py:87-93`). | Sin gap abierto — bajo impacto fuera del rol admin, ya cubierto por AST-02. |

### Activo de respuesta

| ID | Activo | Ubicación | C/I/D | Criticidad | Justificación (impacto si se compromete) | Controles actuales | Gap → sección |
|---|---|---|---|---|---|---|---|
| AST-09 | `AuditLog` (bitácora append-only) | `db/models.py:117-126` | C:Bajo · I:Alto · D:Medio | Alto | No protege datos directamente — protege la **capacidad de investigar** qué pasó con AST-01 a AST-08. Si se puede alterar o silenciar, se pierde la trazabilidad de cualquier incidente sobre los demás activos. | Ya se usa con disciplina: `detail` (JSON) nunca contiene secretos en los usos actuales (`register`, `login`, `settle_fixture`, `sync_fixtures`). | 03 — no hay traza de requests HTTP a nivel de infraestructura, solo eventos de negocio; sin protección explícita contra escritura directa a la tabla fuera de la app. |

---

## Fuera de alcance (por ahora)

| Activo potencial | Por qué no está en el registro | Cuándo agregarlo |
|---|---|---|
| Secretos de CI/CD | No existe pipeline (`.github/workflows` no encontrado) | Al configurar CI, antes del primer secreto en GitHub Actions |
| Certificados TLS | Terminación de TLS delegada al proveedor (Railway), no gestionada en el repo | Si se migra a infraestructura propia (ver sección 04 de `hardening-plan.md`, opción no recomendada) |
| Datos de tarjetas/pagos | El producto usa puntos virtuales, sin pasarela de pago | Si el modelo de negocio incorpora dinero real — cambia todo el modelo de amenaza, no solo este inventario |

---

## Cómo mantenerlo vivo

1. Cualquier PR que añada una columna a `db/models.py` o una variable a `core/config.py` **debe** añadir o actualizar una fila aquí.
2. Cualquier hallazgo nuevo en `hardening-plan.md` debe apuntar a un `ID` de este inventario, no describir el activo de nuevo.
3. Revisión completa trimestral, o inmediatamente después de cualquier incidente de seguridad real.

_Última actualización: 2026-07-13._
