// Same palette as the website (frontend/style.css), light and dark.
import { useColorScheme } from "react-native";

const light = {
  bg: "#fff9f1", surface: "#fffdf8", raised: "#f1ead6", sunk: "#f6f0e2",
  text: "#0b0b0c", soft: "#57534a", faint: "#8a8578", line: "rgba(11,11,12,0.12)",
  accent: "#fc9073", gold: "#ffd43f", btn: "#0b0b0c", btnText: "#fff9f1",
  red: "#e2462e", redSoft: "#fde3da", amber: "#b77f00", amberSoft: "#fff1c4", green: "#2f8f5b", greenSoft: "#dcf0e2",
  expert: "#5b5bd6", expertSoft: "rgba(91,91,214,0.12)", logoInk: "#1B1F3B", logoAccent: "#E8962E",
};

const dark: typeof light = {
  bg: "#0c0c10", surface: "#15151b", raised: "#1e1e26", sunk: "#101015",
  text: "#f6f1e7", soft: "#b9b3a6", faint: "#8a8578", line: "rgba(246,241,231,0.14)",
  accent: "#fc9073", gold: "#ffd43f", btn: "#fff9f1", btnText: "#0b0b0c",
  red: "#ff8a6b", redSoft: "rgba(226,70,46,0.18)", amber: "#f2c14e", amberSoft: "rgba(242,193,78,0.16)",
  green: "#5fd39a", greenSoft: "rgba(95,211,154,0.14)",
  expert: "#a5a6ff", expertSoft: "rgba(165,166,255,0.12)", logoInk: "#F7F4EE", logoAccent: "#E8962E",
};

export type Theme = typeof light;

export function useTheme(): Theme {
  return useColorScheme() === "dark" ? dark : light;
}

export const fonts = {
  display: "Fraunces_600SemiBold",
  displayItalic: "Fraunces_500Medium_Italic",
  body: "SpaceGrotesk_400Regular",
  medium: "SpaceGrotesk_500Medium",
  bold: "SpaceGrotesk_700Bold",
};

export const radius = { lg: 20, md: 14, pill: 999 };

export const riskColor = (t: Theme, level?: string) =>
  level === "red" ? { fg: t.red, bg: t.redSoft } : level === "amber" ? { fg: t.amber, bg: t.amberSoft } : { fg: t.green, bg: t.greenSoft };

export const decisionColor = (t: Theme, d: string) =>
  d === "lawyer" ? { fg: t.red, bg: t.redSoft } : d === "negotiate" ? { fg: t.amber, bg: t.amberSoft }
    : d === "expert" ? { fg: t.expert, bg: t.expertSoft } : { fg: t.green, bg: t.greenSoft };
