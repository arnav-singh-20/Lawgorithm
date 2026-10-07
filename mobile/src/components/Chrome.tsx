// The app's frame: header (menu · logo · language), footer and the sidebar.
// Self-contained (plain Text) so ui.tsx can use it without an import cycle.
import { router } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Animated, Dimensions, Modal, Pressable, ScrollView, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAppState } from "../appState";
import { siteUrl } from "../config";
import { useI18n } from "../i18n";
import { fonts, radius, useTheme } from "../theme";
import { LogoMark, Logo } from "./Logo";

// ── sidebar state ──
const DrawerCtx = createContext<{ open: () => void }>({ open: () => {} });
export const useDrawer = () => useContext(DrawerCtx);

export function DrawerProvider({ children }: { children: React.ReactNode }) {
  const [visible, setVisible] = useState(false);
  const open = useCallback(() => setVisible(true), []);
  return (
    <DrawerCtx.Provider value={{ open }}>
      {children}
      <Sidebar visible={visible} onClose={() => setVisible(false)} />
    </DrawerCtx.Provider>
  );
}

const openSite = (route: string) => WebBrowser.openBrowserAsync(siteUrl(route)).catch(() => {});

// ── header ──
export function AppHeader() {
  const t = useTheme();
  const { meta, t: tr } = useI18n();
  const { open } = useDrawer();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, paddingVertical: 8,
      borderBottomWidth: 1, borderBottomColor: t.line, backgroundColor: t.bg }}>
      <Pressable onPress={open} hitSlop={10} accessibilityRole="button" accessibilityLabel="Menu"
        style={{ width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: t.line }}>
        <Text style={{ fontSize: 18, color: t.text }}>☰</Text>
      </Pressable>
      <Pressable onPress={() => router.replace("/")} accessibilityRole="link" accessibilityLabel="Lawgorithm home" style={{ flex: 1 }}>
        <Logo size={20} />
      </Pressable>
      <Pressable onPress={() => router.push("/language")} accessibilityRole="button" accessibilityLabel={tr("app.language")}
        style={{ flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 11, height: 36, borderRadius: radius.pill, borderWidth: 1, borderColor: t.line }}>
        <Text style={{ fontSize: 13 }}>🌐</Text>
        <Text style={{ fontFamily: fonts.medium, fontSize: 13.5, color: t.text }}>{meta.native}</Text>
      </Pressable>
    </View>
  );
}

// ── footer ──
export function AppFooter() {
  const t = useTheme();
  const { t: tr } = useI18n();
  const { config } = useAppState();
  const link = (label: string, onPress: () => void) => (
    <Pressable key={label} onPress={onPress} hitSlop={6} accessibilityRole="link">
      <Text style={{ fontFamily: fonts.medium, fontSize: 13.5, color: t.soft }}>{label}</Text>
    </Pressable>
  );
  return (
    <View style={{ marginTop: 18, paddingTop: 20, borderTopWidth: 1, borderTopColor: t.line, gap: 12 }}>
      <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
        <LogoMark size={26} />
        <Text style={{ fontFamily: fonts.displayItalic, fontSize: 17, color: t.text, flex: 1 }}>{tr("tagline")}</Text>
      </View>
      <Text style={{ fontFamily: fonts.medium, fontSize: 11, letterSpacing: 1.2, color: t.faint }}>{tr("footer.made").toUpperCase()}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: 16, rowGap: 8 }}>
        {link(tr("footer.privacy"), () => router.push("/privacy"))}
        {config.payments_enabled ? link(tr("footer.pricing"), () => openSite("pricing")) : null}
        {link(tr("footer.terms"), () => openSite("terms"))}
        {config.payments_enabled ? link(tr("footer.refunds"), () => openSite("refunds")) : null}
        {link(tr("footer.contact"), () => router.push("/contact"))}
        {config.expert_review_enabled ? link(tr("footer.reviewers"), () => router.push("/review")) : null}
      </View>
      <Text style={{ fontFamily: fonts.body, fontSize: 12, lineHeight: 17, color: t.faint }}>{tr("footer.legal")}</Text>
    </View>
  );
}

