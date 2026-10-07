// The Lawgorithm server API (same endpoints the website uses).
import { API_BASE } from "./config";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function api<T = any>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + path, options);
  } catch {
    throw new ApiError("network", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(typeof body.detail === "string" ? body.detail : "generic", res.status);
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export type PickedFile = { uri: string; name: string; mimeType?: string; webFile?: File };
export type Payment = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string };

export function getConfig() { return api("/config"); }

export function startAnalysis(file: PickedFile, documentType: string, payment?: Payment | null) {
  const form = new FormData();
  // React Native uploads a local file from {uri, name, type}; on web we have a real File.
  form.append("file", (file.webFile ?? { uri: file.uri, name: file.name, type: file.mimeType || "application/octet-stream" }) as any, file.name);
  form.append("document_type", documentType);
  form.append("consent", "true");          // DPDP: the box was ticked
  if (payment) Object.entries(payment).forEach(([k, v]) => form.append(k, v));
  return api<{ job_id: string }>("/analyze-document/start", { method: "POST", body: form });
}

export const getJob = (id: string) => api(`/jobs/${id}`);
export const deleteDocument = (id: string) => api(`/document/${id}`, { method: "DELETE" });
export const deleteJob = (id: string) => api(`/jobs/${id}`, { method: "DELETE" });
export const createOrder = (purpose: "analysis" | "expert") => api("/payments/order", json({ purpose }));
export const translate = (text: string, target: string) =>
  api("/translate", json({ text, target_language: target, validate_translation: true }));
export const sendForReview = (documentId: string, clauseRowIds: string[], payment?: Payment | null) =>
  api("/expert-review", json({ document_id: documentId, clause_row_ids: clauseRowIds, consent: true, ...(payment || {}) }));
export const getTicket = (id: string) => api(`/expert-review/${id}`);
export const deleteTicket = (id: string) => api(`/expert-review/${id}`, { method: "DELETE" });
export const sampleText = (type: "rental" | "employment") =>
  fetch(`${API_BASE}/static/samples/${type}.txt`).then(r => { if (!r.ok) throw new ApiError("network", r.status); return r.text(); });
