# Guía de implementación de CI/CD — Ludopatia593

> ⚠️ **SUPERSEDED (2026-07-19):** el CI ya está implementado en `.github/workflows/ci.yml`
> (pytest+cobertura con gate 80%, build de ambas imágenes y escaneo Trivy). La suite pasó
> de un único `smoke.py` a una suite pytest en `backend/tests/`. Este documento se conserva
> como registro del plan original; para el estado real ver `Despliegue-Railway.md` §0 + Apéndice A.
>
> Documento para **el compañero que implementará el CI/CD**. Estado original: **no había CI**; el CD es el auto-deploy de Railway al hacer push. Esta guía dice qué crear, con archivos listos para copiar, y cómo conectarlo con Railway para que un push roto **no** llegue a producción.
>
> _Creado: 2026-07-19._

---

## 1. Punto de partida (verificado hoy)

- ❌ **No existe `.github/workflows/`** ni ningún otro pipeline (GitLab/Circle/Travis/Jenkins).
- ✅ **CD parcial ya activo:** `backend/railway.toml` y `frontend/railway.toml` (builder Dockerfile) → Railway redepliega al hacer push a la rama conectada.
- ⚠️ **Problema a resolver:** como no hay CI, hoy un push con el código roto se despliega igual. Tu objetivo es meter una **puerta de calidad antes del deploy**.

### Herramientas disponibles en el repo (para no inventar comandos)
| Área | Qué hay | Qué NO hay |
|---|---|---|
| Backend | Smoke test end-to-end: `backend/tests/smoke.py` (SQLite, sin Docker) | pytest, ruff, mypy (no están en `requirements.txt`) |
| Frontend | `npm run lint` (next lint) + TypeScript (`tsc`) | tests unitarios |
| Contenedores | `backend/Dockerfile`, `frontend/Dockerfile` (+ `.dockerignore` ya creados) | escaneo de imágenes |

> Diseña el CI sobre lo que **ya existe**. Añadir ruff/pytest/jest es opcional y va como mejora posterior (sección 7), no como bloqueante.

---

## 2. Objetivo y estrategia

**Meta:** que cada Pull Request corra automáticamente: smoke test del backend, lint + typecheck del frontend, y build de ambas imágenes Docker. Solo si todo pasa, se permite el merge a `main`. Railway despliega **desde `main`**.

**Flujo objetivo:**
```
feature branch → Pull Request → [CI corre: smoke + lint + typecheck + build] → verde → merge a main → Railway auto-deploy
```

Dos capas de protección:
1. **GitHub Actions** corre las verificaciones.
2. **Branch protection** en `main` exige que esas verificaciones estén en verde antes de mergear.
3. (Refuerzo) **Railway "Wait for CI"** para que ni siquiera despliegue si las checks del commit no pasaron.

---

## 3. Tareas paso a paso

- [ ] **T1.** Crear `.github/workflows/ci.yml` (contenido en sección 4).
- [ ] **T2.** (Opcional pero recomendado) Crear `.github/workflows/security-scan.yml` con Trivy (sección 5).
- [ ] **T3.** Confirmar que `backend/tests/smoke.py` corre en limpio localmente antes de subir el workflow (evita un primer run rojo por otra causa).
- [ ] **T4.** Abrir un PR de prueba y confirmar que las checks aparecen y pasan.
- [ ] **T5.** Activar **branch protection** en `main` (sección 6) exigiendo las checks de CI.
- [ ] **T6.** En Railway, activar **"Wait for CI"** en cada servicio (sección 6).
- [ ] **T7.** Documentar en el `README` que se trabaja por feature branch + PR (ya no push directo a `main`).

---

## 4. `.github/workflows/ci.yml` (listo para copiar)

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

# Cancela runs viejos del mismo PR si llega un push nuevo
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend-smoke:
    name: Backend · smoke test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Instalar dependencias
        run: pip install -r backend/requirements.txt
      - name: Smoke test end-to-end (SQLite)
        working-directory: backend
        env:
          DATABASE_URL: sqlite:///./smoke.db
          JWT_SECRET: test-secret-ci-only-not-a-real-secret
          ADMIN_PASSWORD: admin-pass-ci
        run: |
          rm -f smoke.db
          python -m tests.smoke

  frontend-checks:
    name: Frontend · lint + typecheck
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      - name: Instalar dependencias
        working-directory: frontend
        run: npm ci || npm install
      - name: Typecheck (tsc --noEmit)
        working-directory: frontend
        run: npx tsc --noEmit
      - name: Lint
        working-directory: frontend
        run: npm run lint

  docker-build:
    name: Build de imágenes Docker
    runs-on: ubuntu-latest
    needs: [backend-smoke, frontend-checks]
    steps:
      - uses: actions/checkout@v4
      - name: Build backend
        run: docker build -t ludopatia-backend:ci ./backend
      - name: Build frontend
        run: docker build -t ludopatia-frontend:ci ./frontend
             --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Notas de diseño (para que entiendas por qué así, no lo copies a ciegas):**
