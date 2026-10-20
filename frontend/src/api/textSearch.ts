import { api } from './client'

export interface TextSearchResult {
  word: string
  chapters: number
  results: { index: number; title: string; times: number; near: string }[]
}

export function searchBookText(bookId: string, word: string, signal?: AbortSignal): Promise<TextSearchResult> {
  return api<TextSearchResult>(`/books/${encodeURIComponent(bookId)}/search?q=${encodeURIComponent(word)}`, { signal })
}
