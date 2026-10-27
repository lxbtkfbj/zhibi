import { useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, GripVertical, LoaderCircle, Pencil, Search, Settings, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useBlocker, useLocation, useSearchParams } from 'react-router-dom'
import { presetApi, PresetApiError, type PresetBlock, type PresetCondition, type PresetDetail, type PresetIssue, type PresetSaveSnapshot, type PresetSelection, type SystemPreset } from '../api/presets'
import { SettingsButton } from '../components/settings/SettingsList'
import { addPresetBlock, blockCharacters, changePresetBlock, comparePresetBlocks, deletePresetBlock, insertPresetPlaceholder, movePresetBlock, presetBlockFields, presetBlockReference, presetDraftChanged, selectedAfterPresetSave, visiblePresetBlocks, type BlockFilter } from '../lib/presetEditor'
import { readPromptReturnContext } from '../lib/promptNavigation'
import { useSettingsModal } from '../lib/settingsModal'
import './prompts.css'
import './presets.css'

const roleLabel = (role: PresetBlock['role']) => ({ system: 'System', user: 'User', assistant: 'Assistant' })[role]
const stamp = (date: string) => new Date(date).toLocaleString('zh-CN', { hour12: false })
const message = (error: unknown) => error instanceof Error ? error.message : '暂时没能完成，请再试一次。'
const basisVersion = (preset: PresetDetail | null) => preset?.source === 'system' ? preset.version : preset?.based_on.source === 'system' ? preset.based_on.version : preset?.based_on.source === 'mine' ? preset.based_on.system_version : undefined

function PresetDialog({ title, onClose, children, wide = false, busy = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean; busy?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close() }, [])
  return <dialog ref={ref} className={clsx('preset-dialog', wide && 'is-wide')} aria-label={title} onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="preset-dialog-heading"><h2>{title}</h2><button type="button" className="prompt-icon-button" aria-label="关闭" disabled={busy} onClick={onClose}><X className="size-5" /></button></div>
    <div className="preset-dialog-body scroll-thin">{children}</div>
  </dialog>
}

function BlockComparison({ left, right, leftLabel, rightLabel }: { left: PresetBlock; right: PresetBlock; leftLabel: string; rightLabel: string }) {
  return <div className="preset-comparison"><section><h3>{leftLabel}</h3><pre>{left.content}</pre></section><section><h3>{rightLabel}</h3><pre>{right.content}</pre></section></div>
}

