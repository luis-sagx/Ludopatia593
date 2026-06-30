"use client";
// Cliente API. Llama al backend vía el proxy /api (rewrite en next.config.js).
// Token en localStorage para demo. NOTA seguridad: en producción, refresh token
// debería ir en cookie HttpOnly; aquí se simplifica por ser proyecto académico.

const TOKEN_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}
export function setTokens(access: string, refresh: string) {
  localStorage.setItem(TOKEN_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}
export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

async function req(path: string, opts: RequestInit = {}, auth = false) {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(opts.headers as any) };
  if (auth) {
    const t = getToken();
    if (t) headers["Authorization"] = `Bearer ${t}`;
  }
  const res = await fetch(`/api${path}`, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail; } catch {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  register: (email: string, password: string) =>
    req("/v1/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: async (email: string, password: string) => {
    const t = await req("/v1/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    setTokens(t.access_token, t.refresh_token);
    return t;
  },
  me: () => req("/v1/auth/me", {}, true),
  fixtures: () => req("/v1/fixtures"),
  prediction: (id: number) => req(`/v1/fixtures/${id}/prediction`),
  tournament: () => req("/v1/tournament/champion"),
  placeBet: (b: any) => req("/v1/bets", { method: "POST", body: JSON.stringify(b) }, true),
  myBets: () => req("/v1/bets", {}, true),
  performance: () => req("/v1/me/performance", {}, true),
  leaderboard: () => req("/v1/leaderboard"),
};
