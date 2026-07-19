"use client";
import { useBetSlip } from "@/lib/betslip";
import { useSession } from "@/lib/session";
import Link from "next/link";

const QUICK = [50, 100, 250, 500];

function SlipInner() {
  const { items, remove, clear, setStake, setAllStakes, maxStake, balance, place, placing, needAuth } = useBetSlip();
  const totalStake = items.reduce((s, i) => s + (i.stake || 0), 0);
  const totalReturn = items.reduce((s, i) => s + Math.round((i.stake || 0) * i.odds), 0);
  const allPlaced = items.length > 0 && items.every((i) => i.status === "placed");
  const pendingStake = items.filter((i) => i.status !== "placed").reduce((s, i) => s + (i.stake || 0), 0);
  const overBalance = balance != null && pendingStake > balance;
  const { authed } = useSession();

  return (
    <>
      <div className="betslip-head">
        <span>Boleto</span>
        <span className="count">{items.length}</span>
        {items.length > 0 && <button className="clear" onClick={clear}>Limpiar</button>}
      </div>

      {items.length === 0 ? (
        <div className="betslip-empty">
          <div className="big">🎫</div>
          <div style={{ fontWeight: 700, color: "var(--text)" }}>Tu boleto está vacío</div>
          <div className="small" style={{ marginTop: 4 }}>Toca una cuota para añadir una selección.</div>
        </div>
      ) : (
        <>
          <div className="betslip-body">
            {items.map((i) => (
              <div key={i.key} className={`slip-item ${i.status ?? ""}`}>
                <div className="si-top">
                  <div style={{ minWidth: 0 }}>
                    <div className="si-sel">{i.selectionLabel}</div>
                    <div className="si-mkt">{i.marketLabel}</div>
                    <div className="si-match">{i.match}</div>
                  </div>
                  <div className="si-odds">{i.odds.toFixed(2)}</div>
                  {i.status !== "placed" && (
                    <button className="si-x" title="Quitar" onClick={() => remove(i.key)}>✕</button>
                  )}
                </div>

                {i.status === "placed" ? (
                  <div className="si-return" style={{ color: "var(--win)" }}>
                    ✓ {i.message} · retorno posible <b>{Math.round(i.stake * i.odds)}</b> pts
                  </div>
                ) : i.status === "error" ? (
                  <div className="si-return" style={{ color: "var(--lose)" }}>⚠ {i.message}</div>
                ) : (
                  <>
                    <div className="si-stake">
                      <input
                        className="stake-input" type="number" min={1} value={i.stake}
                        onChange={(e) => setStake(i.key, Math.max(1, Math.floor(+e.target.value) || 1))}
                      />
                      <span className="small muted">pts</span>
                      {authed && balance != null && (
                        <button className="si-max" title="Apostar todo el saldo disponible"
                          onClick={() => maxStake(i.key)}>Máx</button>
                      )}
                    </div>
                    <div className="si-return">
                      Retorno posible <b>{Math.round((i.stake || 0) * i.odds)}</b> pts
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          <div className="betslip-foot">
            {!allPlaced && (
              <div className="chips">
                {QUICK.map((q) => (
                  <button key={q} className="chip-stake" onClick={() => setAllStakes(q)}>{q}</button>
                ))}
              </div>
            )}
            <div className="slip-summary"><span className="muted">Selecciones</span><span>{items.length}</span></div>
            <div className="slip-summary"><span className="muted">Total apostado</span><span>{totalStake} pts</span></div>
            {authed && balance != null && (
              <div className="slip-summary"><span className="muted">Saldo disponible</span><span>{balance} pts</span></div>
            )}
            <div className="slip-summary total"><span>Retorno posible</span><span className="ret">{totalReturn} pts</span></div>

            {overBalance && (
              <p className="err" style={{ marginTop: 8 }}>
                El total ({pendingStake} pts) supera tu saldo ({balance} pts).
              </p>
            )}

            {needAuth && !authed && (
              <p className="err" style={{ marginTop: 8 }}>
                Inicia sesión para apostar. <Link href="/login">Entrar →</Link>
              </p>
            )}

            {allPlaced ? (
              <button className="btn btn-ghost btn-block" style={{ marginTop: 10 }} onClick={clear}>
                Nueva apuesta
              </button>
            ) : (
              <button
                className="btn btn-primary btn-block" style={{ marginTop: 10 }}
                disabled={placing || totalStake <= 0 || overBalance}
                onClick={place}
              >
                {placing ? <span className="spinner" /> : `Apostar ${totalStake} pts`}
              </button>
            )}
          </div>
        </>
      )}
    </>
  );
}

export default function BetSlip() {
  const { items, mobileOpen, setMobileOpen } = useBetSlip();

  return (
    <>
      {/* desktop */}
      <aside className="betslip desktop">
        <SlipInner />
      </aside>

      {/* mobile FAB + sheet */}
      <button className="slip-fab" onClick={() => setMobileOpen(true)}>
        <span>🎫 Boleto</span>
        <span className="count" style={{ background: "rgba(0,0,0,0.2)", color: "inherit" }}>{items.length}</span>
      </button>
      {mobileOpen && (
        <>
          <div className="slip-backdrop" onClick={() => setMobileOpen(false)} />
          <aside className="betslip mobile-open">
            <SlipInner />
          </aside>
        </>
      )}
    </>
  );
}
