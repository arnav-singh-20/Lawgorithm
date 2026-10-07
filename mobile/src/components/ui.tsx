// Small shared building blocks, styled like the website.
import React from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextProps, View, ViewStyle } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { DECISION_ICON } from "../decisions";
import { useI18n } from "../i18n";
import { decisionColor, fonts, radius, riskColor, useTheme } from "../theme";

export function Screen({ children, scroll = true }: { children: React.ReactNode; scroll?: boolean }) {
  const t = useTheme();
  const body = scroll
    ? <ScrollView contentContainerStyle={{ padding: 18, paddingBottom: 48, gap: 16 }} keyboardShouldPersistTaps="handled">{children}</ScrollView>
    : <View style={{ flex: 1, padding: 18, gap: 16 }}>{children}</View>;
  return <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }} edges={["top", "left", "right"]}>{body}</SafeAreaView>;
}

type TxtProps = TextProps & { kind?: "body" | "soft" | "title" | "display" | "label" | "strong" | "small"; color?: string };
export function Txt({ kind = "body", color, style, ...rest }: TxtProps) {
  const t = useTheme();
  const base: Record<string, object> = {
    body: { fontFamily: fonts.body, fontSize: 15.5, lineHeight: 23, color: t.text },
    soft: { fontFamily: fonts.body, fontSize: 14.5, lineHeight: 21, color: t.soft },
    small: { fontFamily: fonts.body, fontSize: 12.5, lineHeight: 18, color: t.soft },
    strong: { fontFamily: fonts.bold, fontSize: 15.5, lineHeight: 22, color: t.text },
    title: { fontFamily: fonts.display, fontSize: 21, lineHeight: 27, color: t.text },
    display: { fontFamily: fonts.display, fontSize: 34, lineHeight: 39, letterSpacing: -0.8, color: t.text },
    label: { fontFamily: fonts.medium, fontSize: 11, letterSpacing: 1.4, textTransform: "uppercase", color: t.faint },
  };
  return <Text {...rest} style={[base[kind], color ? { color } : null, style]} />;
}

export function Card({ children, style, accent }: { children: React.ReactNode; style?: ViewStyle; accent?: string }) {
  const t = useTheme();
  return (
    <View style={[{ backgroundColor: t.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: t.line, padding: 16, gap: 10 },
      accent ? { borderLeftWidth: 4, borderLeftColor: accent } : null, style]}>
      {children}
    </View>
  );
}

export function Btn({ title, onPress, kind = "ink", disabled, busy, icon, small }: {
  title: string; onPress: () => void; kind?: "ink" | "outline" | "link"; disabled?: boolean; busy?: boolean; icon?: string; small?: boolean;
}) {
  const t = useTheme();
  if (kind === "link") {
    return (
      <Pressable onPress={onPress} disabled={disabled} accessibilityRole="link" hitSlop={8}>
        <Text style={{ fontFamily: fonts.medium, fontSize: 14.5, color: t.text, textDecorationLine: "underline", textDecorationColor: t.accent }}>{title}</Text>
      </Pressable>
    );
  }
  const ink = kind === "ink";
  return (
    <Pressable onPress={onPress} disabled={disabled || busy} accessibilityRole="button" accessibilityState={{ disabled: !!(disabled || busy) }}
      style={({ pressed }) => [{
        minHeight: small ? 40 : 52, paddingHorizontal: small ? 14 : 20, borderRadius: radius.pill, alignItems: "center", justifyContent: "center",
        flexDirection: "row", gap: 8, backgroundColor: ink ? t.btn : "transparent", borderWidth: ink ? 0 : 1.5, borderColor: t.text,
        opacity: disabled ? 0.45 : pressed ? 0.85 : 1,
      }]}>
      {busy ? <ActivityIndicator color={ink ? t.btnText : t.text} /> : null}
      {icon ? <Text style={{ fontSize: small ? 14 : 16 }}>{icon}</Text> : null}
      <Text style={{ fontFamily: fonts.bold, fontSize: small ? 14 : 16, color: ink ? t.btnText : t.text }}>{title}</Text>
    </Pressable>
  );
}

export function RiskPill({ level }: { level?: string }) {
  const t = useTheme();
  const { t: tr } = useI18n();
  const c = riskColor(t, level);
  const emoji = level === "red" ? "🚩" : level === "amber" ? "⚠️" : "✅";
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill, backgroundColor: c.bg }}>
      <Text style={{ fontSize: 12 }}>{emoji}</Text>
      <Text style={{ fontFamily: fonts.bold, fontSize: 12.5, color: c.fg }}>{tr(`risk.${level || "amber"}`)}</Text>
    </View>
  );
}

export function Chip({ text, tone }: { text: string; tone?: "flag" }) {
  const t = useTheme();
  return (
    <View style={{ paddingHorizontal: 9, paddingVertical: 3, borderRadius: radius.pill, borderWidth: 1,
      borderColor: tone === "flag" ? t.amber : t.line, backgroundColor: tone === "flag" ? t.amberSoft : "transparent" }}>
      <Text style={{ fontFamily: fonts.medium, fontSize: 12, color: tone === "flag" ? t.amber : t.soft }}>{text}</Text>
    </View>
  );
}

export function DecisionBox({ decision, title, children }: { decision: string; title: string; children?: React.ReactNode }) {
  const t = useTheme();
  const c = decisionColor(t, decision);
  return (
    <View style={{ flexDirection: "row", gap: 10, padding: 12, borderRadius: radius.md, backgroundColor: c.bg, borderWidth: 1, borderColor: c.fg + "55" }}>
      <Text style={{ fontSize: 20 }}>{DECISION_ICON[decision] || "🧑‍⚖️"}</Text>
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={{ fontFamily: fonts.bold, fontSize: 15, color: c.fg }}>{title}</Text>
        {children}
      </View>
    </View>
  );
}

export function ErrorBanner({ text }: { text: string }) {
  const t = useTheme();
  return (
    <View style={{ padding: 12, borderRadius: radius.md, backgroundColor: t.redSoft, borderWidth: 1, borderColor: t.red + "66" }} accessibilityRole="alert">
      <Text style={{ fontFamily: fonts.body, fontSize: 14.5, lineHeight: 21, color: t.text }}>{text}</Text>
    </View>
  );
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[styles.row, style]}>{children}</View>;
}

const styles = StyleSheet.create({ row: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 8 } });
