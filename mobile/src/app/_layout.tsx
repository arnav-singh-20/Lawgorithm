import { Fraunces_500Medium_Italic, Fraunces_600SemiBold } from "@expo-google-fonts/fraunces";
import { SpaceGrotesk_400Regular, SpaceGrotesk_500Medium, SpaceGrotesk_700Bold } from "@expo-google-fonts/space-grotesk";
import { useFonts } from "expo-font";
import { Stack } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import React, { useEffect } from "react";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider } from "../appState";
import { I18nProvider, useI18n } from "../i18n";
import { useTheme } from "../theme";

SplashScreen.preventAutoHideAsync().catch(() => {});

function Root() {
  const theme = useTheme();
  const { ready } = useI18n();
  const [fontsLoaded] = useFonts({
    Fraunces_600SemiBold, Fraunces_500Medium_Italic, SpaceGrotesk_400Regular, SpaceGrotesk_500Medium, SpaceGrotesk_700Bold,
  });
  const loaded = ready && fontsLoaded;
  useEffect(() => { if (loaded) SplashScreen.hideAsync().catch(() => {}); }, [loaded]);
  if (!loaded) return null;
  return (
    <>
      <StatusBar style="auto" />
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: theme.bg }, animation: "slide_from_right" }} />
    </>
  );
}

export default function Layout() {
  return (
    <SafeAreaProvider>
      <I18nProvider>
        <AppStateProvider>
          <Root />
        </AppStateProvider>
      </I18nProvider>
    </SafeAreaProvider>
  );
}
