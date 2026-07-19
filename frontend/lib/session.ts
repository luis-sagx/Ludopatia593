"use client";
// Access token SOLO en memoria (nunca localStorage/sessionStorage) -- una
// recarga de página lo pierde a propósito; se recupera con refreshSession()
// usando la cookie HttpOnly de refresh, que el navegador maneja solo.
import { useEffect, useSyncExternalStore } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

let accessToken: string | null = null;
let initializing = true;
const listeners = new Set<() => void>();
function emit() {
  listeners.forEach((l) => l());
}
function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken() {
  return accessToken;
}
export function setAccessToken(token: string | null) {
  accessToken = token;
  emit();
}

/** Hook reactivo: refleja si hay sesión y si todavía se está resolviendo al cargar. */
export function useSession() {
  const authed = useSyncExternalStore(subscribe, () => accessToken !== null, () => false);
  const isInitializing = useSyncExternalStore(subscribe, () => initializing, () => true);
  return { authed, initializing: isInitializing };
}

export function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Renueva el access token usando la cookie HttpOnly de refresh (doble-envío CSRF). */
export async function refreshSession(): Promise<boolean> {
  // Token al inicio de la llamada: si durante el refresh (asíncrono) el usuario
  // inicia sesión y setea un token nuevo, NO debemos pisarlo al fallar el
  // refresh. Esto evita la race del bootstrap que dejaba deslogueado tras login.
  const tokenAtStart = accessToken;
  const clearIfUnchanged = () => {
    if (accessToken === tokenAtStart) setAccessToken(null);
  };
  try {
    const csrf = getCsrfToken();
    const res = await fetch(`${BASE}/v1/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: csrf ? { "X-CSRF-Token": csrf } : {},
    });
    if (!res.ok) {
      clearIfUnchanged();
      return false;
    }
    const data = await res.json();
    setAccessToken(data.access_token);
    return true;
  } catch {
    clearIfUnchanged();
    return false;
  }
}

/** Se monta una vez en el layout raíz: intenta recuperar sesión al cargar la app. */
export function SessionBootstrap() {
  useEffect(() => {
    refreshSession().finally(() => {
      initializing = false;
      emit();
    });
  }, []);
  return null;
}
