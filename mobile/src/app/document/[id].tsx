// Results: the decision, summary, action plan and every clause explained.
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import React, { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, Share, Text, View } from "react-native";

import { api, deleteDocument, Payment, sendForReview } from "../../api";
import { useAppState } from "../../appState";
import { Btn, Card, Chip, DecisionBox, ErrorBanner, RiskPill, Row, Screen, Txt } from "../../components/ui";
import { clauseDecision, DECISION_ICON, DECISION_ORDER, documentDecision, importantSentence, needsHuman, planItems, titleCase } from "../../decisions";
import { errorText } from "../../errors";
import { useI18n } from "../../i18n";
import { Order, PaySheet, prepareOrder } from "../../payments";
import { decisionColor, fonts, radius, riskColor, useTheme } from "../../theme";
import { TText, useTranslateAll } from "../../translation";

export default function Results() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const theme = useTheme();
  const { t, plural, meta } = useI18n();
  const { config } = useAppState();
  const [doc, setDoc] = useState<any>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "red" | "amber" | "green">("all");

  useEffect(() => {
    api(`/document/${id}`).then(setDoc).catch(err => setError(errorText(err, t)));
  }, [id, t]);

  const texts = useMemo(() => {
    if (!doc) return [];
    const list: string[] = [];
    if (doc.document_summary?.summary) list.push(doc.document_summary.summary);
    for (const c of doc.clauses) {
      list.push(c.plain_explanation);
      if (c.recommended_action) list.push(c.recommended_action);
      if (needsHuman(clauseDecision(c))) list.push(importantSentence(c.consequence));
    }
    return list;
  }, [doc]);
  const progress = useTranslateAll(texts);

  if (error) return <Screen><ErrorBanner text={error} /><Btn title={t("results.new")} onPress={() => router.replace("/")} /></Screen>;
  if (!doc) return <Screen><ActivityIndicator style={{ marginTop: 80 }} color={theme.text} /></Screen>;

  const dd = documentDecision(doc);
  const n = dd.decision === "sign" ? 0 : dd.counts[dd.decision];
  const counts: Record<string, number> = { red: 0, amber: 0, green: 0 };
  doc.clauses.forEach((c: any) => { counts[c.risk_level] = (counts[c.risk_level] || 0) + 1; });
  const shown = doc.clauses.filter((c: any) => filter === "all" || c.risk_level === filter);
  const plan = planItems(doc);
  const summary = doc.document_summary;
  const states: string[] = doc.jurisdiction_states || [];
  const dColor = decisionColor(theme, dd.decision === "sign" ? "no_lawyer" : dd.decision);

  const sharePlan = () => Share.share({
    message: [t("plan.title"), ...plan.map((p: any, i: number) => `${i + 1}. [${t(`risk.${p.level}`)}] ${p.title}: ${p.action}`)].join("\n"),
  }).catch(() => {});

  const deleteNow = async () => {
    await deleteDocument(doc.document_id).catch(() => {});
    router.replace("/");
  };

  return (
    <Screen>
      <Btn kind="link" title={`← ${t("results.new")}`} onPress={() => router.replace("/")} />
      <Txt kind="label">{doc.filename}</Txt>
      <Txt kind="display">{t(doc.document_type === "employment" ? "results.title.employment" : "results.title.rental")}</Txt>

      {/* the decision */}
      <View style={{ gap: 8 }}>
        <View style={{ alignSelf: "flex-start", paddingHorizontal: 12, paddingVertical: 5, borderRadius: radius.pill, backgroundColor: dColor.fg }}>
          <Text style={{ fontFamily: fonts.bold, fontSize: 12, letterSpacing: 1, color: theme.bg }}>{t(`docDecision.${dd.decision}.badge`).toUpperCase()}</Text>
        </View>
        <Txt kind="strong">{dd.decision === "sign" ? t("docDecision.sign") : plural(`docDecision.${dd.decision}`, n)}</Txt>
        <Row>
          {DECISION_ORDER.filter(d => dd.counts[d]).map(d => {
            const c = decisionColor(theme, d);
            return (
              <View key={d} style={{ flexDirection: "row", gap: 5, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, backgroundColor: c.bg }}>
                <Text>{DECISION_ICON[d]}</Text>
                <Text style={{ fontFamily: fonts.bold, fontSize: 13, color: c.fg }}>{dd.counts[d]} {t(`decisionCount.${d}`)}</Text>
              </View>
            );
          })}
        </Row>
      </View>

      <ExpertPanel doc={doc} />

      <Row style={{ justifyContent: "space-between" }}>
        <Txt kind="small" style={{ flex: 1 }}>{doc.stored ? "" : t("privacy.retention", { minutes: config.retention_minutes })}</Txt>
        <Btn small kind="outline" icon="🗑" title={t("privacy.deleteNow")} onPress={deleteNow} />
      </Row>

      {progress.active && progress.total ? (
        <Txt kind="small">{progress.done < progress.total
          ? t("translate.working", { lang: meta.native, done: progress.done, total: progress.total })
          : t("translate.done", { lang: meta.native })}</Txt>
      ) : null}

      {/* in short */}
      <Card>
        <Txt kind="label">{t("results.inShort")}</Txt>
        {summary ? <TText text={summary.summary} style={{ fontFamily: fonts.display, fontSize: 18, lineHeight: 26 }} /> : <Txt kind="soft">{t("results.noSummary")}</Txt>}
        {(summary?.key_terms || []).slice(0, 8).map((kt: any, i: number) => (
          <View key={i} style={{ flexDirection: "row", justifyContent: "space-between", gap: 10, padding: 10, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line }}>
            <Txt kind="small" style={{ flex: 1 }}>{kt.term}</Txt>
            <Txt kind="strong" style={{ flex: 1.3, textAlign: "right", fontSize: 14 }}>{kt.value}</Txt>
          </View>
        ))}
        <Txt kind="small">{states.length ? t("results.state", { states: states.join(", ") }) : t("results.noState")}</Txt>
      </Card>

      {/* action plan */}
      <Card style={{ borderStyle: "dashed" }}>
        <Txt kind="title">{t("plan.title")}</Txt>
        <Txt kind="small">{t("plan.sub")}</Txt>
        {plan.length ? plan.map((p: any, i: number) => (
          <View key={i} style={{ flexDirection: "row", gap: 10 }}>
            <View style={{ width: 22, height: 22, borderRadius: 11, backgroundColor: riskColor(theme, p.level).fg, alignItems: "center", justifyContent: "center" }}>
              <Text style={{ color: "#fff", fontFamily: fonts.bold, fontSize: 12 }}>{i + 1}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Txt kind="label">{p.title}</Txt>
              <TText text={p.action} style={{ fontSize: 14.5, lineHeight: 21 }} />
            </View>
          </View>
        )) : <Txt kind="soft">{t("plan.empty")}</Txt>}
        {plan.length ? <Btn small kind="outline" icon="⧉" title={t("app.share")} onPress={sharePlan} /> : null}
      </Card>

      {/* filters */}
      <Row>
        {(["all", "red", "amber", "green"] as const).map(f => (
          <Pressable key={f} onPress={() => setFilter(f)} accessibilityRole="tab" accessibilityState={{ selected: filter === f }}
            style={{ paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill, borderWidth: 1,
              borderColor: filter === f ? theme.text : theme.line, backgroundColor: filter === f ? theme.raised : "transparent" }}>
            <Text style={{ fontFamily: fonts.medium, color: theme.text }}>
              {f === "all" ? t("results.all") : t(`risk.${f}`)} {f === "all" ? doc.clauses.length : counts[f]}
            </Text>
          </Pressable>
        ))}
      </Row>

      {shown.length ? shown.map((c: any, i: number) => <ClauseCard key={c.clause_row_id || i} clause={c} index={i} />)
        : <Txt kind="soft">{t("results.empty")}</Txt>}

      {(doc.failed_clauses || []).length
        ? <ErrorBanner text={t("results.failed", { titles: doc.failed_clauses.map((f: any) => titleCase(f.clause_title)).join(", ") })} /> : null}
      <Txt kind="small">{t("results.disclaimer")}</Txt>
    </Screen>
  );
}

