// Privacy notice (DPDP Act, 2023) -- the same text as the website.
import { router } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import React from "react";
import { View } from "react-native";

import { useAppState } from "../appState";
import { Btn, Card, Screen, Txt } from "../components/ui";
import { useI18n } from "../i18n";

export default function Privacy() {
  const { t } = useI18n();
  const { config: c } = useAppState();
  const vars = {
    service: c.ai_service || "", minutes: c.retention_minutes, contact: c.privacy_contact || t("privacy.noContact"),
    keep: c.expert_review_keep_days, max: c.expert_review_max_days,
  };
  const items = [1, 2, 3, 4, 5, 9, 6, 7, 8].filter(n => n !== 9 || c.expert_review_enabled);
  return (
    <Screen>
      <Btn kind="link" title={`← ${t("privacy.back")}`} onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} />
      <Txt kind="label">{t("privacy.eyebrow")}</Txt>
      <Txt kind="display">{t("privacy.title")}</Txt>
      {items.map((n, i) => {
        const key = n === 9 && c.reviewer_kind !== "legal" ? "privacy.p9.d.team" : `privacy.p${n}.d`;
        const body = n === 3 && !c.ai_service ? t("privacy.p3.local") : t(key, vars);
        return (
          <Card key={n}>
            <Txt kind="strong">{i + 1}. {t(`privacy.p${n}.t`)}</Txt>
            <Txt kind="soft">{body}</Txt>
            {n === 7 && c.dpdp_act_url ? (
              <View><Btn kind="link" title={`${t("privacy.p7.link")} ↗`} onPress={() => WebBrowser.openBrowserAsync(c.dpdp_act_url!).catch(() => {})} /></View>
            ) : null}
          </Card>
        );
      })}
    </Screen>
  );
}
