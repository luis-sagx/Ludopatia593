"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { flag, stageLabel } from "@/lib/flags";
import { useBetSlip } from "@/lib/betslip";
import BetSlip from "@/components/BetSlip";

type Fixture = {
  id: number; stage: string; home_team: string; away_team: string;
  kickoff_utc: string; status: string; home_score: number | null; away_score: number | null;
};
type Odds = { prob: number; fair_odds: number | null };

function timeLabel(iso: string) {
  const d = new Date(iso);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const t = d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? `Hoy ${t}` : d.toLocaleDateString("es", { day: "2-digit", month: "short" }) + ` · ${t}`;
}

function OddsBtn(props: {
  fixtureId: number; match: string; marketKey: string; marketLabel: string;
  sel: string; label: string; selectionLabel: string; odds: number | null;
}) {
  const { toggle, isSelected } = useBetSlip();
  const key = `${props.fixtureId}:${props.marketKey}:${props.sel}`;
  if (props.odds == null) return (
    <div className="odds disabled"><span className="lbl">{props.label}</span><span className="val">—</span></div>
  );
  return (
    <button
      className={`odds ${isSelected(key) ? "selected" : ""}`}
      onClick={() => toggle({
        key, fixtureId: props.fixtureId, match: props.match,
        market: props.marketKey, marketLabel: props.marketLabel,
        selection: props.sel, selectionLabel: props.selectionLabel, odds: props.odds!,
      })}
    >
      <span className="lbl">{props.label}</span>
      <span className="val">{props.odds!.toFixed(2)}</span>
    </button>
  );
}

function MatchCard({ fx, pred }: { fx: Fixture; pred: any }) {
  const [more, setMore] = useState(false);
  const finished = fx.status === "finished";
  const live = fx.status === "live";
  const match = `${fx.home_team} vs ${fx.away_team}`;
  const x = pred?.markets?.["1x2"];
  const ou25 = pred?.markets?.over_under?.["ou_2.5"];
  const btts = pred?.markets?.btts;

  const hs = fx.home_score, as = fx.away_score;
  const homeWon = finished && hs != null && as != null && hs > as;
  const awayWon = finished && hs != null && as != null && as > hs;

  return (
    <div className="match">
      <div className="match-top">
        <span className="league">🏆 {stageLabel(fx.stage)}</span>
        <span className="dot">•</span>
        <span>{timeLabel(fx.kickoff_utc)}</span>
        <span style={{ marginLeft: "auto" }}>
          {live && <span className="badge-live"><span className="pulse" />En vivo</span>}
          {finished && <span className="badge-final">Final</span>}
        </span>
      </div>

      <div className="match-body">
        <div className="teams">
          <div className={`team ${homeWon ? "winner" : ""}`}>
            <span className="flag">{flag(fx.home_team)}</span>
            <span className="name">{fx.home_team}</span>
            {finished && <span className="score">{hs}</span>}
          </div>
          <div className={`team ${awayWon ? "winner" : ""}`}>
            <span className="flag">{flag(fx.away_team)}</span>
            <span className="name">{fx.away_team}</span>
            {finished && <span className="score">{as}</span>}
          </div>
        </div>

        {!finished && (
          <div className="odds-row">
            <OddsBtn fixtureId={fx.id} match={match} marketKey="1x2" marketLabel="Ganador del partido (1X2)"
              sel="home" label="1" selectionLabel={fx.home_team} odds={x?.home?.fair_odds ?? null} />
            <OddsBtn fixtureId={fx.id} match={match} marketKey="1x2" marketLabel="Ganador del partido (1X2)"
              sel="draw" label="X" selectionLabel="Empate" odds={x?.draw?.fair_odds ?? null} />
            <OddsBtn fixtureId={fx.id} match={match} marketKey="1x2" marketLabel="Ganador del partido (1X2)"
              sel="away" label="2" selectionLabel={fx.away_team} odds={x?.away?.fair_odds ?? null} />
          </div>
        )}
        {finished && <div className="small muted" style={{ textAlign: "right" }}>Partido finalizado</div>}
      </div>

      {!finished && (ou25 || btts) && (
        <>
          {more && (
            <div className="markets-more">
              {ou25 && (
                <div className="market-group">
                  <div className="mg-title">Total de goles · línea 2.5</div>
                  <div className="market-line">
                    <OddsBtn fixtureId={fx.id} match={match} marketKey="ou_2.5" marketLabel="Más/Menos 2.5 goles"
                      sel="over" label="Más 2.5" selectionLabel="Más de 2.5 goles" odds={ou25.over?.fair_odds ?? null} />
                    <OddsBtn fixtureId={fx.id} match={match} marketKey="ou_2.5" marketLabel="Más/Menos 2.5 goles"
                      sel="under" label="Menos 2.5" selectionLabel="Menos de 2.5 goles" odds={ou25.under?.fair_odds ?? null} />
                  </div>
                </div>
              )}
              {btts && (
                <div className="market-group">
                  <div className="mg-title">Ambos equipos marcan</div>
                  <div className="market-line">
                    <OddsBtn fixtureId={fx.id} match={match} marketKey="btts" marketLabel="Ambos marcan"
                      sel="yes" label="Sí" selectionLabel="Ambos marcan: Sí" odds={btts.yes?.fair_odds ?? null} />
                    <OddsBtn fixtureId={fx.id} match={match} marketKey="btts" marketLabel="Ambos marcan"
                      sel="no" label="No" selectionLabel="Ambos marcan: No" odds={btts.no?.fair_odds ?? null} />
                  </div>
                </div>
              )}
            </div>
          )}
          <button className="expander-toggle" onClick={() => setMore(!more)}>
            {more ? "Menos mercados ▲" : "+ Más mercados (goles, ambos marcan) ▼"}
          </button>
        </>
      )}
    </div>
  );
}

