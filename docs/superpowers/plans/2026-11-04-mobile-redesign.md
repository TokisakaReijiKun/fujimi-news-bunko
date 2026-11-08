# Android mobile redesign implementation plan

**Goal:** Ship a signed, upgrade-compatible Android APK implementing the approved mobile Demo 2.46.

**Architecture:** Keep the existing WebView, verified file library, dictionary and Media3 playback. Move the approved app shell into formal `static/mobile-*` resources; activate it only for the Android bridge or the explicit browser QA flag. Remove all preview memory writes and connect actions to persistent Android APIs.

**Tech stack:** Existing vanilla JavaScript/CSS, Kotlin Android/core modules, Gradle, Android instrumentation.

**Design reference:** `tests/mobile-japanese-design/` Demo 2.46 and the accepted changes in this conversation.

- [x] Move the approved shell and reading styles into formal assets; preserve the original desktop interface and dictionary implementation.
- [x] Connect daily tasks, Android pairing/sync, settings and reference audio. No demo endpoints, simulated save responses or PC-only QR panel in the phone app.
- [x] Implement persistent article bookmarks, ebook progress and ebook bookmarks using the existing verified file stores and transaction boundaries.
- [x] Enforce source minimum totals at or below the article target in both editing directions and test concurrent/invalid updates.
- [x] Verify the shell and readers at 375/390px, navigation/back behavior, settings persistence and real reference audio. Use isolated test data.
- [x] Build debug/instrumentation artifacts for a dedicated QA emulator, then build the signed release, verify certificate/version/assets and deliver the APK.

Version: application ID and signing certificate remain unchanged; release `1.1.0`, version code `23`. Existing rollback content is retained outside the explicit new mobile resources. Do not modify or bundle the user's library or keys. The Android platform's existing limitations on local model synthesis and standalone EPUB import remain accurately represented.
