import clsx from 'clsx'
import { X } from 'lucide-react'
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

type Variant = 'primary' | 'seal' | 'ghost' | 'outline' | 'danger'

export function Button({
  variant = 'outline',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md'; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-seal',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-8 px-3 text-sm' : 'h-10 px-4 text-sm',
        {
          primary: 'bg-ink text-paper-2 hover:bg-ink-2',
          seal: 'bg-seal text-paper-2 hover:bg-seal-dark',
          ghost: 'text-ink-2 hover:bg-line/60',
          outline: 'border border-line-2 bg-card text-ink hover:bg-paper-2',
          danger: 'border border-seal/40 bg-card text-seal hover:bg-seal-soft',
        }[variant],
        className,
      )}
    >
      {loading && <Spinner className="size-3.5" />}
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={clsx('inline-block animate-spin rounded-full border-2 border-current border-t-transparent', className ?? 'size-4')}
    />
  )
}

export function TypingDots() {
  return (
    <span className="inline-flex gap-0.5" aria-label="进行中">
      <span className="typing-dot size-1 rounded-full bg-current" />
      <span className="typing-dot size-1 rounded-full bg-current" />
      <span className="typing-dot size-1 rounded-full bg-current" />
    </span>
  )
}

export function Badge({ tone = 'idle', children }: { tone?: 'busy' | 'wait' | 'ok' | 'idle' | 'error'; children: ReactNode }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap',
        {
          busy: 'bg-chief-soft text-chief',
          wait: 'bg-seal-soft text-seal',
          ok: 'bg-lore-soft text-lore',
          idle: 'bg-line/70 text-ink-2',
          error: 'bg-seal text-paper-2',
        }[tone],
      )}
    >
      {children}
    </span>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('rounded-xl border border-line bg-card', className)}>{children}</div>
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    panel.current?.querySelector<HTMLElement>('textarea, input, select')?.focus()
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-6" onMouseDown={onClose}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(e) => e.stopPropagation()}
        className={clsx(
          'flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-paper-2 shadow-xl sm:rounded-2xl',
          wide ? 'sm:max-w-3xl' : 'sm:max-w-xl',
        )}
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="font-serif text-lg font-semibold">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-ink-3 hover:bg-line/60 hover:text-ink" aria-label="关闭">
            <X className="size-5" />
          </button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

export function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <span className="mb-1.5 block text-sm font-medium text-ink-2">
      {children}
      {hint && <span className="ml-2 font-normal text-ink-3">{hint}</span>}
    </span>
  )
}

export const inputClass =
  'w-full rounded-lg border border-line-2 bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-seal focus:outline-none focus:ring-2 focus:ring-seal/15'

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="mt-2 text-sm text-seal">{error instanceof Error ? error.message : String(error)}</p>
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      {icon && <div className="text-ink-3">{icon}</div>}
      <p className="font-serif text-lg text-ink-2">{title}</p>
      {children && <div className="max-w-sm text-sm text-ink-3">{children}</div>}
    </div>
  )
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="font-serif text-base font-semibold text-ink">{children}</h3>
      {action}
    </div>
  )
}
