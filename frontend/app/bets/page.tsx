"use client";
import { useEffect, useState } from "react";
import { api, getToken } from "@/lib/api";
import { useRouter } from "next/navigation";

export default function BetsPage() {
  const [bets, setBets] = useState<any[]>([]);
  const [perf, setPerf] = useState<any>(null);
  const [err, setErr] = useState("");
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) { router.push("/login"); return; }
    api.myBets().then(setBets).catch((e) => setErr(e.message));
    api.performance().then(setPerf).catch(() => {});
  }, []);

  const badge = (s: string) =>
    s === "won" ? "ev-pos" : s === "lost" ? "ev-neg" : "muted";

  return (
    <div>
      <h1>Mis predicciones</h1>
      {err && <p className="err">{err}</p>}
      {perf && (
        <div className="card grid" style={{ gridTemplateColumns: "repeat(4,1fr)" }}>
          <div className="pill"><span className="muted">Aciertos</span><b>{(perf.hit_rate * 100).toFixed(0)}%</b></div>
          <div className="pill"><span className="muted">ROI</span><b className={perf.roi >= 0 ? "ev-pos" : "ev-neg"}>{(perf.roi * 100).toFixed(1)}%</b></div>
          <div className="pill"><span className="muted">Predicciones</span><b>{perf.total_predictions}</b></div>
          <div className="pill"><span className="muted">Saldo</span><b>{perf.points_balance}</b></div>
        </div>
      )}
      <div className="card">
        <table>
          <thead><tr><th>#</th><th>Mercado</th><th>Selección</th><th>Stake</th><th>Cuota</th><th>Estado</th><th>Pago</th></tr></thead>
          <tbody>
            {bets.map((b) => (
              <tr key={b.id}>
                <td>{b.id}</td><td>{b.market}</td><td>{b.selection}</td>
                <td>{b.stake_points}</td><td>{b.odds_taken}</td>
                <td className={badge(b.status)}>{b.status}</td>
                <td>{b.payout_points ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
