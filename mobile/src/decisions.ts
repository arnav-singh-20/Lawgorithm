// Mirrors backend/risk/decision.py (the server normally sends `decision`).
export const DECISION_ORDER = ["lawyer", "expert", "negotiate", "no_lawyer"] as const;
export const DECISION_ICON: Record<string, string> = { lawyer: "⚖️", expert: "🧑‍⚖️", negotiate: "🤝", no_lawyer: "✅" };

export function clauseDecision(c: any): string {
  if (c.decision) return c.decision;
  const flags: string[] = c.review_flags || [];
  if (c.risk_level === "green") return flags.includes("skipped_legal_check") ? "expert" : "no_lawyer";
  const confirmed = c.verification_status === "human_verified" ||
    (["grounded", "partially_grounded"].includes(c.status) && c.citation_valid !== false && !flags.length);
  if (!confirmed) return "expert";
  return c.risk_level === "red" ? "lawyer" : "negotiate";
}

export function documentDecision(doc: any) {
  const counts: Record<string, number> = { lawyer: 0, expert: 0, negotiate: 0, no_lawyer: 0 };
  (doc.clauses || []).forEach((c: any) => { counts[clauseDecision(c)] += 1; });
  const decision = (["lawyer", "expert", "negotiate"] as const).find(d => counts[d]) || "sign";
  return { decision, counts };
}

// The human-in-the-loop answer, one English sentence so it translates whole.
export const importantSentence = (consequence?: string) => consequence
  ? `This clause is important. If you don’t fix it, ${consequence}. For more detail, talk to a lawyer.` : "";

export const needsHuman = (d: string) => d === "lawyer" || d === "expert";

export const titleCase = (s = "") => s.toLowerCase().replace(/(^|\s|[-/(])([a-zÀ-ɏ])/g, (_, p, c) => p + c.toUpperCase());

// Every "what to do" in one list, red first.
export function planItems(doc: any) {
  const order: Record<string, number> = { red: 0, amber: 1, green: 2 };
  return (doc.clauses || [])
    .filter((c: any) => c.recommended_action && c.risk_level !== "green")
    .sort((a: any, b: any) => order[a.risk_level] - order[b.risk_level])
    .map((c: any) => ({ level: c.risk_level, title: titleCase(c.clause_title), action: c.recommended_action }));
}
