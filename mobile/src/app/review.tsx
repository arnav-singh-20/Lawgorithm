// Reviewer desk (the human in the loop): sign in, review waiting clauses,
// and -- for the owner -- manage reviewers and read Contact messages.
import * as Clipboard from "expo-clipboard";
import { router, useLocalSearchParams } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Share, Text, TextInput, View } from "react-native";

import { Btn, Card, Chip, ErrorBanner, RiskPill, Row, Screen, Txt } from "../components/ui";
import { confirmAsync } from "../confirm";
import { DECISION_ICON, titleCase } from "../decisions";
import { errorText } from "../errors";
import { useI18n } from "../i18n";
import {
  addReviewer, clearReviewerKey, deleteMessage, getReviewerKey, inviteLink, listMessages, listReviewers,
  removeReviewer, reviewerQueue, setReviewerKey, submitReview,
} from "../reviewer";
import { decisionColor, fonts, radius, useTheme } from "../theme";

type Tab = "queue" | "team" | "messages";

export default function ReviewerDesk() {
  const { invite } = useLocalSearchParams<{ invite?: string }>();
  const theme = useTheme();
  const { t, plural } = useI18n();
  const [key, setKey] = useState<string | null | undefined>(undefined);   // undefined = still loading
  const [desk, setDesk] = useState<any>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("queue");

  // an invite link (…/review?invite=KEY) signs the reviewer straight in
  useEffect(() => {
    (async () => {
      if (invite) {
        await setReviewerKey(String(invite));
        router.setParams({ invite: undefined });
      }
      setKey(await getReviewerKey());
    })();
  }, [invite]);

  const load = useCallback(async (k: string) => {
    setError("");
    try {
      setDesk(await reviewerQueue(k));
    } catch (err: any) {
      if (err?.status === 401) { await clearReviewerKey(); setKey(null); setError(t("desk.badKey")); }
      else setError(errorText(err, t));
    }
  }, [t]);

  useEffect(() => { if (key) load(key); }, [key, load]);

  if (key === undefined) return <Screen><ActivityIndicator style={{ marginTop: 60 }} color={theme.text} /></Screen>;
  if (!key) return <SignIn error={error} onKey={async k => { await setReviewerKey(k); setKey(k); }} />;

  const owner = desk?.role === "owner";
  const signOut = async () => { await clearReviewerKey(); setDesk(null); setKey(null); };

  return (
    <Screen>
      <Txt kind="label">{t("review.eyebrow")}</Txt>
      <Txt kind="display">{t("review.title")}</Txt>
      <Txt kind="soft">{t("desk.sub")}</Txt>
      {desk ? (
        <Row style={{ justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            <Txt kind="soft">{t("desk.signedIn", { name: desk.reviewer })}</Txt>
            <Txt kind="strong">{plural("desk.count", desk.count)}</Txt>
          </View>
          <Btn small kind="outline" title={t("desk.signOut")} onPress={signOut} />
        </Row>
      ) : null}

      {owner ? (
        <Row>
          {([["queue", `🧑‍⚖️ ${desk.count}`], ["team", `👥 ${t("desk.manage")}`], ["messages", `📨 ${t("desk.messages")}`]] as [Tab, string][]).map(([k, label]) => (
            <Pressable key={k} onPress={() => setTab(k)} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}
              style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1,
                borderColor: tab === k ? theme.text : theme.line, backgroundColor: tab === k ? theme.raised : "transparent" }}>
              <Text style={{ fontFamily: fonts.medium, color: theme.text }}>{label}</Text>
            </Pressable>
          ))}
        </Row>
      ) : null}

      {error ? <ErrorBanner text={error} /> : null}
      {!desk ? <ActivityIndicator color={theme.text} /> : null}

      {desk && (tab === "queue" || !owner) ? (
        desk.items.length
          ? desk.items.map((item: any) => <DeskCard key={`${item.ticket_id}-${item.clause_row_id}`} item={item} reviewerKey={key} onDone={() => load(key)} />)
          : <Card><Txt style={{ textAlign: "center" }}>✨ {t("desk.empty")}</Txt></Card>
      ) : null}
      {desk && owner && tab === "team" ? <Team reviewerKey={key} /> : null}
      {desk && owner && tab === "messages" ? <Messages reviewerKey={key} /> : null}
    </Screen>
  );
}

function Input(props: React.ComponentProps<typeof TextInput>) {
  const theme = useTheme();
  return (
    <TextInput placeholderTextColor={theme.faint} {...props}
      style={[{ minHeight: 48, paddingHorizontal: 14, paddingVertical: 12, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line,
        backgroundColor: theme.bg, color: theme.text, fontFamily: fonts.body, fontSize: 15 }, props.multiline ? { minHeight: 84, textAlignVertical: "top" } : null, props.style]} />
  );
}

