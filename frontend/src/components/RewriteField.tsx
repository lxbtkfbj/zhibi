import { BookContext } from '../pages/book/context'
import { useContext, useEffect, useRef, useState } from 'react'
import { useChooseLibraryCandidate, useRewrite, useTargetCandidates, useTargetVersions, useRevertVersion, useLibraryConfig, useLibrary } from '../api/library'
import type { TargetType, RewriteMode } from '../api/library'
import { appliedSelectionText, selectedTextRange, storySentences } from '../lib/textSelection'
import { Button, ErrorText, inputClass, Modal } from './ui'
import { compareHistory } from '../lib/historyDisplay'

export interface RewriteFieldProps {
  bookId: string; targetType: TargetType; targetId: string; path: string; value: string
  quoteWhere?: string | ((selectionPath: string) => string); locked?: boolean; disabled?: boolean; label?: string; emptyText?: string; className?: string; optionsOnly?: boolean
}

export function RewriteField({ bookId, targetType, targetId, path, value, locked, disabled, label, emptyText = '（空）', className, optionsOnly, quoteWhere }: RewriteFieldProps) {
  const chat = useContext(BookContext)
  const rewrite = useRewrite(bookId)
  const choose = useChooseLibraryCandidate(bookId)
  const candidates = useTargetCandidates(bookId, targetType, targetId)
  const root = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<{ start: number; end: number } | null>(null)
  const [menu, setMenu] = useState<string | null>(null)
  const [instruction, setInstruction] = useState<string | null>(null)
  const [instructionPath, setInstructionPath] = useState(path)
  const [highlight, setHighlight] = useState<{ start: number; text: string } | null>(null)
  const [notice, setNotice] = useState('')
  const storageKey = `zhibi-candidates-closed:${bookId}:${targetType}:${targetId}`
  const [closed, setClosed] = useState<string[]>(() => { try { const stored: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '[]'); return Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : [] } catch { return [] } })
  const busy = rewrite.isPending || choose.isPending
  const activePath = selected ? `${path}@${selected.start}:${selected.end}` : path
  const groups = (candidates.data ?? []).filter(item => item.path.split('@')[0] === path && item.chosen === null && !closed.includes(item.id))
  useEffect(() => {
    const onSelect = () => { if (root.current) setSelected(selectedTextRange(root.current, window.getSelection())) }
    document.addEventListener('selectionchange', onSelect)
    return () => document.removeEventListener('selectionchange', onSelect)
  }, [])
  useEffect(() => {
    if (!highlight) return
    const clear = () => setHighlight(null)
    document.addEventListener('pointerdown', clear, { once: true })
    document.addEventListener('keydown', clear, { once: true })
    return () => { document.removeEventListener('pointerdown', clear); document.removeEventListener('keydown', clear) }
  }, [highlight])
  const mark = (changedPath: string, after: string) => {
    setHighlight({ start: Number(changedPath.match(/@(\d+):/)?.[1] ?? 0), text: after })
    setSelected(null)
    window.getSelection()?.removeAllRanges()
  }
  const run = async (mode: RewriteMode, changedPath: string, instructionValue?: string) => {
    if (locked) { setNotice('已锁：AI 不能改这一处，先解锁'); return }
    if (busy || disabled) return
    setNotice(''); setHighlight(null); setMenu(null)
    try {
      const result = await rewrite.mutateAsync({ target_type: targetType, target_id: targetId, path: changedPath, mode, ...(instructionValue !== undefined ? { instruction: instructionValue } : {}) })
      setInstruction(null)
      if (result.applied) mark(result.applied.path, appliedSelectionText(result.applied))
    } catch { /* 保留输入与原文，可再次提交。 */ }
  }
  const open = (changedPath: string) => {
    if (locked) { setNotice('已锁：AI 不能改这一处，先解锁'); return }
    setNotice(''); setHighlight(null); setMenu(menu === changedPath ? null : changedPath)
  }
  const content = () => {
    if (!value) return <span className="text-ink-2">{emptyText}</span>
    const characters = Array.from(value)
    if (highlight && characters.slice(highlight.start, highlight.start + Array.from(highlight.text).length).join('') === highlight.text) return <>{characters.slice(0, highlight.start).join('')}<mark data-testid="rewrite-highlight" className="rounded bg-[var(--color-edit-highlight)] text-inherit">{highlight.text}</mark>{characters.slice(highlight.start + Array.from(highlight.text).length).join('')}</>
    return storySentences(value).map((sentence, index) => <span key={index}>{sentence}</span>)
  }
  return <section data-rewrite-path={path} className={`group/rewrite relative min-w-0 space-y-2 ${className ?? ''}`}>
    {/* 没有标题的字段（设定库卡片里的每一项）：按钮悬停时浮在右上角，不单独占一行。 */}
    <div className={!label && !optionsOnly ? 'absolute -top-1 right-0 z-[1] !mt-0' : 'flex flex-wrap items-center justify-between gap-2'}>{label && <h3 className="text-sm text-ink-2">{label}</h3>}<Button className={!optionsOnly && (!label || targetType === 'character' || /^(fields|levels)\./.test(path)) ? `${!label ? 'bg-card shadow-[var(--shadow-paper)] ' : ''}[@media(hover:hover)]:opacity-0 group-hover/rewrite:opacity-100 group-focus-within/rewrite:opacity-100` : undefined} variant="ghost" size="sm" disabled={busy || disabled} onClick={() => optionsOnly ? void run('options', path) : open(path)}>{optionsOnly ? '给我几个写法' : '改这一项'}</Button></div>
    <div ref={root} data-selectable-text className="whitespace-pre-wrap break-words text-[15px] leading-loose select-text">{content()}</div>
    {selected && <div className="sticky bottom-2 z-10 flex w-fit flex-wrap rounded-lg border border-line bg-card shadow-md">{!disabled && <Button size="sm" variant="soft" disabled={busy} onPointerDown={event => event.preventDefault()} onClick={() => open(activePath)}>改这一句</Button>}{chat && <Button size="sm" variant="ghost" onPointerDown={event => event.preventDefault()} onClick={() => { chat.askChief({ text: Array.from(value).slice(selected.start, selected.end).join(''), where: (typeof quoteWhere === 'function' ? quoteWhere(activePath) : quoteWhere) ?? (targetType === 'concept' ? '定调' : `大纲 · ${label ?? ''}`) }); window.getSelection()?.removeAllRanges(); setSelected(null) }}>问问主编</Button>}</div>}

    {menu && <div role="menu" aria-label="选择修改方式" className="flex flex-wrap gap-2 rounded-xl border border-line bg-card p-3 shadow-sm">{([['options', '给我几个写法'], ['instruction', '照我的意思改'], ['expand', '写细一点'], ['shorten', '精简一点']] as const).map(([mode, title]) => <Button key={mode} size="sm" variant="ghost" disabled={busy} onClick={() => { if (mode === 'instruction') { setInstructionPath(menu); setInstruction(''); setMenu(null) } else void run(mode, menu) }}>{title}</Button>)}</div>}
    {instruction !== null && <form className="space-y-2 rounded-lg border border-line p-3" onSubmit={event => { event.preventDefault(); if (instruction.trim()) void run('instruction', instructionPath, instruction.trim()) }}><label className="text-sm">照我的意思改<textarea autoFocus aria-label="修改意见" value={instruction} onChange={event => setInstruction(event.target.value)} className={`${inputClass} mt-2`} /></label><div className="flex gap-2"><Button type="submit" size="sm" disabled={!instruction.trim() || busy}>照这个改</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setInstruction(null)}>取消</Button></div></form>}
    {busy && <p role="status" className="text-sm text-chief">主编正在想……</p>}
    {notice && <p role="alert" className="text-sm text-seal">{notice}</p>}
    <ErrorText error={rewrite.error ?? choose.error ?? candidates.error} />
    {rewrite.isError && <Button size="sm" variant="ghost" disabled={busy} onClick={() => { const input = rewrite.variables; if (input) void run(input.mode, input.path, input.instruction) }}>再试一次</Button>}
    {groups.map(group => <section key={group.id} aria-label="候选写法" className="space-y-3 rounded-xl border border-chief/25 bg-chief-soft/20 p-3"><div className="flex items-center justify-between"><h4 className="text-sm font-medium">三种写法</h4><Button size="sm" variant="ghost" onClick={() => { const next = [...closed, group.id]; setClosed(next); try { localStorage.setItem(storageKey, JSON.stringify(next)) } catch { /* 浏览器禁用存储时，本页仍可关闭候选。 */ } }}>关闭候选</Button></div>{group.options.map((option, index) => <article key={index} className="rounded-lg border border-line bg-card p-3"><h5 className="text-sm font-bold">{option.label}{index === 0 && <span className="ml-2 text-xs font-normal text-chief">推荐</span>}</h5><p className="my-2 whitespace-pre-wrap break-words text-[15px] leading-relaxed">{option.text}</p>{option.why && <p className="mb-2 text-xs text-ink-2">{option.why}</p>}<Button size="sm" variant="soft" disabled={busy || disabled} onClick={async () => { if (locked) { setNotice('已锁：AI 不能改这一处，先解锁'); return } try { const result = await choose.mutateAsync({ id: group.id, index }); mark(result.candidate.path, option.text ?? '') } catch { /* 错误保留候选。 */ } }}>用这个</Button></article>)}</section>)}
  </section>
}

