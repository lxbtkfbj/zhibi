import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import clsx from 'clsx'
import { ArrowLeft, ChevronDown, ChevronUp, LockKeyhole, Plus, Search, UnlockKeyhole, X } from 'lucide-react'
import { useSecrets } from '../../../api/hooks'
import { useLibrary, useLibraryCategoryActions, useLibraryConfig, useLibraryItemActions, useLibrarySuggestionActions, useLibrarySuggestions, useRewrite, useTargetVersions } from '../../../api/library'
import type { CategoryInput, LibraryCategory, LibraryConfig, LibraryItem, LibraryItemPatch, LibrarySnapshot, LibrarySuggestion } from '../../../api/library'
import { Button, ErrorText, inputClass, Modal } from '../../../components/ui'
import { RewriteField, TargetHistory } from '../../../components/RewriteField'
import { filterLibraryRows, libraryRows, parentChoices, suggestionAction, suggestionTargetId } from '../../../lib/libraryView'
import type { LibraryRow } from '../../../lib/libraryView'
import { useBookContext } from '../context'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'

const panel = 'rounded-2xl border border-line bg-card'

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
  const [error, setError] = useState<unknown>(null)
  const [skipped, setSkipped] = useState<{ title: string; reason: string }[]>([])
  const [written, setWritten] = useState<string | null>(null)
  const items = library ? libraryRows(library) : []
  // 标题保存的是生成时的锁状态；解锁后不能继续拿旧标题阻止作者接受。
  const locked = (suggestion: LibrarySuggestion) => items.find(item => item.id === suggestion.target_id)?.locked ?? false
  const title = (suggestion: LibrarySuggestion) => items.some(item => item.id === suggestion.target_id) ? suggestion.title.replaceAll('（已锁）', '') : suggestion.title
  const accept = (suggestion: LibrarySuggestion) => {
    setError(null)
    if (locked(suggestion)) { setError(new Error('已锁：AI 不能改这一处，先解锁')); return }
    if (suggestion.kind === 'written') { setWritten(suggestion.id); return }
    resolve.mutate({ id: suggestion.id, action: 'accept' })
  }
  const acceptEvery = async () => {
    if (suggestions.some(item => item.kind === 'written') && !window.confirm('建议中有前文替换。全部接受会把列出的正文旧叫法也一起换掉；你可以先逐条展开查看。确认全部接受？')) return
    try { const result = await acceptAll.mutateAsync(); setSkipped(result.skipped.map(item => ({ title: suggestions.find(row => row.id === item.id)?.title ?? '这条建议', reason: item.reason }))) } catch { /* 显示接口错误 */ }
  }
  const list = <div className="mt-3 space-y-3">{suggestions.map(suggestion => <div key={suggestion.id} className="rounded-xl border border-line bg-card p-3"><div className="flex flex-wrap items-start justify-between gap-2"><button type="button" className="min-w-0 flex-1 text-left text-sm leading-relaxed hover:text-chief" onClick={() => onJump(suggestion)}>{title(suggestion)}{locked(suggestion) && <span className="text-seal">（已锁）</span>}</button><div className="flex gap-1"><Button size="sm" variant="ghost" disabled={resolve.isPending || acceptAll.isPending} onClick={() => accept(suggestion)}>{suggestionAction(suggestion)}</Button><Button size="sm" variant="ghost" disabled={resolve.isPending || acceptAll.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'ignore' })}>{suggestion.kind === 'written' ? '只管以后' : '不用'}</Button></div></div>{suggestion.kind === 'written' && <details className="mt-2 text-xs text-ink-2" open={written === suggestion.id || undefined}><summary className="cursor-pointer">查看前文出现的位置</summary><div className="mt-2 space-y-2">{Array.isArray(suggestion.payload.matches) && (suggestion.payload.matches as { chapter: number; count: number; contexts: string[] }[]).map(match => <div key={match.chapter}><p className="font-medium">第 {match.chapter} 章 · {match.count} 处</p>{match.contexts.map((context, index) => <p key={index} className="mt-1 rounded bg-paper-2 p-2 leading-relaxed">…{context}…</p>)}</div>)}{written === suggestion.id && <Button size="sm" variant="danger" disabled={resolve.isPending} onClick={() => resolve.mutate({ id: suggestion.id, action: 'accept' })}>确认，替换上面的前文</Button>}</div></details>}</div>)}<ErrorText error={error ?? resolve.error ?? acceptAll.error} /></div>
  return <section aria-label={compact ? '这一条的建议' : '待处理的建议'} className={clsx(panel, 'p-4')}>
    {compact ? <><h3 className="text-sm font-medium">这一条的建议</h3>{list}</> : <><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-serif font-bold">待处理的建议 {suggestions.length}</h2><Button size="sm" disabled={resolve.isPending} loading={acceptAll.isPending} onClick={() => void acceptEvery()}>全部接受</Button></div><details className="mt-2"><summary className="cursor-pointer text-sm text-chief">展开建议</summary>{list}</details></>}
    {!compact && <ErrorText error={acceptAll.error} />}
    {!!skipped.length && <div role="status" className="mt-3 rounded-lg bg-seal-soft p-3 text-sm text-seal"><p className="font-medium">以下建议暂未接受：</p>{skipped.map((row, index) => <p key={index} className="mt-2">{row.title}：{row.reason}</p>)}</div>}
  </section>
}

