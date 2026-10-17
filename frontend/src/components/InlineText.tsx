import clsx from 'clsx'
import { Check, LockKeyhole, Sparkles, Undo2, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
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

/** Chrome、Edge 能让输入框按内容自己长高；别的浏览器用脚本量。 */
const FITS_CONTENT = typeof CSS !== 'undefined' && CSS.supports('field-sizing', 'content')
const fit = (element: HTMLTextAreaElement) => { element.style.height = 'auto'; element.style.height = `${element.scrollHeight}px` }

/**
 * 字本身就是输入框：点哪里光标落在哪里，改完点别处自动保存。
 * 不换框、不加提示行，点进去页面一点不动。旁边的 ✨ 让 AI 直接改这一处，改完标黄、可撤销。
 */
export function InlineText({ value, onSave, placeholder = '点这里写', label, multiline = true, className, ai, disabled, autoEdit, onDone }: {
  value: string
  onSave: (value: string) => Promise<unknown>
  placeholder?: string
  /** 读屏用的名字；不给就用 AI 那一项的名字或占位字。 */
  label?: string
  multiline?: boolean
  className?: string
  ai?: InlineAi
  disabled?: boolean
  /** 刚从「还可以写」点进来：直接把光标放进去。 */
  autoEdit?: boolean
  /** 离开输入框时（保存完或按了 Esc）告诉外面最后是什么字。 */
  onDone?: (text: string) => void
}) {
  // 光标在框里时的文字；离开就保存并清掉。
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  // 保存时先显示新文字，不等刷新；刷新回来就用刷新的值。
  const [optimistic, setOptimistic] = useState<{ text: string; base: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [menu, setMenu] = useState(false)
  const [asking, setAsking] = useState<string | null>(null)
  const [changed, setChanged] = useState<{ before: string } | null>(null)
  const [candidate, setCandidate] = useState<LibraryCandidate | null>(null)
  const rewrite = useRewrite(ai?.bookId ?? '')
  const choose = useChooseLibraryCandidate(ai?.bookId ?? '')
  const field = useRef<HTMLTextAreaElement & HTMLInputElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const cancelled = useRef(false)
  const timer = useRef(0)
  const busy = rewrite.isPending || choose.isPending
  if (optimistic && optimistic.base !== value) setOptimistic(null)
  const shown = optimistic?.text ?? value
  const text = draft ?? shown
  const empty = !text.trim()

  useLayoutEffect(() => { if (multiline && !FITS_CONTENT && field.current) fit(field.current) }, [text, multiline, disabled])
  useEffect(() => {
    const element = field.current
    if (!multiline || FITS_CONTENT || !element) return
    // 聊天栏拖宽拖窄时，换行变了要重新量高度；放到下一帧，免得量的时候又触发自己。
    let width = element.clientWidth
    let frame = 0
    const observer = new ResizeObserver(() => {
      if (element.clientWidth === width) return
      width = element.clientWidth
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => fit(element))
    })
    observer.observe(element)
    void document.fonts?.ready.then(() => fit(element))
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [multiline, disabled])
  useEffect(() => { if (autoEdit) field.current?.focus() }, [autoEdit])
  useEffect(() => () => window.clearTimeout(timer.current), [])
  useEffect(() => {
    if (!menu) return
    const close = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) { setMenu(false); setAsking(null) } }
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [menu])

  const commit = async () => {
    if (draft === null) return
    const next = draft.trim()
    setDraft(null)
    if (next === value.trim()) { onDone?.(next); return }
    setSaving(true); setError(null); setOptimistic({ text: next, base: value })
    try {
      await onSave(next)
      setChanged(null); setSaved(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setSaved(false), 1600)
      onDone?.(next)
    } catch (cause) {
      setOptimistic(null); setDraft(next); setError(`没保存上：${cause instanceof Error ? cause.message : String(cause)}`)
    } finally { setSaving(false) }
  }
  const leave = () => {
    if (!cancelled.current) { void commit(); return }
    cancelled.current = false; setDraft(null); setError(null); onDone?.(value.trim())
  }
  const keys = (event: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return
    if (event.key === 'Escape') { event.preventDefault(); cancelled.current = true; event.currentTarget.blur() }
    else if (event.key === 'Enter' && (!multiline || event.ctrlKey || event.metaKey)) { event.preventDefault(); event.currentTarget.blur() }
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

  // 平时就是一段字；鼠标移上去淡淡一层底色，点进去多一圈细边。只用底色和阴影，不占地方。
  const look = clsx('-mx-2 -my-1 min-w-0 flex-1 rounded-lg px-2 py-1 break-words outline-none placeholder:text-ink-3',
    changed && 'bg-[var(--color-edit-highlight)]/60')
  const editable = 'transition-[background-color,box-shadow] duration-150 hover:bg-subtle focus:bg-page focus:shadow-[0_0_0_1px_var(--color-line-2)]'
  const props = {
    value: text, placeholder, spellCheck: false, 'aria-label': label ?? ai?.label ?? placeholder,
    onFocus: () => { setDraft(current => current ?? shown); setSaved(false) },
    onChange: (event: { target: { value: string } }) => setDraft(event.target.value),
    onBlur: leave, onKeyDown: keys,
  }

  return <div ref={box} className={clsx('group/inline relative min-w-0', className)}>
    <div className="flex items-start gap-1">
      {disabled
        ? <p className={clsx(look, 'whitespace-pre-wrap', empty && 'text-ink-3')}>{empty ? placeholder : text}</p>
        : multiline
          ? <textarea ref={field} rows={1} {...props} className={clsx(look, editable, 'resize-none overflow-hidden [field-sizing:content]')} />
          : <input ref={field} {...props} className={clsx(look, editable, 'text-ellipsis')} />}
      {ai && !disabled && <span className={clsx('shrink-0 transition-opacity', menu || busy || saving || saved ? 'opacity-100' : 'opacity-0 group-focus-within/inline:opacity-100 group-hover/inline:opacity-100')}>
        <button type="button" aria-label={`让 AI 改「${ai.label}」`} title={ai.locked ? '锁住了，AI 不会改；要改先解锁' : saved ? '已保存' : `让 AI 改「${ai.label}」`} disabled={ai.locked || busy} onClick={() => setMenu(value => !value)}
          className="flex size-7 items-center justify-center rounded-lg text-chief hover:bg-chief-soft disabled:text-ink-3 disabled:hover:bg-transparent">
          {busy || saving ? <Spinner className={clsx('size-3.5', saving && !busy && 'text-ink-3')} /> : saved ? <Check className="size-4 text-lore" /> : ai.locked ? <LockKeyhole className="size-3.5" /> : <Sparkles className="size-4" />}
        </button>
      </span>}
    </div>
    <span role="status" className="sr-only">{saving ? '正在保存' : saved ? '已保存' : ''}</span>
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
    {changed && <p className="mt-1 flex items-center gap-2 text-xs text-ink-3"><Check className="size-3.5 text-lore" />AI 改好了<button type="button" onClick={() => void undo()} className="flex items-center gap-0.5 text-chief hover:underline"><Undo2 className="size-3" />撤销</button><button type="button" onClick={() => setChanged(null)} className="hover:text-ink">知道了</button></p>}
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
