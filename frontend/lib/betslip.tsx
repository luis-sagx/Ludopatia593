"use client";
import { createContext, useContext, useState, useCallback, useEffect, ReactNode } from "react";
import { api } from "./api";
import { useSession } from "./session";

/** UUID robusto: crypto.randomUUID no existe en contextos no seguros (HTTP en
 *  una IP/host distinto de localhost). Cae a getRandomValues y, en último caso,
 *  a Math.random para no romper la creación de la clave de idempotencia. */
function safeUuid(): string {
  try {
    const c = typeof crypto !== "undefined" ? crypto : undefined;
    if (c?.randomUUID) return c.randomUUID();
    if (c?.getRandomValues) {
      const b = c.getRandomValues(new Uint8Array(16));
      b[6] = (b[6] & 0x0f) | 0x40;
      b[8] = (b[8] & 0x3f) | 0x80;
      const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch { /* noop */ }
  return `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx`.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

export type SlipItem = {
  key: string;
  fixtureId: number;
  match: string;
  market: string;
  marketLabel: string;
  selection: string;
  selectionLabel: string;
  odds: number;
  stake: number;
  // Clave de idempotencia FIJA por selección: se genera una sola vez al añadir
  // el ítem, así un reintento (red lenta, doble click) NO crea apuestas duplicadas.
  idempotencyKey: string;
  status?: "placed" | "error";
  message?: string;
  betId?: number;
};

type Ctx = {
  items: SlipItem[];
  isSelected: (key: string) => boolean;
  toggle: (item: Omit<SlipItem, "stake" | "idempotencyKey">) => void;
  remove: (key: string) => void;
  clear: () => void;
  setStake: (key: string, stake: number) => void;
  setAllStakes: (stake: number) => void;
  maxStake: (key: string) => void;
  balance: number | null;
  place: () => Promise<void>;
  placing: boolean;
  needAuth: boolean;
  mobileOpen: boolean;
  setMobileOpen: (v: boolean) => void;
};

const BetSlipContext = createContext<Ctx | null>(null);
const DEFAULT_STAKE = 100;

export function BetSlipProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SlipItem[]>([]);
  const [placing, setPlacing] = useState(false);
  const [needAuth, setNeedAuth] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const { authed } = useSession();

  // Saldo disponible (para el botón "Máx"/all-in). Se refresca al iniciar sesión
  // y tras liquidar/apostar (evento balance:refresh).
  useEffect(() => {
    if (!authed) { setBalance(null); return; }
    const load = () => api.me().then((u: any) => setBalance(u.points_balance)).catch(() => {});
    load();
    const h = () => load();
    if (typeof window !== "undefined") window.addEventListener("balance:refresh", h);
    return () => { if (typeof window !== "undefined") window.removeEventListener("balance:refresh", h); };
  }, [authed]);

  const isSelected = useCallback((key: string) => items.some((i) => i.key === key), [items]);

  const toggle = useCallback((item: Omit<SlipItem, "stake" | "idempotencyKey">) => {
    setItems((prev) => {
      if (prev.some((i) => i.key === item.key)) return prev.filter((i) => i.key !== item.key);
      return [...prev, { ...item, stake: DEFAULT_STAKE, idempotencyKey: safeUuid() }];
    });
    setNeedAuth(false);
  }, []);

  const remove = useCallback((key: string) => setItems((p) => p.filter((i) => i.key !== key)), []);
  const clear = useCallback(() => { setItems([]); setNeedAuth(false); }, []);
  const setStake = useCallback((key: string, stake: number) => {
    setItems((p) => p.map((i) => (i.key === key ? { ...i, stake } : i)));
  }, []);
  const setAllStakes = useCallback((stake: number) => {
    setItems((p) => p.map((i) => ({ ...i, stake })));
  }, []);
  // Apuesta "todo": pone en esta selección el saldo disponible restante (saldo
  // menos lo ya comprometido en las otras selecciones aún no colocadas). Regla
  // real de casa de apuestas: el máximo de una apuesta es tu saldo disponible.
  const maxStake = useCallback((key: string) => {
    setItems((prev) => {
      if (balance == null) return prev;
      const others = prev
        .filter((i) => i.key !== key && i.status !== "placed")
        .reduce((s, i) => s + (i.stake || 0), 0);
      const avail = Math.max(1, balance - others);
      return prev.map((i) => (i.key === key ? { ...i, stake: avail } : i));
    });
  }, [balance]);

  const place = useCallback(async () => {
    if (!authed) { setNeedAuth(true); return; }
    setPlacing(true);
    const pending = items.filter((i) => i.status !== "placed");
    const results = await Promise.all(
      pending.map(async (i) => {
        try {
          const r = await api.placeBet({
            fixture_id: i.fixtureId, market: i.market, selection: i.selection,
            stake_points: i.stake, idempotency_key: i.idempotencyKey,
          });
          // Reconcilia con la fuente de verdad del servidor: la cuota y el stake
          // efectivamente registrados (el backend re-deriva la cuota del modelo).
          return {
            key: i.key, ok: true as const, betId: r.id,
            odds: typeof r.odds_taken === "number" ? r.odds_taken : i.odds,
            stake: typeof r.stake_points === "number" ? r.stake_points : i.stake,
          };
        } catch (e: any) {
          return { key: i.key, ok: false as const, message: e.message as string };
        }
      })
    );
    setItems((prev) =>
      prev.map((i) => {
        const r = results.find((x) => x.key === i.key);
        if (!r) return i;
        return r.ok
          ? { ...i, odds: r.odds, stake: r.stake, status: "placed", message: `Apuesta #${r.betId}`, betId: r.betId }
          : { ...i, status: "error", message: r.message };
      })
    );
    setPlacing(false);
    // avisa a la barra superior para refrescar el saldo
    if (typeof window !== "undefined") window.dispatchEvent(new Event("balance:refresh"));
    // Auto-limpia el boleto: tras mostrar la confirmación, quita las apuestas ya
    // colocadas para que no queden selecciones antiguas reutilizables. Las que
    // fallaron se conservan para que el usuario pueda reintentarlas.
    setTimeout(() => {
      setItems((prev) => prev.filter((i) => i.status !== "placed"));
    }, 2500);
  }, [items, authed]);

  return (
    <BetSlipContext.Provider
      value={{ items, isSelected, toggle, remove, clear, setStake, setAllStakes, maxStake, balance, place, placing, needAuth, mobileOpen, setMobileOpen }}
    >
      {children}
    </BetSlipContext.Provider>
  );
}

export function useBetSlip() {
  const ctx = useContext(BetSlipContext);
  if (!ctx) throw new Error("useBetSlip fuera de BetSlipProvider");
  return ctx;
}