function ClauseCard({ clause, index }: { clause: any; index: number }) {
  const theme = useTheme();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const d = clauseDecision(clause);
  const conf = Math.round((clause.confidence || 0) * 100);
  const sentence = needsHuman(d) ? importantSentence(clause.consequence) : "";
  const reviewed = ["human_verified", "rejected"].includes(clause.verification_status);

  return (
    <Card accent={riskColor(theme, clause.risk_level).fg}>
      <Row style={{ justifyContent: "space-between" }}>
        <Txt kind="title" style={{ flex: 1, fontSize: 19 }}>
          <Text style={{ fontFamily: fonts.medium, fontSize: 12, color: theme.faint }}>§ {String(clause.clause_id || index + 1).padStart(2, "0")}  </Text>
          {titleCase(clause.clause_title)}
        </Txt>
        <RiskPill level={clause.risk_level} />
      </Row>
      <Row>
        {clause.clause_type?.clause_type ? <Chip text={t("clause.type", { type: clause.clause_type.label || clause.clause_type.clause_type })} /> : null}
        {(clause.review_flags || []).map((f: string) => <Chip key={f} tone="flag" text={`⚑ ${t(`flagShort.${f}`)}`} />)}
      </Row>
      <TText text={clause.plain_explanation} />
      {clause.recommended_action ? (
        <View style={{ padding: 12, borderRadius: radius.md, borderWidth: 1, borderStyle: "dashed", borderColor: theme.line, gap: 4 }}>
          <Txt kind="label">→ {t("clause.whatToDo")}</Txt>
          <TText text={clause.recommended_action} style={{ fontSize: 14.5, lineHeight: 21 }} />
        </View>
      ) : null}
      <DecisionBox decision={d} title={`${t(`decision.${d}`)}${reviewed ? ` · ${t(`status.${clause.verification_status}`)}` : ""}`}>
        {sentence ? <TText text={sentence} style={{ fontFamily: fonts.bold, fontSize: 14.5, lineHeight: 21 }} /> : null}
        {!sentence || d === "expert" ? <Txt kind="soft" style={{ fontSize: 13.5 }}>{t(`decisionWhy.${d}`)}</Txt> : null}
      </DecisionBox>
      <Row style={{ justifyContent: "space-between" }}>
        <Row>
          <Txt kind="small">{t("clause.confidence")}</Txt>
          <View style={{ width: 70, height: 5, borderRadius: 3, backgroundColor: theme.raised, overflow: "hidden" }}>
            <View style={{ width: `${conf}%`, height: "100%", backgroundColor: theme.text }} />
          </View>
          <Txt kind="small">{conf}%</Txt>
        </Row>
        <Btn small kind="outline" title={`${open ? t("clause.less") : t("clause.more")} ${open ? "⌃" : "⌄"}`} onPress={() => setOpen(o => !o)} />
      </Row>
      {open ? <ClauseDetails clause={clause} /> : null}
    </Card>
  );
}

