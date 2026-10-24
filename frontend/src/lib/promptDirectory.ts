export const PROMPT_DIRECTORY_STORAGE_KEY = 'zhibi:prompt-directory:collapsed'
export type CollapsedPromptGroups = Record<string, boolean>

export function readCollapsedPromptGroups(): CollapsedPromptGroups {
  const defaults: CollapsedPromptGroups = { '拆书': true, '拆书精髓': true }
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(PROMPT_DIRECTORY_STORAGE_KEY) ?? 'null')
    if (stored && typeof stored === 'object' && !Array.isArray(stored)) {
      for (const [group, collapsed] of Object.entries(stored)) {
        if (typeof collapsed === 'boolean') defaults[group] = collapsed
      }
    }
  } catch { /* Use defaults if local storage is unavailable or malformed. */ }
  return defaults
}

export function writeCollapsedPromptGroups(groups: CollapsedPromptGroups): void {
  try { localStorage.setItem(PROMPT_DIRECTORY_STORAGE_KEY, JSON.stringify(groups)) } catch { /* Current-page toggles still work without storage. */ }
}
