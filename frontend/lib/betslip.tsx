"use client";
import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { api } from "./api";
import { useSession } from "./session";

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
  status?: "placed" | "error";
  message?: string;
  betId?: number;
};

type Ctx = {
  items: SlipItem[];
  isSelected: (key: string) => boolean;
  toggle: (item: Omit<SlipItem, "stake">) => void;
  remove: (key: string) => void;
  clear: () => void;
  setStake: (key: string, stake: number) => void;
  setAllStakes: (stake: number) => void;
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
  const { authed } = useSession();

  const isSelected = useCallback((key: string) => items.some((i) => i.key === key), [items]);

  const toggle = useCallback((item: Omit<SlipItem, "stake">) => {
    setItems((prev) => {
      if (prev.some((i) => i.key === item.key)) return prev.filter((i) => i.key !== item.key);
      return [...prev, { ...item, stake: DEFAULT_STAKE }];
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

  const place = useCallback(async () => {
    if (!authed) { setNeedAuth(true); return; }
    setPlacing(true);
    const pending = items.filter((i) => i.status !== "placed");
    const results = await Promise.all(
      pending.map(async (i) => {
        try {
          const r = await api.placeBet({
            fixture_id: i.fixtureId, market: i.market, selection: i.selection,
            stake_points: i.stake, idempotency_key: crypto.randomUUID(),
          });
          return { key: i.key, ok: true as const, betId: r.id };
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
          ? { ...i, status: "placed", message: `Apuesta #${r.betId}`, betId: r.betId }
          : { ...i, status: "error", message: r.message };
      })
    );
    setPlacing(false);
    // avisa a la barra superior para refrescar el saldo
    if (typeof window !== "undefined") window.dispatchEvent(new Event("balance:refresh"));
  }, [items, authed]);

  return (
    <BetSlipContext.Provider
      value={{ items, isSelected, toggle, remove, clear, setStake, setAllStakes, place, placing, needAuth, mobileOpen, setMobileOpen }}
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
