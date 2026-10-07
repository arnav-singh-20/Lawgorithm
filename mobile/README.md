# Lawgorithm app (Android + iPhone)

*Your Rights in Your Language.* The mobile app for Lawgorithm, built with
Expo (React Native, SDK 57). It talks to the same server as the website
(`https://arnavsingh18-lawgorithm.hf.space`), so analysis, translation,
privacy, expert review and payments behave exactly like the site.

## Try it on your phone (no Android Studio / Xcode needed)

1. Install **Expo Go** from the Play Store / App Store.
2. On this Mac:
   ```
   cd mobile
   npx expo start
   ```
3. Scan the QR code (Android: in Expo Go; iPhone: with the Camera app).
   The phone and the Mac must be on the same Wi-Fi -- if not, use
   `npx expo start --tunnel`.

## Build an installable app (in the cloud, free tier)

```
npx eas-cli@latest login                                   # your Expo account
npx eas-cli@latest build -p android --profile preview      # -> a downloadable .apk
npx eas-cli@latest build -p android --profile production   # -> .aab for the Play Store
npx eas-cli@latest build -p ios --profile production       # needs an Apple Developer account
```

The app id is `com.lawgorithm.app` (app.json) -- change it before the first
store upload if you want a different one; it can't change afterwards.

## What's inside

| Screen | File |
|---|---|
| Language picker (first launch) | `src/app/language.tsx` |
| Home: file / photo / sample, consent, pay, start | `src/app/index.tsx` |
| Progress (polls the job) | `src/app/job/[id].tsx` |
| Results: decision, summary, action plan, clauses, expert check | `src/app/document/[id].tsx` |
| Your expert check (private) | `src/app/expert/[id].tsx` |
| Privacy notice (DPDP Act, 2023) | `src/app/privacy.tsx` |

- **Text**: every string comes from the website (`frontend/i18n.js`). After
  changing website text run `npm run sync-strings`. App-only phrases:
  `src/appStrings.ts`.
- **Payments**: Razorpay's own checkout in a secure web view
  (`src/payments.tsx`); UPI apps open outside it. The server verifies every
  payment.
- **Decisions** mirror `backend/risk/decision.py` (`src/decisions.ts`).
- **Server**: `src/config.ts`. Point at a local backend with
  `EXPO_PUBLIC_API_URL=http://<mac-ip>:8000 npx expo start`.

Checks: `npm run typecheck` and `npx expo-doctor`.
