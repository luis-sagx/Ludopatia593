"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function TournamentPage() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.tournament().then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <p className="err">{err}</p>;
  if (!data) return <p className="muted">Simulando torneo (Monte Carlo)…</p>;

  const champ = Object.entries(data.champion) as [string, number][];

  return (
    <div>
      <h1>Probabilidad de campeón</h1>
      <p className="muted">Monte Carlo · {data.n_sims.toLocaleString()} simulaciones · estructura de grupos estimada</p>
      <div className="card">
        <table>
          <thead><tr><th>#</th><th>Selección</th><th>Campeón</th><th>Finalista</th><th>Avanza grupo</th></tr></thead>
          <tbody>
            {champ.slice(0, 16).map(([team, p], i) => (
              <tr key={team}>
                <td>{i + 1}</td>
                <td><b>{team}</b></td>
                <td>{(p * 100).toFixed(1)}%</td>
                <td>{(((data.finalist[team] ?? 0) as number) * 100).toFixed(1)}%</td>
                <td>{(((data.advance_group[team] ?? 0) as number) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
