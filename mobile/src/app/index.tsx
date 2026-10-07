// Home: choose a contract (file, photo or sample), consent, pay if needed, start.
import * as DocumentPicker from "expo-document-picker";
import { File as FsFile, Paths } from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import { Redirect, router } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import React, { useState } from "react";
import { Platform, Pressable, Text, View } from "react-native";

import { Payment, PickedFile, sampleText, startAnalysis } from "../api";
import { useAppState } from "../appState";
import { Logo } from "../components/Logo";
import { Btn, Card, ErrorBanner, Row, Screen, Txt } from "../components/ui";
import { siteUrl } from "../config";
import { errorText } from "../errors";
import { useI18n } from "../i18n";
import { Order, PaySheet, prepareOrder } from "../payments";
import { fonts, radius, useTheme } from "../theme";

const ACCEPTED = /\.(pdf|png|jpe?g|webp|heic|docx|txt)$/i;

export default function Home() {
  const theme = useTheme();
  const { t, chosen, meta } = useI18n();
  const { config, checks } = useAppState();
  const [docType, setDocType] = useState<"rental" | "employment">("rental");
  const [file, setFile] = useState<PickedFile | null>(null);
  const [isSample, setIsSample] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [order, setOrder] = useState<Order | null>(null);

  if (!chosen) return <Redirect href="/language" />;

  const needsPayment = config.payments_enabled && config.price_analysis > 0 && !isSample;

  const choose = (f: PickedFile | null, sample = false) => { setError(""); setFile(f); setIsSample(sample); };

  async function pickFile() {
    const res = await DocumentPicker.getDocumentAsync({
      type: ["application/pdf", "image/*", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    if (!ACCEPTED.test(a.name) && !(a.mimeType || "").startsWith("image/")) return setError(t("err.type"));
    choose({ uri: a.uri, name: a.name, mimeType: a.mimeType, webFile: (a as any).file });
  }

  async function takePhoto() {
    if (Platform.OS !== "web") {
      const perm = await ImagePicker.requestCameraPermissionsAsync();
      if (!perm.granted) return;
    }
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.85 });
    if (res.canceled || !res.assets?.length) return;
    const a = res.assets[0];
    choose({ uri: a.uri, name: a.fileName || `photo_${Date.now()}.jpg`, mimeType: a.mimeType || "image/jpeg", webFile: (a as any).file });
  }

  async function useSample(type: "rental" | "employment") {
    setDocType(type);
    try {
      const text = await sampleText(type);
      const name = `sample_${type === "rental" ? "lease" : "job_offer"}.txt`;
      if (Platform.OS === "web") {
        choose({ uri: "", name, mimeType: "text/plain", webFile: new File([text], name, { type: "text/plain" }) }, true);
      } else {
        // write it to a temporary file so it uploads like any picked document
        const tmp = new FsFile(Paths.cache, name);
        if (tmp.exists) tmp.delete();
        tmp.create();
        tmp.write(text);
        choose({ uri: tmp.uri, name, mimeType: "text/plain" }, true);
      }
    } catch (err) { setError(errorText(err, t)); }
  }

  async function start(payment?: Payment | null) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const { job_id } = await startAnalysis(file, docType, payment);
      router.push(`/job/${job_id}`);
    } catch (err) {
      setError(errorText(err, t));
    } finally {
      setBusy(false);
    }
  }

  async function onDecode() {
    if (!file || !consent) return;
    if (!needsPayment) return start(null);
    setBusy(true);
    try { setOrder(await prepareOrder("analysis")); }
    catch (err) { setError(errorText(err, t)); }
    finally { setBusy(false); }
  }

  const label = needsPayment ? t("pay.button", { price: config.price_analysis }) : t("upload.cta");
  const open = (route: string) => WebBrowser.openBrowserAsync(siteUrl(route)).catch(() => {});

  return (
    <Screen>
      <Row style={{ justifyContent: "space-between" }}>
        <Logo />
        <Pressable onPress={() => router.push("/language")} accessibilityRole="button" accessibilityLabel={t("app.language")}
          style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill, borderWidth: 1, borderColor: theme.line }}>
          <Text style={{ fontSize: 14 }}>🌐</Text>
          <Text style={{ fontFamily: fonts.medium, fontSize: 14, color: theme.text }}>{meta.native}</Text>
        </Pressable>
      </Row>

      <View style={{ gap: 6, marginTop: 6 }}>
        <Txt style={{ fontFamily: fonts.displayItalic, fontSize: 18, color: theme.accent }}>{t("tagline")}</Txt>
        <Txt kind="display">{t("hero.title.a")} <Text style={{ fontFamily: fonts.displayItalic }}>{t("hero.title.b")}</Text></Txt>
        <Txt kind="soft">{t("hero.lede")}</Txt>
      </View>

      <Card>
        <Row>
          {(["rental", "employment"] as const).map(d => (
            <Pressable key={d} onPress={() => setDocType(d)} accessibilityRole="radio" accessibilityState={{ selected: docType === d }}
              style={{ paddingHorizontal: 18, paddingVertical: 9, borderRadius: radius.pill, backgroundColor: docType === d ? theme.btn : theme.raised }}>
              <Text style={{ fontFamily: fonts.bold, color: docType === d ? theme.btnText : theme.text }}>{t(d === "rental" ? "upload.rental" : "upload.job")}</Text>
            </Pressable>
          ))}
        </Row>

        <Pressable onPress={pickFile} accessibilityRole="button"
          style={({ pressed }) => ({ padding: 22, borderRadius: radius.md, borderWidth: 1.5, borderStyle: "dashed", borderColor: theme.text,
            alignItems: "center", gap: 6, backgroundColor: pressed ? theme.raised : theme.surface })}>
          <Text style={{ fontSize: 30 }}>📄</Text>
          <Txt kind="title">{file ? file.name : t("app.pick")}</Txt>
          <Txt kind="small">{file ? (isSample ? t("pay.noteFreeSample") : t("app.change")) : t("app.pickSub")}</Txt>
        </Pressable>

        <Btn kind="outline" icon="📷" title={t("upload.camera")} onPress={takePhoto} />

        <Row>
          <Txt kind="label">{t("upload.noFile")}</Txt>
          <Btn kind="link" title={t("upload.sampleRental")} onPress={() => useSample("rental")} />
          <Txt kind="soft">·</Txt>
          <Btn kind="link" title={t("upload.sampleJob")} onPress={() => useSample("employment")} />
        </Row>

        <Pressable onPress={() => setConsent(c => !c)} accessibilityRole="checkbox" accessibilityState={{ checked: consent }}
          style={{ flexDirection: "row", gap: 10, padding: 12, borderRadius: radius.md, borderWidth: 1, borderColor: theme.line }}>
          <View style={{ width: 22, height: 22, borderRadius: 6, borderWidth: 2, borderColor: theme.text, alignItems: "center", justifyContent: "center",
            backgroundColor: consent ? theme.text : "transparent", marginTop: 1 }}>
            {consent ? <Text style={{ color: theme.bg, fontFamily: fonts.bold, fontSize: 14 }}>✓</Text> : null}
          </View>
          <Txt kind="soft" style={{ flex: 1 }}>
            {t("consent.label")} <Text onPress={() => router.push("/privacy")} style={{ fontFamily: fonts.bold, color: theme.text, textDecorationLine: "underline" }}>
              {t("consent.link")}</Text>{t("consent.rights")}
          </Txt>
        </Pressable>

        <Btn title={label} onPress={onDecode} disabled={!file || !consent} busy={busy} />
        {config.payments_enabled && config.price_analysis > 0
          ? <Txt kind="small">{isSample ? t("pay.noteFreeSample") : t("pay.note", { price: config.price_analysis })}</Txt> : null}
        {error ? <ErrorBanner text={error} /> : null}
      </Card>

      {checks.length ? (
        <Card>
          <Txt kind="label">{t("app.myChecks")}</Txt>
          {checks.map(c => <Btn key={c.id} kind="link" title={`🧑‍⚖️ ${c.filename || t("expert.view")}`} onPress={() => router.push(`/expert/${c.id}`)} />)}
        </Card>
      ) : null}

      <Row style={{ justifyContent: "center", marginTop: 6 }}>
        <Btn kind="link" title={t("footer.privacy")} onPress={() => router.push("/privacy")} />
        {config.payments_enabled ? <Btn kind="link" title={t("footer.pricing")} onPress={() => open("pricing")} /> : null}
        <Btn kind="link" title={t("footer.terms")} onPress={() => open("terms")} />
        {config.payments_enabled ? <Btn kind="link" title={t("footer.refunds")} onPress={() => open("refunds")} /> : null}
        <Btn kind="link" title={t("footer.contact")} onPress={() => open("contact")} />
      </Row>
      <Txt kind="small" style={{ textAlign: "center" }}>{t("footer.legal")}</Txt>

      <PaySheet order={order} description={file?.name || "Contract check"} onDone={payment => { setOrder(null); if (payment) start(payment); else setError(t("pay.cancelled")); }} />
    </Screen>
  );
}
