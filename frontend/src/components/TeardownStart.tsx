import clsx from 'clsx'
import { X } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTeardownModel } from '../api/teardown'
import { parseTeardownUpto } from '../lib/teardownStart'
import { Button, ErrorText, inputClass } from './ui'

/** 确认页与已经导入的书用同一块输入、同一份费用提醒。 */
export function TeardownOptions({ total, value, onChange, disabled }: { total: number; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  const id = useId()
  const model = useTeardownModel()
  const invalid = parseTeardownUpto(value, total) === undefined
  return <section aria-label="拆书范围和费用">
    <label htmlFor={id} className="mb-2 block text-sm text-ink-2">拆到第几章</label>
    <input id={id} type="number" min={1} step={1} value={value} disabled={disabled} placeholder={`不填就是全本（${total} 章）`}
      aria-invalid={invalid} aria-describedby={`${id}-hint${invalid ? ` ${id}-error` : ''}`}
      onChange={event => onChange(event.target.value)} className={clsx(inputClass, invalid && 'border-seal')} />
    {invalid && <p id={`${id}-error`} role="alert" className="mt-2 text-xs text-seal">至少拆 1 章</p>}
    <p id={`${id}-hint`} className="mt-2 text-xs leading-relaxed text-ink-3">只想学开篇，或者没读过怕剧透，就填一个数</p>
    <p className="mt-4 rounded-lg border border-seal/40 px-4 py-3 text-[13px] leading-relaxed text-ink-2">拆书要把整本原文发给模型，书越长调用越多，费用可能不小。用的是系统设置里「拆书」那一行的模型（现在是 {model.name}）。</p>
    <div role="alert"><ErrorText error={model.error} /></div>
  </section>
}

export interface TeardownStartDialogProps {
  open: boolean
  title: string
  total: number
  initialUpto?: number | null
  onClose: () => void
  onStart: (upto: number | null) => Promise<void>
}

export function TeardownStartDialog({ open, ...props }: TeardownStartDialogProps) {
  // 关上就卸载，重开时用上次目标，不保留取消的输入和失败提示。
  return open ? createPortal(<StartDialog {...props} />, document.body) : null
}

function StartDialog({ title, total, initialUpto, onClose, onStart }: Omit<TeardownStartDialogProps, 'open'>) {
  const [value, setValue] = useState(initialUpto == null ? '' : String(initialUpto))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const operating = useRef(false)
  const model = useTeardownModel()
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        if (!operating.current) closeRef.current()
      }
      if (event.key !== 'Tab') return
      const items = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]') ?? []).filter(item => item.getClientRects().length > 0)
      const first = items[0]
      const last = items.at(-1)
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === panel.current)) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); document.body.style.overflow = overflow; previous?.focus() }
  }, [])
  const upto = parseTeardownUpto(value, total)
  const start = async () => {
    if (operating.current || !model.ready || upto === undefined) return
    operating.current = true
    setBusy(true)
    setError(null)
    try { await onStart(upto); onClose() }
    catch (reason) { setError(reason) }
    finally { operating.current = false; setBusy(false) }
  }
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-overlay)] p-4 backdrop-blur-[6px]"
    onMouseDown={event => { if (event.target === event.currentTarget && !operating.current) onClose() }}>
    <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby={titleId}
      className="flex w-[560px] flex-col overflow-hidden rounded-2xl border border-line bg-paper shadow-[var(--shadow-lift)] outline-none"
      style={{ zoom: 'calc(var(--desk-zoom) * var(--desk-scale))', maxWidth: 'calc((100vw - 32px) / var(--desk-zoom) / var(--desk-scale))', maxHeight: 'calc(88dvh / var(--desk-zoom) / var(--desk-scale))' }}>
      <header className="flex shrink-0 items-start gap-4 border-b border-line px-7 pt-6 pb-5">
        <h2 id={titleId} className="min-w-0 flex-1 font-serif text-[24px] leading-tight font-bold">开始拆《{title}》</h2>
        <button type="button" aria-label="关上开始拆" title="关上（Esc）" disabled={busy} onClick={onClose} className="-mt-1 -mr-2 rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink disabled:opacity-40"><X className="size-5" /></button>
      </header>
      <form onSubmit={event => { event.preventDefault(); void start() }} className="scroll-thin overflow-y-auto px-7 py-6">
        <TeardownOptions total={total} value={value} onChange={setValue} disabled={busy} />
        <div role="alert"><ErrorText error={error} /></div>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>先不拆</Button>
          <Button type="submit" variant="primary" disabled={busy || !model.ready || upto === undefined} loading={busy}>开始拆</Button>
        </div>
      </form>
    </div>
  </div>
}
