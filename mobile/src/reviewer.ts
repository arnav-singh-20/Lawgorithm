// Reviewer desk: the reviewer's key lives in the phone's secure storage
// (Keychain / Keystore). The web preview has no secure storage, so it falls
// back to the browser's local storage, like the website does.
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { api } from "./api";
import { API_BASE } from "./config";

const KEY = "lawgorithm.reviewerKey";

export async function getReviewerKey(): Promise<string | null> {
  try {
    return Platform.OS === "web" ? await AsyncStorage.getItem(KEY) : await SecureStore.getItemAsync(KEY);
  } catch { return null; }
}

export async function setReviewerKey(value: string) {
  if (Platform.OS === "web") await AsyncStorage.setItem(KEY, value);
  else await SecureStore.setItemAsync(KEY, value);
}

export async function clearReviewerKey() {
  try {
    if (Platform.OS === "web") await AsyncStorage.removeItem(KEY);
    else await SecureStore.deleteItemAsync(KEY);
  } catch { /* nothing stored */ }
}

const headers = (key: string, json = false): Record<string, string> =>
  ({ "X-Reviewer-Key": key, ...(json ? { "Content-Type": "application/json" } : {}) });

export const reviewerQueue = (key: string) => api("/expert-review/reviewer/queue", { headers: headers(key) });
export const submitReview = (key: string, ticketId: string, clauseRowId: string, body: object) =>
  api(`/expert-review/${ticketId}/clauses/${clauseRowId}`, { method: "POST", headers: headers(key, true), body: JSON.stringify(body) });
export const listReviewers = (key: string) => api("/expert-review/reviewers", { headers: headers(key) });
export const addReviewer = (key: string, name: string) =>
  api("/expert-review/reviewers", { method: "POST", headers: headers(key, true), body: JSON.stringify({ name }) });
export const removeReviewer = (key: string, id: string) => api(`/expert-review/reviewers/${id}`, { method: "DELETE", headers: headers(key) });
export const listMessages = (key: string) => api("/contact/messages", { headers: headers(key) });
export const deleteMessage = (key: string, id: string) => api(`/contact/messages/${id}`, { method: "DELETE", headers: headers(key) });

// Invite links open the website's reviewer page, which works for everyone
// (with or without the app); the app accepts the same ?invite= key.
export const inviteLink = (key: string) => `${API_BASE}/#/review?invite=${key}`;
