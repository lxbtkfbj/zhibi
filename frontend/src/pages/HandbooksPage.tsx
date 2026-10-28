import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, LoaderCircle, Search, Settings, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { handbookApi, type HandbookDetail, type HandbookFields, type HandbookItem, type HandbookList, type HandbookSave } from '../api/handbooks'
import { PromptEditor } from '../components/PromptEditor'
import { SettingsButton } from '../components/settings/SettingsList'
import { clearHandbookDraftIfUnchanged, handbookDraftChanged, readHandbookDraft, writeHandbookDraft } from '../lib/handbookDrafts'
import { changeHandbookEnabled, compareHandbookParagraphs, visibleHandbooks, type HandbookParagraph } from '../lib/handbookEditor'
import { readPromptReturnContext } from '../lib/promptNavigation'
import { useSettingsModal } from '../lib/settingsModal'
import './prompts.css'
import './presets.css'
import './handbooks.css'

const message = (error: unknown) => error instanceof Error ? error.message : '暂时没能完成，请再试一次。'
const count = (value: number) => value.toLocaleString('zh-CN')
const fieldsOf = ({ name, when, body }: HandbookFields): HandbookFields => ({ name, when, body })
const sourceLabel = (book: HandbookItem) => book.source === 'mine' ? '你写的' : book.modified ? '程序带的 · 你改过' : '程序带的'
const detailLabel = (book: HandbookItem) => `${sourceLabel(book)}${book.source === 'system' && !book.modified ? ' · 没改过' : ` · 保存过 ${book.saved} 次`} · ${count(book.chars)} 字`
const saveKind = (save: HandbookSave) => ({ save: '', create: '新建', use_system: '换回程序带的', restore: `退回到第 ${save.restore_saved} 次保存`, migrated: '从提示词页搬过来' })[save.kind]
const stamp = (value: string) => {
  const date = new Date(value)
  const part = (n: number) => String(n).padStart(2, '0')
  return `${part(date.getMonth() + 1)}-${part(date.getDate())} ${part(date.getHours())}:${part(date.getMinutes())}`
}

function HandbookDialog({ title, onClose, children, wide = false, busy = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close() }, [])
  return <dialog ref={ref} className={clsx('preset-dialog handbook-dialog', wide && 'is-wide')} aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="preset-dialog-heading"><h2>{title}</h2><button type="button" className="prompt-icon-button" aria-label="关闭" disabled={busy} onClick={onClose}><X className="size-5" /></button></div>
    <div className="preset-dialog-body scroll-thin">{children}</div>
  </dialog>
}

function ParagraphPair({ row }: { row: HandbookParagraph }) {
  return <div className={clsx('handbook-comparison-row', `is-${row.kind}`)}>
    <section>{row.kind === 'delete' && <small>程序带的有，你的没有</small>}<pre>{row.left}</pre></section>
    <section>{row.kind === 'add' && <small>你加的</small>}<pre>{row.right}</pre></section>
  </div>
}

function HandbookComparison({ book, mine }: { book: HandbookDetail; mine: HandbookFields }) {
  const system = book.system!
  const comparison = compareHandbookParagraphs(system.body, mine.body)
  const groups: { same: boolean; rows: HandbookParagraph[] }[] = []
  for (const row of comparison.rows) {
    const same = row.kind === 'same', last = groups.at(-1)
    if (last?.same === same) last.rows.push(row)
    else groups.push({ same, rows: [row] })
  }
  return <div className="handbook-comparison">
    <p className="handbook-comparison-summary">改了 {comparison.changed} 段，加了 {comparison.added} 段，删了 {comparison.deleted} 段</p>
    <div className="handbook-comparison-head"><h3>程序带的</h3><h3>你的</h3></div>
    {(['name', 'when'] as const).filter(key => system[key] !== mine[key]).map(key => <div className="handbook-comparison-row handbook-field-comparison" key={key}><section><h4>{key === 'name' ? '名称' : '什么时候翻'}</h4><p>{system[key]}</p></section><section><h4>{key === 'name' ? '名称' : '什么时候翻'}</h4><p>{mine[key]}</p></section></div>)}
    {groups.map((group, index) => group.same ? <details key={index}><summary>一样的 {group.rows.length} 段</summary>{group.rows.map((row, n) => <ParagraphPair row={row} key={n} />)}</details> : <div key={index}>{group.rows.map((row, n) => <ParagraphPair row={row} key={n} />)}</div>)}
  </div>
}

