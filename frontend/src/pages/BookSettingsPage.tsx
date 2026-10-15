import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { del, patch, post } from '../api/client'
import { useBook } from '../api/hooks'
import { settingsKeys, useAuthorRequirements, useBookSettings, useSettingsEditor, type AuthorRequirement, type SettingsResponse } from '../api/settings'
import { SettingsButton, SettingsGroup, SettingsRow } from '../components/settings/SettingsList'
import { RulesPreview, WritingSettings } from '../components/settings/WritingSettings'
import { ErrorText, Spinner } from '../components/ui'
import { automaticPlaybookName, requirementSource } from '../lib/writingSettings'

function RequirementItem({ item }: { item: AuthorRequirement }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(item.text)
  const update = useMutation({ mutationFn: () => patch<AuthorRequirement>(`/requirements/${item.id}`, { text }), onSuccess: () => { setEditing(false); void qc.invalidateQueries({ queryKey: settingsKeys.requirements(item.book_id) }) } })
  const remove = useMutation({ mutationFn: () => del(`/requirements/${item.id}`), onSuccess: () => qc.invalidateQueries({ queryKey: settingsKeys.requirements(item.book_id) }) })
  const date = new Date(item.created_at)
  const formatted = Number.isNaN(date.getTime()) ? item.created_at : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  return <SettingsRow label={item.text} hint={`${requirementSource(item.source)} · ${formatted}`} extra={<>
    {editing && <div className="space-y-2"><textarea className="settings-textarea" aria-label="修改作者要求" value={text} onChange={event => setText(event.target.value)} /><div className="flex justify-end gap-2"><SettingsButton disabled={update.isPending} onClick={() => setEditing(false)}>取消</SettingsButton><SettingsButton primary disabled={update.isPending || !text.trim()} onClick={() => update.mutate()}>{update.isPending ? '保存中…' : '保存'}</SettingsButton></div></div>}
    <ErrorText error={update.error || remove.error} />
  </>}><SettingsButton disabled={remove.isPending} onClick={() => { setText(item.text); setEditing(true) }}>修改</SettingsButton><SettingsButton danger disabled={remove.isPending} onClick={() => { if (confirm('删除这条作者要求？删除后，下一步起编辑部将不再收到它。')) remove.mutate() }}>删除</SettingsButton></SettingsRow>
}

function RequirementsList({ bookId }: { bookId: string }) {
  const qc = useQueryClient()
  const query = useAuthorRequirements(bookId)
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  const create = useMutation({ mutationFn: () => post<AuthorRequirement>(`/books/${bookId}/requirements`, { text }), onSuccess: () => { setText(''); setAdding(false); void qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) }) } })
  return <SettingsGroup title="作者要求清单 · 一直有效，过时的自己删" action={<SettingsButton onClick={() => setAdding(true)}>＋ 添加</SettingsButton>}>
    {adding && <SettingsRow label="手动添加" extra={<div className="space-y-2"><textarea className="settings-textarea" aria-label="新增作者要求" placeholder="写下需要一直遵守的要求" autoFocus value={text} onChange={event => setText(event.target.value)} /><div className="flex justify-end gap-2"><SettingsButton disabled={create.isPending} onClick={() => setAdding(false)}>取消</SettingsButton><SettingsButton primary disabled={create.isPending || !text.trim()} onClick={() => create.mutate()}>{create.isPending ? '保存中…' : '添加'}</SettingsButton></div><ErrorText error={create.error} /></div>} />}
    {query.isLoading && <SettingsRow label={<Spinner />} />}
    {query.error && <SettingsRow label={<ErrorText error={query.error} />} />}
    {!query.isLoading && query.data?.length === 0 && <SettingsRow label="还没有作者要求" hint="动笔前的回答、插话、私聊、试读和卷纲意见会记录在这里。" />}
    {query.data?.map(item => <RequirementItem key={item.id} item={item} />)}
  </SettingsGroup>
}

function BookSettingsEditor({ bookId, initial }: { bookId: string; initial: SettingsResponse }) {
  const editor = useSettingsEditor(initial, `/books/${bookId}/settings`, 'PATCH')
  const { data: book } = useBook(bookId)
  const currentPlaybook = automaticPlaybookName(book?.concept)
  return <div className="mx-auto w-full max-w-3xl px-5 py-7 sm:px-8">
    <h1 className="mb-2 font-serif text-2xl font-bold">这本书的设置</h1><p className="mb-6 text-xs leading-6 text-ink-3">每项修改自动保存。编辑部正在工作也可以改，从下一步开始生效。</p>
    {!!editor.error && <div role="alert" className="mb-4"><ErrorText error={editor.error} /><SettingsButton className="mt-2" onClick={editor.retry}>重试保存</SettingsButton></div>}
    <WritingSettings value={editor.value} onChange={editor.update} statuses={editor.statuses} currentPlaybook={currentPlaybook} />
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
