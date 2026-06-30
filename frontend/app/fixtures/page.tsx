"use client";
import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";

type Fixture = {
  id: number; stage: string; home_team: string; away_team: string;
  kickoff_utc: string; status: string;
};

function Prediction({ fx }: { fx: Fixture }) {
  const [pred, setPred] = useState<any>(null);
  const [err, setErr] = useState("");
  const [stake, setStake] = useState(100);
  const [sel, setSel] = useState("home");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.prediction(fx.id).then(setPred).catch((e) => setErr(e.message));
  }, [fx.id]);

  async function bet() {
    setMsg("");
    if (!getToken()) { setMsg("Inicia sesión para predecir."); return; }
    try {
      const r = await api.placeBet({
        fixture_id: fx.id, market: "1x2", selection: sel,
        stake_points: stake, idempotency_key: crypto.randomUUID(),
      });
      setMsg(`✅ Predicción #${r.id} — cuota ${r.odds_taken}, posible retorno ${Math.round(r.stake_points * r.odds_taken)} pts`);
    } catch (e: any) { setMsg("⚠️ " + e.message); }
  }

  if (err) return <p className="err">{err}</p>;
  if (!pred) return <p className="muted">Calculando probabilidades…</p>;

  const x = pred.markets["1x2"];
  const outcomes: [string, string][] = [["home", fx.home_team], ["draw", "Empate"], ["away", fx.away_team]];

  return (
    <div style={{ marginTop: 12 }}>
      <div className="grid">
        {outcomes.map(([k, label]) => (
          <div className="pill" key={k}>
            <span className="muted">{label}</span>
            <b>{(x[k].prob * 100).toFixed(1)}%</b>
            <span className="muted">cuota {x[k].fair_odds}</span>
          </div>
        ))}
      </div>
      {fx.status === "scheduled" && (
        <div className="row" style={{ marginTop: 12 }}>
          <select value={sel} onChange={(e) => setSel(e.target.value)} style={{ maxWidth: 180 }}>
            {outcomes.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <input type="number" min={1} value={stake} onChange={(e) => setStake(+e.target.value)} style={{ maxWidth: 120 }} />
          <button onClick={bet}>Predecir (pts)</button>
        </div>
      )}
      {msg && <p className="muted" style={{ marginTop: 8 }}>{msg}</p>}
      <p className="muted" style={{ marginTop: 6 }}>modelo {pred.model_version} · Dixon-Coles</p>
    </div>
  );
}

export default function FixturesPage() {
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.fixtures().then(setFixtures).catch((e) => setErr(e.message));
  }, []);

  return (
    <div>
      <h1>Partidos — Mundial 2026</h1>
      {err && <p className="err">{err}</p>}
      {fixtures.map((fx) => (
        <div className="card" key={fx.id}>
          <div className="row" onClick={() => setOpen(open === fx.id ? null : fx.id)} style={{ cursor: "pointer" }}>
            <div>
              <b>{fx.home_team}</b> vs <b>{fx.away_team}</b>
              <div className="muted">{fx.stage} · {new Date(fx.kickoff_utc).toLocaleString("es")}</div>
            </div>
            <span className="muted">{open === fx.id ? "▲" : "▼"}</span>
          </div>
          {open === fx.id && <Prediction fx={fx} />}
        </div>
      ))}
    </div>
  );
}