function HandbookForm({ book, draft, busy, onChange }: { book: HandbookDetail; draft: HandbookFields; busy: boolean; onChange: (fields: HandbookFields) => void }) {
  const whenInput = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const resize = () => {
      if (!whenInput.current) return
      whenInput.current.style.height = 'auto'
      whenInput.current.style.height = `${whenInput.current.scrollHeight}px`
    }
    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [draft.when, book.key])
  const dirty = handbookDraftChanged(book, draft)
  return <div className="handbook-form">
    <label className="handbook-field">名称<input aria-label="名称" value={draft.name} disabled={busy} onChange={event => onChange({ ...draft, name: event.target.value })} /><small>主编照这个名字翻它。开着的手册不能重名。</small></label>
    <label className="handbook-field">什么时候翻<textarea ref={whenInput} aria-label="什么时候翻" rows={1} value={draft.when} disabled={busy} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) event.preventDefault() }} onChange={event => onChange({ ...draft, when: event.target.value.replace(/[\r\n\u2028\u2029]+/g, ' ') })} /><small>主编看目录里的这一行决定翻不翻：写清聊到什么的时候翻。</small></label>
    <div className="handbook-body-label">正文</div>
    {dirty && <p className="handbook-draft-note">有没保存的改动：切到别的手册、刷新页面都还在，点「保存」才给主编用。</p>}
    <PromptEditor key={book.key} value={draft.body} editable={!busy} variables={[]} onChange={body => onChange({ ...draft, body })} />
  </div>
}

type Popup = { type: 'compare' } | { type: 'saves'; saves: HandbookSave[]; viewing?: HandbookSave }

