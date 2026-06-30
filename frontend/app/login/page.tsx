"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      if (mode === "register") {
        await api.register(email, password);
      }
      await api.login(email, password);
      router.push("/fixtures");
      location.reload();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 420, margin: "40px auto" }}>
      <h1>{mode === "login" ? "Entrar" : "Crear cuenta"}</h1>
      <form onSubmit={submit}>
        <label>Email</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label>Contraseña {mode === "register" && <span className="muted">(mín. 10 caracteres)</span>}</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === "register" ? 10 : 1} />
        {err && <p className="err">{err}</p>}
        <div style={{ marginTop: 14, display: "flex", gap: 10 }}>
          <button disabled={busy} type="submit">{busy ? "…" : mode === "login" ? "Entrar" : "Registrar"}</button>
          <button type="button" className="secondary" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(""); }}>
            {mode === "login" ? "Crear cuenta" : "Ya tengo cuenta"}
          </button>
        </div>
      </form>
    </div>
  );
}