function LibraryDetail({ bookId, item, library, config, suggestions, onDeleted, onJump }: { bookId: string; item: LibraryRow; library: LibrarySnapshot; config: LibraryConfig; suggestions: LibrarySuggestion[]; onDeleted: () => void; onJump: (suggestion: LibrarySuggestion) => void }) {
  const { update, remove } = useLibraryItemActions(bookId)
  const { inspect } = useLibrarySuggestionActions(bookId)
  const rewrite = useRewrite(bookId)
  const versions = useTargetVersions(bookId, item.targetType, item.id)
  const secrets = useSecrets(bookId)
  const [editing, setEditing] = useState(false)
  const [addingLevel, setAddingLevel] = useState(false)
  const [tag, setTag] = useState('')
  const [localError, setLocalError] = useState<unknown>(null)
  const category = library.categories.find(row => row.key === item.categoryKey)
  const style = item.targetType === 'character' ? 'card' : item.style ?? category?.style ?? 'paragraph'
  const fieldNames = category?.fields ?? (item.fields ?? []).map(field => field.name)
  const change = (body: LibraryItemPatch) => { setLocalError(null); update.mutate({ type: item.targetType, id: item.id, body }) }
  const addTag = (value: string) => { if (value.trim() && !item.tags.includes(value.trim())) change({ tags: [...item.tags, value.trim()] }); setTag('') }
  const field = (path: string, value: string, label?: string, emptyText?: string) => <RewriteField bookId={bookId} targetType={item.targetType} targetId={item.id} path={path} value={value} label={label} emptyText={emptyText} locked={item.locked} />
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
  return <article aria-label={`${item.name}详情`} className={clsx(panel, 'p-4 sm:p-5')}>
    <header className="border-b border-line pb-4">
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="min-w-0 break-words font-serif text-2xl font-bold">{item.name}</h2><Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => change({ locked: !item.locked })}>{item.locked ? <LockKeyhole className="size-4" /> : <UnlockKeyhole className="size-4" />}{item.locked ? '已锁住 · 解锁' : '锁住'}</Button></div>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink-2"><span>{category?.name}</span><span>·</span><select className="rounded border border-line bg-paper-2 px-2 py-1 text-ink" aria-label="条目状态" value={item.status} disabled={update.isPending} onChange={event => change({ status: event.target.value })}>{Object.entries(config.statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span>· {config.sources[item.source] ?? item.source}</span><span>· 第 {versions.data?.[0]?.version ?? 1} 版</span></div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">{item.tags.map(value => <button key={value} type="button" disabled={update.isPending} className="inline-flex items-center gap-1 rounded-full bg-chief-soft px-2.5 py-1 text-xs text-chief" onClick={() => change({ tags: item.tags.filter(row => row !== value) })} aria-label={`移除标签${value}`}>{value}<X className="size-3" /></button>)}{config.common_tags.filter(value => !item.tags.includes(value)).map(value => <button key={value} type="button" disabled={update.isPending} className="rounded-full border border-dashed border-line-2 px-2.5 py-1 text-xs text-ink-3 hover:text-chief" onClick={() => addTag(value)}>＋{value}</button>)}<form className="flex gap-1" onSubmit={event => { event.preventDefault(); addTag(tag) }}><input aria-label="新标签" className="w-24 rounded-lg border border-line bg-paper-2 px-2 py-1 text-xs" value={tag} onChange={event => setTag(event.target.value)} placeholder="加标签" /><button className="rounded px-1 text-xs text-chief" type="submit" disabled={!tag.trim() || update.isPending}>添加</button></form></div>
      <div className="mt-3 flex flex-wrap gap-1.5"><Button size="sm" variant="ghost" onClick={() => { setAddingLevel(false); setEditing(true) }}>自己改</Button><TargetHistory bookId={bookId} targetType={item.targetType} targetId={item.id} /><Button size="sm" variant="ghost" loading={inspect.isPending} onClick={() => inspect.mutate({ mode: 'check', target_type: item.targetType, target_id: item.id })}>查一查</Button><Button size="sm" variant="ghost" loading={rewrite.isPending} onClick={fill}>让 AI 先填一版</Button><details className="relative"><summary className="cursor-pointer rounded-xl px-3 py-1.5 text-[13px] text-ink-2">更多</summary><div className="absolute right-0 z-10 mt-1 rounded-xl border border-line bg-paper-2 p-2 shadow-lg"><Button size="sm" variant="danger" loading={remove.isPending} onClick={() => void deleteItem()}>删除这一条</Button></div></details></div>
    </header>
    <div className="mt-5 space-y-5">
      {style === 'card' && <div className="divide-y divide-line">{item.targetType === 'character' ? config.character_category.fields.map(spec => <div key={spec.column} className="grid gap-2 py-3 sm:grid-cols-[7rem_minmax(0,1fr)]"><h3 className="pt-1 text-xs text-ink-2">{spec.name}</h3><div className="min-w-0">{spec.column === 'aliases' ? <p className="text-sm leading-relaxed">{item.aliases?.join('、') || <span className="text-ink-3">（空）</span>}</p> : field(spec.column, String(item[spec.column] ?? ''), undefined, '（空）')}</div></div>) : fieldNames.map(name => <div key={name} className="grid gap-2 py-3 sm:grid-cols-[7rem_minmax(0,1fr)]"><h3 className="pt-1 text-xs text-ink-2">{name}</h3><div className="min-w-0">{field(`fields.${name}`, item.fields?.find(row => row.name === name)?.value ?? '', undefined, '（空）')}</div></div>)}</div>}
      {item.targetType === 'character' && <section className="rounded-xl bg-paper-2 p-4"><h3 className="mb-3 text-sm font-medium">写作中每章更新<span className="ml-2 text-xs font-normal text-ink-3">设定师每章写</span></h3><dl className="space-y-2 text-sm">{config.character_category.state_fields.map(spec => <div className="grid grid-cols-[5rem_minmax(0,1fr)] gap-2" key={spec.column}><dt className="text-ink-2">{spec.name}</dt><dd>{typeof item[spec.column] === 'boolean' ? (item[spec.column] ? '活着' : '已故') : String(item[spec.column] || '（空）')}</dd></div>)}</dl></section>}
      {style === 'ladder' && <><section><h3 className="mb-2 text-xs text-ink-2">总说明</h3>{field('content', item.content ?? '')}</section><ol className="space-y-4">{item.levels?.map((level, index) => <li className="relative border-l-2 border-chief/25 pl-4" key={index}><span className="absolute top-1 -left-[9px] flex size-4 items-center justify-center rounded-full bg-chief-soft text-[10px] text-chief">{index + 1}</span><div className="font-bold">{field(`levels.${index}.name`, level.name)}</div><div className="mt-2">{field(`levels.${index}.text`, level.text, undefined, '（还没写介绍）')}</div></li>)}</ol><Button variant="ghost" size="sm" onClick={() => { setAddingLevel(true); setEditing(true) }}>＋加一级</Button></>}
      {style === 'paragraph' && <><section className="text-sm"><h3 className="mb-2 text-xs text-ink-3">一句话</h3>{field('one_line', item.one_line)}</section><section>{field('content', item.content ?? '')}</section></>}
      {item.categoryKey === '世界与地图' && <label className="block space-y-2 text-sm"><span className="text-ink-2">属于哪里</span><select aria-label="属于哪里" className={clsx(inputClass, 'w-full')} value={item.parent_id ?? ''} disabled={update.isPending} onChange={event => change({ parent_id: event.target.value || null })}><option value="">不属于其他地方</option>{parentChoices(library.entries, item).map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>}
      {item.categoryKey === '往事与秘密' && <section className="rounded-xl bg-paper-2 p-4"><h3 className="text-sm font-medium">谁知道</h3>{secret ? <><p className="mt-2 text-sm">{secret.knowers.length ? secret.knowers.map(row => row.name).join('、') : '还没有知情人'}</p><p className="mt-2 text-xs text-ink-2">读者知不知道：{secret.reader_knows ?? '未标注'}</p></> : <p className="mt-2 text-sm text-ink-3">还没关联信息差</p>}<select aria-label="关联信息差" value={item.secret_id ?? ''} disabled={update.isPending} onChange={event => change({ secret_id: event.target.value || null })} className={clsx(inputClass, 'mt-3 w-full')}><option value="">选择一条信息差</option>{secrets.data?.map(row => <option key={row.id} value={row.id}>{row.code} · {row.title}</option>)}</select></section>}
      {rewrite.isPending && <p role="status" className="text-sm text-chief">主编正在想……</p>}
      {!!suggestions.length && <SuggestionInbox bookId={bookId} suggestions={suggestions} library={library} onJump={onJump} compact />}
      <ErrorText error={localError ?? update.error ?? remove.error ?? inspect.error ?? rewrite.error ?? versions.error ?? secrets.error} />
    </div>
    {editing && <EditItemModal bookId={bookId} item={item} category={category} library={library} config={config} addLevel={addingLevel} onClose={() => setEditing(false)} />}
  </article>
}

