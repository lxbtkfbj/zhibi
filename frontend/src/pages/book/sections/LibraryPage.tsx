import { libraryQuoteWhere } from '../../../lib/chat'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { post } from '../../../api/client'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { BookMarked, ChevronDown, ChevronUp, EyeOff, Flag, Gem, Globe2, Layers, Lightbulb, Link2, LockKeyhole, Plus, ScrollText, Search, Sparkles, Star, Tags, Trash2, UnlockKeyhole, Users, X } from 'lucide-react'
import { useBible, useBibleMutations, useNodes, useSecretMutations, useSecrets } from '../../../api/hooks'
import type { Secret } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { SecretCard } from './SecretsPage'
import { useLibrary, useLibraryCategoryActions, useLibraryConfig, useLibraryItemActions, useLibrarySuggestionActions, useLibrarySuggestions, useRewrite, useTargetVersions } from '../../../api/library'
import type { CategoryInput, LibraryCategory, LibraryConfig, LibraryItem, LibraryItemPatch, LibrarySnapshot, LibrarySuggestion } from '../../../api/library'
import { Button, ErrorText, inputClass, Modal, Skeleton } from '../../../components/ui'
import { RewriteField, TargetHistory } from '../../../components/RewriteField'
import { filterLibraryRows, libraryRows, parentChoices, suggestionAction, suggestionTargetId } from '../../../lib/libraryView'
import type { LibraryRow } from '../../../lib/libraryView'
import { useBookContext } from '../context'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'


function NewItemModal({ bookId, categories, defaultCategory, config, onClose, onCreated }: { bookId: string; categories: LibraryCategory[]; defaultCategory?: string; config: LibraryConfig; onClose: () => void; onCreated: (item: LibraryItem, category: string) => void }) {
  const { create } = useLibraryItemActions(bookId)
  const [categoryKey, setCategoryKey] = useState(defaultCategory ?? categories[0]?.key ?? '')
  const [name, setName] = useState('')
  const [status, setStatus] = useState(Object.keys(config.statuses)[0])
  const category = categories.find(row => row.key === categoryKey)
  const save = async () => {
    const type = categoryKey === config.character_category.key ? 'character' : 'entry'
    try { const result = await create.mutateAsync({ type, body: { name: name.trim(), status, ...(type === 'entry' ? { category: categoryKey, style: category?.style, fields: (category?.fields ?? []).map(field => ({ name: field, value: '' })) } : {}) } }); onCreated(result, categoryKey) } catch { /* 表单不清空 */ }
  }
  return <Modal open onClose={onClose} title="新增一条" footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="seal" disabled={!name.trim() || !category} loading={create.isPending} onClick={() => void save()}>建好这一条</Button></>}><div className="space-y-4"><label className="block space-y-2 text-sm"><span>类别</span><select aria-label="新条目的类别" className={clsx(inputClass, 'w-full')} value={categoryKey} onChange={event => setCategoryKey(event.target.value)}>{categories.map(row => <option key={row.key} value={row.key}>{row.name}</option>)}</select></label><label className="block space-y-2 text-sm"><span>名称（必填）</span><input aria-label="条目名称" autoFocus maxLength={100} className={clsx(inputClass, 'w-full')} value={name} onChange={event => setName(event.target.value)} /></label><label className="block space-y-2 text-sm"><span>状态</span><select aria-label="新条目的状态" className={clsx(inputClass, 'w-full')} value={status} onChange={event => setStatus(event.target.value)}>{Object.entries(config.statuses).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><p className="text-xs leading-relaxed text-ink-2">{category?.hint}</p><ErrorText error={create.error} /></div></Modal>
}

function CategoryModal({ bookId, category, config, onClose, onSaved }: { bookId: string; category?: LibraryCategory; config?: LibraryConfig; onClose: () => void; onSaved: (key: string) => void }) {
  const { save } = useLibraryCategoryActions(bookId)
  const [draft, setDraft] = useState<CategoryInput>({ name: category?.name ?? '', style: category?.style === 'card' ? 'card' : 'paragraph', fields: category?.fields ?? [], hint: category?.hint ?? '' })
  const update = (body: Partial<CategoryInput>) => setDraft(previous => ({ ...previous, ...body }))
  const move = (index: number, offset: number) => { const next = [...draft.fields]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; update({ fields: next }) }
  const submit = async () => { try { const row = await save.mutateAsync({ id: category?.id, body: { ...draft, name: draft.name.trim(), fields: draft.style === 'card' ? draft.fields.map(field => field.trim()) : [] } }); onSaved(row.key.startsWith('custom:') ? row.key : `custom:${row.key}`) } catch { /* 保留表单 */ } }
  const fieldsValid = draft.style !== 'card' || draft.fields.every(field => field.trim()) && new Set(draft.fields.map(field => field.trim())).size === draft.fields.length
  return <Modal open onClose={onClose} title={category ? '修改自建类别' : '自建类别'} footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="seal" loading={save.isPending} disabled={!draft.name.trim() || !fieldsValid} onClick={() => void submit()}>保存类别</Button></>}><div className="space-y-4"><label className="block space-y-2 text-sm"><span>类别名称</span><input autoFocus aria-label="类别名称" maxLength={40} value={draft.name} onChange={event => update({ name: event.target.value })} className={clsx(inputClass, 'w-full')} /></label><label className="block space-y-2 text-sm"><span>样式{category && '（建好后不能更换）'}</span><select aria-label="类别样式" disabled={!!category} value={draft.style} onChange={event => update({ style: event.target.value as CategoryInput['style'] })} className={clsx(inputClass, 'w-full')}>{(['card', 'paragraph'] as const).map(style => <option key={style} value={style}>{config?.styles[style] ?? style}</option>)}</select></label>{draft.style === 'card' && <fieldset className="space-y-2"><legend className="mb-2 text-sm">卡片字段（按显示顺序）</legend>{draft.fields.map((field, index) => <div key={index} className="flex items-center gap-1"><input aria-label={`字段 ${index + 1}`} className={clsx(inputClass, 'min-w-0 flex-1')} value={field} onChange={event => update({ fields: draft.fields.map((value, at) => at === index ? event.target.value : value) })} /><button type="button" className="p-1 disabled:opacity-30" aria-label={`字段 ${index + 1} 上移`} disabled={index === 0} onClick={() => move(index, -1)}><ChevronUp className="size-4" /></button><button type="button" className="p-1 disabled:opacity-30" aria-label={`字段 ${index + 1} 下移`} disabled={index === draft.fields.length - 1} onClick={() => move(index, 1)}><ChevronDown className="size-4" /></button><button type="button" className="p-1" aria-label={`删除字段 ${index + 1}`} onClick={() => update({ fields: draft.fields.filter((_, at) => at !== index) })}><X className="size-4" /></button></div>)}<Button variant="ghost" size="sm" onClick={() => update({ fields: [...draft.fields, ''] })}>＋加一个字段</Button>{!fieldsValid && <p className="text-xs text-seal">字段名不能留空或重复。</p>}</fieldset>}<label className="block space-y-2 text-sm"><span>这一类该写清什么</span><textarea rows={3} aria-label="这一类该写清什么" className={clsx(inputClass, 'w-full')} value={draft.hint} onChange={event => update({ hint: event.target.value })} /></label><ErrorText error={save.error} /></div></Modal>
}

