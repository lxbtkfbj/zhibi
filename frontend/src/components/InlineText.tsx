import clsx from 'clsx'
import { Check, LockKeyhole, Sparkles, Undo2, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useChooseLibraryCandidate, useRewrite, type LibraryCandidate, type RewriteMode, type TargetType } from '../api/library'
import { Spinner } from './ui'

export interface InlineAi {
  bookId: string
  targetType: TargetType
  targetId: string
  path: string
  /** 这一项叫什么，拼进「帮我写」的说法里。 */
  label: string
  locked?: boolean
}

const MODES: { key: string; label: string; mode: RewriteMode; instruction?: (label: string) => string; empty?: boolean; filled?: boolean }[] = [
  { key: 'write', label: '帮我写', mode: 'instruction', instruction: label => `按定调、设定库和这一类该写清的事，写「${label}」这一项：具体、能直接用在正文里`, empty: true },
  { key: 'better', label: '改得更好', mode: 'instruction', instruction: () => '保持原意，改得更具体、更有画面、更好用', filled: true },
  { key: 'expand', label: '写细一点', mode: 'expand', filled: true },
  { key: 'shorten', label: '精简一点', mode: 'shorten', filled: true },
  { key: 'options', label: '给我几个写法', mode: 'options' },
]

/** 点了就在原处改，点别处自动保存；旁边的 ✨ 让 AI 直接改这一处，改完标黄、可撤销。 */
export function InlineText({ value, onSave, placeholder = '点这里写', multiline = true, className, inputClassName, ai, disabled, autoEdit, onDone }: {
  value: string
  onSave: (value: string) => Promise<unknown>
  placeholder?: string
  multiline?: boolean
  className?: string
  inputClassName?: string
  ai?: InlineAi
  disabled?: boolean
  /** 刚从「还可以写」点进来：直接进入编辑。 */
  autoEdit?: boolean
  onDone?: () => void
}) {
  const [draft, setDraft] = useState<string | null>(autoEdit ? value : null)
  const [saving, setSaving] = useState(false)
  // 保存时先显示新文字，不等刷新；刷新回来的值不同或失败时再收回。
  const [optimistic, setOptimistic] = useState<{ text: string; base: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [menu, setMenu] = useState(false)
  const [asking, setAsking] = useState<string | null>(null)
  const [changed, setChanged] = useState<{ before: string } | null>(null)
  const [candidate, setCandidate] = useState<LibraryCandidate | null>(null)
  const rewrite = useRewrite(ai?.bookId ?? '')
  const choose = useChooseLibraryCandidate(ai?.bookId ?? '')
  const ref = useRef<HTMLTextAreaElement & HTMLInputElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const busy = rewrite.isPending || choose.isPending

  useEffect(() => {
    const element = ref.current
    if (draft === null || !element || !multiline) return
    element.style.height = 'auto'
    element.style.height = `${element.scrollHeight + 2}px`
  }, [draft, multiline])
  useEffect(() => {
    if (!menu) return
    const close = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) { setMenu(false); setAsking(null) } }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [menu])

  const start = () => { if (disabled || busy) return; setError(null); setDraft(value); requestAnimationFrame(() => { ref.current?.focus(); const end = ref.current?.value.length ?? 0; ref.current?.setSelectionRange(end, end) }) }
  const commit = async () => {
    if (draft === null) return
    const next = draft.trim()
    if (next === value.trim()) { setDraft(null); onDone?.(); return }
    setSaving(true); setError(null); setOptimistic({ text: next, base: value }); setDraft(null)
    try { await onSave(next); setChanged(null); onDone?.() } catch (cause) { setOptimistic(null); setDraft(next); setError(`没保存上：${cause instanceof Error ? cause.message : String(cause)}`) } finally { setSaving(false) }
  }
  const keys = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); setDraft(null); setError(null); onDone?.() }
    else if (event.key === 'Enter' && (!multiline || event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) { event.preventDefault(); void commit() }
  }
  const run = async (mode: RewriteMode, instruction?: string) => {
    if (!ai) return
    setMenu(false); setAsking(null); setError(null); setCandidate(null)
    try {
      const result = await rewrite.mutateAsync({ target_type: ai.targetType, target_id: ai.targetId, path: ai.path, mode, ...(instruction ? { instruction } : {}) })
      if (result.candidate) setCandidate(result.candidate)
      else if (result.applied) setChanged({ before: result.applied.before })
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }
  const pick = async (index: number) => {
    if (!candidate) return
    try { const before = value; await choose.mutateAsync({ id: candidate.id, index }); setCandidate(null); setChanged({ before }) } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }
  const undo = async () => {
    if (!changed) return
    try { await onSave(changed.before); setChanged(null) } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }
  const shown = optimistic && optimistic.base === value ? optimistic.text : value
  const empty = !shown.trim()

  return <div ref={box} className={clsx('group/inline relative min-w-0', className)}>
    {draft !== null ? <div>
      {multiline
        ? <textarea ref={ref} value={draft} onChange={event => setDraft(event.target.value)} onBlur={() => void commit()} onKeyDown={keys} rows={2} placeholder={placeholder}
          className={clsx('-mx-2 -my-1 block w-[calc(100%+1rem)] resize-none rounded-lg border border-ink-3/50 bg-card px-2 py-1 leading-[1.8] text-ink shadow-[0_0_0_3px_rgb(0_0_0/0.03)] outline-none placeholder:text-ink-3', inputClassName)} />
        : <input ref={ref} value={draft} onChange={event => setDraft(event.target.value)} onBlur={() => void commit()} onKeyDown={keys} placeholder={placeholder}
          className={clsx('-mx-2 -my-1 block w-[calc(100%+1rem)] rounded-lg border border-ink-3/50 bg-card px-2 py-1 text-ink outline-none placeholder:text-ink-3', inputClassName)} />}
      <p className="mt-1.5 flex items-center gap-2 text-xs text-ink-3">{saving ? <><Spinner className="size-3" />正在保存…</> : <>点别处自动保存{multiline ? ' · Ctrl+Enter 保存' : ' · Enter 保存'} · Esc 不改了</>}</p>
    </div>
      : <div className="flex items-start gap-1">
        <button type="button" disabled={disabled} onClick={start} title={disabled ? undefined : '点一下就能改'}
          className={clsx('-mx-2 -my-1 min-w-0 flex-1 rounded-lg px-2 py-1 text-left break-words whitespace-pre-wrap transition-colors', !disabled && 'hover:bg-subtle', changed && 'bg-[var(--color-edit-highlight)]/60', empty ? 'text-ink-3' : 'text-ink')}>
          {empty ? placeholder : shown}{saving && <Spinner className="ml-2 inline size-3 align-middle text-ink-3" />}
        </button>
        {ai && !disabled && <span className={clsx('shrink-0 transition-opacity', menu || busy ? 'opacity-100' : 'opacity-0 group-hover/inline:opacity-100 focus-within:opacity-100')}>
          <button type="button" aria-label={`让 AI 改「${ai.label}」`} title={ai.locked ? '锁住了，AI 不会改；要改先解锁' : `让 AI 改「${ai.label}」`} disabled={ai.locked || busy} onClick={() => setMenu(value => !value)}
            className="flex size-7 items-center justify-center rounded-lg text-chief hover:bg-chief-soft disabled:text-ink-3 disabled:hover:bg-transparent">
            {busy ? <Spinner className="size-3.5" /> : ai.locked ? <LockKeyhole className="size-3.5" /> : <Sparkles className="size-4" />}
          </button>
        </span>}
      </div>}
    {menu && ai && <div role="menu" className="absolute top-8 right-0 z-30 w-56 rounded-xl border border-line bg-card p-1.5 shadow-[var(--shadow-lift)]">
      {MODES.filter(item => (empty ? !item.filled : !item.empty)).map(item => <button key={item.key} type="button" role="menuitem" onClick={() => void run(item.mode, item.instruction?.(ai.label))} className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-subtle">{item.label}</button>)}
      {asking === null
        ? <button type="button" role="menuitem" onClick={() => setAsking('')} className="flex w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-subtle">照我的意思{empty ? '写' : '改'}…</button>
        : <form className="p-1.5" onSubmit={event => { event.preventDefault(); if (asking.trim()) void run('instruction', asking.trim()) }}>
          <textarea autoFocus value={asking} onChange={event => setAsking(event.target.value)} rows={3} placeholder="比如：改成冷静隐忍，但对家人护短" className="block w-full resize-none rounded-lg border border-line-2 bg-card px-2.5 py-1.5 text-sm outline-none focus:border-ink-3" />
          <button type="submit" disabled={!asking.trim()} className="mt-1.5 w-full rounded-lg bg-ink py-1.5 text-sm text-paper-2 disabled:opacity-40">照这个{empty ? '写' : '改'}</button>
        </form>}
    </div>}
    {busy && <p role="status" className="mt-1 text-xs text-chief">AI 正在写…</p>}
    {changed && draft === null && <p className="mt-1 flex items-center gap-2 text-xs text-ink-3"><Check className="size-3.5 text-lore" />AI 改好了<button type="button" onClick={() => void undo()} className="flex items-center gap-0.5 text-chief hover:underline"><Undo2 className="size-3" />撤销</button><button type="button" onClick={() => setChanged(null)} className="hover:text-ink">知道了</button></p>}
    {candidate && <div className="mt-2 space-y-2 rounded-xl border border-chief/25 bg-chief-soft/30 p-3">
      <p className="flex items-center text-xs text-ink-2">几个写法，挑一个就换上<button type="button" aria-label="不要了" onClick={() => setCandidate(null)} className="ml-auto rounded p-0.5 hover:text-ink"><X className="size-3.5" /></button></p>
      {candidate.options.map((option, index) => <div key={index} className="rounded-lg border border-line bg-card p-2.5 text-sm">
        <p className="mb-1 text-xs text-ink-3">{option.label}{index === 0 && ' · 推荐'}</p>
        <p className="leading-relaxed whitespace-pre-wrap">{option.text}</p>
        <button type="button" disabled={choose.isPending} onClick={() => void pick(index)} className="mt-1.5 text-xs font-medium text-chief hover:underline">用这个</button>
      </div>)}
    </div>}
    {error && <p role="alert" className="mt-1 text-xs text-seal">{error}</p>}
  </div>
}
