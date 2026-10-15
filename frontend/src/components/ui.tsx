import clsx from 'clsx'
import { X } from 'lucide-react'
import { animate, AnimatePresence, motion, useInView, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { type ButtonHTMLAttributes, type ReactNode, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { Tone } from '../lib/status'

type Variant = 'primary' | 'seal' | 'ghost' | 'outline' | 'danger' | 'soft'

export function Button({
  variant = 'outline',
  size = 'md',
  loading,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' | 'lg'; loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={clsx(
        'press inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl font-medium whitespace-nowrap transition-colors',
        'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-seal',
        'disabled:cursor-not-allowed disabled:opacity-50',
        { sm: 'h-8 px-3 text-[13px]', md: 'h-10 px-4 text-sm', lg: 'h-12 px-6 text-[15px]' }[size],
        {
          primary: 'bg-ink text-paper-2 shadow-[0_6px_16px_-8px_rgb(38_35_32/0.6)] hover:bg-ink-2',
          seal: 'bg-seal text-paper-2 shadow-[0_8px_20px_-10px_rgb(180_67_46/0.8)] hover:bg-seal-dark',
          ghost: 'text-ink-2 hover:bg-line/60 hover:text-ink',
          outline: 'border border-line-2 bg-card text-ink hover:border-ink-3/50 hover:bg-paper-2',
          danger: 'border border-seal/40 bg-card text-seal hover:bg-seal-soft',
          soft: 'bg-paper-2 text-ink-2 ring-1 ring-line hover:text-ink hover:ring-line-2',
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

export function TypingDots({ className }: { className?: string }) {
  return (
    <span className={clsx('inline-flex items-center gap-[3px]', className)} aria-label="进行中">
      <span className="typing-dot size-1 rounded-full bg-current" />
      <span className="typing-dot size-1 rounded-full bg-current" />
      <span className="typing-dot size-1 rounded-full bg-current" />
    </span>
  )
}

const TONE_CLASS: Record<Tone, string> = {
  busy: 'bg-chief-soft text-chief',
  wait: 'bg-seal-soft text-seal',
  ok: 'bg-lore-soft text-lore',
  idle: 'bg-line/70 text-ink-2',
  error: 'bg-seal text-paper-2',
}

export function Badge({ tone = 'idle', children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function Card({ className, children, hover }: { className?: string; children: ReactNode; hover?: boolean }) {
  return <div className={clsx('paper', hover && 'lift', className)}>{children}</div>
}

/** 进入视口时淡入上浮。 */
export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}

/** 数字从 0 滚动到目标值。 */
export function CountUp({ value, className }: { value: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const reduce = useReducedMotion()
  const count = useMotionValue(0)
  const rounded = useTransform(count, (v) => Math.round(v).toString())
  useEffect(() => {
    if (!inView) return
    if (reduce) {
      count.set(value)
      return
    }
    const controls = animate(count, value, { duration: 0.9, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [inView, value, count, reduce])
  return (
    <motion.span ref={ref} className={className}>
      {rounded}
    </motion.span>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('shimmer rounded-lg', className)} />
}

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  wide,
  stableHeight,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
  stableHeight?: boolean
}) {
  useEscape(open, onClose)
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center bg-ink/30 p-0 backdrop-blur-[2px] sm:items-center sm:p-6"
          onMouseDown={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            onMouseDown={(e) => e.stopPropagation()}
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            className={clsx(
              'flex w-full flex-col rounded-t-2xl bg-paper-2 shadow-[var(--shadow-lift)] sm:rounded-2xl',
              stableHeight ? 'h-[min(92dvh,52rem)] max-h-[92dvh]' : 'max-h-[92vh]',
              wide ? 'sm:max-w-3xl' : 'sm:max-w-xl',
            )}
          >
            <div className="flex shrink-0 items-center justify-between px-6 pt-5 pb-3">
              <h2 className="font-serif text-xl font-bold">{title}</h2>
              <button onClick={onClose} className="rounded-lg p-1.5 text-ink-2 hover:bg-line/60 hover:text-ink" aria-label="关闭">
                <X className="size-5" />
              </button>
            </div>
            <div className={clsx('scroll-thin min-h-0 flex-1 overflow-y-auto px-6 pb-5', stableHeight && '[scrollbar-gutter:stable]')}>{children}</div>
            {footer && <div className="flex shrink-0 justify-end gap-2 border-t border-line px-6 py-3.5">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

/** 从右侧滑出的抽屉。 */
export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  useEscape(open, onClose)
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 bg-ink/20 backdrop-blur-[1px]"
          onMouseDown={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.aside
            role="dialog"
            aria-modal="true"
            onMouseDown={(e) => e.stopPropagation()}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-paper-2 shadow-[var(--shadow-panel)]"
          >
            <div className="flex items-center justify-between gap-3 border-b border-line px-6 py-4">
              <div className="min-w-0 font-serif text-xl font-bold">{title}</div>
              <button onClick={onClose} className="rounded-lg p-1.5 text-ink-2 hover:bg-line/60 hover:text-ink" aria-label="关闭">
                <X className="size-5" />
              </button>
            </div>
            <div className="scroll-thin flex-1 overflow-y-auto px-6 py-4">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-3">{footer}</div>}
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

export function Label({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <span className="mb-1.5 block text-sm font-medium text-ink-2">
      {children}
      {hint && <span className="ml-2 font-normal text-ink-2">{hint}</span>}
    </span>
  )
}

export const inputClass =
  'w-full rounded-xl border border-line-2 bg-card px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink-3 transition-shadow focus:border-seal/60 focus:outline-none focus:ring-4 focus:ring-seal/10'

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="mt-2 text-sm text-seal">{error instanceof Error ? error.message : String(error)}</p>
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-16 text-center">
      {icon && <div className="text-ink-2">{icon}</div>}
      <p className="font-serif text-lg text-ink-2">{title}</p>
      {children && <div className="max-w-sm text-sm leading-relaxed text-ink-2">{children}</div>}
    </div>
  )
}