function SignIn({ error, onKey }: { error: string; onKey: (k: string) => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState("");
  return (
    <Screen>
      <Card>
        <Txt kind="title">{t("desk.loginTitle")}</Txt>
        <Txt kind="soft">{t("desk.loginSub")}</Txt>
        <Input value={value} onChangeText={setValue} placeholder={t("desk.key")} secureTextEntry autoCapitalize="none" autoCorrect={false}
          onSubmitEditing={() => value.trim() && onKey(value.trim())} />
        {error ? <ErrorBanner text={error} /> : null}
        <Btn title={t("desk.signIn")} onPress={() => value.trim() && onKey(value.trim())} disabled={!value.trim()} />
      </Card>
    </Screen>
  );
}

function Choice<T extends string>({ options, value, onChange }: { options: [T, string][]; value: T | ""; onChange: (v: T) => void }) {
  const theme = useTheme();
  return (
    <Row>
      {options.map(([v, label]) => (
        <Pressable key={v} onPress={() => onChange(v)} accessibilityRole="radio" accessibilityState={{ selected: value === v }}
          style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: value === v ? 2 : 1,
            borderColor: value === v ? theme.text : theme.line, backgroundColor: value === v ? theme.raised : "transparent" }}>
          <Text style={{ fontFamily: value === v ? fonts.bold : fonts.medium, fontSize: 13.5, color: theme.text }}>{label}</Text>
        </Pressable>
      ))}
    </Row>
  );
}

function DeskCard({ item, reviewerKey, onDone }: { item: any; reviewerKey: string; onDone: () => void }) {
  const theme = useTheme();
  const { t } = useI18n();
  const ai = item.ai || {};
  const [decision, setDecision] = useState<"no_lawyer" | "negotiate" | "lawyer" | "">("");
  const [risk, setRisk] = useState<"green" | "amber" | "red">(ai.risk_level || "amber");
  const [consequence, setConsequence] = useState<string>(ai.consequence || "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const when = new Date(item.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

  const send = async () => {
    if (!decision) return setError(t("desk.yourDecision"));
    setBusy(true);
    setError("");
    try {
      await submitReview(reviewerKey, item.ticket_id, item.clause_row_id, { decision, risk_level: risk, consequence: consequence.trim(), note: note.trim() });
      onDone();
    } catch (err) { setError(errorText(err, t)); }
    finally { setBusy(false); }
  };

  const block = (label: string, children: React.ReactNode) => (
    <View style={{ gap: 4, paddingTop: 8, borderTopWidth: 1, borderTopColor: theme.line }}><Txt kind="label">{label}</Txt>{children}</View>
  );
  return (
    <Card accent={decisionColor(theme, ai.decision || "expert").fg}>
      <Txt kind="small">{t("desk.meta", { type: item.document_type || "", states: (item.jurisdiction_states || []).join(", ") || t("desk.anyState"), date: when })}</Txt>
      <Row style={{ justifyContent: "space-between" }}>
        <Txt kind="title" style={{ flex: 1, fontSize: 19 }}>{titleCase(item.clause_title)}</Txt>
        <RiskPill level={ai.risk_level} />
      </Row>
      {block(t("desk.original"), <Txt kind="soft" style={{ fontStyle: "italic" }}>{item.clause_text}</Txt>)}
      {block(t("desk.ai"), <>
        <Txt>{ai.plain_explanation || "—"}</Txt>
        <Txt kind="soft"><Text style={{ fontFamily: fonts.bold }}>{t("desk.assessment")}: </Text>{ai.legal_assessment || "—"}</Txt>
        <Txt kind="soft"><Text style={{ fontFamily: fonts.bold }}>{t("clause.whatToDo")}: </Text>{ai.recommended_action || "—"}</Txt>
        <Txt kind="soft"><Text style={{ fontFamily: fonts.bold }}>{t("desk.aiDecision")}: </Text>
          {DECISION_ICON[ai.decision || "expert"]} {t(`decision.${ai.decision || "expert"}`)} · {Math.round((ai.confidence || 0) * 100)}%</Txt>
      </>)}
      {(ai.review_flags || []).length ? block(t("desk.flags"), <Row>{ai.review_flags.map((f: string) => <Chip key={f} tone="flag" text={`⚑ ${t(`flagShort.${f}`)}`} />)}</Row>) : null}
      {block(t("desk.sources"), (ai.cited_sources || []).length ? ai.cited_sources.map((s: any) => (
        <Pressable key={s.id} disabled={!s.official_source} onPress={() => WebBrowser.openBrowserAsync(s.official_source).catch(() => {})}>
          <Txt kind="soft">• {s.law}, s.{s.section}{s.title ? ` — ${s.title}` : ""}{s.official_source ? " ↗" : ""}</Txt>
        </Pressable>
      )) : <Txt kind="soft">{t("desk.noSources")}</Txt>)}

      <View style={{ gap: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: theme.line, borderStyle: "dashed" }}>
        <Txt kind="label">{t("desk.yourDecision")}</Txt>
        <Choice value={decision} onChange={setDecision}
          options={[["no_lawyer", `✅ ${t("decision.no_lawyer")}`], ["negotiate", `🤝 ${t("decision.negotiate")}`], ["lawyer", `⚖️ ${t("decision.lawyer")}`]]} />
        <Txt kind="label">{t("desk.risk")}</Txt>
        <Choice value={risk} onChange={setRisk} options={[["green", t("risk.green")], ["amber", t("risk.amber")], ["red", t("risk.red")]]} />
        <Txt kind="label">{t("desk.consequence")}</Txt>
        <Input value={consequence} onChangeText={setConsequence} placeholder={t("desk.consequencePlaceholder")} />
        <Txt kind="small">{t("desk.consequenceHelp")}</Txt>
        <Txt kind="label">{t("desk.noteOptional")}</Txt>
        <Input value={note} onChangeText={setNote} placeholder={t("desk.notePlaceholder")} multiline />
        {error ? <ErrorBanner text={error} /> : null}
        <Btn title={t("desk.submit")} onPress={send} busy={busy} />
      </View>
    </Card>
  );
}

function Team({ reviewerKey }: { reviewerKey: string }) {
  const { t } = useI18n();
  const [list, setList] = useState<any[] | null>(null);
  const [name, setName] = useState("");
  const [invite, setInvite] = useState<{ name: string; link: string } | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => listReviewers(reviewerKey).then((r: any) => setList(r.reviewers)).catch(err => setError(errorText(err, t))), [reviewerKey, t]);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!name.trim()) return;
    setError("");
    try {
      const r: any = await addReviewer(reviewerKey, name.trim());
      setInvite({ name: r.name, link: inviteLink(r.key) });
      setName("");
      load();
    } catch (err) { setError(errorText(err, t)); }
  };
  const remove = async (r: any) => {
    if (!(await confirmAsync(t("desk.removeConfirm", { name: r.name }), t("desk.remove")))) return;
    try { await removeReviewer(reviewerKey, r.id); load(); } catch (err) { setError(errorText(err, t)); }
  };
  const message = invite ? t("desk.inviteMessage", { link: invite.link }) : "";

  return (
    <Card>
      <Txt kind="title">{t("desk.manage")}</Txt>
      <Txt kind="soft">{t("desk.manageSub")}</Txt>
      {invite ? (
        <View style={{ gap: 8, padding: 12, borderRadius: radius.md, backgroundColor: "rgba(47,143,91,0.12)" }}>
          <Txt kind="strong">{t("desk.inviteReady", { name: invite.name })}</Txt>
          <Txt kind="small" selectable>{invite.link}</Txt>
          <Row>
            <Btn small icon="📤" title={t("app.share")} onPress={() => Share.share({ message }).catch(() => {})} />
            <Btn small kind="outline" icon="⧉" title={t("desk.copyInvite")} onPress={async () => { await Clipboard.setStringAsync(message); }} />
          </Row>
          <Txt kind="small">{t("desk.inviteWarning", { name: invite.name })}</Txt>
        </View>
      ) : null}
      <Input value={name} onChangeText={setName} placeholder={t("desk.addPlaceholder")} maxLength={60} onSubmitEditing={add} />
      <Btn title={t("desk.add")} onPress={add} disabled={!name.trim()} />
      {error ? <ErrorBanner text={error} /> : null}
      {!list ? <ActivityIndicator /> : list.map(r => (
        <Row key={r.id || r.name} style={{ justifyContent: "space-between", paddingVertical: 8, borderTopWidth: 1, borderTopColor: "rgba(128,128,128,0.2)" }}>
          <View style={{ flex: 1 }}>
            <Txt kind="strong">{r.name}</Txt>
            <Txt kind="label">{r.role === "owner" ? t("desk.owner") : t("desk.addedOn", { date: new Date(r.added_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) })}</Txt>
          </View>
          {r.role === "owner" ? null : <Btn small kind="outline" title={t("desk.remove")} onPress={() => remove(r)} />}
        </Row>
      ))}
    </Card>
  );
}

