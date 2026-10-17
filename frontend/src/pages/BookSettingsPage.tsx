import { RequirementDialog, ScopeSelect } from '../components/RequirementDialog'
import type { RequirementScope } from '../lib/chat'
import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { del, patch, post } from '../api/client'
import { useBook, useUpdateBook } from '../api/hooks'
import { settingsKeys, useAuthorRequirements, useBookSettings, useSettingsEditor, type AuthorRequirement, type SettingsResponse } from '../api/settings'
import { SettingsButton, SettingsGroup, SettingsRow } from '../components/settings/SettingsList'
import { RulesPreview, WritingSettings } from '../components/settings/WritingSettings'
import { ErrorText, Spinner } from '../components/ui'
import { automaticPlaybookName, bookLengthEstimate, parseTargetLength, requirementSource } from '../lib/writingSettings'
import { useBookContext } from './book/context'

function RequirementItem({ item }: { item: AuthorRequirement }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(item.text)
  const [scope, setScope] = useState<RequirementScope | null>(null)
  const update = useMutation({ mutationFn: () => patch<AuthorRequirement>(`/requirements/${item.id}`, { text, ...(scope ? { scope } : {}) }), onSuccess: () => { setEditing(false); void qc.invalidateQueries({ queryKey: settingsKeys.requirements(item.book_id) }) } })
  const remove = useMutation({ mutationFn: () => del(`/requirements/${item.id}`), onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.requirements(item.book_id) }) })
  const date = new Date(item.created_at)
  const formatted = Number.isNaN(date.getTime()) ? item.created_at : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  return <SettingsRow className={!item.active && !editing ? 'opacity-50' : undefined} label={item.text} hint={`${item.label} · ${requirementSource(item.source)} · ${formatted}`} extra={<>
    {editing && <div className="space-y-2"><textarea className="settings-textarea" aria-label="修改作者要求" value={text} onChange={event => setText(event.target.value)} /><ScopeSelect value={scope ?? (item.scope === 'chapter' ? 'next_chapter' : item.scope === 'volume' ? 'this_volume' : 'always')} onChange={setScope} /><div className="flex justify-end gap-2"><SettingsButton disabled={update.isPending} onClick={() => setEditing(false)}>取消</SettingsButton><SettingsButton primary disabled={update.isPending || !text.trim()} onClick={() => update.mutate()}>{update.isPending ? '保存中…' : '保存'}</SettingsButton></div></div>}
    <ErrorText error={update.error || remove.error} />
  </>}><SettingsButton disabled={remove.isPending} onClick={() => { setText(item.text); setScope(null); setEditing(true) }}>修改</SettingsButton><SettingsButton danger disabled={remove.isPending} onClick={() => { if (confirm('删除这条作者要求？删除后，下一步起编辑部将不再收到它。')) remove.mutate() }}>删除</SettingsButton></SettingsRow>
}

interface TidyItem { id: string; text: string; action: string; reason: string; rewrite: string }
function RequirementsList({ bookId }: { bookId: string }) {
  const qc = useQueryClient()
  const query = useAuthorRequirements(bookId)
  const [adding, setAdding] = useState(false)
  const [tidyItems, setTidyItems] = useState<TidyItem[] | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const tidy = useMutation({ mutationFn: () => post<{ items: TidyItem[] }>(`/books/${bookId}/requirements/tidy`), onSuccess: response => { const items = response.items.filter(item => item.action !== '保留'); setTidyItems(items); setSelected(items.map(item => item.id)) } })
  const apply = useMutation({ mutationFn: () => post(`/books/${bookId}/requirements/apply`, { delete: tidyItems?.filter(item => selected.includes(item.id) && item.action === '删掉').map(item => item.id), rewrite: tidyItems?.filter(item => selected.includes(item.id) && item.action === '改写').map(item => ({ id: item.id, text: item.rewrite })) }), onSuccess: () => { setTidyItems(null); void qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) }) } })
  return <SettingsGroup title="作者要求清单" action={<div className="flex gap-2"><SettingsButton disabled={tidy.isPending} onClick={() => tidy.mutate()}>{tidy.isPending ? '主编正在看…' : '整理一下'}</SettingsButton><SettingsButton onClick={() => setAdding(true)}>＋ 添加</SettingsButton></div>}>
    {adding && <RequirementDialog initial="" onClose={() => setAdding(false)} onSave={async (text, scope) => { await post(`/books/${bookId}/requirements`, { text, scope }); await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) }) }} />}
    {tidyItems && <SettingsRow label="主编的整理建议" extra={<div className="space-y-3">{tidyItems.length === 0 ? <p className="text-sm text-ink-2">看过了，没有要整理的。</p> : tidyItems.map(item => <label key={item.id} className="flex gap-2 rounded-lg border border-line p-3"><input type="checkbox" checked={selected.includes(item.id)} onChange={event => setSelected(previous => event.target.checked ? [...previous, item.id] : previous.filter(id => id !== item.id))} /><span className="text-sm leading-7"><span className="block">{item.text}</span><span className="block text-chief">{item.action === '删掉' ? '删掉' : `改写成「${item.rewrite}」`}</span><span className="text-xs text-ink-2">{item.reason}</span></span></label>)}<div className="flex justify-end gap-2"><SettingsButton disabled={apply.isPending} onClick={() => setTidyItems(null)}>算了</SettingsButton>{tidyItems.length > 0 && <SettingsButton primary disabled={apply.isPending} onClick={() => apply.mutate()}>照勾的改</SettingsButton>}</div><ErrorText error={apply.error} /></div>} />}
    {!!tidy.error && <SettingsRow label={<ErrorText error={tidy.error} />} />}
    {query.isLoading && <SettingsRow label={<Spinner />} />}
    {query.error && <SettingsRow label={<ErrorText error={query.error} />} />}
    {!query.isLoading && query.data?.length === 0 && <SettingsRow label="还没有作者要求" hint="群聊里交代的要求、明确记下的聊天结论和拍板意见会记录在这里。" />}
    {query.data?.map(item => <RequirementItem key={item.id} item={item} />)}
  </SettingsGroup>
}

