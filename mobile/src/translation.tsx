// AI text (explanations, notes) translated into the chosen language through
// the server's /translate, which back-translates and checks numbers and roles.
// Same behaviour as the website: if a check fails, the English is shown too.
import React, { useEffect, useState } from "react";
import { Text, TextStyle } from "react-native";

import { translate } from "./api";
import { useI18n } from "./i18n";
import { fonts, useTheme } from "./theme";

type Hit = { text: string; validated: boolean; numbersOk: boolean; rolesOk: boolean; score: number } | "failed";
const cache = new Map<string, Hit>();
const key = (lang: string, text: string) => `${lang}::${text}`;
const listeners = new Set<() => void>();

let running = 0;
/** Translate texts one by one (the free AI tier is rate-limited); returns live progress. */
export function useTranslateAll(texts: string[]) {
  const { meta } = useI18n();
  const [done, setDone] = useState(0);
  const todo = Array.from(new Set(texts.filter(Boolean)));
  const sig = meta.code + "|" + todo.join("\u0000");

  useEffect(() => {
    if (!meta.backend) return;
    const run = ++running;
    let count = todo.filter(x => cache.has(key(meta.code, x))).length;
    setDone(count);
    (async () => {
      for (const text of todo) {
        if (run !== running) return;
        if (cache.has(key(meta.code, text))) continue;
        try {
          const r: any = await translate(text, meta.backend!);
          cache.set(key(meta.code, text), { text: r.translated_text, validated: !!r.validated, numbersOk: r.numbers_preserved !== false,
            rolesOk: r.roles_preserved !== false, score: r.similarity_score ?? 0 });
        } catch {
          cache.set(key(meta.code, text), "failed");
        }
        count += 1;
        if (run === running) setDone(count);
        listeners.forEach(fn => fn());
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig]);

  return { active: !!meta.backend, done: Math.min(done, todo.length), total: todo.length };
}

/** A piece of AI text, shown in the chosen language once translated. */
export function TText({ text, style }: { text: string; style?: TextStyle }) {
  const { meta, t } = useI18n();
  const theme = useTheme();
  const [, force] = useState(0);
  useEffect(() => { const fn = () => force(n => n + 1); listeners.add(fn); return () => { listeners.delete(fn); }; }, []);

  const base: TextStyle = { fontFamily: fonts.body, fontSize: 15.5, lineHeight: 23, color: theme.text };
  if (!text) return null;
  if (!meta.backend) return <Text style={[base, style]}>{text}</Text>;
  const hit = cache.get(key(meta.code, text));
  if (!hit) return <Text style={[base, style, { opacity: 0.55 }]}>{text}</Text>;
  const note = (s: string, warn = false) => (
    <Text style={{ fontFamily: fonts.body, fontSize: 12, lineHeight: 17, color: warn ? theme.amber : theme.faint }}>{s}</Text>
  );
  if (hit === "failed" || !hit.validated) {
    return (
      <Text style={[base, style]}>
        {hit === "failed" ? text : `${hit.text}\n\n${text}`}
        {"\n"}{note(hit === "failed" ? t("translate.failed") : !hit.numbersOk ? t("translate.numbers") : !hit.rolesOk ? t("translate.roles") : t("translate.warn"), true)}
      </Text>
    );
  }
  return <Text style={[base, style]}>{hit.text}</Text>;
}
