// App-wide state: the server's public settings (/config) and the expert
// checks this phone has sent (remembered on the device only).
import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";

import { getConfig } from "./api";

export type Config = {
  ai_service: string | null; retention_minutes: number; expert_review_enabled: boolean;
  expert_review_keep_days: number; expert_review_max_days: number; free_legal_aid: string;
  reviewer_kind: string; payments_enabled: boolean; price_analysis: number; price_expert: number;
  dpdp_act_url: string | null; contact_email: string | null; privacy_contact: string | null;
};

const DEFAULT_CONFIG: Config = {
  ai_service: null, retention_minutes: 60, expert_review_enabled: false, expert_review_keep_days: 7, expert_review_max_days: 30,
  free_legal_aid: "15100", reviewer_kind: "team", payments_enabled: false, price_analysis: 0, price_expert: 0,
  dpdp_act_url: null, contact_email: null, privacy_contact: null,
};

export type SavedCheck = { id: string; docId: string; filename?: string; created?: string };
const CHECKS_KEY = "lawgorithm.expertChecks";

type AppState = {
  config: Config;
  checks: SavedCheck[];
  rememberCheck: (c: SavedCheck) => void;
  forgetCheck: (id: string) => void;
};
const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<Config>(DEFAULT_CONFIG);
  const [checks, setChecks] = useState<SavedCheck[]>([]);

  useEffect(() => {
    getConfig().then(c => setConfig({ ...DEFAULT_CONFIG, ...c })).catch(() => {});
    AsyncStorage.getItem(CHECKS_KEY).then(v => setChecks(v ? JSON.parse(v) : [])).catch(() => {});
  }, []);

  const rememberCheck = useCallback((c: SavedCheck) => setChecks(prev => {
    const list = [c, ...prev.filter(x => x.id !== c.id)].slice(0, 10);
    AsyncStorage.setItem(CHECKS_KEY, JSON.stringify(list)).catch(() => {});
    return list;
  }), []);
  const forgetCheck = useCallback((id: string) => setChecks(prev => {
    const list = prev.filter(x => x.id !== id);
    AsyncStorage.setItem(CHECKS_KEY, JSON.stringify(list)).catch(() => {});
    return list;
  }), []);

  return <Ctx.Provider value={{ config, checks, rememberCheck, forgetCheck }}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState outside AppStateProvider");
  return v;
}