function BookLengthSettings({ chapterWords }: { chapterWords: number | null }) {
  const { bookId, book, working } = useBookContext()
  const update = useUpdateBook(bookId)
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const committing = useRef(false)
  const value = draft ?? String(book.concept.target_length ?? '')
  const estimate = bookLengthEstimate(parseTargetLength(value), chapterWords, book.concept.chapter_words)
  const save = async () => {
    if (working || committing.current || draft === null) return
    const targetLength = parseTargetLength(draft)
    if (targetLength === null) { setError(new Error('请填写 5–1000 之间的整数（万字）')); return }
    if (targetLength === book.concept.target_length) { setDraft(null); setError(null); return }
    committing.current = true
    setError(null); setSaved(false)
    try {
      await update.mutateAsync({ concept: { target_length: targetLength } })
      setDraft(null); setSaved(true)
    } catch (cause) { setError(cause) } finally { committing.current = false }
  }
  return <SettingsGroup title="篇幅">
    <SettingsRow label="全书计划写多长" hint="定下一篇时，主编按这个篇幅判断还剩多少、要不要开始收尾；正在写的这一篇不变。" status={update.isPending ? '保存中…' : saved ? '已保存' : undefined}
      extra={<>
        {working && <p id="book-length-locked" className="text-xs text-ink-2">编辑部工作时不能改，等这一步做完</p>}
        {!!error && <div role="alert"><ErrorText error={error} />{update.isError && <SettingsButton disabled={working || update.isPending} onClick={() => void save()}>重试保存篇幅</SettingsButton>}</div>}
      </>}>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <input className="settings-input w-24 disabled:cursor-not-allowed disabled:opacity-50" aria-label="全书计划写多长（万字）" aria-invalid={!!error} aria-describedby={working ? 'book-length-locked book-length-estimate' : 'book-length-estimate'} type="number" min={5} max={1000} step={1} value={value} disabled={working || update.isPending}
          onChange={event => { setDraft(event.target.value); setError(null); setSaved(false) }} onBlur={() => void save()} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); void save() } }} />
        <span className="text-xs text-ink-2">万字</span>
        <span id="book-length-estimate" className="text-xs text-ink-3">按每章约 {estimate.chapterWords} 字，约 {estimate.chapters ?? '—'} 章</span>
      </div>
    </SettingsRow>
  </SettingsGroup>
}

function BookSettingsEditor({ bookId, initial }: { bookId: string; initial: SettingsResponse }) {
  const editor = useSettingsEditor(initial, `/books/${bookId}/settings`, 'PATCH')
  const { data: book } = useBook(bookId)
  const currentPlaybook = automaticPlaybookName(book?.concept)
  return <div className="mx-auto w-full max-w-3xl px-5 py-7 sm:px-8">
    <h1 className="mb-2 font-serif text-2xl font-bold">本书设置</h1><p className="mb-6 text-xs leading-6 text-ink-3">每项修改自动保存。除全书篇幅外，编辑部正在工作也可以改，从下一步开始生效。</p>
    {!!editor.error && <div role="alert" className="mb-4"><ErrorText error={editor.error} /><SettingsButton className="mt-2" onClick={editor.retry}>重试保存</SettingsButton></div>}
    <WritingSettings value={editor.value} onChange={editor.update} statuses={editor.statuses} currentPlaybook={currentPlaybook} afterPreferences={<BookLengthSettings chapterWords={editor.value.chapter_words} />} />
    <div className="mt-6"><RequirementsList bookId={bookId} /></div>
    <RulesPreview text={editor.rulesText} />
  </div>
}

export function BookSettingsPage() {
  const { bookId = '' } = useParams()
  const query = useBookSettings(bookId)
  if (query.isLoading) return <div className="p-8 text-ink-3"><Spinner /> 正在读取设置…</div>
  if (!query.data) return <div className="p-8"><ErrorText error={query.error} /><SettingsButton onClick={() => void query.refetch()}>重试</SettingsButton></div>
  return <BookSettingsEditor key={bookId} bookId={bookId} initial={query.data} />
}