export function HandbooksPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const cache = useQueryClient()
  const { returnTo, bookId } = readPromptReturnContext(location.search)
  const { openSettings } = useSettingsModal()
  const list = useQuery({ queryKey: ['handbooks'], queryFn: handbookApi.list })
  const items = list.data?.items ?? []
  const requested = params.get('key')
  const selected = items.some(item => item.key === requested) ? requested! : items[0]?.key ?? null
  const detail = useQuery({ queryKey: ['handbook', selected], queryFn: () => handbookApi.detail(selected!), enabled: selected !== null })
  const [drafts, setDrafts] = useState<Record<string, HandbookFields | null>>({})
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const running = useRef(false)
  const [error, setError] = useState('')
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [optimistic, setOptimistic] = useState<Record<string, boolean>>({})
  const [popup, setPopup] = useState<Popup | null>(null)
  const book = detail.data
  const localDraft = selected ? selected in drafts ? drafts[selected] : readHandbookDraft(selected) : null
  const draft = localDraft ?? (book ? fieldsOf(book) : null)
  const dirty = !!book && !!draft && handbookDraftChanged(book, draft)
  const visible = visibleHandbooks(items, search)
  const choose = (key: string) => {
    setError(''); setPopup(null)
    setParams(previous => { const next = new URLSearchParams(previous); next.set('key', key); return next }, { replace: true })
  }
  useEffect(() => {
    if (!selected || requested === selected) return
    setParams(previous => { const next = new URLSearchParams(previous); next.set('key', selected); return next }, { replace: true })
  }, [selected, requested, setParams])
  const writeDraft = (key: string, value: HandbookFields | null) => {
    writeHandbookDraft(key, value)
    setDrafts(previous => ({ ...previous, [key]: value }))
  }
  const clearDraft = (key: string, expected: HandbookFields | null) => {
    if (clearHandbookDraftIfUnchanged(key, expected)) setDrafts(previous => ({ ...previous, [key]: null }))
  }
  const updateDraft = (fields: HandbookFields) => {
    if (!book) return
    writeDraft(book.key, handbookDraftChanged(book, fields) ? fields : null)
    setError('')
  }
  const run = async (action: () => Promise<void>) => {
    if (running.current) return
    running.current = true; setBusy(true); setError('')
    try { await action() } catch (failure) { setError(message(failure)) }
    finally { running.current = false; setBusy(false) }
  }
  const apply = async (updated: HandbookDetail, discardSnapshot?: HandbookFields | null) => {
    cache.setQueryData(['handbook', updated.key], updated)
    cache.setQueryData<HandbookList>(['handbooks'], previous => previous ? { ...previous, items: previous.items.map(item => item.key === updated.key ? updated : item) } : previous)
    const currentDraft = readHandbookDraft(updated.key)
    if (discardSnapshot !== undefined) clearDraft(updated.key, discardSnapshot)
    else if (currentDraft && !handbookDraftChanged(updated, currentDraft)) clearDraft(updated.key, currentDraft)
    setRowErrors(previous => ({ ...previous, [updated.key]: '' }))
    await cache.invalidateQueries({ queryKey: ['handbooks'] })
  }
  const toggle = (item: HandbookItem) => run(async () => {
    setRowErrors(previous => ({ ...previous, [item.key]: '' }))
    setOptimistic(previous => ({ ...previous, [item.key]: !item.enabled }))
    try {
      const result = await changeHandbookEnabled(item, enabled => handbookApi.enabled(item.key, enabled))
      if (result.error) setRowErrors(previous => ({ ...previous, [item.key]: result.error }))
      else {
        await cache.invalidateQueries({ queryKey: ['handbook', item.key] })
        await cache.invalidateQueries({ queryKey: ['handbooks'] })
      }
    } finally { setOptimistic(previous => { const next = { ...previous }; delete next[item.key]; return next }) }
  })
  const save = () => {
    if (!book || !draft) return
    const submitted = fieldsOf(draft)
    return run(async () => { await apply(await handbookApi.save(book.key, submitted), submitted) })
  }
  const discard = () => { if (book && draft && window.confirm('改的还没保存，确定不要了吗？')) { clearDraft(book.key, fieldsOf(draft)); setError('') } }
  const useSystem = () => {
    if (!book || !window.confirm(`换回程序带的？你改的这份会留在保存记录里，随时能退回来。${dirty ? '没保存的改动会丢掉。' : ''}`)) return
    const discardSnapshot = readHandbookDraft(book.key)
    void run(async () => { await apply(await handbookApi.useSystem(book.key), discardSnapshot); setPopup(null) })
  }
  const showSaves = () => run(async () => { if (book) setPopup({ type: 'saves', saves: await handbookApi.saves(book.key) }) })
  const restore = (saved: number) => {
    if (!book || !window.confirm(`退回到第 ${saved} 次保存？现在的会另存一次，不会丢。`)) return
    void run(async () => {
      // Browser drafts are not saved versions. Keep them until the author explicitly saves or discards them.
      await apply(await handbookApi.restore(book.key, saved))
      setPopup({ type: 'saves', saves: await handbookApi.saves(book.key) })
    })
  }
  const remove = () => {
    if (!book || !window.confirm(`删掉「${book.name}」？保存记录也一起删，删了找不回来。`)) return
    const discardSnapshot = readHandbookDraft(book.key)
    void run(async () => {
      await handbookApi.remove(book.key); clearDraft(book.key, discardSnapshot); setPopup(null)
      cache.setQueryData<HandbookList>(['handbooks'], previous => previous ? { ...previous, items: previous.items.filter(item => item.key !== book.key) } : previous)
      cache.removeQueries({ queryKey: ['handbook', book.key] })
      await cache.invalidateQueries({ queryKey: ['handbooks'] })
    })
  }
  const create = () => run(async () => {
    const created = await handbookApi.create()
    setSearch(''); cache.setQueryData(['handbook', created.key], created)
    await cache.invalidateQueries({ queryKey: ['handbooks'] }); choose(created.key)
  })
  const listDraft = (key: string) => key in drafts ? drafts[key] : readHandbookDraft(key)
  const listDirty = (key: string) => {
    const stored = listDraft(key), committed = cache.getQueryData<HandbookDetail>(['handbook', key])
    return !!stored && (!committed || handbookDraftChanged(committed, stored))
  }
  const popupTitle = popup?.type === 'compare' ? `跟程序带的比一比${dirty ? '（含没保存的）' : ''}` : popup?.viewing ? `第 ${popup.viewing.saved} 次保存` : '保存记录'

  return <div className="handbooks-page presets-page desk-zoom">
    <header className="prompts-topbar"><Link to={returnTo} className="prompts-return"><ArrowLeft className="size-4" />{bookId ? '返回当前书' : '返回书房'}</Link><button type="button" className="prompt-icon-button ml-auto" aria-label="系统设置" title="系统设置" onClick={openSettings}><Settings className="size-5" /></button></header>
    <main className="handbooks-main">
      <div className="presets-heading"><div><h1>手册管理</h1><p>编辑部在群聊里聊到手册管的事，会先翻那本再答；翻哪本，看目录里每本的「什么时候翻」。私聊和拆的书里不翻。改了点「保存」才生效，所有书都用同一套。</p></div></div>
      {list.isPending && <div className="preset-loading" role="status"><LoaderCircle className="size-5 animate-spin" />正在读取手册…</div>}
      {list.isError && <div className="preset-error" role="alert">{message(list.error)} <button type="button" className="prompt-text-link" onClick={() => void list.refetch()}>重试</button></div>}
      {list.data && <div className="handbooks-workspace">
        <aside className="handbook-directory handbook-list-panel">
          <div className="preset-column-heading"><h2>手册</h2><span>{items.length} 本 · {items.filter(item => item.enabled).length} 本开着</span></div>
          <label className="prompt-search"><Search className="size-4" /><input aria-label="搜名称或什么时候翻" placeholder="搜名称或什么时候翻" value={search} onChange={event => setSearch(event.target.value)} /></label>
          <nav className="handbook-list scroll-thin" aria-label="手册列表">{visible.map(item => <div key={item.key} data-handbook-key={item.key} className={clsx('handbook-row', selected === item.key && 'is-selected', !item.enabled && 'is-off')}>
            <button type="button" aria-label={item.name} aria-current={selected === item.key ? 'page' : undefined} disabled={busy} className="handbook-select" onClick={() => choose(item.key)}><span>{item.name}{listDirty(item.key) && <i className="preset-unsaved-dot" aria-label="有没保存的改动" />}</span><small>{sourceLabel(item)}{item.system_updated ? ' · 有新版' : ''}</small></button>
            <button type="button" role="switch" aria-label={`${item.name}开关`} aria-checked={optimistic[item.key] ?? item.enabled} disabled={busy} title="开着：主编能翻；关着：主编翻不到" className={clsx('settings-toggle', (optimistic[item.key] ?? item.enabled) && 'is-on')} onClick={() => void toggle(item)}><span /></button>
            {rowErrors[item.key] && <p className="handbook-row-error" role="alert">{rowErrors[item.key]}</p>}
          </div>)}{!visible.length && <p className="handbook-empty">没有找到匹配的手册。</p>}</nav>
          <div className="handbook-directory-footer"><SettingsButton disabled={busy} onClick={() => void create()}>新建手册</SettingsButton></div>
          <details className="handbook-catalog-details"><summary>主编看到的目录</summary>{list.data.catalog ? <pre className="handbook-catalog" data-testid="handbook-catalog">{list.data.catalog}</pre> : <p>现在没有开着的手册：主编不会翻手册，预设里「工具：翻手册」那块也不发。</p>}</details>
        </aside>
        <section className="handbook-editor scroll-thin" aria-label="选中的手册">
          {detail.isPending && selected && <div className="preset-loading" role="status"><LoaderCircle className="size-5 animate-spin" />正在读取手册…</div>}
          {detail.isError && <div className="preset-error" role="alert">{message(detail.error)} <button type="button" className="prompt-text-link" onClick={() => void detail.refetch()}>重试</button></div>}
          {book && draft && <>
            <div className="handbook-selected-summary"><div><h2>{book.name}</h2><p>{detailLabel(book)}</p></div><div className="preset-actions">
              {dirty && <><SettingsButton primary disabled={busy} onClick={() => void save()}>保存</SettingsButton><SettingsButton disabled={busy} onClick={discard}>放弃修改</SettingsButton></>}
              {book.saved > 0 && <SettingsButton disabled={busy} onClick={() => void showSaves()}>保存记录</SettingsButton>}
              {book.source === 'system' && book.modified && <><SettingsButton disabled={busy} onClick={() => { setError(''); setPopup({ type: 'compare' }) }}>跟程序带的比一比</SettingsButton><SettingsButton disabled={busy} onClick={useSystem}>换回程序带的</SettingsButton></>}
              {book.source === 'mine' && <SettingsButton danger disabled={busy} onClick={remove}>删除</SettingsButton>}
            </div></div>
            {error && <p className="preset-error handbook-error" role="alert">{error}</p>}
            {book.source === 'system' && !book.modified && <div className="preset-banner"><p>这本是程序带的。直接改，存了就是你的版本；改坏了，随时能换回程序带的。</p></div>}
            {book.system_updated && <div className="preset-banner handbook-update"><p>程序带的这本后来更新过，你用的还是你改的那份。</p><div className="preset-actions"><SettingsButton disabled={busy} onClick={() => { setError(''); setPopup({ type: 'compare' }) }}>比一比</SettingsButton><SettingsButton disabled={busy} onClick={useSystem}>换成新版</SettingsButton><SettingsButton disabled={busy} onClick={() => void run(async () => { await apply(await handbookApi.seenSystem(book.key)) })}>知道了</SettingsButton></div></div>}
            {!book.enabled && !book.complete && <div className="preset-banner"><p>还没写完：名称、什么时候翻、正文都写上，才能打开给主编翻。</p></div>}
            <HandbookForm book={book} draft={draft} busy={busy} onChange={updateDraft} />
          </>}
          {!items.length && <p className="handbook-empty">还没有手册，点「新建手册」写一本。</p>}
        </section>
      </div>}
      {error && !book && <p className="preset-error" role="alert">{error}</p>}
    </main>
    {popup && book && draft && <HandbookDialog title={popupTitle} wide={popup.type === 'compare' || !!popup.viewing} busy={busy} onClose={() => setPopup(null)}>
      {error && <p className="preset-error" role="alert">{error}</p>}
      {popup.type === 'compare' && book.system && <HandbookComparison book={book} mine={draft} />}
      {popup.type === 'saves' && <>
        {!popup.viewing && <div className="preset-saves-list handbook-saves-list">{[...popup.saves].sort((a, b) => b.saved - a.saved).map(snapshot => <article key={snapshot.saved} data-handbook-save={snapshot.saved}><p>第 {snapshot.saved} 次保存 · {stamp(snapshot.saved_at)} · {count(snapshot.chars)} 字{saveKind(snapshot) ? ` · ${saveKind(snapshot)}` : ''}</p><div><SettingsButton disabled={busy} onClick={() => setPopup({ ...popup, viewing: snapshot })}>看这一版</SettingsButton><SettingsButton disabled={busy} onClick={() => restore(snapshot.saved)}>退回这一版</SettingsButton></div></article>)}</div>}
        {popup.viewing && <section className="handbook-snapshot" aria-label={`第 ${popup.viewing.saved} 次保存`}><h3>第 {popup.viewing.saved} 次保存</h3><h4>名称</h4><p>{popup.viewing.name}</p><h4>什么时候翻</h4><p>{popup.viewing.when}</p><h4>正文</h4><pre>{popup.viewing.body}</pre></section>}
      </>}
    </HandbookDialog>}
  </div>
}
