"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, clearTokens, getToken } from "@/lib/api";
import { useRouter } from "next/navigation";

export default function Nav() {
  const [points, setPoints] = useState<number | null>(null);
  const [authed, setAuthed] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) return;
    api.me().then((u) => { setPoints(u.points_balance); setAuthed(true); }).catch(() => {});
  }, []);

  return (
    <nav>
      <span className="brand">⚽ Predictor 2026</span>
      <Link href="/fixtures">Partidos</Link>
      <Link href="/tournament">Torneo</Link>
      <Link href="/leaderboard">Ranking</Link>
      {authed && <Link href="/bets">Mis predicciones</Link>}
      {authed ? (
        <>
          <span className="muted">{points ?? "…"} pts</span>
          <button className="secondary" onClick={() => { clearTokens(); router.push("/login"); location.reload(); }}>Salir</button>
        </>
      ) : (
        <Link href="/login">Entrar</Link>
      )}
    </nav>
  );
}
