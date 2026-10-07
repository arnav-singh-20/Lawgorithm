// The app talks to the same server as the website. Override for local
// testing with: EXPO_PUBLIC_API_URL=http://<your-computer-ip>:8000 npx expo start
export const API_BASE = (process.env.EXPO_PUBLIC_API_URL || "https://arnavsingh18-lawgorithm.hf.space").replace(/\/$/, "");

// Pages that live on the website (opened in the in-app browser).
export const siteUrl = (route: string) => `${API_BASE}/#/${route}`;

export const POLL_MS = 1500;