function ClauseDetails({ clause }: { clause: any }) {
  const theme = useTheme();
  const { t } = useI18n();
  const block = (label: string, children: React.ReactNode) => (
    <View style={{ gap: 4, paddingTop: 8, borderTopWidth: 1, borderTopColor: theme.line }}>
      <Txt kind="label">{label}</Txt>{children}
    </View>
  );
  const sources = clause.cited_sources || [];
  return (
    <View style={{ gap: 10 }}>
      {clause.clause_text ? block(t("clause.original"), <Txt kind="soft" style={{ fontStyle: "italic" }}>{clause.clause_text}</Txt>) : null}
      {(clause.review_flags || []).length ? block(t("clause.flags"), (clause.review_flags || []).map((f: string) => <Txt key={f} kind="soft">• {t(`flag.${f}`)}</Txt>)) : null}
      {block(t("clause.assessment"), <Txt kind="soft">{clause.legal_assessment || "—"}</Txt>)}
      {(clause.claims || []).length ? block(t("clause.claims"), clause.claims.map((c: any, i: number) => <Txt key={i} kind="soft">• {c.claim}</Txt>)) : null}
      {block(t("clause.sources"), sources.length ? sources.map((s: any) => (
        <Pressable key={s.id} disabled={!s.official_source} onPress={() => WebBrowser.openBrowserAsync(s.official_source).catch(() => {})}
          style={{ padding: 10, borderRadius: radius.md, backgroundColor: theme.sunk, gap: 2 }}>
          <Txt kind="strong" style={{ fontSize: 14 }}>{s.law}{s.section ? `, s.${s.section}` : ""}{s.official_source ? "  ↗" : ""}</Txt>
          {s.title ? <Txt kind="small">{s.title}</Txt> : null}
        </Pressable>
      )) : <Txt kind="soft">{t("clause.noSources")}</Txt>)}
    </View>
  );
}