// ── sidebar ──
function Sidebar({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const t = useTheme();
  const { t: tr, meta } = useI18n();
  const { config, checks } = useAppState();
  const insets = useSafeAreaInsets();
  const width = Math.min(320, Dimensions.get("window").width * 0.84);
  const slide = useRef(new Animated.Value(-width)).current;
  const [mounted, setMounted] = useState(visible);

  useEffect(() => {
    if (visible) setMounted(true);
    Animated.timing(slide, { toValue: visible ? 0 : -width, duration: 220, useNativeDriver: false })
      .start(() => { if (!visible) setMounted(false); });
  }, [visible, slide, width]);

  if (!mounted) return null;
  const go = (fn: () => void) => { onClose(); setTimeout(fn, 160); };
  const item = (icon: string, label: string, onPress: () => void, sub?: string) => (
    <Pressable key={label} onPress={() => go(onPress)} accessibilityRole="menuitem"
      style={({ pressed }) => ({ flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12, paddingHorizontal: 12,
        borderRadius: radius.md, backgroundColor: pressed ? t.raised : "transparent" })}>
      <Text style={{ fontSize: 18, width: 24, textAlign: "center" }}>{icon}</Text>
      <View style={{ flex: 1 }}>
        <Text style={{ fontFamily: fonts.medium, fontSize: 15.5, color: t.text }}>{label}</Text>
        {sub ? <Text style={{ fontFamily: fonts.body, fontSize: 12, color: t.faint }} numberOfLines={1}>{sub}</Text> : null}
      </View>
    </Pressable>
  );
  const section = (label: string) => (
    <Text style={{ fontFamily: fonts.medium, fontSize: 11, letterSpacing: 1.3, color: t.faint, marginTop: 14, marginBottom: 2, paddingHorizontal: 12 }}>
      {label.toUpperCase()}</Text>
  );

  return (
    <Modal transparent visible animationType="none" onRequestClose={onClose}>
      <Pressable onPress={onClose} accessibilityLabel="Close menu" style={{ flex: 1, backgroundColor: "rgba(0,0,0,0.45)" }} />
      <Animated.View style={{ position: "absolute", top: 0, bottom: 0, left: slide, width, backgroundColor: t.bg,
        paddingTop: insets.top + 12, paddingBottom: insets.bottom + 12, borderRightWidth: 1, borderRightColor: t.line }}>
        <ScrollView contentContainerStyle={{ paddingHorizontal: 12, paddingBottom: 24 }}>
          <View style={{ paddingHorizontal: 12, paddingBottom: 12, gap: 6 }}>
            <Logo size={22} />
            <Text style={{ fontFamily: fonts.displayItalic, fontSize: 16, color: t.accent }}>{tr("tagline")}</Text>
          </View>
          {item("📄", tr("nav.analyse"), () => router.replace("/"))}
          {checks.length ? section(tr("app.myChecks")) : null}
          {checks.map(c => item("🧑‍⚖️", c.filename || tr("expert.view"), () => router.push(`/expert/${c.id}`)))}
          {section(tr("app.links"))}
          {config.expert_review_enabled ? item("⚖️", tr("nav.review"), () => router.push("/review")) : null}
          {item("🔒", tr("footer.privacy"), () => router.push("/privacy"))}
          {config.payments_enabled ? item("₹", tr("footer.pricing"), () => openSite("pricing")) : null}
          {item("📜", tr("footer.terms"), () => openSite("terms"))}
          {config.payments_enabled ? item("↺", tr("footer.refunds"), () => openSite("refunds")) : null}
          {item("✉️", tr("footer.contact"), () => router.push("/contact"))}
          {item("🌐", tr("app.language"), () => router.push("/language"), meta.native)}
          <Text style={{ fontFamily: fonts.body, fontSize: 12, lineHeight: 17, color: t.faint, marginTop: 18, paddingHorizontal: 12 }}>
            {tr("footer.legal")}</Text>
        </ScrollView>
      </Animated.View>
    </Modal>
  );
}
