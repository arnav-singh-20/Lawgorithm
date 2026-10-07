// Contact / grievances (DPDP Act, 2023): goes to the owner's Messages inbox.
import * as WebBrowser from "expo-web-browser";
import React, { useState } from "react";
import { Linking, Pressable, Text, TextInput, View } from "react-native";

import { api } from "../api";
import { useAppState } from "../appState";
import { Btn, Card, ErrorBanner, Row, Screen, Txt } from "../components/ui";
import { errorText } from "../errors";
import { useI18n } from "../i18n";
import { fonts, radius, useTheme } from "../theme";

const TOPICS = ["grievance", "payment", "question", "other"] as const;

export default function Contact() {
  const theme = useTheme();
  const { t } = useI18n();
  const { config } = useAppState();
  const [topic, setTopic] = useState<(typeof TOPICS)[number]>("grievance");
  const [message, setMessage] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/contact", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, message: message.trim(), reply_to: replyTo.trim() }) });
      setSent(true);
    } catch (err) { setError(errorText(err, t)); }
    finally { setBusy(false); }
  };

  const input = { minHeight: 48, paddingHorizontal: 14, paddingVertical: 12, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line,
    backgroundColor: theme.bg, color: theme.text, fontFamily: fonts.body, fontSize: 15 } as const;

  return (
    <Screen>
      <Txt kind="label">{t("contact.eyebrow")}</Txt>
      <Txt kind="display">{t("contact.title")}</Txt>
      <Txt kind="soft">{t("contact.sub")}</Txt>
      <Card>
        {sent ? <Txt kind="strong" color={theme.green}>✓ {t("contact.sent")}</Txt> : (
          <>
            <Txt kind="label">{t("contact.topic")}</Txt>
            <Row>
              {TOPICS.map(k => (
                <Pressable key={k} onPress={() => setTopic(k)} accessibilityRole="radio" accessibilityState={{ selected: topic === k }}
                  style={{ paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: topic === k ? 2 : 1,
                    borderColor: topic === k ? theme.text : theme.line }}>
                  <Text style={{ fontFamily: topic === k ? fonts.bold : fonts.medium, fontSize: 13.5, color: theme.text }}>{t(`contact.t.${k}`)}</Text>
                </Pressable>
              ))}
            </Row>
            <Txt kind="label">{t("contact.message")}</Txt>
            <TextInput value={message} onChangeText={setMessage} multiline maxLength={2000} placeholderTextColor={theme.faint}
              style={[input, { minHeight: 120, textAlignVertical: "top" }]} />
            <Txt kind="label">{t("contact.replyTo")}</Txt>
            <TextInput value={replyTo} onChangeText={setReplyTo} maxLength={200} autoCapitalize="none" keyboardType="email-address" style={input} />
            <Txt kind="small">{t("contact.replyHelp")}</Txt>
            {error ? <ErrorBanner text={error} /> : null}
            <Btn title={t("contact.send")} onPress={send} busy={busy} disabled={message.trim().length < 5} />
          </>
        )}
      </Card>
      {config.contact_email ? (
        <Pressable onPress={() => Linking.openURL(`mailto:${config.contact_email}`)}>
          <Txt kind="soft">{t("contact.email")} <Text style={{ fontFamily: fonts.bold, color: theme.text }}>{config.contact_email}</Text></Txt>
        </Pressable>
      ) : null}
      <View>
        <Txt kind="small">{t("contact.rights")}</Txt>
        {config.dpdp_act_url ? <Btn kind="link" title="DPDP Act, 2023 ↗" onPress={() => WebBrowser.openBrowserAsync(config.dpdp_act_url!).catch(() => {})} /> : null}
      </View>
    </Screen>
  );
}
