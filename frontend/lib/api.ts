"use client";
// Cliente API. El navegador llama al backend directo (puerto publicado).
// CORS lo habilita el backend para http://localhost:3000.
// Access token en memoria (lib/session.ts), nunca localStorage. El refresh
// token vive en una cookie HttpOnly que pone el backend -- este archivo
// nunca la toca directamente, solo manda `credentials: "include"` para que
// el navegador la adjunte solo.

// NEXT_PUBLIC_* se hornea en build; default localhost:8000 sirve en Docker (puerto
// publicado, el navegador corre en el host) y en dev local.
const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

import { getAccessToken, setAccessToken, refreshSession, getCsrfToken } from "./session";

async function req(path: string, opts: RequestInit = {}, auth = false, _retried = false): Promise<any> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any) };
  if (auth) {
    const t = getAccessToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(`${BASE}${path}`, { ...opts, headers, credentials: "include" });

  // Access token vencido (dura 15 min): intenta renovar UNA vez con la
  // cookie de refresh antes de rendirse, para no desloguear al usuario en
  // cada sesión de navegación normal.
  if (res.status === 401 && auth && !_retried) {
    const renewed = await refreshSession();
    if (renewed) return req(path, opts, auth, true);
  }

  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch {}
    const err: any = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    err.status = res.status;
    // Retry-After (segundos) en respuestas 429 -> el llamador puede bloquear el
    // botón durante ese tiempo.
    const ra = res.headers.get("Retry-After");
    if (ra) err.retryAfter = parseInt(ra, 10);
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

function csrfHeaders(): Record<string, string> {
  const csrf = getCsrfToken();
  return csrf ? { "X-CSRF-Token": csrf } : {};
}

export const api = {
  register: (email: string, password: string, nickname: string) =>
    req("/v1/auth/register", { method: "POST", body: JSON.stringify({ email, nickname, password }) }),
  login: async (email: string, password: string) => {
    const t = await req("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    setAccessToken(t.access_token);
    return t;
  },
  logout: async () => {
    try {
      await req("/v1/auth/logout", { method: "POST", headers: csrfHeaders() }, true);
    } finally {
      setAccessToken(null);
    }
  },
  me: () => req("/v1/auth/me", {}, true),
  sessions: () => req("/v1/auth/sessions", {}, true),
  revokeSession: (jti: string) => req(`/v1/auth/sessions/${jti}`, { method: "DELETE" }, true),
  fixtures: () => req("/v1/fixtures"),
  prediction: (id: number) => req(`/v1/fixtures/${id}/prediction`),
  // Predicciones de TODOS los partidos por jugar en una sola petición (evita N+1).
  predictionsBatch: () => req("/v1/fixtures/predictions"),
  tournament: () => req("/v1/tournament/champion"),
  placeBet: (b: any) => req("/v1/bets", { method: "POST", body: JSON.stringify(b) }, true),
  myBets: () => req("/v1/bets", {}, true),
  performance: () => req("/v1/me/performance", {}, true),
  leaderboard: () => req("/v1/leaderboard"),
  // Admin: simula el cierre de partidos por jugar y liquida las apuestas pendientes.
  simulate: (body: { count?: number; stage?: string } = {}) =>
    req("/v1/admin/simulate", { method: "POST", body: JSON.stringify(body) }, true),
  // Admin: reinicia el torneo desde cero (todos apuestan desde el primer partido).
  resetTournament: () =>
    req("/v1/admin/reset-tournament", { method: "POST" }, true),
};
