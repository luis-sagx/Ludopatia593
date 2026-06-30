"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function LeaderboardPage() {
  const [rows, setRows] = useState<any[]>([]);
  const [err, setErr] = useState("");
  useEffect(() => { api.leaderboard().then(setRows).catch((e) => setErr(e.message)); }, []);

  return (
    <div>
      <h1>Ranking</h1>
      {err && <p className="err">{err}</p>}
      <div className="card">
        <table>
          <thead><tr><th>#</th><th>Usuario</th><th>Puntos</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.user_id}><td>{r.rank}</td><td>{r.email}</td><td><b>{r.points}</b></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
