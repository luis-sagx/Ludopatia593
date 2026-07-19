# Operar la demo — reiniciar el torneo y avanzarlo

> Cómo correr la presentación en vivo: reiniciar el Mundial desde el primer partido, dejar que los usuarios apuesten, e ir revelando resultados ronda a ronda desde el panel admin.
>
> _Última actualización: 2026-07-19._

---

## Idea

El torneo arranca **desde el primer partido**: TODOS los partidos están abiertos para apostar (con desbloqueo progresivo: primero la jornada 1, luego se abren las siguientes). Los usuarios apuestan con puntos virtuales; el admin va "jugando" cada ronda y se revela el **resultado real** del Mundial 2026, liquidando quién ganó y quién perdió puntos.

## Flujo de la presentación

1. **Entra como admin** (la cuenta de `ADMIN_EMAIL` / `ADMIN_PASSWORD`) y ve a **Mis apuestas**. Ahí aparece el **Panel admin · Control del torneo**.
2. **Reiniciar torneo** (botón). Deja todo desde cero: borra todas las apuestas, restablece el saldo de todos los usuarios (1000 puntos) y reabre todos los partidos desde la jornada 1. Pide confirmación (es destructivo).
3. **Los usuarios apuestan** en la jornada activa (al inicio, la jornada 1 de grupos).
4. **Jugar siguiente jornada** (botón). Juega la ronda activa con los marcadores reales, liquida las apuestas pendientes (gana/pierde puntos) y **desbloquea la siguiente ronda**.
5. Repite el paso 4 avanzando: jornadas 1→2→3 de grupos, luego dieciseisavos, octavos, cuartos, semis, 3.º puesto y final. El **leaderboard** se actualiza en cada ronda.

> El 3.er puesto y la final no tienen resultado real (aún no se jugaron en la vida real): esos dos se resuelven con el modelo (marcador simulado realista).

## Endpoints detrás de los botones (por si se opera por API)

Ambos requieren token de **admin** (rol `admin`) y están protegidos por rate limit del router admin.

```bash
BACK=https://<backend>.up.railway.app
ATOK=<access_token_admin>   # de POST /v1/auth/login con la cuenta admin

# Reiniciar el torneo desde cero
curl -X POST $BACK/v1/admin/reset-tournament -H "Authorization: Bearer $ATOK"
# -> {"ok":true,"predictions_deleted":N,"users_reset":M,"fixtures_reset":K}

# Jugar la siguiente jornada/ronda (sin body = ronda activa completa)
curl -X POST $BACK/v1/admin/simulate -H "Authorization: Bearer $ATOK" \
  -H 'Content-Type: application/json' -d '{}'

# Jugar solo N partidos de la ronda activa (avance partido a partido)
curl -X POST $BACK/v1/admin/simulate -H "Authorization: Bearer $ATOK" \
  -H 'Content-Type: application/json' -d '{"count":1}'
```

## En el deploy actual de Railway (torneo ya jugado)

La base de Railway tiene el torneo de una demo anterior. **No hace falta recrear la base**: basta con desplegar esta rama (Railway redepliega solo al hacer push/merge) y pulsar **Reiniciar torneo** una vez. El reset **rehace los partidos desde el seed** (round_order correcto, con su resultado real oculto), borra apuestas y restablece saldos. Esto además **sana bases viejas**: si los partidos traían `round_order=0` de un esquema anterior (por eso salían las 104 rondas de golpe en vez de una a la vez), al rehacerlos se corrige y el desbloqueo progresivo vuelve a funcionar (solo se ve la jornada 1, luego las siguientes al avanzar).

> El reset **no** borra cuentas de usuario ni la bitácora de auditoría (`audit_log`): solo reinicia el estado del juego (apuestas, saldos y estado de los partidos).
