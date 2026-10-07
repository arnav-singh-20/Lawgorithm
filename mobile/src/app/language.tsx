// First launch (and from the globe button): choose the language.
import { router } from "expo-router";
import React from "react";
import { Pressable, Text, View } from "react-native";

import { Screen, Txt } from "../components/ui";
import { LANGUAGES, useI18n } from "../i18n";
import { fonts, radius, useTheme } from "../theme";

export default function LanguageScreen() {
  const t = useTheme();
  const { lang, setLang, t: tr } = useI18n();
  const choose = (code: string) => {
    setLang(code);
    if (router.canGoBack()) router.back();
    else router.replace("/");
  };
  return (
    <Screen>
      <Txt kind="label">Language · भाषा · மொழி · ভাষা</Txt>
      <Txt kind="display" style={{ fontStyle: "italic", fontFamily: fonts.displayItalic, color: t.accent, fontSize: 22, lineHeight: 28 }}>
        {tr("tagline")}
      </Txt>
      <Txt kind="display">Choose your language</Txt>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 10 }}>
        {LANGUAGES.map(l => {
          const active = l.code === lang;
          return (
            <Pressable key={l.code} onPress={() => choose(l.code)} accessibilityRole="button" accessibilityState={{ selected: active }}
              style={({ pressed }) => ({
                width: "47%", padding: 16, borderRadius: radius.md, borderWidth: active ? 2 : 1,
                borderColor: active ? t.text : t.line, backgroundColor: active ? t.raised : t.surface, opacity: pressed ? 0.8 : 1,
              })}>
              <Text style={{ fontFamily: fonts.display, fontSize: 22, color: t.text }}>{l.native}</Text>
              <Text style={{ fontFamily: fonts.medium, fontSize: 11, letterSpacing: 1.2, color: t.faint, marginTop: 2 }}>{l.english.toUpperCase()}</Text>
            </Pressable>
          );
        })}
      </View>
    </Screen>
  );
}