function Messages({ reviewerKey }: { reviewerKey: string }) {
  const { t } = useI18n();
  const [list, setList] = useState<any[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => listMessages(reviewerKey).then((r: any) => setList(r.messages)).catch(err => setError(errorText(err, t))), [reviewerKey, t]);
  useEffect(() => { load(); }, [load]);
  const remove = async (id: string) => {
    if (!(await confirmAsync(t("desk.deleteMsgConfirm"), t("desk.delete")))) return;
    try { await deleteMessage(reviewerKey, id); load(); } catch (err) { setError(errorText(err, t)); }
  };
  return (
    <Card>
      <Txt kind="title">{t("desk.messages")}</Txt>
      {error ? <ErrorBanner text={error} /> : null}
      {!list ? <ActivityIndicator /> : list.length ? list.map(m => (
        <View key={m.id} style={{ gap: 4, paddingVertical: 10, borderTopWidth: 1, borderTopColor: "rgba(128,128,128,0.2)" }}>
          <Txt kind="label">{t(`contact.t.${m.topic}`)} · {new Date(m.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</Txt>
          <Txt selectable>{m.message}</Txt>
          <Txt kind="small" selectable>{t("desk.replyTo")}: {m.reply_to || t("desk.noReplyTo")}</Txt>
          <View style={{ alignSelf: "flex-start" }}><Btn small kind="outline" title={t("desk.delete")} onPress={() => remove(m.id)} /></View>
        </View>
      )) : <Txt kind="soft">{t("desk.messagesEmpty")}</Txt>}
    </Card>
  );
}