function EditItemModal({ bookId, item, category, library, config, onClose, addLevel = false }: { bookId: string; item: LibraryRow; category?: LibraryCategory; library: LibrarySnapshot; config: LibraryConfig; onClose: () => void; addLevel?: boolean }) {
  const { update } = useLibraryItemActions(bookId)
  const [aliasText, setAliasText] = useState((item.aliases ?? []).join('、'))
  const [draft, setDraft] = useState<LibraryItemPatch>(() => {
    if (item.targetType === 'character') return Object.fromEntries(['one_line', 'aliases', ...config.character_category.fields.map(field => field.column)].map(key => [key, item[key as keyof LibraryItem]])) as LibraryItemPatch
    return { name: item.name, aliases: item.aliases ?? [], category: item.category, one_line: item.one_line, content: item.content ?? '', fields: [...new Set([...(category?.fields ?? []), ...(item.fields ?? []).map(field => field.name)])].map(name => ({ name, value: item.fields?.find(field => field.name === name)?.value ?? '' })), levels: [...(item.levels ?? []).map(level => ({ ...level })), ...(addLevel ? [{ name: '', text: '' }] : [])] }
  })
  const change = (body: LibraryItemPatch) => setDraft(previous => ({ ...previous, ...body }))
  const style = item.targetType === 'character' ? 'card' : category?.style ?? item.style
  const submit = async () => { try { await update.mutateAsync({ type: item.targetType, id: item.id, body: { ...draft, aliases: aliasText.split(/[、,，]/).map(value => value.trim()).filter(Boolean) } }); onClose() } catch { /* 原文与输入均保留 */ } }
  const text = (label: string, key: keyof LibraryItemPatch, rows = 2) => <label key={key} className="block space-y-1.5 text-sm"><span>{label}</span><textarea aria-label={`编辑${label}`} rows={rows} className={clsx(inputClass, 'w-full')} value={String(draft[key] ?? '')} onChange={event => change({ [key]: event.target.value })} /></label>
  return <Modal open wide onClose={onClose} title={`自己改 · ${item.name}`} footer={<><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="seal" loading={update.isPending} disabled={!draft.name?.trim()} onClick={() => void submit()}>保存这一条</Button></>}><div className="space-y-4">
    {item.targetType === 'character' ? config.character_category.fields.filter(field => field.column !== 'aliases').map(field => field.column === 'role_type' ? <label key={field.column} className="block space-y-2 text-sm"><span>{field.name}</span><select className={clsx(inputClass, 'w-full')} value={draft.role_type} onChange={event => change({ role_type: event.target.value })}>{[...new Set([draft.role_type ?? '', ...config.role_types])].filter(Boolean).map(role => <option key={role}>{role}</option>)}</select></label> : text(field.name, field.column as keyof LibraryItemPatch)) : text('名称', 'name', 1)}
    <label className="block space-y-1.5 text-sm"><span>别名（用顿号隔开）</span><input aria-label="编辑别名" className={clsx(inputClass, 'w-full')} value={aliasText} onChange={event => setAliasText(event.target.value)} /></label>
    {text('一句话', 'one_line')}
    {item.targetType === 'entry' && <><label className="block space-y-2 text-sm"><span>归到类别</span><select aria-label="移动到类别" className={clsx(inputClass, 'w-full')} value={draft.category} onChange={event => change({ category: event.target.value })}>{library.categories.filter(row => row.key !== config.character_category.key && row.style === style).map(row => <option key={row.key} value={row.key}>{row.name}</option>)}</select></label>{style === 'card' ? draft.fields?.filter(field => !category?.fields || category.fields.includes(field.name)).map((field) => <label key={field.name} className="block space-y-1.5 text-sm"><span>{field.name}</span><textarea aria-label={`编辑${field.name}`} className={clsx(inputClass, 'w-full')} rows={3} value={field.value} onChange={event => change({ fields: draft.fields!.map(row => row.name === field.name ? { ...row, value: event.target.value } : row) })} /></label>) : text(style === 'ladder' ? '总说明' : '一段话', 'content', 5)}{style === 'ladder' && <fieldset className="space-y-3"><legend className="mb-2 text-sm font-medium">各级（从低到高）</legend>{draft.levels?.map((level, index) => <div key={index} className="space-y-2 rounded-xl border border-line p-3"><div className="flex gap-2"><input aria-label={`第 ${index + 1} 级名称`} className={clsx(inputClass, 'min-w-0 flex-1')} value={level.name} onChange={event => change({ levels: draft.levels!.map((row, at) => at === index ? { ...row, name: event.target.value } : row) })} /><Button variant="ghost" size="sm" onClick={() => change({ levels: draft.levels!.filter((_, at) => at !== index) })}>删除这一级</Button></div><textarea aria-label={`第 ${index + 1} 级介绍`} className={clsx(inputClass, 'w-full')} rows={3} value={level.text} onChange={event => change({ levels: draft.levels!.map((row, at) => at === index ? { ...row, text: event.target.value } : row) })} /></div>)}<Button variant="ghost" size="sm" onClick={() => change({ levels: [...(draft.levels ?? []), { name: '', text: '' }] })}>＋加一级</Button></fieldset>}</>}
    <ErrorText error={update.error} />
  </div></Modal>
}

