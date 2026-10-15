/** Unsaved template edits survive navigation; sessionStorage never crosses browser sessions. */
const memory = new Map<string, string | null>()
const key = (name: string) => `zhibi:prompt-draft:${name}`

export function readPromptDraft(name: string): string | null {
  if (memory.has(name)) return memory.get(name) ?? null
  let content: string | null = null
  try { content = sessionStorage.getItem(key(name)) } catch { /* Memory-only fallback when storage is disabled. */ }
  memory.set(name, content)
  return content
}

export function writePromptDraft(name: string, content: string | null): void {
  memory.set(name, content)
  try {
    if (content === null) sessionStorage.removeItem(key(name))
    else sessionStorage.setItem(key(name), content)
  } catch { /* Keep the in-memory copy even if storage is blocked or full. */ }
}