- El smoke test **entrena el modelo y siembra la DB**; por eso necesita `JWT_SECRET` y `ADMIN_PASSWORD` (sin este último, el seed aborta). Son valores de CI, no secretos reales.
- `ENVIRONMENT` no se setea → queda en `dev`, correcto para el smoke (el fail-fast del JWT solo aplica fuera de `dev`).
- `docker-build` corre **después** de las verificaciones (`needs:`) para no gastar minutos si algo básico ya falló.
- El build del frontend pasa `NEXT_PUBLIC_API_URL` como build-arg porque el Dockerfile lo exige; en CI el valor es irrelevante (solo valida que compile).

---

## 5. `.github/workflows/security-scan.yml` (opcional — cierra el pendiente de la sección 04 de seguridad)

```yaml
name: Security scan

on:
  pull_request:
  schedule:
    - cron: "0 6 * * 1"   # lunes 06:00 UTC, re-escaneo semanal

jobs:
  trivy:
    name: Trivy · imágenes
    runs-on: ubuntu-latest
    strategy:
      matrix:
        service: [backend, frontend]
    steps:
      - uses: actions/checkout@v4
      - name: Build ${{ matrix.service }}
        run: |
          if [ "${{ matrix.service }}" = "frontend" ]; then
            docker build -t scan:${{ matrix.service }} ./frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000
          else
            docker build -t scan:${{ matrix.service }} ./backend
          fi
      - name: Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: scan:${{ matrix.service }}
          severity: CRITICAL,HIGH
          exit-code: "1"          # falla el job si hay CRITICAL/HIGH con parche
          ignore-unfixed: true    # no bloquea por vulns sin parche disponible
```

> Esto implementa el ítem "trivy image sin CRITICAL sin parche" que quedó pendiente en `docs/security/Docker.md`.

---

## 6. Conectar CI con el CD de Railway (la parte que la gente olvida)

Sin esto, GitHub Actions corre pero Railway despliega igual aunque el CI esté rojo.

### 6.1 Branch protection en `main` (GitHub)
1. GitHub → Settings → Branches → Add branch protection rule → Branch name pattern: `main`.
2. Marcar **"Require a pull request before merging"**.
3. Marcar **"Require status checks to pass before merging"** y seleccionar:
   - `Backend · smoke test`
   - `Frontend · lint + typecheck`
   - `Build de imágenes Docker`
4. (Recomendado) **"Require branches to be up to date before merging"**.

### 6.2 "Wait for CI" en Railway
1. Railway → cada servicio (backend y frontend) → Settings → Deploys.
2. Activar **"Wait for CI"** (o "Check Suites must pass"). Así Railway espera a que las GitHub Checks del commit estén verdes antes de desplegar.
3. Confirmar que la **rama de deploy** de cada servicio es `main`.

Resultado: un PR con smoke roto no se puede mergear (6.1); y si algo llega a `main` con checks fallando, Railway no lo despliega (6.2).

---

## 7. Mejoras posteriores (no bloqueantes, backlog)

| Mejora | Por qué | Esfuerzo |
|---|---|---|
| Añadir `ruff` al backend (`ruff check backend/`) | Lint/format Python, hoy inexistente | Bajo (añadir dep + un step) |
| Migrar el smoke a `pytest` con casos separados | Mejor reporting de qué falló | Medio |
| Tests unitarios de frontend (Vitest/Jest) | Hoy 0 cobertura de UI | Medio |
| Fijar digest de imágenes base (`@sha256:...`) | Builds reproducibles (sección 04 seguridad) | Bajo |
| Publicar imágenes a un registry y que Railway despliegue esa imagen (en vez de rebuild) | Deploy determinista: se despliega exactamente lo que pasó el CI | Alto |

---

## 8. Criterio de "hecho" (Definition of Done)

- [ ] `.github/workflows/ci.yml` existe y corre en cada PR.
- [ ] Un PR con el smoke test roto **no** se puede mergear (branch protection lo bloquea).
- [ ] `main` está protegida: sin push directo, solo vía PR con checks verdes.
- [ ] Railway despliega **solo** desde `main` y con "Wait for CI" activo.
- [ ] (Opcional) Trivy corre y falla ante CRITICAL/HIGH con parche.
- [ ] `README` actualizado con el flujo feature-branch → PR → merge.

---

## Referencias cruzadas
- `docs/Despliegue-Railway.md` — runbook de despliegue (variables, verificación post-deploy). El CI/CD es complementario a ese doc.
- `docs/security/hardening-plan.md` — controles de seguridad; el Trivy de la sección 5 cierra un pendiente de ahí.