export function LibraryPage() {
  const { bookId, job, working, manualNavigate, outline } = useBookContext()
  const config = useLibraryConfig()
  const library = useLibrary(bookId)
  const suggestions = useLibrarySuggestions(bookId)
  const actions = useLibrarySuggestionActions(bookId)
  const categoryActions = useLibraryCategoryActions(bookId)
  const [params] = useSearchParams()
  const [mustOnly, setMustOnly] = useState(false)
  const [suggestionsOnly, setSuggestionsOnly] = useState(false)
  const [search, setSearch] = useState('')
  const [add, setAdd] = useState(false)
  const [categoryEditor, setCategoryEditor] = useState<LibraryCategory | 'new' | null>(null)
  const [localError, setLocalError] = useState<unknown>(null)
  const focus = params.get('view') === 'focus' || !params.has('cat')
  const category = library.data?.categories.find(row => row.key === params.get('cat'))
  const data = library.data
  const pending = job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece' && job.pending.piece === 'settings' ? job.pending : null
  const rows = data && config.data ? filterLibraryRows(data, suggestions.data ?? [], { category: category?.key, focus, mustOnly, suggestionsOnly, search }, Object.keys(config.data.statuses)) : []
  const selected = rows.find(row => row.id === params.get('id')) ?? rows[0]
  const hasExplicitSelection = !!params.get('id') && !!selected
  const suggested = new Set((suggestions.data ?? []).map(suggestionTargetId))
  const navigate = (next: { category?: string; id?: string; focus?: boolean }) => {
    const query = new URLSearchParams(next.focus ? { view: 'focus' } : { cat: next.category ?? category?.key ?? data?.categories[0]?.key ?? '' })
    if (next.id) query.set('id', next.id)
    manualNavigate(`/books/${bookId}/library?${query.toString()}`)
  }
  const jumpSuggestion = (suggestion: LibrarySuggestion) => {
    const id = suggestionTargetId(suggestion)
    const row = data && libraryRows(data).find(item => item.id === id)
    if (row) { setMustOnly(false); setSuggestionsOnly(false); setSearch(''); navigate({ category: row.categoryKey, id: row.id }) }
    else if (suggestion.target_type === 'concept') manualNavigate(`/books/${bookId}/concept`)
    else if (suggestion.target_type && id && ['segment', 'volume', 'unit'].includes(suggestion.target_type)) {
      const reference = suggestion.target_type === 'volume' ? outline?.volumes.find(volume => volume.id === id)?.index ?? id : id
      manualNavigate(`/books/${bookId}/outline?node=${suggestion.target_type}-${reference}`)
    }
  }
  const removeCategory = async () => {
    if (!category?.id) return
    if (category.count) { setLocalError(new Error(`这个类别下还有 ${category.count} 条设定，先删掉或挪走`)); return }
    if (!window.confirm(`删除「${category.name}」这个自建类别？`)) return
    try { await categoryActions.remove.mutateAsync(category.id); navigate({ focus: true }) } catch { /* 显示接口错误 */ }
  }
  return <section data-testid="library-page" className="space-y-5">
    <PageHeader eyebrow="书稿 · 设定库" title="把故事里的人和事，放在手边" subtitle="先看重点；需要的时候，再把一处写清楚。修改只动你选中的地方。" />
    {job?.kind === 'book_setup' && <div aria-label="设定库总结" className="rounded-xl border border-chief/20 bg-chief-soft/50 px-4 py-3 text-sm leading-relaxed text-chief">{pending?.summary || (working ? '重点先出来，其余设定正在补。先看「重点」就行。' : `主编建了 ${(data?.characters.length ?? 0) + (data?.entries.length ?? 0)} 条设定，先看「重点」就行。`)}</div>}
    {!!suggestions.data?.length && <SuggestionInbox bookId={bookId} suggestions={suggestions.data} library={data} onJump={jumpSuggestion} />}
    <nav aria-label="设定类别" className="flex flex-wrap gap-2 max-[768px]:flex-nowrap max-[768px]:overflow-x-auto max-[768px]:pb-2">
      <button type="button" className={clsx('shrink-0 whitespace-nowrap rounded-xl border px-3 py-2 text-sm', focus ? 'border-chief/40 bg-chief-soft text-chief' : 'border-line bg-card text-ink-2')} onClick={() => navigate({ focus: true })}>重点{data && <span className="ml-1.5 text-xs">{data.focus.characters.length + data.focus.entries.length}</span>}</button>
      {data?.categories.map(row => <button type="button" key={row.key} className={clsx('shrink-0 whitespace-nowrap rounded-xl border px-3 py-2 text-sm', !focus && category?.key === row.key ? 'border-chief/40 bg-chief-soft text-chief' : 'border-line bg-card text-ink-2')} onClick={() => navigate({ category: row.key })}>{row.name} <span className="text-xs">{row.count}{row.must_count > 0 && ` · 要定 ${row.must_count}`}</span>{libraryRows(data).some(item => item.categoryKey === row.key && suggested.has(item.id)) && <span className="ml-1.5 inline-block size-1.5 rounded-full bg-seal" aria-label="有待处理建议" />}</button>)}
      <Button size="sm" variant="ghost" disabled={!config.data} onClick={() => setCategoryEditor('new')}><Plus className="size-3.5" />自建类别</Button>
    </nav>
      {!focus && category && !category.builtin && <details className="relative"><summary className="cursor-pointer rounded-xl border border-line px-3 py-2 text-sm">类别更多</summary><div className="absolute right-0 z-10 mt-1 w-40 space-y-1 rounded-xl border border-line bg-paper-2 p-2 shadow-lg"><Button className="w-full" variant="ghost" size="sm" onClick={() => setCategoryEditor(category)}>修改这个类别</Button><Button className="w-full" variant="ghost" size="sm" onClick={() => void removeCategory()}>删除这个类别</Button></div></details>}
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 text-sm">
      <label className="flex items-center gap-2"><input type="checkbox" className="accent-[var(--color-chief)]" checked={mustOnly} onChange={event => setMustOnly(event.target.checked)} />只看现在要定</label>
      <label className="flex items-center gap-2"><input type="checkbox" className="accent-[var(--color-chief)]" checked={suggestionsOnly} onChange={event => setSuggestionsOnly(event.target.checked)} />只看有建议</label>
      <label className="relative min-w-36 flex-1"><Search className="pointer-events-none absolute top-3 left-3 size-4 text-ink-3" /><input aria-label="搜索设定" className={clsx(inputClass, 'w-full pl-9')} value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索…" /></label>
      <Button size="sm" disabled={actions.inspect.isPending} onClick={() => actions.inspect.mutate({ mode: 'fill-gaps' })}>让 AI 补漏</Button>
      <Button size="sm" disabled={actions.inspect.isPending} onClick={() => actions.inspect.mutate({ mode: 'review' })}>全部查一遍</Button>
    </div>
    {actions.inspect.isPending && <p role="status" className="text-sm text-chief">主编正在想……结果会放进待处理的建议，也会在群聊里告诉你。</p>}
    <ErrorText error={config.error ?? library.error ?? suggestions.error ?? actions.inspect.error ?? categoryActions.remove.error ?? localError} />
    {(config.isLoading || library.isLoading) && <p role="status" className="py-10 text-center text-ink-2">正在打开设定库…</p>}
    {data && config.data && <div className="grid items-start gap-4 min-[769px]:grid-cols-[minmax(170px,0.7fr)_minmax(0,2fr)]">
      <aside aria-label="设定条目列表" className={clsx(panel, 'overflow-hidden', hasExplicitSelection && 'max-[768px]:hidden')}>
        <div className="border-b border-line px-4 py-3 text-sm font-medium">{focus ? '重点' : category?.name} <span className="ml-2 text-xs text-ink-3">{rows.length} 条</span></div>
        <div className="max-h-[65vh] overflow-y-auto">{rows.map(row => <button key={row.id} type="button" data-testid={`library-item-${row.id}`} onClick={() => navigate({ category: row.categoryKey, focus, id: row.id })} className={clsx('block w-full border-b border-line/60 py-3 pr-3 text-left transition-colors hover:bg-paper-2', selected?.id === row.id ? 'border-l-2 border-l-chief bg-chief-soft/30' : 'border-l-2 border-l-transparent')} style={{ paddingLeft: `${14 + Math.min(row.depth, 5) * 14}px` }}><span className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="font-medium">{row.name}{suggested.has(row.id) && <span className="ml-1.5 inline-block size-1.5 rounded-full bg-seal" aria-label="有待处理建议" />}</span><span className="text-[11px] text-ink-3">{config.data?.statuses[row.status]}</span></span><span className="mt-1 block truncate text-xs text-ink-2">{row.one_line || '还没有一句话'}</span></button>)}{!rows.length && <p className="px-4 py-8 text-sm leading-relaxed text-ink-3">没有符合条件的条目。换个筛选，或新建一条。</p>}</div>
        <Button variant="ghost" className="m-2" size="sm" onClick={() => setAdd(true)}><Plus className="size-3.5" />新增一条</Button>
      </aside>
      <div className={clsx('min-w-0', !hasExplicitSelection && 'max-[768px]:hidden')}>
        {selected ? <><Button className="mb-3 min-[769px]:hidden" variant="ghost" size="sm" onClick={() => navigate({ category: category?.key, focus })}><ArrowLeft className="size-4" />返回列表</Button><LibraryDetail key={selected.id} bookId={bookId} item={selected} library={data} config={config.data} suggestions={(suggestions.data ?? []).filter(suggestion => suggestionTargetId(suggestion) === selected.id)} onDeleted={() => navigate({ category: category?.key, focus })} onJump={jumpSuggestion} /></> : <div className={clsx(panel, 'px-6 py-14 text-center text-sm text-ink-3')}>从左边选一条，慢慢写清楚。</div>}
      </div>
    </div>}
    <SetupGate piece="settings" />
    {add && data && config.data && <NewItemModal bookId={bookId} categories={data.categories} defaultCategory={category?.key} config={config.data} onClose={() => setAdd(false)} onCreated={(item, categoryKey) => { setAdd(false); setMustOnly(false); setSuggestionsOnly(false); setSearch(''); navigate({ category: categoryKey, id: item.id }) }} />}
    {categoryEditor && <CategoryModal key={categoryEditor === 'new' ? 'new' : categoryEditor.id} bookId={bookId} category={categoryEditor === 'new' ? undefined : categoryEditor} config={config.data} onClose={() => setCategoryEditor(null)} onSaved={key => { setCategoryEditor(null); navigate({ category: key }) }} />}
  </section>
}
