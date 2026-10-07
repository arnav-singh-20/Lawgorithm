// Progress: poll the background job until the analysis is done.
import { router, useLocalSearchParams } from "expo-router";
import React, { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";

import { deleteJob, getJob } from "../../api";
import { useAppState } from "../../appState";
import { Btn, Card, ErrorBanner, Screen, Txt } from "../../components/ui";
import { POLL_MS } from "../../config";
import { titleCase } from "../../decisions";
import { useI18n } from "../../i18n";
import { fonts, radius, useTheme } from "../../theme";
import { errorText } from "../../errors";

const STAGES = ["reading", "summarising", "clauses"] as const;

export default function Progress() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const theme = useTheme();
  const { t } = useI18n();
  const { config } = useAppState();
  const [job, setJob] = useState<any>(null);
  const [error, setError] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const j: any = await getJob(String(id));
        if (!alive) return;
        setJob(j);
        if (j.status === "done" && j.result) return router.replace(`/document/${j.result.document_id}`);
        if (j.status === "failed") return;
      } catch (err) {
        if (!alive) return;
        setError(errorText(err, t));
      }
      timer.current = setTimeout(poll, POLL_MS);
    };
    poll();
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, [id, t]);

  const stage = job?.stage;
  const stageIndex = STAGES.indexOf(stage);
  const pct = job?.total ? Math.round(((job.done || 0) / job.total) * 100) : stageIndex >= 0 ? (stageIndex + 1) * 8 : 4;

  const failed = job?.status === "failed";
  const failText = failed ? [job.error || t("err.generic"), job.refunded ? t("pay.refunded", { price: config.price_analysis }) : ""].filter(Boolean).join(" ") : "";

  return (
    <Screen>
      <Card>
        <Txt kind="label">{t("progress.eyebrow")} · {job?.filename || ""}</Txt>
        <Txt kind="display" style={{ fontSize: 28, lineHeight: 33 }}>{t("progress.title")}</Txt>
        {STAGES.map((s, i) => {
          const done = stageIndex > i || stage === "done";
          const now = stageIndex === i;
          return (
            <View key={s} style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={{ width: 24, height: 24, borderRadius: 12, borderWidth: 2, alignItems: "center", justifyContent: "center",
                borderColor: done || now ? theme.text : theme.line, backgroundColor: done ? theme.text : "transparent" }}>
                {done ? <Text style={{ color: theme.bg, fontFamily: fonts.bold, fontSize: 12 }}>✓</Text> : now ? <ActivityIndicator size="small" color={theme.text} /> : null}
              </View>
              <Txt kind={now ? "strong" : "soft"} style={{ flex: 1 }}>
                {t(`progress.${s}`)}{s === "clauses" && job?.total ? `  ·  ${t("progress.count", { done: job.done || 0, total: job.total })}` : ""}
              </Txt>
            </View>
          );
        })}
        <View style={{ height: 8, borderRadius: radius.pill, backgroundColor: theme.raised, overflow: "hidden" }}>
          <View style={{ width: `${pct}%`, height: "100%", backgroundColor: theme.gold }} />
        </View>
        {job?.status === "queued" ? <Txt kind="soft">{t("progress.queued")}</Txt> : null}
        {job?.current_title ? <Txt kind="soft">{t("progress.current", { title: titleCase(job.current_title) })}</Txt> : null}
        <Txt kind="small">{config.ai_service ? t("progress.noteSafe", { minutes: config.retention_minutes }) : t("progress.note")}</Txt>
      </Card>

      {failed ? <ErrorBanner text={failText} /> : null}
      {error ? <ErrorBanner text={error} /> : null}
      <Btn kind="outline" title={failed ? t("results.new") : t("privacy.deleteNow")} onPress={async () => {
        if (!failed) await deleteJob(String(id)).catch(() => {});
        router.replace("/");
      }} />
    </Screen>
  );
}
