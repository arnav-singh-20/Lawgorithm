// The person's private expert check: waiting, or the reviewer's decision.
import { router, useLocalSearchParams } from "expo-router";
import React, { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Share, View } from "react-native";

import { deleteTicket, getTicket } from "../../api";
import { useAppState } from "../../appState";
import { Btn, Card, DecisionBox, ErrorBanner, RiskPill, Row, Screen, Txt } from "../../components/ui";
import { siteUrl } from "../../config";
import { importantSentence, titleCase } from "../../decisions";
import { errorText } from "../../errors";
import { useI18n } from "../../i18n";
import { riskColor, useTheme } from "../../theme";
import { TText, useTranslateAll } from "../../translation";

export default function ExpertCheck() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const theme = useTheme();
  const { t, plural, lang } = useI18n();
  const { config, forgetCheck } = useAppState();
  const [ticket, setTicket] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const tk: any = await getTicket(String(id));
        if (!alive) return;
        setTicket(tk);
        if (tk.status === "waiting") timer = setTimeout(load, 30000);
      } catch (err: any) {
        if (!alive) return;
        if (err?.status === 404) { forgetCheck(String(id)); setError(t("expert.gone")); }
        else setError(errorText(err, t));
      }
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [id, t, forgetCheck]);

  const texts = useMemo(() => (ticket?.clauses || []).flatMap((c: any) => [
    c.ai?.plain_explanation, c.review?.note, c.review && c.review.decision !== "no_lawyer" ? importantSentence(c.review.consequence) : "",
  ]).filter(Boolean), [ticket]);
  useTranslateAll(texts);

  if (error) return <Screen><ErrorBanner text={error} /><Btn title={t("results.new")} onPress={() => router.replace("/")} /></Screen>;
  if (!ticket) return <Screen><ActivityIndicator style={{ marginTop: 80 }} color={theme.text} /></Screen>;

  const waiting = ticket.clauses.filter((c: any) => !c.review).length;
  const date = (iso: string) => new Date(iso).toLocaleDateString(lang === "en" ? "en-IN" : lang, { day: "numeric", month: "short", year: "numeric" });

  return (
    <Screen>
      <Btn kind="link" title={`← ${t("results.new")}`} onPress={() => router.replace("/")} />
      <Txt kind="label">{t("expert.eyebrow")}</Txt>
      <Txt kind="display">{t("expert.title")}</Txt>
      <Txt kind="soft">{waiting ? plural("expert.waiting", waiting) : t("expert.done")}</Txt>
      <Txt kind="small">{t("expert.retention", { keep: ticket.keep_days, max: ticket.max_days })}</Txt>
      <Row>
        <Btn small kind="outline" icon="⧉" title={t("app.share")} onPress={() => Share.share({ message: siteUrl(`expert/${ticket.id}`) }).catch(() => {})} />
        <Btn small kind="outline" icon="🗑" title={t("privacy.deleteNow")} onPress={async () => {
          await deleteTicket(ticket.id).catch(() => {});
          forgetCheck(ticket.id);
          router.replace("/");
        }} />
      </Row>

      {ticket.clauses.map((c: any) => {
        const level = (c.review || c.ai || {}).risk_level || "amber";
        const sentence = c.review && c.review.decision !== "no_lawyer" ? importantSentence(c.review.consequence) : "";
        return (
          <Card key={c.clause_row_id} accent={riskColor(theme, level).fg}>
            <Row style={{ justifyContent: "space-between" }}>
              <Txt kind="title" style={{ flex: 1, fontSize: 19 }}>{titleCase(c.clause_title)}</Txt>
              <RiskPill level={level} />
            </Row>
            <Txt kind="label">{t("expert.aiSaid")}</Txt>
            <TText text={c.ai?.plain_explanation} />
            {c.review ? (
              <DecisionBox decision={c.review.decision} title={`${t("expert.reviewerSaid")}: ${t(`decision.${c.review.decision}`)}`}>
                {sentence ? <TText text={sentence} style={{ fontWeight: "700", fontSize: 14.5, lineHeight: 21 }} /> : null}
                {c.review.note ? <TText text={c.review.note} style={{ fontSize: 14, lineHeight: 20 }} /> : null}
                <Txt kind="small">{t("expert.by", { name: c.review.reviewer, date: date(c.review.reviewed_at) })}</Txt>
                {c.review.decision === "lawyer" && config.free_legal_aid
                  ? <Txt kind="strong" style={{ fontSize: 13.5 }}>{t("expert.aidShort", { number: config.free_legal_aid })}</Txt> : null}
              </DecisionBox>
            ) : (
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                <ActivityIndicator size="small" color={theme.expert} />
                <Txt kind="soft">{t("expert.pendingClause")}</Txt>
              </View>
            )}
          </Card>
        );
      })}
    </Screen>
  );
}
