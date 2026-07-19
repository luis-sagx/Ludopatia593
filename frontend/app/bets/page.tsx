"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";
import { useRouter } from "next/navigation";

const MARKET_LABEL: Record<string, string> = {
  "1x2": "Ganador (1X2)", btts: "Ambos marcan",
};
const SEL_LABEL: Record<string, string> = {
  home: "Local", draw: "Empate", away: "Visita", over: "Más goles", under: "Menos goles",
  yes: "Sí", no: "No",
};
function marketName(m: string) {
  if (m?.startsWith("ou_")) return `Goles ${m.split("_")[1]}`;
  return MARKET_LABEL[m] ?? m;
}
function statusText(s: string) {
  return s === "won" ? "Ganada" : s === "lost" ? "Perdida" : s === "void" ? "Anulada" : "Pendiente";
}

export default function BetsPage() {
  const [bets, setBets] = useState<any[]>([]);
  const [perf, setPerf] = useState<any>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [isAdmin, setIsAdmin] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [simMsg, setSimMsg] = useState("");
  const [resetting, setResetting] = useState(false);
  const router = useRouter();
  const { authed, initializing } = useSession();

  function refresh() {
    return Promise.all([
      api.myBets().then(setBets).catch((e) => setErr(e.message)),
      api.performance().then(setPerf).catch(() => {}),
    ]);
  }

  useEffect(() => {
    if (initializing) return;
    if (!authed) { router.push("/login"); return; }
    api.me().then((m: any) => setIsAdmin(m?.role === "admin")).catch(() => {});
    refresh().finally(() => setLoading(false));
  }, [initializing, authed]);

  async function runSimulate() {
    setSimulating(true);
    setSimMsg("");
    try {
      // Sin parámetros: el backend juega la SIGUIENTE jornada/ronda completa y
      // desbloquea la siguiente (desbloqueo progresivo, como un mundial real).
      const r = await api.simulate({});
      if (r.tournament_over && r.simulated === 0) {
        setSimMsg("El torneo ha terminado: no quedan partidos por jugar.");
      } else {
        const next = r.tournament_over ? " Fue la última ronda del torneo." : " Se desbloqueó la siguiente ronda.";
        setSimMsg(`Se jugó ${r.round_label}: ${r.simulated} partidos cerrados y ${r.settled} apuestas liquidadas.${next}`);
      }
      await refresh();
      window.dispatchEvent(new Event("balance:refresh"));
    } catch (e: any) {
      setSimMsg(`Error: ${e.message}`);
    } finally {
      setSimulating(false);
    }
  }

  async function runReset() {
    // Acción destructiva: borra apuestas y reinicia saldos. Confirmar antes.
    if (!window.confirm(
      "¿Reiniciar el torneo desde cero? Se borran TODAS las apuestas, se " +
      "restablece el saldo de todos los usuarios y el torneo vuelve al primer " +
      "partido. Esta acción no se puede deshacer."
    )) return;
    setResetting(true);
    setSimMsg("");
    try {
      const r = await api.resetTournament();
      setSimMsg(
        `Torneo reiniciado: ${r.fixtures_reset} partidos reabiertos, ` +
        `${r.predictions_deleted} apuestas borradas, ${r.users_reset} usuarios con saldo restablecido.`
      );
      await refresh();
      window.dispatchEvent(new Event("balance:refresh"));
    } catch (e: any) {
      setSimMsg(`Error: ${e.message}`);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="content-single">
      <div className="section-head">
        <h1 style={{ margin: 0 }}>Mis apuestas</h1>
        <span className="chip">Historial y rendimiento</span>
      </div>

      {isAdmin && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--gold)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontWeight: 700 }}>Panel admin · Control del torneo</div>
              <div className="muted small">
                <b>Jugar siguiente jornada</b>: juega la próxima ronda (grupos → eliminatorias)
                con los resultados reales, liquida las apuestas pendientes y desbloquea la
                siguiente ronda. <b>Reiniciar torneo</b>: vuelve todo al primer partido, borra
                las apuestas y restablece el saldo de todos para empezar de nuevo.
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="btn" onClick={runSimulate} disabled={simulating || resetting}>
                {simulating ? <><span className="spinner" /> Jugando…</> : "Jugar siguiente jornada"}
              </button>
              <button className="btn" onClick={runReset} disabled={simulating || resetting}
                style={{ background: "transparent", borderColor: "var(--gold)" }}>
                {resetting ? <><span className="spinner" /> Reiniciando…</> : "Reiniciar torneo"}
              </button>
            </div>
          </div>
          {simMsg && <p className="small" style={{ marginBottom: 0, marginTop: 10 }}>{simMsg}</p>}
        </div>
      )}

      {perf && (
        <div className="stat-grid" style={{ marginBottom: 16 }}>
          <div className="stat">
            <span className="k">Saldo</span>
            <span className="v" style={{ color: "var(--gold)" }}>{perf.points_balance}</span>
          </div>
          <div className="stat">
            <span className="k">Aciertos</span>
            <span className="v">{(perf.hit_rate * 100).toFixed(0)}%</span>
          </div>
          <div className="stat">
            <span className="k">ROI</span>
            <span className={`v ${perf.roi >= 0 ? "pos" : "neg"}`}>{(perf.roi * 100).toFixed(1)}%</span>
          </div>
          <div className="stat">
            <span className="k">Apuestas</span>
            <span className="v">{perf.total_predictions}</span>
          </div>
        </div>
      )}

      {err && <div className="card"><p className="err">⚠ {err}</p></div>}

      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        {loading ? (
          <div style={{ padding: 20 }}><span className="skeleton" style={{ display: "block", height: 120 }} /></div>
        ) : bets.length === 0 ? (
          <div className="betslip-empty">
            <div className="big">🎫</div>
            <div style={{ fontWeight: 700, color: "var(--text)" }}>Aún no tienes apuestas</div>
            <div className="small" style={{ marginTop: 4 }}>Ve a <a href="/fixtures">Partidos</a> y arma tu primer boleto.</div>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th><th>Mercado</th><th>Selección</th><th style={{ textAlign: "right" }}>Stake</th>
                <th style={{ textAlign: "right" }}>Cuota</th><th>Estado</th><th style={{ textAlign: "right" }}>Pago</th>
              </tr>
            </thead>
            <tbody>
              {bets.map((b) => (
                <tr key={b.id}>
                  <td className="muted">{b.id}</td>
                  <td>{marketName(b.market)}</td>
                  <td>{SEL_LABEL[b.selection] ?? b.selection}</td>
                  <td style={{ textAlign: "right" }}>{b.stake_points}</td>
                  <td style={{ textAlign: "right" }}>{b.odds_taken.toFixed(2)}</td>
                  <td><span className={`status ${b.status}`}>{statusText(b.status)}</span></td>
                  <td style={{ textAlign: "right", fontWeight: 700, color: b.status === "won" ? "var(--win)" : "inherit" }}>
                    {b.status === "won" ? `+${b.payout_points}` : b.payout_points === 0 && b.status === "lost" ? `−${b.stake_points}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
