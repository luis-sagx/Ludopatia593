# Ofuscación de versiones de tecnología — Ludopatia593 (Sección 05 del hardening plan)

> A diferencia de las secciones 03 y 04, acá la mayor parte ya estaba resuelta desde el commit `0d3fdf5` (`/docs` oculto, `poweredByHeader: false`). Faltaban dos puntos: el header `Server` seguía revelando `uvicorn`, y no se había probado en la práctica que un error `500` no filtre stack trace.

## Resumen de estado — evidencia de cierre del plan

| Ítem (checklist original) | Estado | Cómo se verificó |
|---|---|---|
| `/docs` y `/openapi.json` responden `404` en producción | ✅ Ya estaba bien (sección 02) | Reverificado en esta pasada: `docs=404 openapi=404`. |
| `curl -I` no muestra `X-Powered-By` en el frontend | ✅ Ya estaba bien (`poweredByHeader: false`) | Verificado en Docker: header ausente. |
| Header `Server` del backend no revela `uvicorn` ni versión | ✅ **Implementado y verificado** (requirió dos intentos, ver abajo) | `curl -I` muestra `server: ludopatia593`, una sola vez, sin rastro de `uvicorn`. |
| Ningún `500` en producción devuelve stack trace | ✅ **Verificado con una prueba forzada real** | Se agregó temporalmente una ruta que lanza una excepción sin manejar, se probó, se confirmó el comportamiento, y se eliminó la ruta. |

## Qué se implementó

### 1. Header `Server` — el primer intento no funcionó, y eso es la parte interesante

Mi primer intento fue simplemente setear `resp.headers["Server"] = "..."` dentro de `security_middleware` (`main.py`), asumiendo que FastAPI/uvicorn solo agregan su valor default (`uvicorn`) si el header no viene ya seteado por la app. **Eso era incorrecto.** Al probarlo en Docker, la respuesta traía **dos** headers `Server`:

```
server: uvicorn
server: ludopatia593
```

uvicorn agrega su propio `Server: uvicorn` en la capa del protocolo HTTP (h11), sin importar lo que la app ya haya seteado. La forma correcta de suprimirlo es el flag `--no-server-header` de uvicorn (equivalente a `server_header=False` en `uvicorn.Config`), que desactiva por completo esa inyección automática — dejando únicamente el header que la propia app define.

**Cambios:**
- `backend/start.sh`: se agregó `--no-server-header` al comando de arranque de uvicorn (usado en producción/Railway).
- `docker-compose.yml`: se agregó el mismo flag al `command:` del servicio `backend` (que sobreescribe el `CMD` del Dockerfile en desarrollo local, así que había que tocarlo en los dos lugares).
- `backend/app/main.py` (`security_middleware`): se mantiene `resp.headers["Server"] = "ludopatia593"` — ahora sí es el único header `Server` de la respuesta, porque uvicorn ya no inyecta el suyo.

**Verificado:**
```
$ curl -I http://localhost:8081/health
server: ludopatia593
```
Una sola línea, sin `uvicorn` en ningún punto.

### 2. Confirmación de que un `500` no filtra stack trace

FastAPI/Starlette ya traían este comportamiento correcto por defecto (`FastAPI()` se instancia sin `debug=True` en `main.py`), pero no estaba **probado**, solo asumido. Para no darlo por bueno sin evidencia, se agregó temporalmente una ruta (`/__debug_boom`) que lanza `RuntimeError` sin capturar, se reconstruyó la imagen, se la invocó, y se eliminó la ruta antes de cerrar la sección.

**Respuesta cruda al cliente:**
```
HTTP/1.1 500 Internal Server Error
content-length: 21
content-type: text/plain; charset=utf-8

Internal Server Error
```
Sin ruta de archivo, sin nombre de excepción, sin traceback — el mensaje real (`"prueba temporal seccion 05 -- fuerza un 500 sin manejar"`) **no** llega al cliente.

**Log del contenedor (para comparar qué sí ve el equipo, server-side):**
```
File "/app/app/main.py", line 119, in _debug_boom
    raise RuntimeError("prueba temporal seccion 05 -- fuerza un 500 sin manejar")
RuntimeError: prueba temporal seccion 05 -- fuerza un 500 sin manejar
```
El traceback completo sí queda disponible para debugging interno (vía `docker logs` / futuro colector de logs de la sección 03) — el control correcto no es "no registrar el error", es "no exponerlo al cliente".

La ruta de prueba se eliminó del código inmediatamente después; no queda ningún rastro en `main.py`.

## Evidencia adicional reverificada (ya cerrada en secciones previas, se confirma que sigue así)

```
$ curl -o /dev/null -w "%{http_code}" http://localhost:8081/docs        # 404
$ curl -o /dev/null -w "%{http_code}" http://localhost:8081/openapi.json # 404
$ curl -I http://localhost:3000/ | grep -i x-powered-by                 # (ausente)
```

## Archivos modificados

- `backend/app/main.py` — `Server` header sobrescrito en `security_middleware`.
- `backend/start.sh` — `--no-server-header` en el comando de uvicorn.
- `docker-compose.yml` — mismo flag en el `command:` de `backend`.

## Qué queda pendiente

Ninguno de código. Lo único que sigue dependiendo de un dominio de producción real (no verificable desde acá, igual que en la sección 02) es confirmar con `curl -I` contra el dominio de Railway una vez que el deploy esté actualizado — el comportamiento en sí ya está verificado en Docker local con `ENVIRONMENT=production`.

## Historial de revisiones

- **2026-07-15** — Cierre de la sección 05: header `Server` corregido (con el hallazgo de que requiere `--no-server-header` en uvicorn, no alcanza con setearlo desde la app) y verificación forzada de que un `500` no filtra stack trace. Todo probado en un proyecto Docker aislado (`ludoptest`), descartado al terminar.