function MatchSkeleton() {
  return (
    <div className="match">
      <div className="match-top"><span className="skeleton" style={{ width: 160, height: 12 }} /></div>
      <div className="match-body">
        <div className="teams" style={{ gap: 14 }}>
          <span className="skeleton" style={{ width: 180, height: 20 }} />
          <span className="skeleton" style={{ width: 150, height: 20 }} />
        </div>
        <div className="odds-row">
          {[0, 1, 2].map((i) => <span key={i} className="skeleton" style={{ height: 46 }} />)}
        </div>
      </div>
    </div>
  );
}

export default function FixturesPage() {
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [preds, setPreds] = useState<Record<number, any>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"upcoming" | "results" | "all">("upcoming");

  useEffect(() => {
    let alive = true;
    // Una sola petición para las cuotas de todos los partidos (endpoint batch)
    // en vez de una por fixture: evita saturar el rate limit al navegar.
    Promise.all([
      api.fixtures(),
      api.predictionsBatch().catch(() => ({} as Record<string, any>)),
    ])
      .then(([fx, batch]: [Fixture[], Record<string, any>]) => {
        if (!alive) return;
        setFixtures(fx);
        setPreds(batch || {});
        setLoading(false);
      })
      .catch((e) => { if (alive) { setErr(e.message); setLoading(false); } });
    return () => { alive = false; };
  }, []);

  const shown = useMemo(() => {
    if (tab === "upcoming") return fixtures.filter((f) => f.status !== "finished");
    if (tab === "results") return fixtures.filter((f) => f.status === "finished");
    return fixtures;
  }, [fixtures, tab]);

  const upcomingCount = fixtures.filter((f) => f.status !== "finished").length;
  const resultsCount = fixtures.filter((f) => f.status === "finished").length;

  return (
    <div className="content-wrap">
      <div className="content-main">
        <div className="section-head">
          <h1 style={{ margin: 0 }}>Mundial 2026</h1>
          <span className="chip">Cuotas justas del modelo</span>
        </div>
        <p className="muted small" style={{ margin: "-8px 2px 16px" }}>
          Cuotas <b>sin margen de casa</b> derivadas de un modelo Dixon-Coles calibrado.
          Toca una cuota para armar tu boleto. Las apuestas <b>se cierran al iniciar el
          partido</b> (kickoff) y se liquidan automáticamente al conocerse el resultado.
        </p>

        <div className="auth-tabs" style={{ maxWidth: 380 }}>
          <button className={`auth-tab ${tab === "upcoming" ? "active" : ""}`} onClick={() => setTab("upcoming")}>
            Próximos {upcomingCount ? `(${upcomingCount})` : ""}
          </button>
          <button className={`auth-tab ${tab === "results" ? "active" : ""}`} onClick={() => setTab("results")}>
            Resultados {resultsCount ? `(${resultsCount})` : ""}
          </button>
          <button className={`auth-tab ${tab === "all" ? "active" : ""}`} onClick={() => setTab("all")}>Todos</button>
        </div>

        {err && <div className="card"><p className="err">⚠ {err}</p></div>}
        {loading && <>{[0, 1, 2].map((i) => <MatchSkeleton key={i} />)}</>}
        {!loading && !err && shown.length === 0 && (
          <div className="card"><p className="muted">No hay partidos en esta vista todavía.</p></div>
        )}
        {shown.map((fx) => <MatchCard key={fx.id} fx={fx} pred={preds[fx.id]} />)}
      </div>

      <BetSlip />
    </div>
  );
}
