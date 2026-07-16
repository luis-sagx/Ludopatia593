"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { useSession } from "@/lib/session";

const LINKS = [
  { href: "/fixtures", label: "Partidos" },
  { href: "/tournament", label: "Campeón" },
  { href: "/leaderboard", label: "Ranking" },
];

export default function Nav() {
  const [points, setPoints] = useState<number | null>(null);
  const [authed, setAuthed] = useState(false);
  const { authed: hasToken, initializing } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  const refresh = useCallback(() => {
    if (initializing) return;
    if (!hasToken) { setAuthed(false); setPoints(null); return; }
    api.me().then((u) => { setPoints(u.points_balance); setAuthed(true); }).catch(() => {
      setAuthed(false); setPoints(null);
    });
  }, [hasToken, initializing]);

  useEffect(() => {
    refresh();
    const h = () => refresh();
    window.addEventListener("balance:refresh", h);
    return () => window.removeEventListener("balance:refresh", h);
  }, [refresh]);

  const isActive = (href: string) => pathname === href || (href !== "/" && pathname?.startsWith(href));

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link href="/" className="brand">
          <span className="logo">⚽</span>
          <span>Predictor<span className="accent">26</span></span>
        </Link>

        <nav className="navlinks">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className={`navlink ${isActive(l.href) ? "active" : ""}`}>
              {l.label}
            </Link>
          ))}
          {authed && (
            <Link href="/bets" className={`navlink ${isActive("/bets") ? "active" : ""}`}>
              Mis apuestas
            </Link>
          )}
        </nav>

        <div className="topbar-right">
          {authed ? (
            <>
              <span className="balance-chip">
                <span className="coin">◈</span>
                {points ?? "…"}<small>pts</small>
              </span>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => { api.logout().finally(() => { setAuthed(false); router.push("/login"); }); }}
              >
                Salir
              </button>
            </>
          ) : (
            <Link href="/login" className="btn btn-primary btn-sm">Entrar</Link>
          )}
        </div>
      </div>
    </header>
  );
}