function SuggestionInbox({ bookId, suggestions, library, onJump, compact = false }: { bookId: string; suggestions: LibrarySuggestion[]; library?: LibrarySnapshot; onJump: (suggestion: LibrarySuggestion) => void; compact?: boolean }) {
  const { resolve, acceptAll } = useLibrarySuggestionActions(bookId)
  const { working, waiting, asking } = useBookContext()
  const qc = useQueryClient()
  const runChat = useMutation({ mutationFn: (id: string) => post(`/suggestions/${id}/run-chat`), onSuccess: () => qc.invalidateQueries({ queryKey: ['library-suggestions', bookId] }) })
  const [error, setError] = useState<unknown>(null)
  const [skipped, setSkipped] = useState<{ title: string; reason: string }[]>([])
  const [written, setWritten] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const items = library ? libraryRows(library) : []
  // 标题保存的是生成时的锁状态；解锁后不能继续拿旧标题阻止作者接受。
  const locked = (suggestion: LibrarySuggestion) => items.find(item => item.id === suggestion.target_id)?.locked ?? false
  const title = (suggestion: LibrarySuggestion) => items.some(item => item.id === suggestion.target_id) ? suggestion.title.replaceAll('（已锁）', '') : suggestion.title
  const accept = (suggestion: LibrarySuggestion) => {
    setError(null)
    if (locked(suggestion)) { setError(new Error('已锁：AI 不能改这一处，先解锁')); return }
    if (suggestion.kind === 'chat') { runChat.mutate(suggestion.id, { onSuccess: () => { void qc.invalidateQueries() } }); return }
    if (suggestion.kind === 'written') { setWritten(suggestion.id); return }
    resolve.mutate({ id: suggestion.id, action: 'accept' })
  }
  const acceptEvery = async () => {
    if (suggestions.some(item => item.kind === 'written') && !window.confirm('建议中有前文替换。全部接受会把列出的正文旧叫法也一起换掉；你可以先逐条展开查看。确认全部接受？')) return
    try { const result = await acceptAll.mutateAsync(); setSkipped(result.skipped.map(item => ({ title: suggestions.find(row => row.id === item.id)?.title ?? '这条建议', reason: item.reason }))) } catch { /* 显示接口错误 */ }
  }
  const list = <div className="mt-3 space-y-2">{suggestions.map(suggestion => <div key={suggestion.id} className="rounded-lg border border-line bg-card p-3"><div className="flex flex-wrap items-start justify-between gap-2"><button type="button" className="min-w-0 flex-1 text-left text-sm leading-relaxed hover:text-chief" onClick={() => onJump(suggestion)}>{suggestion.kind === 'chat' && <span className="mr-2 rounded bg-chief-soft px-1.5 py-0.5 text-xs text-chief">群聊里说的</span>}{title(suggestion)}{locked(suggestion) && <span className="text-seal">（已锁）</span>}</button><div className="flex gap-1"><Button size="sm" variant="ghost" disabled={resolve.isPending || acceptAll.isPending || runChat.isPending || (suggestion.kind === 'chat' && (working || waiting || asking))} onClick={() => accept(suggestion)}>{suggestionAction(suggestion)}</Button><Button size="sm" variant="ghost" disabled={resolve.isPending || acceptAll.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>{suggestion.kind === 'written' ? '只管以后' : '不用'}</Button></div></div>{suggestion.kind === 'written' && <details className="mt-2 text-xs text-ink-2" open={written === suggestion.id || undefined}><summary className="cursor-pointer">查看前文出现的位置</summary><div className="mt-2 space-y-2">{Array.isArray(suggestion.payload.matches) && (suggestion.payload.matches as { chapter: number; count: number; contexts: string[] }[]).map(match => <div key={match.chapter}><p className="font-medium">第 {match.chapter} 章 · {match.count} 处</p>{match.contexts.map((context, index) => <p key={index} className="mt-1 rounded bg-paper-2 p-2 leading-relaxed">…{context}…</p>)}</div>)}{written === suggestion.id && <Button size="sm" variant="danger" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>确认，替换上面的前文</Button>}</div></details>}</div>)}<ErrorText error={error ?? runChat.error ?? resolve.error ?? acceptAll.error} /></div>
  if (compact) return <section aria-label="这一条的建议" className="rounded-xl border border-line bg-subtle p-4"><h3 className="text-sm font-medium">这一条的建议</h3>{list}</section>
  return <section aria-label="待处理的建议" className="mb-5 rounded-xl border border-line bg-paper-2">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 py-2 pr-2 pl-4">
      <Lightbulb aria-hidden className="size-4 shrink-0 text-writer" />
      <h2 className="text-[13px] font-medium text-ink">{suggestions.length} 条建议等你看</h2>
      <button type="button" aria-expanded={open} onClick={() => setOpen(value => !value)} className="text-[13px] text-chief hover:underline hover:underline-offset-4">{open ? '收起' : '逐条看'}</button>
      <Button className="ml-auto" size="sm" variant="outline" disabled={resolve.isPending} loading={acceptAll.isPending} onClick={() => void acceptEvery()}>全部接受</Button>
    </div>
    {open && <div className="border-t border-line px-4 pb-4">{list}</div>}
    {!!acceptAll.error && <div className="px-4 pb-3"><ErrorText error={acceptAll.error} /></div>}
    {!!skipped.length && <div role="status" className="mx-4 mb-4 rounded-lg bg-seal-soft p-3 text-sm text-seal-dark"><p className="font-medium">以下建议暂未接受：</p>{skipped.map((row, index) => <p key={index} className="mt-2">{row.title}：{row.reason}</p>)}</div>}
  </section>
}

function LibraryDetail({ bookId, item, library, config, suggestions, onDeleted, onJump, onClose }: { bookId: string; item: LibraryRow; library: LibrarySnapshot; config: LibraryConfig; suggestions: LibrarySuggestion[]; onDeleted: () => void; onJump: (suggestion: LibrarySuggestion) => void; onClose: () => void }) {
  const { update, remove } = useLibraryItemActions(bookId)
  const { inspect } = useLibrarySuggestionActions(bookId)
  const rewrite = useRewrite(bookId)
  const versions = useTargetVersions(bookId, item.targetType, item.id)
  const secrets = useSecrets(bookId)
  const secretActions = useSecretMutations(bookId)
  const bible = useBible(bookId)
  const nodes = useNodes(bookId)
  const [editing, setEditing] = useState(false)
  const [addingLevel, setAddingLevel] = useState(false)
  const [tag, setTag] = useState('')
  const [localError, setLocalError] = useState<unknown>(null)
  const category = library.categories.find(row => row.key === item.categoryKey)
  const style = item.targetType === 'character' ? 'card' : item.style ?? category?.style ?? 'paragraph'
  const fieldNames = category?.fields ?? (item.fields ?? []).map(field => field.name)
  const change = (body: LibraryItemPatch) => { setLocalError(null); update.mutate({ type: item.targetType, id: item.id, body }) }
  const addTag = (value: string) => { if (value.trim() && !item.tags.includes(value.trim())) change({ tags: [...item.tags, value.trim()] }); setTag('') }
  const field = (path: string, value: string, label?: string, emptyText?: string) => <RewriteField bookId={bookId} targetType={item.targetType} targetId={item.id} path={path} value={value} quoteWhere={selectionPath => libraryQuoteWhere(item, selectionPath, config)} label={label} emptyText={emptyText} locked={item.locked} />
  const fill = () => {
    if (item.locked) { setLocalError(new Error('已锁：AI 不能改这一处，先解锁')); return }
    const path = item.targetType === 'character' ? config.character_category.fields.find(row => row.column !== 'name' && row.column !== 'aliases' && row.column !== 'role_type')?.column ?? 'background' : style === 'card' && fieldNames[0] ? `fields.${fieldNames[0]}` : 'content'
    rewrite.mutate({ target_type: item.targetType, target_id: item.id, path, mode: 'instruction', instruction: '按定调和这一类该写清的事，写这一条' })
  }
  const deleteItem = async () => {
    if (!window.confirm(`删除「${item.name}」？这条设定将从设定库移除。`)) return
    try { await remove.mutateAsync({ type: item.targetType, id: item.id }); onDeleted() } catch { /* 保留原文 */ }
  }
  const secret = secrets.data?.find(row => row.id === item.secret_id)
  const linkSecret = async () => {
    try { const row = await secretActions.create.mutateAsync({ title: item.name, truth: item.content || item.one_line }); change({ secret_id: row.id }) } catch { /* 显示错误 */ }
  }
  return <article aria-label={`${item.name}详情`} className="flex h-full min-h-0 flex-col">
    <header className="shrink-0 border-b border-line px-6 pt-5 pb-4">
      <div className="flex items-start gap-3"><h2 className="min-w-0 flex-1 break-words font-serif text-2xl font-bold">{item.name}</h2><Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => change({ locked: !item.locked })}>{item.locked ? <LockKeyhole className="size-4" /> : <UnlockKeyhole className="size-4" />}{item.locked ? '已锁住 · 解锁' : '锁住'}</Button><button type="button" aria-label="关闭详情" title="关闭（Esc）" onClick={onClose} className="rounded-lg p-1.5 text-ink-2 hover:bg-line/70 hover:text-ink"><X className="size-5" /></button></div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3"><span>{category?.name}</span><span>·</span><select className="rounded-md border border-line bg-card px-1.5 py-0.5 text-ink" aria-label="条目状态" value={item.status} disabled={update.isPending} onChange={event => change({ status: event.target.value })}>{Object.entries(config.statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span>· {config.sources[item.source] ?? item.source}</span><span>· 第 {versions.data?.[0]?.version ?? 1} 版</span></div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">{item.tags.map(value => <button key={value} type="button" disabled={update.isPending} className="inline-flex items-center gap-1 rounded-full bg-chief-soft px-2.5 py-1 text-xs text-chief" onClick={() => change({ tags: item.tags.filter(row => row !== value) })} aria-label={`移除标签${value}`}>{value}<X className="size-3" /></button>)}{config.common_tags.filter(value => !item.tags.includes(value)).map(value => <button key={value} type="button" disabled={update.isPending} className="rounded-full border border-dashed border-line-2 px-2.5 py-1 text-xs text-ink-3 hover:text-chief" onClick={() => addTag(value)}>＋{value}</button>)}<form className="flex gap-1" onSubmit={event => { event.preventDefault(); addTag(tag) }}><input aria-label="新标签" className="w-24 rounded-lg border border-line bg-paper-2 px-2 py-1 text-xs" value={tag} onChange={event => setTag(event.target.value)} placeholder="加标签" /><button className="rounded px-1 text-xs text-chief" type="submit" disabled={!tag.trim() || update.isPending}>添加</button></form></div>
      <div className="mt-3 flex flex-wrap gap-1.5"><Button size="sm" variant="outline" loading={rewrite.isPending} onClick={fill}><Sparkles className="size-3.5" />让 AI 先填一版</Button><Button size="sm" variant="ghost" onClick={() => { setAddingLevel(false); setEditing(true) }}>自己改</Button><Button size="sm" variant="ghost" loading={inspect.isPending} onClick={() => inspect.mutate({ mode: 'check', target_type: item.targetType, target_id: item.id })}>查一查</Button><TargetHistory bookId={bookId} targetType={item.targetType} targetId={item.id} /><details className="relative"><summary className="flex h-8 cursor-pointer list-none items-center rounded-lg px-3 text-[13px] text-ink-2 hover:bg-line/70 hover:text-ink [&::-webkit-details-marker]:hidden">更多</summary><div className="absolute left-0 z-10 mt-1 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]"><Button size="sm" variant="danger" loading={remove.isPending} onClick={() => void deleteItem()}>删除这一条</Button></div></details></div>
    </header>
    <div className="scroll-thin min-h-0 flex-1 space-y-5 overflow-y-auto px-6 pt-2 pb-24">
      {style === 'card' && <div className="divide-y divide-line">{item.targetType === 'character' ? config.character_category.fields.map(spec => <div key={spec.column} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3 py-3"><h3 className="pt-1.5 text-[13px] text-ink-3">{spec.name}</h3><div className="min-w-0">{spec.column === 'aliases' ? <p className="text-sm leading-relaxed">{item.aliases?.join('、') || <span className="text-ink-3">（空）</span>}</p> : field(spec.column, String(item[spec.column] ?? ''), undefined, '（空）')}</div></div>) : fieldNames.map(name => <div key={name} className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3 py-3"><h3 className="pt-1.5 text-[13px] text-ink-3">{name}</h3><div className="min-w-0">{field(`fields.${name}`, item.fields?.find(row => row.name === name)?.value ?? '', undefined, '（空）')}</div></div>)}</div>}
      {item.targetType === 'character' && <CharacterRelations bookId={bookId} characterId={item.id} />}
      {item.targetType === 'character' && <section className="rounded-xl border border-line bg-subtle p-4"><h3 className="mb-3 text-sm font-medium">写作中每章更新<span className="ml-2 text-xs font-normal text-ink-3">设定师每章写</span></h3><dl className="space-y-2 text-sm">{config.character_category.state_fields.map(spec => <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2" key={spec.column}><dt className="text-ink-2">{spec.name}</dt><dd>{typeof item[spec.column] === 'boolean' ? (item[spec.column] ? '活着' : '已故') : String(item[spec.column] || '（空）')}</dd></div>)}</dl></section>}
      {style === 'ladder' && <><section><h3 className="mb-2 text-xs text-ink-2">总说明</h3>{field('content', item.content ?? '')}</section><ol className="space-y-4">{item.levels?.map((level, index) => <li className="relative border-l-2 border-chief/25 pl-4" key={index}><span className="absolute top-1 -left-[9px] flex size-4 items-center justify-center rounded-full bg-chief-soft text-[10px] text-chief">{index + 1}</span><div className="font-bold">{field(`levels.${index}.name`, level.name)}</div><div className="mt-2">{field(`levels.${index}.text`, level.text, undefined, '（还没写介绍）')}</div></li>)}</ol><Button variant="ghost" size="sm" onClick={() => { setAddingLevel(true); setEditing(true) }}>＋加一级</Button></>}
      {style === 'paragraph' && <><section className="text-sm"><h3 className="mb-2 text-xs text-ink-3">一句话</h3>{field('one_line', item.one_line)}</section><section>{field('content', item.content ?? '')}</section></>}
      {item.categoryKey === '世界与地图' && <label className="block space-y-2 text-sm"><span className="text-ink-2">属于哪里</span><select aria-label="属于哪里" className={clsx(inputClass, 'w-full')} value={item.parent_id ?? ''} disabled={update.isPending} onChange={event => change({ parent_id: event.target.value || null })}><option value="">不属于其他地方</option>{parentChoices(library.entries, item).map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>}
      {item.categoryKey === '往事与秘密' && <section aria-label="信息差" className="space-y-3">
        <h3 className="flex items-center gap-2 text-sm font-medium"><EyeOff className="size-4" />信息差<span className="text-xs font-normal text-ink-3">谁知道、读者知不知道、打算怎么揭开</span></h3>
        {secret ? <SecretCard secret={secret} characters={bible.data?.characters ?? []} nodes={nodes.data ?? []} />
          : <p className="rounded-xl border border-dashed border-line-2 p-4 text-sm text-ink-2">还没记谁知道这件事。<button type="button" disabled={secretActions.create.isPending} onClick={() => void linkSecret()} className="ml-1 text-chief hover:underline">记一笔</button></p>}
        {!!secrets.data?.length && <label className="flex items-center gap-2 text-xs text-ink-3">换成另一条：<select aria-label="关联信息差" value={item.secret_id ?? ''} disabled={update.isPending} onChange={event => change({ secret_id: event.target.value || null })} className="min-w-0 flex-1 rounded-md border border-line bg-card px-2 py-1 text-ink"><option value="">不关联</option>{secrets.data.map(row => <option key={row.id} value={row.id}>{row.code} · {row.title}</option>)}</select></label>}
        <ErrorText error={secretActions.create.error} />
      </section>}
      {rewrite.isPending && <p role="status" className="text-sm text-chief">主编正在想……</p>}
      {!!suggestions.length && <SuggestionInbox bookId={bookId} suggestions={suggestions} library={library} onJump={onJump} compact />}
      <ErrorText error={localError ?? update.error ?? remove.error ?? inspect.error ?? rewrite.error ?? versions.error ?? secrets.error} />
    </div>
    {editing && <EditItemModal bookId={bookId} item={item} category={category} library={library} config={config} addLevel={addingLevel} onClose={() => setEditing(false)} />}
  </article>
}

/** 人物关系写在角色卡里：和谁、什么关系、补充一句。 */
function CharacterRelations({ bookId, characterId }: { bookId: string; characterId: string }) {
  const { working } = useBookContext()
  const { data: bible } = useBible(bookId)
  const { create, update, remove } = useBibleMutations(bookId, 'relationships')
  const [target, setTarget] = useState('')
  const [kind, setKind] = useState('')
  const characters = bible?.characters ?? []
  const names = Object.fromEntries(characters.map(row => [row.id, row.name]))
  const rows = (bible?.relationships ?? []).filter(row => row.source_id === characterId || row.target_id === characterId)
  const others = characters.filter(row => row.id !== characterId)
  return <section aria-label="人物关系">
    <h3 className="mb-2.5 flex items-center gap-2 text-sm font-medium"><Link2 className="size-4" />人物关系</h3>
    <div className="space-y-2">{rows.map(row => {
      const other = row.source_id === characterId ? row.target_id : row.source_id
      return <div key={row.id} className="group flex items-start gap-3 rounded-xl bg-subtle px-3 py-2.5 text-sm">
        <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-ink-2 font-serif text-xs text-on-role">{(names[other] ?? '？').slice(0, 1)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><b className="font-medium">{names[other] ?? '（已删除）'}</b><EditableText value={row.kind} onSave={value => update.mutateAsync({ id: row.id, kind: value })} locked={working} className="text-ink-2" /></div>
          <EditableText value={row.description} onSave={value => update.mutateAsync({ id: row.id, description: value })} locked={working} multiline placeholder="（补充一句，比如之间有什么张力）" className="mt-0.5 text-[13px] text-ink-3" />
        </div>
        {!working && <button type="button" aria-label={`删除和${names[other]}的关系`} onClick={() => remove.mutate(row.id)} className="rounded p-1 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:text-seal focus-visible:opacity-100"><Trash2 className="size-4" /></button>}
      </div>
    })}</div>
    {!rows.length && <p className="text-[13px] text-ink-3">还没记下和其他人的关系。</p>}
    {!working && others.length > 0 && <form className="mt-2.5 flex flex-wrap items-center gap-2" onSubmit={async event => { event.preventDefault(); if (!target || !kind.trim()) return; await create.mutateAsync({ source_id: characterId, target_id: target, kind: kind.trim(), description: '' }); setKind(''); setTarget('') }}>
      <select aria-label="和谁" value={target} onChange={event => setTarget(event.target.value)} className="h-8 rounded-lg border border-line-2 bg-card px-2 text-[13px]"><option value="">和谁…</option>{others.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select>
      <input aria-label="什么关系" value={kind} onChange={event => setKind(event.target.value)} placeholder="什么关系，如 师徒、死敌" className="h-8 min-w-0 flex-1 rounded-lg border border-line-2 bg-card px-2.5 text-[13px] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
      <Button type="submit" size="sm" variant="outline" disabled={!target || !kind.trim()} loading={create.isPending}><Plus className="size-3.5" />加一条</Button>
    </form>}
    <ErrorText error={create.error ?? update.error ?? remove.error} />
  </section>
}

const ROLE_TONE: Record<string, string> = { 主角: 'bg-seal-soft text-seal-dark', 女主: 'bg-lore-soft text-lore', 男主: 'bg-lore-soft text-lore', 对手: 'bg-reviewer-soft text-reviewer' }
const CATEGORY_ICON: Record<string, typeof Users> = { 角色卡片: Users, 等级体系: Layers, 世界与地图: Globe2, 势力划分: Flag, 物品与功法: Gem, 往事与秘密: EyeOff, 特殊规则: ScrollText }

function EntryCard({ row, config, relations, secret, suggested, selected, onOpen }: { row: LibraryRow; config: LibraryConfig; relations: { name: string; kind: string }[]; secret?: Secret; suggested: boolean; selected: boolean; onOpen: () => void }) {
  const later = row.status === 'later'
  const tag = row.targetType === 'character' ? row.role_type : row.tags[0]
  const lines: [string, string][] = row.targetType === 'character'
    ? ([['想要', row.goal ?? ''], ['能力', row.abilities ?? ''], ['性格', row.personality ?? '']] as [string, string][]).filter(([, value]) => value).slice(0, 2)
    : (row.fields ?? []).filter(field => field.value).slice(0, 2).map(field => [field.name, field.value])
  const text = row.one_line || (row.targetType === 'character' ? row.background : row.content) || ''
  const ladder = row.style === 'ladder' && !!row.levels?.length
  return <button type="button" data-testid={`library-item-${row.id}`} aria-current={selected ? 'true' : undefined} onClick={onOpen}
    className={clsx('relative flex min-h-32 flex-col rounded-2xl border bg-card p-4 text-left shadow-[var(--shadow-paper)] transition-[border-color,box-shadow,transform] hover:-translate-y-px hover:border-line-2 motion-reduce:hover:translate-y-0',
      selected ? 'border-chief shadow-[0_0_0_1.5px_var(--color-chief)]' : 'border-line', later && 'opacity-75', ladder && 'col-span-full')}>
    <span className="flex w-full items-center gap-2 pr-6">
      <span className="min-w-0 truncate font-serif text-lg font-bold text-ink">{row.name}</span>
      {tag && <span className={clsx('shrink-0 rounded-md px-1.5 text-xs leading-5', ROLE_TONE[tag] ?? 'bg-subtle text-ink-2 ring-1 ring-line')}>{tag}</span>}
      {later && <span className="shrink-0 text-xs text-ink-3">{config.statuses[row.status]}</span>}
      {suggested && <span aria-label="有待处理建议" className="size-1.5 shrink-0 rounded-full bg-seal" />}
    </span>
    {row.locked && <LockKeyhole aria-label="已锁住" className="absolute top-4 right-4 size-3.5 text-ink-3" />}
    {text && <span className={clsx('mt-1.5 text-sm leading-relaxed text-ink-2', ladder ? 'line-clamp-1' : 'line-clamp-3')}>{text}</span>}
    {ladder && <span className="mt-3 flex w-full gap-0 overflow-hidden">{row.levels!.slice(0, 9).map((level, index) => <span key={index} className="min-w-0 flex-1 border-t-[3px] px-2.5 pt-2 text-[13px] leading-snug text-ink-2" style={{ borderColor: `color-mix(in srgb, var(--color-ink) ${18 + index * 9}%, transparent)` }}><b className="block truncate font-serif text-[15px] text-ink">{level.name}</b><span className="line-clamp-2">{level.text}</span></span>)}</span>}
    {!!lines.length && <span className="mt-2.5 flex flex-col gap-1 text-[13px] text-ink-2">{lines.map(([label, value]) => <span key={label} className="line-clamp-1"><span className="mr-1.5 text-ink-3">{label}</span>{value}</span>)}</span>}
    {secret && <span className="mt-2.5 flex flex-col gap-1 text-[13px] text-ink-2"><span className="line-clamp-1"><span className="mr-1.5 text-ink-3">谁知道</span>{secret.knowers.length ? secret.knowers.map(knower => knower.name).join('、') : '还没记'}</span><span><span className="mr-1.5 text-ink-3">读者</span>{secret.reader_knows ?? '未标注'}</span></span>}
    {!!relations.length && <span className="mt-auto flex flex-wrap gap-1.5 pt-3">{relations.slice(0, 3).map((relation, index) => <span key={index} className="inline-flex max-w-full items-center gap-1 rounded-md bg-subtle px-1.5 text-xs leading-5 text-ink-2 ring-1 ring-line"><Link2 className="size-3 shrink-0" /><span className="truncate">{relation.name} · {relation.kind}</span></span>)}{relations.length > 3 && <span className="text-xs leading-5 text-ink-3">等 {relations.length} 条</span>}</span>}
  </button>
}

export function LibraryPage() {
  const { bookId, book, job, working, manualNavigate, outline } = useBookContext()
  const config = useLibraryConfig()
  const library = useLibrary(bookId)
  const suggestions = useLibrarySuggestions(bookId)
  const actions = useLibrarySuggestionActions(bookId)
  const categoryActions = useLibraryCategoryActions(bookId)
  const bible = useBible(bookId)
  const secrets = useSecrets(bookId)
  const [params] = useSearchParams()
  const [mustOnly, setMustOnly] = useState(false)
  const [suggestionsOnly, setSuggestionsOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [add, setAdd] = useState<string | null>(null)
  const [categoryEditor, setCategoryEditor] = useState<LibraryCategory | 'new' | null>(null)
  const [localError, setLocalError] = useState<unknown>(null)
  const focus = params.get('view') === 'focus'
  const category = library.data?.categories.find(row => row.key === params.get('cat'))
  const data = library.data
  const statusOrder = config.data ? Object.keys(config.data.statuses) : []
  const all = data ? libraryRows(data) : []
  const selected = all.find(row => row.id === params.get('id'))
  const suggested = new Set((suggestions.data ?? []).map(suggestionTargetId))
  const total = all.length
  const must = data?.categories.reduce((sum, row) => sum + row.must_count, 0) ?? 0
  const settingUp = job?.kind === 'book_setup' && working
  const filters = { mustOnly, suggestionsOnly, search }
  const sections = !data || !config.data ? [] : focus
    ? [{ key: 'focus', name: '重点', rows: filterLibraryRows(data, suggestions.data ?? [], { ...filters, focus: true }, statusOrder), row: undefined }]
    : data.categories.filter(row => !category || row.key === category.key).map(row => ({ key: row.key, name: row.name, rows: filterLibraryRows(data, suggestions.data ?? [], { ...filters, category: row.key }, statusOrder), row }))
  const query = (next: { cat?: string | null; focus?: boolean; id?: string | null }) => {
    const out = new URLSearchParams()
    const cat = next.cat === undefined ? category?.key : next.cat
    const isFocus = next.focus ?? (next.cat === undefined ? focus : false)
    if (isFocus) out.set('view', 'focus'); else if (cat) out.set('cat', cat)
    const id = next.id === undefined ? selected?.id : next.id
    if (id) out.set('id', id)
    const text = out.toString()
    manualNavigate(`/books/${bookId}/library${text ? `?${text}` : ''}`)
  }
  const jumpSuggestion = (suggestion: LibrarySuggestion) => {
    const id = suggestionTargetId(suggestion)
    const row = all.find(item => item.id === id)
    if (row) { setMustOnly(false); setSuggestionsOnly(false); setSearch(''); query({ id: row.id }) }
    else if (suggestion.target_type === 'concept') manualNavigate(`/books/${bookId}/concept`)
    else if (suggestion.target_type && id && ['segment', 'volume', 'unit'].includes(suggestion.target_type)) {
      const reference = suggestion.target_type === 'volume' ? outline?.volumes.find(volume => volume.id === id)?.index ?? id : id
      manualNavigate(`/books/${bookId}/outline?node=${suggestion.target_type}-${reference}`)
    }
  }
  const removeCategory = async (row: LibraryCategory) => {
    if (!row.id) return
    if (row.count) { setLocalError(new Error(`这个类别下还有 ${row.count} 条设定，先删掉或挪走`)); return }
    if (!window.confirm(`删除「${row.name}」这个自建类别？`)) return
    try { await categoryActions.remove.mutateAsync(row.id); query({ cat: null }) } catch { /* 显示接口错误 */ }
  }
  useEffect(() => {
    if (!selected) return
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape' && !document.querySelector('[role="dialog"]')) query({ id: null }) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  })
  const names = Object.fromEntries((bible.data?.characters ?? []).map(row => [row.id, row.name]))
  const relationsOf = (id: string) => (bible.data?.relationships ?? []).filter(row => row.source_id === id || row.target_id === id).map(row => ({ name: names[row.source_id === id ? row.target_id : row.source_id] ?? '？', kind: row.kind }))
  const pane = typeof document === 'undefined' ? null : document.getElementById('manuscript-pane')
  const indexButton = (key: string, label: string, count: number, active: boolean, onClick: () => void, Icon: typeof Users) => <button key={key} type="button" aria-current={active ? 'true' : undefined} onClick={onClick}
    className={clsx('flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-[15px] transition-colors', active ? 'bg-card font-semibold text-ink shadow-[var(--shadow-paper)]' : 'text-ink-2 hover:bg-line/50 hover:text-ink')}>
    <Icon className="size-4 shrink-0" /><span className="min-w-0 flex-1 truncate">{label}</span><span className="text-[13px] font-normal text-ink-3 tabular-nums">{count || ''}</span>
  </button>
  return <section data-testid="library-page">
    <SetupGate piece="settings" />
    <PageHeader eyebrow="书稿 · 设定" title="设定"
      subtitle={data ? total ? `共 ${total} 条${must ? ` · 现在要定 ${must} 条` : ''}${settingUp ? ' · 编辑部还在补' : ''}` : '人物、世界、等级、势力、物品、往事与秘密、特殊规则，都放在这里。' : undefined}
      action={<>
        <Button size="sm" variant="outline" disabled={actions.inspect.isPending} onClick={() => actions.inspect.mutate({ mode: 'fill-gaps' })}><Sparkles className="size-3.5" />让 AI 补漏</Button>
        <Button size="sm" variant="outline" disabled={actions.inspect.isPending || !total} onClick={() => actions.inspect.mutate({ mode: 'review' })}>全部查一遍</Button>
        <Button size="sm" variant="primary" disabled={!data || !config.data} onClick={() => setAdd(category?.key ?? '')}><Plus className="size-3.5" />新增</Button>
      </>} />
    {actions.inspect.isPending && <p role="status" className="mb-4 flex items-center gap-2 text-sm text-chief"><span className="size-1.5 rounded-full bg-chief motion-safe:animate-pulse" />主编正在想……结果会放进待处理的建议，也会在群聊里告诉你。</p>}
    <ErrorText error={config.error ?? library.error ?? suggestions.error ?? actions.inspect.error ?? categoryActions.remove.error ?? localError} />
    {!!suggestions.data?.length && <SuggestionInbox bookId={bookId} suggestions={suggestions.data} library={data} onJump={jumpSuggestion} />}
    {(config.isLoading || library.isLoading) && <div className="grid gap-4 @3xl/manuscript:grid-cols-3"><Skeleton className="h-36" /><Skeleton className="h-36" /><Skeleton className="h-36" /></div>}
    {data && config.data && !total && <div className="rounded-2xl border-[1.5px] border-dashed border-line-2 bg-card/50 px-6 py-16 text-center">
      <BookMarked aria-hidden className="mx-auto size-7 text-ink-3" />
      <p className="mt-3 font-serif text-xl font-bold text-ink">设定还空着</p>
      <p className="mx-auto mt-2 max-w-lg text-sm leading-relaxed text-ink-2">{job?.kind === 'book_setup' && !book.concept.story ? '在群聊里聊定了，「总结一下」再「按这个来」，聊出来的人和事会直接写进来；挑了故事方向，编辑部也会一口气建好。想好的设定也可以先自己写几条。' : '可以自己先写一条，也可以让 AI 按定调补一遍。'}</p>
      <Button className="mt-5" variant="outline" onClick={() => setAdd('')}><Plus className="size-4" />自己先写一条</Button>
    </div>}
    {data && config.data && !!total && <>
      <div className="mb-5 flex flex-wrap items-center gap-2.5">
        <label className="relative w-full max-w-xs"><Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3" /><input aria-label="搜索设定" className="h-9 w-full rounded-xl border border-line-2 bg-card pr-3 pl-9 text-sm placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜人名、地名、设定…" /></label>
        {([['只看现在要定', mustOnly, setMustOnly], ['只看有建议', suggestionsOnly, setSuggestionsOnly]] as const).map(([label, value, set]) => <button key={label} type="button" aria-pressed={value} onClick={() => set(!value)} className={clsx('rounded-full border px-3 py-1.5 text-[13px] transition-colors', value ? 'border-chief/40 bg-chief-soft text-chief' : 'border-line-2 bg-card text-ink-2 hover:text-ink')}>{label}</button>)}
      </div>
      <div className="grid items-start gap-7 @3xl/manuscript:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="设定类别" className="flex flex-col gap-0.5 @3xl/manuscript:sticky @3xl/manuscript:top-0 max-[700px]:flex-row max-[700px]:overflow-x-auto">
          {indexButton('all', '全部', total, !focus && !category, () => query({ cat: null, focus: false }), BookMarked)}
          {indexButton('focus', '重点', data.focus.characters.length + data.focus.entries.length, focus, () => query({ focus: true }), Star)}
          {data.categories.map(row => indexButton(row.key, row.name, row.count, !focus && category?.key === row.key, () => query({ cat: row.key }), CATEGORY_ICON[row.key] ?? Tags))}
          <button type="button" onClick={() => setCategoryEditor('new')} className="mt-1 flex items-center gap-2.5 rounded-xl px-3 py-2 text-[15px] text-chief hover:bg-line/50"><Plus className="size-4" />自建类别</button>
        </nav>
        <div className="min-w-0 space-y-9">
          {sections.map(section => {
            const Icon = section.key === 'focus' ? Star : CATEGORY_ICON[section.key] ?? Tags
            const empty = !section.rows.length
            return <section key={section.key} aria-label={section.name}>
              <h2 className="mb-3.5 flex flex-wrap items-center gap-2.5 text-[17px] font-semibold"><Icon className="size-[18px]" />{section.name}<span className="text-sm font-normal text-ink-3">{section.rows.length || ''}</span>
                {section.key === '角色卡片' && <span className="text-[13px] font-normal text-ink-3">人物关系写在每张卡里</span>}
                {section.key === '往事与秘密' && <span className="text-[13px] font-normal text-ink-3">谁知道、读者知不知道、怎么揭开，都在卡里</span>}
                {empty && <span className="text-[13px] font-normal text-ink-3">{search || mustOnly || suggestionsOnly ? '没有符合条件的' : '还空着'}</span>}
                {section.row && !section.row.builtin && <span className="ml-1 flex gap-3 text-[13px] font-normal"><button type="button" className="text-chief hover:underline" onClick={() => setCategoryEditor(section.row!)}>改这个类别</button><button type="button" className="text-ink-3 hover:text-seal hover:underline" onClick={() => void removeCategory(section.row!)}>删掉</button></span>}
                {section.row && empty && <button type="button" onClick={() => setAdd(section.key)} className="ml-auto flex items-center gap-1 text-[13px] font-normal text-chief hover:underline"><Plus className="size-3.5" />新增</button>}
              </h2>
              {!empty && <div className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-3.5">
                {section.rows.map(row => <EntryCard key={row.id} row={row} config={config.data!} relations={row.targetType === 'character' ? relationsOf(row.id) : []} secret={row.categoryKey === '往事与秘密' ? secrets.data?.find(item => item.id === row.secret_id) : undefined} suggested={suggested.has(row.id)} selected={selected?.id === row.id} onOpen={() => query({ id: row.id })} />)}
                {section.row && section.row.style !== 'ladder' && <button type="button" onClick={() => setAdd(section.key)} className="flex min-h-32 items-center justify-center gap-1.5 rounded-2xl border-[1.5px] border-dashed border-line-2 text-sm text-ink-3 transition-colors hover:border-ink-3 hover:text-ink-2"><Plus className="size-4" />新增{section.name.replace('卡片', '')}</button>}
              </div>}
            </section>
          })}
        </div>
      </div>
    </>}
    {selected && data && config.data && pane && createPortal(<aside aria-label="设定详情" className="absolute top-14 right-0 bottom-0 z-[5] flex w-full flex-col border-l border-line bg-card shadow-[-18px_0_40px_-24px_rgb(40_25_10/0.35)] @3xl/manuscript:w-[min(540px,48%)]">
      <LibraryDetail key={selected.id} bookId={bookId} item={selected} library={data} config={config.data} suggestions={(suggestions.data ?? []).filter(suggestion => suggestionTargetId(suggestion) === selected.id)} onDeleted={() => query({ id: null })} onJump={jumpSuggestion} onClose={() => query({ id: null })} />
    </aside>, pane)}
    {add !== null && data && config.data && <NewItemModal bookId={bookId} categories={data.categories} defaultCategory={add || undefined} config={config.data} onClose={() => setAdd(null)} onCreated={(item, categoryKey) => { setAdd(null); setMustOnly(false); setSuggestionsOnly(false); setSearch(''); query({ cat: categoryKey, focus: false, id: item.id }) }} />}
    {categoryEditor && <CategoryModal key={categoryEditor === 'new' ? 'new' : categoryEditor.id} bookId={bookId} category={categoryEditor === 'new' ? undefined : categoryEditor} config={config.data} onClose={() => setCategoryEditor(null)} onSaved={key => { setCategoryEditor(null); query({ cat: key, focus: false }) }} />}
  </section>
}
