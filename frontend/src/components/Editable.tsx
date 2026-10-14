import clsx from 'clsx'
import { Check, Pencil } from 'lucide-react'
import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Spinner } from './ui'

function useAutosize(ref: React.RefObject<HTMLTextAreaElement | null>, value: string, active: boolean) {
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || !active) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight + 2}px`
  }, [ref, value, active])
}

interface EditableProps {
  value: string
  onSave: (value: string) => Promise<unknown>
  locked?: boolean
  multiline?: boolean
  placeholder?: string
  className?: string
  inputClassName?: string
}

/** 点击即可修改的文本。Ctrl+Enter 或失去焦点时保存，Esc 取消。 */
export function EditableText({ value, onSave, locked, multiline, placeholder = '（空）', className, inputClassName }: EditableProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  useAutosize(ref, draft, editing)

  const startEditing = () => {
    setDraft(value)
    setEditing(true)
  }

  useEffect(() => {
    if (editing) {
      ref.current?.focus()
      ref.current?.setSelectionRange(ref.current.value.length, ref.current.value.length)
    }
  }, [editing])

  const commit = async () => {
    if (draft === value) {
      setEditing(false)
      return
    }
    setSaving(true)
    setError('')
    try {
      await onSave(draft)
      setEditing(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      setDraft(value)
      setEditing(false)
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || !multiline)) {
      e.preventDefault()
      void commit()
    }
  }

  if (editing) {
    return (
      <div className="relative">
        <textarea
          ref={ref}
          value={draft}
          rows={1}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={onKeyDown}
          className={clsx(
            'w-full resize-none rounded-md border border-seal/50 bg-card px-2 py-1 leading-relaxed text-ink focus:outline-none focus:ring-2 focus:ring-seal/15',
            inputClassName,
          )}
        />
        <div className="mt-1 flex items-center gap-2 text-xs text-ink-3">
          {saving ? <Spinner className="size-3" /> : <Check className="size-3" />}
          {multiline ? 'Ctrl+Enter 保存，Esc 取消' : 'Enter 保存，Esc 取消'}
          {error && <span className="text-seal">{error}</span>}
        </div>
      </div>
    )
  }

  return (
    <div
      role={locked ? undefined : 'button'}
      tabIndex={locked ? undefined : 0}
      onClick={() => !locked && startEditing()}
      onKeyDown={(e) => !locked && e.key === 'Enter' && startEditing()}
      className={clsx(
        'group relative -mx-1 rounded-md px-1 leading-relaxed whitespace-pre-wrap',
        !locked && 'cursor-text hover:bg-line/40',
        className,
      )}
      title={locked ? '编辑部工作时不能修改' : '点击修改'}
    >
      {value || <span className="text-ink-3">{placeholder}</span>}
      {!locked && (
        <Pencil className="absolute top-1 -right-4 size-3 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100" />
      )}
    </div>
  )
}

/** 列表（卖点、关键事件、秘密等）：每行一条。 */
export function EditableList({
  items,
  onSave,
  locked,
  ordered,
  placeholder = '（空）',
}: {
  items: string[]
  onSave: (items: string[]) => Promise<unknown>
  locked?: boolean
  ordered?: boolean
  placeholder?: string
}) {
  const [editing, setEditing] = useState(false)
  if (editing) {
    return (
      <EditableTextAutoOpen
        value={items.join('\n')}
        onSave={async (text) => {
          await onSave(text.split('\n').map((s) => s.trim()).filter(Boolean))
        }}
        onDone={() => setEditing(false)}
      />
    )
  }
  return (
    <div
      role={locked ? undefined : 'button'}
      tabIndex={locked ? undefined : 0}
      onClick={() => !locked && setEditing(true)}
      onKeyDown={(e) => !locked && e.key === 'Enter' && setEditing(true)}
      className={clsx('group -mx-1 rounded-md px-1', !locked && 'cursor-text hover:bg-line/40')}
      title={locked ? '编辑部工作时不能修改' : '点击修改（每行一条）'}
    >
      {items.length ? (
        <ul className="space-y-1">
          {items.map((item, i) => (
            <li key={i} className="flex gap-2 leading-relaxed">
              <span className="shrink-0 text-ink-3">{ordered ? `${i + 1}.` : '·'}</span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-ink-3">{placeholder}</span>
      )}
    </div>
  )
}

function EditableTextAutoOpen({ value, onSave, onDone }: { value: string; onSave: (v: string) => Promise<void>; onDone: () => void }) {
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  useAutosize(ref, draft, true)
  useEffect(() => ref.current?.focus(), [])
  const commit = async () => {
    if (draft !== value) {
      setSaving(true)
      try {
        await onSave(draft)
      } finally {
        setSaving(false)
      }
    }
    onDone()
  }
  return (
    <div>
      <textarea
        ref={ref}
        value={draft}
        rows={2}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onDone()
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void commit()
        }}
        className="w-full resize-none rounded-md border border-seal/50 bg-card px-2 py-1 leading-relaxed focus:outline-none focus:ring-2 focus:ring-seal/15"
      />
      <div className="mt-1 flex items-center gap-2 text-xs text-ink-3">
        {saving && <Spinner className="size-3" />}每行一条 · Ctrl+Enter 保存 · Esc 取消
      </div>
    </div>
  )
}
