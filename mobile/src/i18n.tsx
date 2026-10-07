// Seven languages, the same strings as the website (strings.json).
import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { APP_STRINGS } from "./appStrings";
import data from "./strings.json";

type Lang = { code: string; native: string; english: string; backend: string | null };
export const LANGUAGES: Lang[] = (data as any).languages;
const STRINGS: Record<string, Record<string, string>> = (data as any).strings;
const LANG_KEY = "lawgorithm.lang";

type I18n = {
  lang: string;
  meta: Lang;
  ready: boolean;
  chosen: boolean;                       // has the person picked a language yet?
  setLang: (code: string) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
  plural: (key: string, n: number) => string;
};

const Ctx = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState("en");
  const [ready, setReady] = useState(false);
  const [chosen, setChosen] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(LANG_KEY)
      .then(saved => { if (saved && STRINGS[saved]) { setLangState(saved); setChosen(true); } })
      .catch(() => {})
      .finally(() => setReady(true));
  }, []);

  const setLang = useCallback((code: string) => {
    setLangState(code);
    setChosen(true);
    AsyncStorage.setItem(LANG_KEY, code).catch(() => {});
  }, []);

  const t = useCallback((key: string, vars?: Record<string, string | number>) => {
    let s = APP_STRINGS[lang]?.[key] ?? STRINGS[lang]?.[key] ?? APP_STRINGS.en[key] ?? STRINGS.en[key] ?? key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`));
    return s;
  }, [lang]);

  const plural = useCallback((key: string, n: number) => (n === 1 && (STRINGS[lang]?.[`${key}.one`] || STRINGS.en[`${key}.one`])
    ? t(`${key}.one`, { n }) : t(key, { n })), [lang, t]);

  const meta = LANGUAGES.find(l => l.code === lang) || LANGUAGES[0];
  const value = useMemo(() => ({ lang, meta, ready, chosen, setLang, t, plural }), [lang, meta, ready, chosen, setLang, t, plural]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
