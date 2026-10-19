/** Backward-compatible entry point for isolated prompt draft/browser regressions.
 * The full suite now uses the real app router with an entirely mocked current
 * catalog; it never fetches the retired setup_interview prompt or a live backend.
 * Preserved checks: local drafts across template/tab/reload, pending-save locks,
 * late old saves preserving newer drafts, call-dialog focus/Escape restoration.
 * Run: node tests/prompt-drafts.browser.mjs
 * Optional: ZHIBI_CHROMIUM / PLAYWRIGHT_CHROMIUM_EXECUTABLE, PROMPTS_TEST_PORT.
 */
await import('./prompts-workspace.browser.mjs')