function ReadOnlyBlocks({ blocks, conditions, systemBlocks }: { blocks: PresetBlock[]; conditions: PresetCondition[]; systemBlocks: PresetBlock[] }) {
  const [selection, setSelection] = useState(blocks[0]?.id ?? '')
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<BlockFilter>('all')
  const content = useRef<HTMLTextAreaElement>(null)
  const block = blocks.find(item => item.id === selection)
  const visible = visiblePresetBlocks(blocks, search, filter)
  const without = (item: PresetBlock) => item.without ?? systemBlocks.find(reference => reference.id === item.id)?.without ?? ''
  useEffect(() => {
    if (!content.current) return
    content.current.style.height = 'auto'
    content.current.style.height = `${Math.max(354, content.current.scrollHeight)}px`
  }, [block?.id, block?.content])
  return <div className="preset-snapshot-layout"><section className="preset-blocks"><div className="preset-column-heading"><h3>预设块</h3><span>{blocks.filter(item => item.enabled).length} / {blocks.length} 开着</span></div><label className="prompt-search"><Search className="size-4" /><input aria-label="搜保存记录块的标题或内容" placeholder="搜块的标题或内容" value={search} onChange={event => setSearch(event.target.value)} /></label><div className="preset-block-filters" role="group" aria-label="筛保存记录的预设块">{([{ value: 'all', label: '全部' }, { value: 'on', label: '开着的' }, { value: 'off', label: '关着的' }] as const).map(item => <button type="button" key={item.value} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>)}</div><p className="preset-block-count">显示 {visible.length} / {blocks.length} 块</p><div className="preset-block-list scroll-thin">{visible.map(({ block: item, index }) => <div key={item.id} className={clsx('preset-block-row', selection === item.id && 'is-selected', !item.enabled && 'is-off')}><button type="button" disabled className="preset-drag-handle" aria-label={`拖动${item.title}`}><GripVertical className="size-3.5" /></button><span className="preset-block-number">{index + 1}</span><button type="button" className="preset-block-select" onClick={() => setSelection(item.id)}><span>{item.title}{item.required && <em>必须</em>}</span><small>{roleLabel(item.role)} · {blockCharacters(item.content)} 字{item.when !== 'always' ? ` · ${conditions.find(condition => condition.when === item.when)?.label ?? item.when}` : ''}</small></button><button type="button" role="switch" aria-label={`${item.title}开关`} aria-checked={item.enabled} className={clsx('settings-toggle', item.enabled && 'is-on')} disabled><span /></button>{item.required && !item.enabled && <p className="preset-without">关了它：{without(item)}</p>}</div>)}</div></section><section className="preset-block-editor scroll-thin">{block && <><div className="preset-block-heading"><h3>{block.title}</h3><span>第 {blocks.indexOf(block) + 1} 块 · {blockCharacters(block.content)} 字</span></div><div className="preset-block-settings"><label>消息角色<select aria-label="保存记录的消息角色" value={block.role} disabled>{(['system', 'user', 'assistant'] as const).map(role => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label><label>什么时候发<select aria-label="保存记录的什么时候发" value={block.when} disabled>{conditions.map(condition => <option key={condition.when} value={condition.when}>{condition.label}</option>)}</select></label></div>{block.required && <p className="preset-required-note">必须的块。关了它：{without(block)}</p>}<textarea ref={content} aria-label="保存记录的预设块内容" readOnly rows={12} value={block.content} /></>}</section></div>
}

type Popup = { type: 'check'; title: string; issues: PresetIssue[] } | { type: 'saves'; snapshots: PresetSaveSnapshot[]; viewing?: PresetSaveSnapshot } | { type: 'compare'; system: SystemPreset } | { type: 'blockCompare'; left: PresetBlock; right: PresetBlock; version: number } | { type: 'origin'; block: PresetBlock; version: number } | { type: 'deleteBlock'; block: PresetBlock } | { type: 'deletePreset' } | { type: 'restore'; snapshot: PresetSaveSnapshot; snapshots: PresetSaveSnapshot[] }

export function PresetsPage() {
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const cache = useQueryClient()
  const { returnTo, bookId } = readPromptReturnContext(location.search)
  const { openSettings } = useSettingsModal()
  const source = params.get('source') === 'mine' && params.get('id') ? 'mine' : 'system'
  const id = source === 'mine' ? params.get('id')! : ''
  const version = Number(params.get('version')) > 0 ? Number(params.get('version')) : undefined
  const selectionKey = source === 'mine' ? `mine:${id}` : `system:${version ?? 'latest'}`
  const detailKey = ['preset', selectionKey]
  const list = useQuery({ queryKey: ['presets'], queryFn: presetApi.list })
  const detail = useQuery<PresetDetail>({ queryKey: detailKey, queryFn: () => source === 'mine' ? presetApi.detail(id) : presetApi.system(version), staleTime: Infinity })
  const conditions = useQuery({ queryKey: ['preset-conditions'], queryFn: presetApi.conditions, staleTime: Infinity })
  const placeholders = useQuery({ queryKey: ['preset-placeholders', bookId], queryFn: async () => {
    try { return await presetApi.placeholders(bookId) }
    catch (error) { if (bookId && error instanceof PresetApiError && error.status === 422) return presetApi.placeholders(); throw error }
  }, retry: false })
  const [original, setOriginal] = useState<PresetDetail | null>(null)
  const [draft, setDraft] = useState<PresetDetail | null>(null)
  const [loadedSelection, setLoadedSelection] = useState('')
  const [search, setSearch] = useState('')
  const [librarySearch, setLibrarySearch] = useState('')
  const [filter, setFilter] = useState<BlockFilter>('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [importError, setImportError] = useState('')
  const [notice, setNotice] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [popup, setPopup] = useState<Popup | null>(null)
  const [pending, setPending] = useState<{ action: () => void | Promise<void> } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const dragged = useRef<string | null>(null)
  const editable = draft?.source === 'mine'
  const dirty = !!original && !!draft && editable && presetDraftChanged(original, draft)
  const blocker = useBlocker(useCallback(({ currentLocation, nextLocation }) => {
    if (!dirty) return false
    if (currentLocation.pathname !== nextLocation.pathname) return true
    const current = new URLSearchParams(currentLocation.search), next = new URLSearchParams(nextLocation.search)
    return ['source', 'id', 'version'].some(key => current.get(key) !== next.get(key))
  }, [dirty]))

  if (detail.data && loadedSelection !== selectionKey) {
    setLoadedSelection(selectionKey)
    setOriginal(detail.data); setDraft(structuredClone(detail.data))
    setSearch(''); setFilter('all'); setRenaming(false); setError(''); setNotice('')
  }
  const requestedBlock = params.get('block')
  const selected = draft?.blocks.some(item => item.id === requestedBlock) ? requestedBlock : draft?.blocks[0]?.id ?? null
  useEffect(() => {
    if (!dirty) return
    const prevent = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])
  const block = draft?.blocks.find(item => item.id === selected)
  const base = basisVersion(draft)
  const baseSystem = useQuery({ queryKey: ['preset-system-base', base], queryFn: () => presetApi.system(base), enabled: base !== undefined, staleTime: Infinity })
  const systemBlocks = draft?.source === 'system' ? draft.blocks : list.data?.system.blocks ?? []
  const { metadata: systemBlock, copied: copiedBlock } = presetBlockReference(block?.id ?? '', systemBlocks, baseSystem.data?.blocks ?? [], base !== undefined)
  const blockModified = !!block && !!copiedBlock && block.content !== copiedBlock.content
  const withoutFor = (item: PresetBlock) => item.without ?? presetBlockReference(item.id, systemBlocks, baseSystem.data?.blocks ?? []).metadata?.without ?? ''
  useEffect(() => {
    if (!textarea.current) return
    textarea.current.style.height = 'auto'
    textarea.current.style.height = `${Math.max(354, textarea.current.scrollHeight)}px`
  }, [block?.id, block?.content])
  const chooseBlock = (blockId: string | null) => {
    setParams(previous => { const next = new URLSearchParams(previous); if (blockId) next.set('block', blockId); else next.delete('block'); return next }, { replace: true })
  }
  const choosePreset = (selection: PresetSelection & { version?: number }) => {
    setPopup(null)
    setParams(previous => { const next = new URLSearchParams(previous); next.set('source', selection.source); if (selection.source === 'mine' && selection.id) next.set('id', selection.id); else next.delete('id'); if (selection.source === 'system' && selection.version) next.set('version', String(selection.version)); else next.delete('version'); next.delete('block'); return next })
  }
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (failure) { setError(message(failure)) } finally { setBusy(false) }
  }
  const refreshList = () => cache.invalidateQueries({ queryKey: ['presets'] })
  const saveDraft = async () => {
    if (draft?.source !== 'mine') return
    const updated = await presetApi.save(draft.id, { name: draft.name, blocks: presetBlockFields(draft.blocks) })
    const nextSelected = selectedAfterPresetSave(draft.blocks, updated.blocks, selected)
    setOriginal(updated); setDraft(structuredClone(updated))
    // Keep a blocked navigation intact: replacing the block query here would
    // complete a different navigation and invalidate the original proceed().
    if (blocker.state !== 'blocked') chooseBlock(nextSelected)
    cache.setQueryData(detailKey, updated)
    setNotice('已保存。')
    await refreshList()
  }
  const guard = (action: () => void | Promise<void>) => { if (dirty) setPending({ action }); else void action() }
  const updateBlock = (change: Partial<PresetBlock>) => {
    if (!editable || busy || !draft || !selected) return
    setDraft({ ...draft, blocks: changePresetBlock(draft.blocks, selected, change) }); setNotice('')
  }
  const copy = (latest = false) => guard(() => run(async () => {
    if (!draft) return
    const created = await presetApi.create(latest ? {} : draft.source === 'mine' ? { source: 'mine', id: draft.id } : { source: 'system', version: draft.version })
    await refreshList(); choosePreset({ source: 'mine', id: created.id })
  }))
  const check = () => run(async () => { if (!draft) return; const checked = await presetApi.check(draft.blocks); setPopup({ type: 'check', title: '检查结果', issues: checked.issues }) })
  const activate = () => guard(() => run(async () => {
    if (!draft) return
    try { await presetApi.activate(draft.source === 'mine' ? { source: 'mine', id: draft.id } : { source: 'system' }); await refreshList(); if (draft.source === 'system' && draft.version !== list.data?.system.version) choosePreset({ source: 'system' }); setNotice('已设为正在用。') }
    catch (failure) { if (failure instanceof PresetApiError && failure.status === 422 && failure.issues.length) setPopup({ type: 'check', title: '这份不能用', issues: failure.issues }); else throw failure }
  }))
  const showSaves = () => run(async () => {
    if (draft?.source !== 'mine') return
    const saves = await presetApi.saves(draft.id)
    const snapshots = await Promise.all(saves.map(save => presetApi.snapshot(draft.id, save.saved)))
    setPopup({ type: 'saves', snapshots })
  })
  const viewOrigin = (originVersion: number) => run(async () => {
    const system = await presetApi.system(originVersion)
    const historical = system.blocks.find(item => item.id === selected)
    if (historical) setPopup({ type: 'origin', block: historical, version: originVersion })
  })
  const insert = (name: string) => {
    if (!editable || busy || !block) return
    const input = textarea.current
    const inserted = insertPresetPlaceholder(block.content, name, input?.selectionStart ?? block.content.length, input?.selectionEnd ?? block.content.length)
    updateBlock({ content: inserted.content })
    requestAnimationFrame(() => { input?.focus(); input?.setSelectionRange(inserted.cursor, inserted.cursor) })
  }
  const importFile = (file: File) => guard(() => run(async () => {
    setImportError('')
    try { const imported = await presetApi.importFile(file); await refreshList(); choosePreset({ source: 'mine', id: imported.id }) }
    catch (failure) { setImportError(message(failure)) }
  }))
  const active = (selection: PresetSelection) => !!list.data && list.data.active.source === selection.source && (selection.source === 'system' || list.data.active.id === selection.id)
  const isActive = draft ? active(draft.source === 'mine' ? { source: 'mine', id: draft.id } : { source: 'system' }) && (draft.source === 'mine' || draft.version === list.data?.system.version) : false
  const libraryItems = list.data ? [{ source: 'system' as const, id: '', name: list.data.system.name, description: `系统 · 第 ${list.data.system.version} 版 · ${list.data.system.blocks.length} 块` }, ...list.data.mine.map(item => ({ ...item, description: `我的 · ${item.block_count} 块 · 保存过 ${item.saved} 次` }))] : []
  const visible = draft ? visiblePresetBlocks(draft.blocks, search, filter) : []
  const enabled = draft?.blocks.filter(item => item.enabled).length ?? 0
  const selectedIndex = draft?.blocks.findIndex(item => item.id === selected) ?? -1
  const basisLabel = draft?.source === 'mine' ? draft.based_on.source === 'system' ? `从系统预设第 ${draft.based_on.version} 版复制` : draft.based_on.source === 'mine' ? (() => { const sourceId = draft.based_on.id; const parent = list.data?.mine.find(item => item.id === sourceId); return parent ? `从「${parent.name}」复制` : '从已删除的预设复制' })() : '导入的' : ''
  const libraryActions = <><SettingsButton disabled={busy} onClick={() => copy(true)}>新建预设</SettingsButton><SettingsButton disabled={busy} onClick={() => fileInput.current?.click()}>导入预设</SettingsButton></>
  const comparison = popup?.type === 'compare' && draft ? comparePresetBlocks(popup.system.blocks, draft.blocks) : null

  return <div className="presets-page desk-zoom">
    <header className="prompts-topbar"><Link to={returnTo} className="prompts-return"><ArrowLeft className="size-4" />{bookId ? '返回当前书' : '返回书房'}</Link><button type="button" className="prompt-icon-button ml-auto" aria-label="系统设置" title="系统设置" onClick={openSettings}><Settings className="size-5" /></button></header>
    <main className="presets-main">
      <div className="presets-heading"><div><h1>预设管理</h1><p>主编在群聊里每回你一句，发给模型的就是正在用的那份预设。改了点「保存」才生效，所有书都用同一份。</p></div><select aria-label="预设种类" value="chief_group" onChange={() => {}}><option value="chief_group">主编群聊</option></select></div>
      {(detail.isPending || list.isPending) && <div className="preset-loading" role="status"><LoaderCircle className="size-5 animate-spin" />正在读取预设…</div>}
      {(detail.isError || list.isError) && <div className="preset-error" role="alert">{message(detail.error ?? list.error)} <button className="prompt-text-link" type="button" onClick={() => { void detail.refetch(); void list.refetch() }}>重试</button></div>}
      {draft && loadedSelection === selectionKey && list.data && <>
        <section className="preset-selected-summary" aria-label="选中的预设">
          <div className="preset-selected-description"><div className="preset-name">{renaming && editable ? <input aria-label="预设名字" maxLength={200} autoFocus disabled={busy} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} onBlur={() => setRenaming(false)} onKeyDown={event => { if (event.key === 'Enter') setRenaming(false) }} /> : <h2>{draft.name}</h2>}{dirty && <span className="preset-unsaved-dot" aria-label="没保存的改动" />}{editable && !renaming && <button type="button" className="prompt-icon-button" aria-label="修改预设名字" disabled={busy} onClick={() => setRenaming(true)}><Pencil className="size-3.5" /></button>}</div><p>{isActive && <span className="preset-active">正在用</span>}{draft.source === 'system' ? `系统预设 · 第 ${draft.version} 版` : `我的 · ${basisLabel} · 保存过 ${draft.saved} 次`} · {draft.blocks.length} 块 · {enabled} 块开着</p></div>
          <div className="preset-actions">{!isActive && <SettingsButton disabled={busy} onClick={activate}>设为正在用</SettingsButton>}<SettingsButton disabled={busy} onClick={() => void check()}>检查</SettingsButton><a className="settings-button" href={presetApi.exportHref(draft.source === 'mine' ? { source: 'mine', id: draft.id } : { source: 'system', version: draft.version })} download>导出</a><SettingsButton disabled={busy} onClick={() => copy()}>复制为新预设</SettingsButton>{editable && <><SettingsButton disabled={busy} onClick={() => void showSaves()}>保存记录</SettingsButton><SettingsButton danger disabled={busy} onClick={() => { if (isActive) setError('这份正在用，先换一份再删'); else setPopup({ type: 'deletePreset' }) }}>删除</SettingsButton></>}{dirty && <><SettingsButton primary disabled={busy} onClick={() => void run(saveDraft)}>保存</SettingsButton><SettingsButton disabled={busy} onClick={() => { setDraft(structuredClone(original)); setRenaming(false); setNotice(''); setError('') }}>放弃修改</SettingsButton></>}</div>
        </section>
        {draft.source === 'system' && <div className="preset-banner"><p>系统预设锁着，只能看。要改，点「解锁编辑」：会先复制一份给你，在复制出来的那份上改。</p><SettingsButton disabled={busy} onClick={() => copy()}>解锁编辑</SettingsButton></div>}
        {draft.source === 'mine' && draft.system_newer && <div className="preset-banner"><p>系统预设出了第 {draft.system_newer.version} 版（{draft.system_newer.date}）：{draft.system_newer.note}</p><SettingsButton disabled={busy} onClick={() => void run(async () => setPopup({ type: 'compare', system: await presetApi.system() }))}>比一比</SettingsButton><SettingsButton disabled={busy} onClick={() => copy(true)}>复制新版</SettingsButton></div>}
        {(error || notice || busy) && <div className="preset-status" role={error ? 'alert' : 'status'}>{error ? <span className="text-seal">{error}</span> : busy ? <span>正在处理…</span> : notice}</div>}
        <div className="preset-compact-library">{importError && <p role="alert" className="preset-import-error">{importError}</p>}<label>预设库<select aria-label="选择预设" value={source === 'system' ? 'system' : id} disabled={busy} onChange={event => choosePreset(event.target.value === 'system' ? { source: 'system' } : { source: 'mine', id: event.target.value })}>{libraryItems.map(item => <option key={item.id || 'system'} value={item.id || 'system'}>{item.name}{active(item) ? ' · 正在用' : ''}</option>)}</select></label><div>{libraryActions}</div></div>
        <div className="presets-workspace">
          <aside className="preset-library"><h3>预设库</h3><label className="prompt-search"><Search className="size-4" /><input aria-label="搜预设名字" placeholder="搜预设名字" value={librarySearch} onChange={event => setLibrarySearch(event.target.value)} /></label><nav aria-label="预设库" className="preset-library-list scroll-thin">{libraryItems.filter(item => item.name.toLocaleLowerCase().includes(librarySearch.trim().toLocaleLowerCase())).map(item => <button type="button" key={item.id || 'system'} aria-label={`选择预设：${item.name}`} aria-current={item.source === source && item.id === id ? 'page' : undefined} disabled={busy} className={clsx('preset-library-item', item.source === source && item.id === id && 'is-selected')} onClick={() => choosePreset(item)}><span>{item.name}</span><small>{item.description}</small>{active(item) && <span className="preset-active">正在用</span>}</button>)}</nav><div className="preset-library-footer">{importError && <p role="alert" className="preset-import-error">{importError}</p>}{libraryActions}</div></aside>
          <section className="preset-blocks" aria-label="预设块"><div className="preset-column-heading"><h3>预设块</h3><span>{enabled} / {draft.blocks.length} 开着</span></div><label className="prompt-search"><Search className="size-4" /><input aria-label="搜块的标题或内容" placeholder="搜块的标题或内容" value={search} onChange={event => setSearch(event.target.value)} /></label><div className="preset-block-filters" role="group" aria-label="筛预设块">{([{ value: 'all', label: '全部' }, { value: 'on', label: '开着的' }, { value: 'off', label: '关着的' }] as const).map(item => <button type="button" key={item.value} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}</button>)}</div><p className="preset-block-count">显示 {visible.length} / {draft.blocks.length} 块</p><div className="preset-block-list scroll-thin">{visible.map(({ block: item, index }) => <div key={item.id} data-block-id={item.id} className={clsx('preset-block-row', selected === item.id && 'is-selected', !item.enabled && 'is-off')} onDragOver={event => { if (editable && !busy) { event.preventDefault(); event.dataTransfer.dropEffect = 'move' } }} onDrop={event => { event.preventDefault(); if (!editable || busy) return; const moving = dragged.current ?? event.dataTransfer.getData('text/plain'); if (moving) { setDraft({ ...draft, blocks: movePresetBlock(draft.blocks, moving, item.id) }); dragged.current = null } }}>
            <button type="button" data-block-drag={item.id} draggable={editable && !busy} disabled={!editable || busy} aria-label={`拖动${item.title}`} title="拖着换先后" className="preset-drag-handle" onDragStart={event => { dragged.current = item.id; event.dataTransfer.setData('text/plain', item.id); event.dataTransfer.effectAllowed = 'move' }} onDragEnd={() => { dragged.current = null }} onKeyDown={event => { if (!editable || busy || !event.altKey || !['ArrowUp', 'ArrowDown'].includes(event.key)) return; event.preventDefault(); const destination = event.key === 'ArrowUp' ? index - 1 : index + 2; if (destination >= 0 && destination < draft.blocks.length) setDraft({ ...draft, blocks: movePresetBlock(draft.blocks, item.id, draft.blocks[destination].id) }); else if (event.key === 'ArrowDown' && index < draft.blocks.length - 1) { const reordered = draft.blocks.filter(row => row.id !== item.id); reordered.push(item); setDraft({ ...draft, blocks: reordered }) } }}><GripVertical className="size-3.5" /></button>
            <span className="preset-block-number">{index + 1}</span><button type="button" className="preset-block-select" onClick={() => chooseBlock(item.id)}><span>{item.title}{item.required && <em>必须</em>}</span><small>{roleLabel(item.role)} · {blockCharacters(item.content)} 字{item.when !== 'always' ? ` · ${conditions.data?.find(condition => condition.when === item.when)?.label ?? item.when}` : ''}</small></button><button type="button" role="switch" aria-label={`${item.title}开关`} aria-checked={item.enabled} className={clsx('settings-toggle', item.enabled && 'is-on')} disabled={!editable || busy} onClick={() => { setDraft({ ...draft, blocks: changePresetBlock(draft.blocks, item.id, { enabled: !item.enabled }) }); setNotice('') }}><span /></button>{item.required && !item.enabled && <p className="preset-without">关了它：{withoutFor(item)}</p>}
          </div>)}</div>{editable && <div className="preset-add-block"><SettingsButton disabled={busy} onClick={() => { const newId = `temporary_${crypto.randomUUID()}`; setDraft({ ...draft, blocks: addPresetBlock(draft.blocks, selected, newId) }); chooseBlock(newId); setSearch(''); setFilter('all') }}>添加预设块</SettingsButton></div>}</section>
          <section className="preset-block-editor scroll-thin" aria-label="选中的那一块">{block ? <>
            <div className="preset-block-heading">{editable ? <input aria-label="预设块标题" value={block.title} disabled={busy} onChange={event => updateBlock({ title: event.target.value })} /> : <h3>{block.title}</h3>}<span>第 {selectedIndex + 1} 块 · {blockCharacters(block.content)} 字</span></div>
            <div className="preset-block-settings"><label>消息角色<select aria-label="消息角色" value={block.role} disabled={!editable || busy} onChange={event => updateBlock({ role: event.target.value as PresetBlock['role'] })}>{(['system', 'user', 'assistant'] as const).map(role => <option key={role} value={role}>{roleLabel(role)}</option>)}</select></label><label>什么时候发<select aria-label="什么时候发" value={block.when} disabled={!editable || busy || conditions.isPending} onChange={event => updateBlock({ when: event.target.value as PresetBlock['when'] })}>{conditions.data?.map(condition => <option key={condition.when} value={condition.when}>{condition.label}</option>)}</select></label></div>
            {conditions.isError && <p className="preset-error" role="alert">{message(conditions.error)} <button type="button" className="prompt-text-link" onClick={() => void conditions.refetch()}>重试</button></p>}
            {block.required && <p className="preset-required-note">必须的块。关了它：{withoutFor(block)}</p>}
            <textarea ref={textarea} aria-label="预设块内容" rows={12} readOnly={!editable} disabled={busy} spellCheck={false} value={block.content} onChange={event => updateBlock({ content: event.target.value })} />
            <details className="preset-placeholders" open><summary>占位符 · {placeholders.data?.length ?? 14} 个</summary>{placeholders.isPending && <p>正在读取占位符…</p>}{placeholders.isError && <p className="preset-error" role="alert">{message(placeholders.error)} <button type="button" className="prompt-text-link" onClick={() => void placeholders.refetch()}>重试</button></p>}{placeholders.data?.map(item => <div key={item.name}><button type="button" className="prompt-variable" disabled={!editable || busy} onMouseDown={event => event.preventDefault()} onClick={() => insert(item.name)}>{`{{${item.name}}}`}</button><p>{item.description}</p>{bookId && item.preview !== undefined && <p className="preset-placeholder-preview">现在：{item.preview}</p>}</div>)}</details>
            <details className="preset-origin" key={`${selectionKey}:${block.id}`}><summary>来历</summary>{systemBlock ? <>{editable && <p>从系统预设第 {base ?? baseSystem.data?.version ?? list.data?.system.version} 版复制{blockModified ? '，后来改过' : ''}{blockModified && <button type="button" className="prompt-text-link" disabled={busy} onClick={() => setPopup({ type: 'blockCompare', left: copiedBlock ?? systemBlock, right: block, version: base ?? list.data!.system.version })}>跟系统的比一比</button>}</p>}{(systemBlock.history ?? []).map(history => <article key={history.version}><div><h4>第 {history.version} 版 · {history.date.slice(5)}</h4><button type="button" className="prompt-text-link" disabled={busy} onClick={() => void viewOrigin(history.version)}>看这一版</button></div><p>{history.change || systemBlock.origin}</p></article>)}</> : <p>你自己加的。</p>}</details>
            {editable && <div className="preset-delete-block"><SettingsButton danger disabled={busy} onClick={() => setPopup({ type: 'deleteBlock', block })}>删掉这一块</SettingsButton></div>}
          </> : <p className="preset-empty">选一块，看看它的内容。</p>}</section>
        </div>
      </>}
    </main>
    <input ref={fileInput} className="sr-only" type="file" accept=".json,application/json" aria-label="导入预设文件" onChange={event => { const file = event.target.files?.[0]; if (file) importFile(file); event.target.value = '' }} />
    {(pending || blocker.state === 'blocked') && <PresetDialog title="这份改了还没保存。" busy={busy} onClose={() => { setPending(null); if (blocker.state === 'blocked') blocker.reset() }}><div className="preset-dialog-actions"><SettingsButton primary disabled={busy} onClick={() => void run(async () => { await saveDraft(); const action = pending?.action; setPending(null); if (blocker.state === 'blocked') blocker.proceed(); else await action?.() })}>保存</SettingsButton><SettingsButton disabled={busy} onClick={() => { setDraft(structuredClone(original)); const action = pending?.action; setPending(null); if (blocker.state === 'blocked') blocker.proceed(); else void action?.() }}>不保存</SettingsButton><SettingsButton disabled={busy} onClick={() => { setPending(null); if (blocker.state === 'blocked') blocker.reset() }}>再看看</SettingsButton></div>{error && <p className="preset-error" role="alert">{error}</p>}</PresetDialog>}
    {popup && <PresetDialog title={popup.type === 'check' ? popup.title : popup.type === 'saves' ? popup.viewing ? `第 ${popup.viewing.saved} 次保存` : '保存记录' : popup.type === 'compare' || popup.type === 'blockCompare' ? '比一比' : popup.type === 'origin' ? `第 ${popup.version} 版 · ${popup.block.title}` : popup.type === 'deleteBlock' ? `删掉「${popup.block.title}」？` : popup.type === 'restore' ? `退回到第 ${popup.snapshot.saved} 次保存？现在的会另存一次，不会丢` : `删掉「${draft?.name}」？`} wide={['compare', 'blockCompare', 'saves', 'origin'].includes(popup.type)} busy={busy} onClose={() => setPopup(null)}>
      {popup.type === 'check' && <>{(['error', 'warning'] as const).map(severity => { const issues = popup.issues.filter(issue => issue.severity === severity); return !!issues.length && <section key={severity} className={`preset-issues is-${severity}`}><h3>{severity === 'error' ? '不让用' : '提醒'}</h3>{issues.map((issue, index) => <button type="button" key={`${issue.code}:${index}`} onClick={() => { setPopup(null); if (issue.block_id && draft?.blocks.some(item => item.id === issue.block_id)) { setSearch(''); setFilter('all'); chooseBlock(issue.block_id) } }}>{issue.message}</button>)}</section> })}{!popup.issues.length && <p>没发现问题。</p>}</>}
      {popup.type === 'saves' && (popup.viewing ? <><button type="button" className="prompt-text-link" onClick={() => setPopup({ type: 'saves', snapshots: popup.snapshots })}>返回保存记录</button><ReadOnlyBlocks blocks={popup.viewing.blocks} conditions={conditions.data ?? []} systemBlocks={systemBlocks} /></> : <div className="preset-saves-list">{popup.snapshots.map(snapshot => <article key={snapshot.saved}><p>第 {snapshot.saved} 次保存 · {stamp(snapshot.saved_at)} · {snapshot.blocks.length} 块</p><div><SettingsButton onClick={() => setPopup({ ...popup, viewing: snapshot })}>看这一版</SettingsButton><SettingsButton disabled={busy} onClick={() => guard(() => setPopup({ type: 'restore', snapshot, snapshots: popup.snapshots }))}>退回这一版</SettingsButton></div></article>)}</div>)}
      {popup.type === 'restore' && <div className="preset-dialog-actions"><SettingsButton onClick={() => setPopup({ type: 'saves', snapshots: popup.snapshots })} disabled={busy}>取消</SettingsButton><SettingsButton primary disabled={busy} onClick={() => void run(async () => { if (draft?.source !== 'mine') return; const restored = await presetApi.restore(draft.id, popup.snapshot.saved); const next = selectedAfterPresetSave(draft.blocks, restored.blocks, selected); setOriginal(restored); setDraft(structuredClone(restored)); cache.setQueryData(detailKey, restored); chooseBlock(next); setPopup(null); await refreshList(); setNotice('已退回这一版。') })}>退回这一版</SettingsButton></div>}
      {popup.type === 'origin' && <pre className="preset-origin-fulltext">{popup.block.content}</pre>}
      {popup.type === 'blockCompare' && <BlockComparison left={popup.left} right={popup.right} leftLabel={`系统预设 · 第 ${popup.version} 版`} rightLabel="现在的" />}
      {popup.type === 'compare' && comparison && <div className="preset-full-comparison"><div className="preset-comparison-head"><h3>系统新版 · 第 {popup.system.version} 版</h3><h3>{draft?.name}</h3></div><section><h3>新版多出来的块</h3>{comparison.leftOnly.length ? comparison.leftOnly.map(item => <details key={item.id}><summary>{item.title}</summary><pre>{item.content}</pre></details>) : <p>没有</p>}</section><section><h3>作者这份多出来的块</h3>{comparison.rightOnly.length ? comparison.rightOnly.map(item => <details key={item.id}><summary>{item.title}</summary><pre>{item.content}</pre></details>) : <p>没有</p>}</section>{comparison.changed.map(pair => <details key={pair.left.id}><summary>{pair.left.title}</summary><BlockComparison left={pair.left} right={pair.right} leftLabel="系统新版" rightLabel="作者这份" /></details>)}<p>另外 {comparison.same} 块一样</p></div>}
      {popup.type === 'deleteBlock' && <>{popup.block.required && <p>这是必须的块：关了它：{withoutFor(popup.block)}</p>}<div className="preset-dialog-actions"><SettingsButton onClick={() => setPopup(null)}>取消</SettingsButton><SettingsButton danger onClick={() => { if (!draft) return; const deleted = deletePresetBlock(draft.blocks, popup.block.id); setDraft({ ...draft, blocks: deleted.blocks }); chooseBlock(deleted.selected); setPopup(null) }}>删掉这一块</SettingsButton></div></>}
      {popup.type === 'deletePreset' && <div className="preset-dialog-actions"><SettingsButton disabled={busy} onClick={() => setPopup(null)}>取消</SettingsButton><SettingsButton danger disabled={busy} onClick={() => void run(async () => { if (draft?.source !== 'mine') return; await presetApi.remove(draft.id); setOriginal(null); setDraft(null); setPopup(null); await refreshList(); choosePreset({ source: 'system' }) })}>删除</SettingsButton></div>}
      {error && <p className="preset-error" role="alert">{error}</p>}
    </PresetDialog>}
  </div>
}
