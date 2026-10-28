import type { HandbookFields } from '../api/handbooks.ts'

const memory = new Map<string, HandbookFields | null>()
const storageKey = (key: string) => `zhibi:handbook-draft:${key}`

export function readHandbookDraft(key: string): HandbookFields | null {
  if (memory.has(key)) return memory.get(key) ?? null
  let draft: HandbookFields | null = null
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(storageKey(key)) ?? 'null')
    if (stored && typeof stored === 'object' && 'name' in stored && 'when' in stored && 'body' in stored
      && typeof stored.name === 'string' && typeof stored.when === 'string' && typeof stored.body === 'string') {
      draft = { name: stored.name, when: stored.when, body: stored.body }
    }
  } catch { /* Storage disabled, full or invalid: do not block editing. */ }
  memory.set(key, draft)
  return draft
}

export function writeHandbookDraft(key: string, fields: HandbookFields | null): void {
  const copy = fields ? { name: fields.name, when: fields.when, body: fields.body } : null
  memory.set(key, copy)
  try {
    if (copy) sessionStorage.setItem(storageKey(key), JSON.stringify(copy))
    else sessionStorage.removeItem(storageKey(key))
  } catch { /* Retain the in-memory draft if browser storage is unavailable. */ }
}

export function handbookDraftChanged(left: HandbookFields, right: HandbookFields): boolean {
  return left.name !== right.name || left.when !== right.when || left.body !== right.body
}

/** A completed request may only clear the browser draft it started with. */
export function clearHandbookDraftIfUnchanged(key: string, expected: HandbookFields | null): boolean {
  const current = readHandbookDraft(key)
  if (expected === null ? current !== null : current === null || handbookDraftChanged(current, expected)) return false
  writeHandbookDraft(key, null)
  return true
}
