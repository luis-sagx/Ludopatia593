# ludopatia593 — Predictor Mundial FIFA 2026

Predictor académico de la Copa Mundial 2026. Estima probabilidades de mercados
(1X2, over/under, BTTS, marcador exacto, campeón) con un modelo **Dixon-Coles**
calibrado, expone cuotas justas + valor esperado, y permite predicciones con
**puntos virtuales** (sin dinero real). Construido con foco en **software seguro**.

## Alcance (decisiones del proyecto)

- **Sin dinero real** — solo predicción/simulación con puntos virtuales.
- **Sin compliance regulatorio** — proyecto no publicado (académico).
- **Datos gratis** — Dixon-Coles entrenado con históricos abiertos (Kaggle); el
  pipeline corre con dataset sintético si no hay CSV. `football-data.org` es
  opcional solo para fixtures.

## Arquitectura

Monolito modular Python. API FastAPI + servicio de inferencia ML en proceso.
PostgreSQL (datos), Redis (cache cuotas/leaderboard + rate limit).

```
backend/app/
  ml/        motor: dixon_coles, markets, calibration, montecarlo, train, inference
  core/      config, security (Argon2id + JWT), ratelimit
  db/        modelos SQLAlchemy + sesión
  api/       auth, predictions, bets, admin, leaderboard
  main.py    wiring + middleware de seguridad
```

## Motor de predicción

- **Dixon-Coles** (Poisson bivariante + corrección tau marcadores bajos +
  decaimiento temporal). Una matriz de marcadores deriva todos los mercados de
  forma consistente.
- **Monte Carlo** del torneo para campeón/finalista/avance de grupo.
- **Evaluación honesta**: Brier, log-loss, RPS con **validación temporal
  walk-forward** (sin fuga de datos). Calibración Platt disponible.

## Seguridad (DevSecOps por diseño)

- Passwords **Argon2id** (memory-hard, parámetros explícitos).
- **JWT** acceso corto (15 min) + **refresh rotatorio con revocación** y
  detección de reuso (revoca cadena ante robo).
- **RBAC** user/admin, mínimo privilegio, rutas admin segregadas.
- **Idempotencia** en predicciones (anti replay/doble-submit).
- **Cuota siempre del servidor** (re-derivada del modelo) — imposible manipular
  odds/payout desde el cliente.
- **Concurrencia**: descuento de puntos bajo `SELECT ... FOR UPDATE` (anti race).
- **IDOR** bloqueado (propiedad por objeto), **rate limiting** por IP,
  headers endurecidos (CSP, nosniff, X-Frame-Options), CORS restringido.
- Secretos **solo desde entorno** (nunca en código). Bitácora de auditoría.

## Correr

### Docker (recomendado)

```bash
cp .env.example .env
# rellena JWT_SECRET (openssl rand -hex 32) y ADMIN_PASSWORD
docker compose up --build
# API en http://localhost:8000  (docs: /docs)
```

Arranque: entrena modelo → siembra DB (admin + fixtures demo) → levanta API.
Frontend en http://localhost:3000.

### Frontend solo (dev)

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000, proxy /api -> backend:8000
```

### Local (sin Docker, SQLite)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt   # incluye pytest/cov; psycopg2 solo para Postgres
python -m app.ml.train                # genera data/model.json
python -m pytest                      # suite completa sobre SQLite
```

## Tests

`backend/tests/` (pytest, sobre SQLite, sin Docker) valida el flujo completo y
la seguridad: registro, login, refresh rotatorio + CSRF, predicción del modelo,
apuesta con puntos, idempotencia, IDOR, liquidación admin, RBAC, rate limiting,
cabeceras endurecidas y leaderboard. Cobertura con gate 80% (`backend/pytest.ini`).

```bash
cd backend && python -m pytest   # corre la suite + reporte de cobertura
```

## Endpoints clave

- `POST /v1/auth/register` · `/login` · `/refresh` · `/logout` · `GET /me`
- `GET /v1/fixtures` · `GET /v1/fixtures/{id}/prediction` · `GET /v1/predict?home=&away=`
- `GET /v1/tournament/champion`
- `POST /v1/bets` (puntos) · `GET /v1/bets` · `GET /v1/bets/{id}`
- `GET /v1/me/performance` · `GET /v1/leaderboard`
- `POST /v1/admin/fixtures/{id}/result` · `POST /v1/admin/model/reload` · `GET /v1/admin/audit`

## Frontend (Next.js 15, App Router)

`frontend/` — login/registro, listado de partidos con predicción + cuota + EV
y apuesta en puntos, simulación de torneo (campeón), ranking y panel "mis
predicciones" con ROI/hit-rate. Proxy `/api/*` al backend (sin CORS en navegador).

## Ensamble GBM (capa ML, fase 2)

`ml/features.py` + `ml/ensemble.py` — features sin fuga de datos (ELO incremental,
forma reciente, descanso, localía) y `HistGradientBoostingClassifier` (sklearn)
regularizado con early stopping. Blend final = `0.6·Dixon-Coles + 0.4·GBM`.

Comparar: `python -m app.ml.eval_ensemble`.

Nota honesta: sobre el dataset **sintético** el ensamble empata/pierde levemente
frente a Dixon-Coles solo — esperado, porque ese dataset se genera con un proceso
Poisson puro sin señal adicional, así que las features ELO/forma solo añaden ruido.
Sobre históricos reales (Kaggle), donde sí hay señal, el blend mejora calibración.

## Pendiente

- ETL real desde `football-data.org` para fixtures del Mundial.
- Serializar el GBM y exponer el blend en el endpoint de predicción en vivo.

## Descargo

Las predicciones son **probabilísticas, no garantías**. Proyecto académico.
