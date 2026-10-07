// The primary logo ("Primary logo — light-html"): scales mark + wordmark.
import React from "react";
import { Text, View } from "react-native";
import Svg, { Circle, G, Line, Path } from "react-native-svg";

import { useTheme } from "../theme";

export function LogoMark({ size = 30, ink, accent }: { size?: number; ink?: string; accent?: string }) {
  const t = useTheme();
  const i = ink ?? t.logoInk;
  return (
    <Svg width={size} height={size} viewBox="0 0 120 120">
      <G stroke={i} strokeWidth={7} strokeLinecap="round" fill="none">
        <Line x1="60" y1="30" x2="60" y2="98" />
        <Line x1="42" y1="100" x2="78" y2="100" />
        <Line x1="24" y1="42" x2="96" y2="42" />
        <Line x1="24" y1="42" x2="24" y2="62" />
        <Line x1="96" y1="42" x2="96" y2="62" />
      </G>
      <Circle cx="60" cy="20" r="9" fill={i} />
      <Path d="M8 64 A16 16 0 0 0 40 64 Z" fill={i} />
      <Path d="M80 64 A16 16 0 0 0 112 64 Z" fill={accent ?? t.logoAccent} />
    </Svg>
  );
}

export function Logo({ size = 22 }: { size?: number }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }} accessibilityRole="header" accessibilityLabel="Lawgorithm">
      <LogoMark size={size * 1.35} />
      <Text style={{ fontFamily: "SpaceGrotesk_400Regular", fontSize: size, color: t.logoInk, letterSpacing: -0.6 }}>
        <Text style={{ fontFamily: "SpaceGrotesk_700Bold" }}>law</Text>gorithm
      </Text>
    </View>
  );
}