export function TargetHistory({ bookId, targetType, targetId, disabled }: { bookId: string; targetType: TargetType; targetId: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const config = useLibraryConfig()
  const library = useLibrary(bookId)
  const versions = useTargetVersions(bookId, targetType, targetId, open)
  const revert = useRevertVersion(bookId)
  const ordered = [...(versions.data ?? [])].sort((a, b) => b.version - a.version)
  return <div><Button size="sm" variant="ghost" onClick={() => setOpen(true)}>历史</Button><Modal open={open} onClose={() => !revert.isPending && setOpen(false)} title="版本历史" wide>
    <section aria-label="版本历史" className="space-y-4">
      {(versions.isLoading || config.isLoading) && <p className="text-sm text-ink-2">正在读取历史…</p>}
      {versions.data?.length === 0 && <p className="text-sm text-ink-2">还没有修改记录。</p>}
      {config.data && ordered.map((version, index) => {
        const previous = ordered[index + 1]
        const rows = compareHistory(version.snapshot, previous?.snapshot ?? null, targetType, config.data, library.data)
        const count = rows.filter(row => row.change !== 'same').length
        return <details key={version.id} className="rounded-xl border border-line bg-card p-4">
          <summary className="cursor-pointer text-sm leading-7">第 {version.version} 版 · {config.data?.sources[version.source] ?? version.source} · {version.note || '保存修改'}<span className="block pl-4 text-xs text-ink-2">{new Date(version.created_at).toLocaleString('zh-CN')}</span></summary>
          <p className="mt-3 text-xs text-ink-2">{previous ? `与第 ${previous.version} 版比较：${count ? `${count} 处有变化，改前和改后一起列出。` : '内容没有变化。'}` : '这是最早保留的版本。'}</p>
          <dl className="my-4 space-y-3">{rows.map(row => <div key={row.key} className={`min-w-0 rounded-lg p-3 ${row.change === 'same' ? 'bg-paper/50' : 'border border-chief/25 bg-chief-soft/20'}`}>
            <dt className="mb-1 flex flex-wrap items-center gap-2 text-xs font-medium text-ink-2">{row.label}{row.change !== 'same' && <span className="rounded bg-chief-soft px-1.5 py-0.5 text-chief">{{ changed: '已改', added: '新增', removed: '已删' }[row.change]}</span>}</dt>
            {row.change !== 'same' && previous ? <dd className="grid gap-3 text-sm leading-7 sm:grid-cols-2"><div><span className="text-xs text-ink-2">改前</span><p className="whitespace-pre-wrap break-words">{row.before ?? '（没有这一项）'}</p></div><div><span className="text-xs text-chief">改后</span><p className="whitespace-pre-wrap break-words">{row.after ?? '（已删除）'}</p></div></dd> : <dd className="whitespace-pre-wrap break-words text-sm leading-7">{row.after}</dd>}
          </div>)}</dl>
          <Button size="sm" variant="soft" disabled={revert.isPending || disabled} onClick={() => { if (window.confirm(`退回到第 ${version.version} 版？当前内容也会保留为历史版本。`)) revert.mutate(version.id) }}>退回到这一版</Button>
          {disabled && <p className="mt-2 text-xs text-ink-2">当前只能查看历史，暂不能退回。</p>}
        </details>
      })}
      <ErrorText error={versions.error ?? revert.error ?? config.error} />
    </section>
  </Modal></div>
}
