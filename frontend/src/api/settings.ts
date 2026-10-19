import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { get, patch, put } from './client'

export interface WritingSettings {
  setup_mode: 'puzzle' | 'oneshot'
  title_style: 'short' | 'tomato' | 'chief' | 'custom'
  title_custom: string
  person: 'first' | 'second' | 'third'
  intimacy: 'heart' | 'fade' | 'custom'
  intimacy_custom: string
  chapter_words: number | null
  other_rules: string
  playbook: 'auto' | 'harem_xuanhuan' | 'general'
  effort_preset: 'quick' | 'balanced' | 'premium' | 'custom'
  max_rewrites: number
  pitches: number
  review_strictness: 'lenient' | 'standard' | 'strict'
  volume_audit: boolean
  volume_approval: boolean
  chapters_approval: boolean
  segment_approval: boolean
  trial_read: boolean
}
export interface SettingsResponse { settings: WritingSettings; rules_text: string }
export interface AuthorRequirement { id: string; book_id: string; text: string; source: string; scope: 'always' | 'chapter' | 'volume'; chapter_index: number | null; volume_index: number | null; active: boolean; label: string; message_id: number | null; created_at: string; updated_at: string }
export const settingsKeys = { defaults: ['new-book-defaults'], book: (id: string) => ['book-settings', id], requirements: (id: string) => ['author-requirements', id] }
export const useBookSettings = (id: string) => useQuery({ queryKey: settingsKeys.book(id), queryFn: () => get<SettingsResponse>(`/books/${id}/settings`), refetchOnMount: 'always' })
export const useNewBookDefaults = () => useQuery({ queryKey: settingsKeys.defaults, queryFn: () => get<SettingsResponse>('/settings/new-book-defaults'), refetchOnMount: 'always' })
export const useAuthorRequirements = (id: string) => useQuery({ queryKey: settingsKeys.requirements(id), queryFn: () => get<AuthorRequirement[]>(`/books/${id}/requirements`), refetchInterval: 5000 })

/** Queue patches in order so a slow earlier response can never undo a later edit. */
export function useSettingsEditor(initial: SettingsResponse, path: string, method: 'PATCH' | 'PUT') {
  const qc = useQueryClient()
  // No local draft when clean: fresh query results then become visible immediately.
  const [draft, setDraft] = useState<WritingSettings | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [statuses, setStatuses] = useState<Partial<Record<keyof WritingSettings, string>>>({})
  const revision = useRef(0)
  const chain = useRef(Promise.resolve())
  const pending = useRef<Partial<WritingSettings>>({})
  const failed = useRef<Partial<WritingSettings>>({})
  const fieldVersions = useRef<Partial<Record<keyof WritingSettings, number>>>({})
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const statusTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const active = useRef(true)
  const save = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = null
    const changes = pending.current
    if (!Object.keys(changes).length && !Object.keys(failed.current).length) return
    pending.current = {}
    const version = revision.current
    chain.current = chain.current.then(async () => {
      const submitted = { ...failed.current, ...changes }
      try {
        const response = await (method === 'PATCH' ? patch<SettingsResponse>(path, submitted) : put<SettingsResponse>(path, submitted))
        failed.current = {}
        const bookId = path.match(/^\/books\/([^/]+)\/settings$/)?.[1]
        qc.setQueryData(bookId ? settingsKeys.book(bookId) : settingsKeys.defaults, response)
        if (bookId) void qc.invalidateQueries({ queryKey: ['book', bookId] })
        // 每章字数变了：书页简介里「约 N 章」跟着重算
        if (bookId && 'chapter_words' in submitted) void qc.invalidateQueries({ queryKey: ['workspace', bookId] })
        if (!active.current) return
        if (version === revision.current) {
          setDraft(null)
          setError(null)
        }
        setStatuses(previous => ({ ...previous, ...Object.fromEntries((Object.keys(submitted) as (keyof WritingSettings)[]).filter(key => (fieldVersions.current[key] ?? 0) <= version).map(key => [key, '已保存'])) }))
        if (statusTimer.current) clearTimeout(statusTimer.current)
        statusTimer.current = setTimeout(() => { if (active.current) setStatuses(previous => Object.fromEntries(Object.entries(previous).filter(([, status]) => status !== '已保存'))) }, 1800)
      } catch (cause) {
        // Keep unsaved author input visible, including when a later save succeeds.
        failed.current = submitted
        if (active.current) {
          setError(cause)
          setStatuses(previous => ({ ...previous, ...Object.fromEntries((Object.keys(submitted) as (keyof WritingSettings)[]).filter(key => (fieldVersions.current[key] ?? 0) <= version).map(key => [key, '未保存'])) }))
        }
      }
    })
  }, [method, path, qc])

  useEffect(() => {
    active.current = true
    return () => {
      // Flush a typing debounce when leaving a tab or closing the window.
      save()
      active.current = false
      if (statusTimer.current) clearTimeout(statusTimer.current)
    }
  }, [save])

  const update = (changes: Partial<WritingSettings>, debounce = false) => {
    revision.current += 1
    for (const key of Object.keys(changes) as (keyof WritingSettings)[]) fieldVersions.current[key] = revision.current
    const bookId = path.match(/^\/books\/([^/]+)\/settings$/)?.[1]
    void qc.cancelQueries({ queryKey: bookId ? settingsKeys.book(bookId) : settingsKeys.defaults })
    setDraft(previous => ({ ...(previous ?? initial.settings), ...changes }))
    pending.current = { ...pending.current, ...changes }
    setStatuses(previous => ({ ...previous, ...Object.fromEntries(Object.keys(changes).map(key => [key, '保存中…'])) }))
    if (timer.current) clearTimeout(timer.current)
    if (debounce) timer.current = setTimeout(save, 350)
    else save()
  }
  return { value: draft ?? initial.settings, rulesText: initial.rules_text, error, statuses, update, retry: save }
}
