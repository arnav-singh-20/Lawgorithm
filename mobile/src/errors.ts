// Turn an API error into words for the person.
export function errorText(err: unknown, t: (k: string) => string) {
  const msg = err instanceof Error ? err.message : "";
  return msg === "network" ? t("err.network") : msg && msg !== "generic" ? msg : t("err.generic");
}
