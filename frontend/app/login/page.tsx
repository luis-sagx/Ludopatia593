"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

// Cuentas precargadas SOLO para la demo académica. Se muestran únicamente si
// NEXT_PUBLIC_DEMO_ACCOUNTS === "1" (se activa en local/compose). En un
// despliegue real la variable NO se define -> el bloque nunca se renderiza:
// seguro por defecto, sin exponer credenciales en producción.
const SHOW_DEMO_ACCOUNTS = process.env.NEXT_PUBLIC_DEMO_ACCOUNTS === "1";
const DEMO_ACCOUNTS = [
  {
    role: "Administrador",
    email: "admin@example.com",
    password: process.env.NEXT_PUBLIC_DEMO_ADMIN_PASSWORD || "admin-pass-123",
    hint: "Panel de simulación y liquidación",
  },
  {
    role: "Usuario normal",
    email: "lucia@demo.io",
    password: process.env.NEXT_PUBLIC_DEMO_USER_PASSWORD || "demo-pass-123",
    hint: "Apuesta con 1000 puntos virtuales",
  },
];

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [capsOn, setCapsOn] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const pwTooShort = mode === "register" && password.length > 0 && password.length < 10;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      if (mode === "register") await api.register(email, password);
      await api.login(email, password);
      window.dispatchEvent(new Event("balance:refresh"));
      router.push("/fixtures");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode(m: "login" | "register") {
    setMode(m); setErr(""); setShowPw(false);
  }

  async function useDemo(acc: (typeof DEMO_ACCOUNTS)[number]) {
    setErr(""); setBusy(true);
    setMode("login"); setEmail(acc.email); setPassword(acc.password);
    try {
      await api.login(acc.email, acc.password);
      window.dispatchEvent(new Event("balance:refresh"));
      router.push("/fixtures");
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="content-single auth-wrap">
      <div className="card auth-card">
        <div className="brand" style={{ justifyContent: "center", margin: "0 0 18px", fontSize: "1.2rem" }}>
          <span className="logo">⚽</span>
          <span>Predictor<span className="accent">26</span></span>
        </div>

        <div className="auth-tabs">
          <button type="button" className={`auth-tab ${mode === "login" ? "active" : ""}`}
            onClick={() => switchMode("login")}>Iniciar sesión</button>
          <button type="button" className={`auth-tab ${mode === "register" ? "active" : ""}`}
            onClick={() => switchMode("register")}>Crear cuenta</button>
        </div>

        <form onSubmit={submit}>
          <label>Correo electrónico</label>
          <input type="email" placeholder="tu@correo.com" value={email}
            onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />

          <label>Contraseña {mode === "register" && <span className="muted">· mín. 10 caracteres</span>}</label>
          <div className="pw-field">
            <input type={showPw ? "text" : "password"} placeholder="••••••••••" value={password}
              onChange={(e) => setPassword(e.target.value)} required
              onKeyUp={(e) => setCapsOn(e.getModifierState?.("CapsLock") ?? false)}
              onBlur={() => setCapsOn(false)}
              minLength={mode === "register" ? 10 : 1}
              autoComplete={mode === "register" ? "new-password" : "current-password"} />
            <button type="button" className="pw-toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? "Ocultar contraseña" : "Mostrar contraseña"} tabIndex={-1}>
              {showPw ? "🙈" : "👁"}
            </button>
          </div>
          {capsOn && <p className="hint warn">⇪ Bloq Mayús activado</p>}
          {pwTooShort && <p className="hint">Te faltan {10 - password.length} caracteres.</p>}

          {err && <p className="err" style={{ marginTop: 12 }}>⚠ {err}</p>}

          <button className="btn btn-primary btn-block" disabled={busy} type="submit" style={{ marginTop: 18 }}>
            {busy ? <span className="spinner" /> : mode === "login" ? "Entrar" : "Crear cuenta y jugar"}
          </button>
        </form>

        <div className="divider" />
        {SHOW_DEMO_ACCOUNTS && (
          <>
            <div className="demo-accounts">
              <p className="muted tiny" style={{ margin: "0 0 8px", textTransform: "uppercase", letterSpacing: ".06em" }}>
                Cuentas de demostración
              </p>
              {DEMO_ACCOUNTS.map((acc) => (
                <button key={acc.email} type="button" className="demo-acc" disabled={busy}
                  onClick={() => useDemo(acc)} title={`Entrar como ${acc.role}`}>
                  <span className="demo-acc-role">{acc.role}</span>
                  <span className="demo-acc-mail">{acc.email}</span>
                  <span className="demo-acc-hint muted tiny">{acc.hint}</span>
                  <span className="demo-acc-go">→</span>
                </button>
              ))}
            </div>
            <div className="divider" />
          </>
        )}
        <div className="auth-perk"><span className="i">◈</span> Recibes <b>&nbsp;1000 puntos&nbsp;</b> virtuales al registrarte.</div>
        <div className="auth-perk"><span className="i">🔒</span> Contraseñas con Argon2id · sesiones JWT rotatorias.</div>
        <div className="auth-perk"><span className="i">🎯</span> Cuotas justas sin margen de casa (modelo Dixon-Coles).</div>
      </div>
      <p className="muted tiny" style={{ textAlign: "center", marginTop: 14 }}>
        Puntos virtuales sin valor monetario · proyecto académico de software seguro.
      </p>
    </div>
  );
}