// "Needs a human expert check": send the uncertain clauses to a reviewer, or
// point to free legal aid when no reviewers are set up.
function ExpertPanel({ doc }: { doc: any }) {
  const theme = useTheme();
  const { t, plural } = useI18n();
  const { config, checks, rememberCheck } = useAppState();
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [order, setOrder] = useState<Order | null>(null);
  const uncertain = doc.clauses.filter((c: any) => clauseDecision(c) === "expert");
  if (!uncertain.length) return null;

  const box = (icon: string, children: React.ReactNode) => (
    <View style={{ flexDirection: "row", gap: 12, padding: 16, borderRadius: radius.lg, backgroundColor: theme.expertSoft, borderWidth: 1, borderColor: theme.expert + "55" }}>
      <Text style={{ fontSize: 24 }}>{icon}</Text><View style={{ flex: 1, gap: 8 }}>{children}</View>
    </View>
  );

  if (!config.expert_review_enabled) {
    return box("📞", <><Txt kind="title" style={{ fontSize: 18 }}>{t("expert.aidTitle")}</Txt>
      <Txt kind="soft">{t("expert.aidText", { number: config.free_legal_aid || "15100" })}</Txt></>);
  }
  const sent = checks.find(c => c.docId === doc.document_id);
  if (sent) {
    return box("🧑‍⚖️", <><Txt kind="title" style={{ fontSize: 18 }}>{t("expert.sent")}</Txt>
      <Btn small title={`${t("expert.view")} →`} onPress={() => router.push(`/expert/${sent.id}`)} /></>);
  }

  const priced = config.payments_enabled && config.price_expert > 0;
  const send = async (payment?: Payment | null) => {
    setBusy(true);
    setError("");
    try {
      const ticket: any = await sendForReview(doc.document_id, uncertain.map((c: any) => c.clause_row_id), payment);
      rememberCheck({ id: ticket.id, docId: doc.document_id, filename: doc.filename, created: ticket.created_at });
      router.push(`/expert/${ticket.id}`);
    } catch (err) { setError(errorText(err, t)); }
    finally { setBusy(false); }
  };
  const onPress = async () => {
    if (!consent) return setError(t("expert.consentNeeded"));
    if (!priced) return send(null);
    try { setOrder(await prepareOrder("expert")); } catch (err) { setError(errorText(err, t)); }
  };

  return box("🧑‍⚖️", <>
    <Txt kind="title" style={{ fontSize: 18 }}>{plural("expert.panelTitle", uncertain.length)}</Txt>
    <Txt kind="soft">{t(config.reviewer_kind === "legal" ? "expert.panelSub" : "expert.panelSub.team",
      { keep: config.expert_review_keep_days, max: config.expert_review_max_days })}</Txt>
    <Pressable onPress={() => setConsent(c => !c)} accessibilityRole="checkbox" accessibilityState={{ checked: consent }} style={{ flexDirection: "row", gap: 10 }}>
      <View style={{ width: 20, height: 20, borderRadius: 5, borderWidth: 2, borderColor: theme.text, backgroundColor: consent ? theme.text : "transparent",
        alignItems: "center", justifyContent: "center", marginTop: 2 }}>
        {consent ? <Text style={{ color: theme.bg, fontFamily: fonts.bold, fontSize: 12 }}>✓</Text> : null}
      </View>
      <Txt kind="soft" style={{ flex: 1, fontSize: 13.5 }}>{t("expert.consent")}</Txt>
    </Pressable>
    <Btn small title={priced ? t("pay.expertButton", { price: config.price_expert }) : t("expert.send")} onPress={onPress} busy={busy} />
    {error ? <ErrorBanner text={error} /> : null}
    <PaySheet order={order} description={doc.filename || "Expert check"} onDone={p => { setOrder(null); if (p) send(p); else setError(t("pay.cancelled")); }} />
  </>);
}
