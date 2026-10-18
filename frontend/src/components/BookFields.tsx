import clsx from 'clsx'
import { ChevronDown, Plus, X } from 'lucide-react'
import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { Channel, NewBookFields, useBookMeta } from '../api/newBook'
import { Button } from './ui'

/* 书的类别、标签、篇幅：新建页和工作台的简介页共用 */

export const MAX_LENGTH = 5000

/** 点外面或按 Esc 就收起的小浮层，贴在触发按钮下面；下面放不下就翻到上面。 */
export function Popover({ open, onClose, children, className }: { open: boolean; onClose: () => void; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [above, setAbove] = useState(false)
  useLayoutEffect(() => {
    if (!open || !ref.current) return
    const anchor = ref.current.parentElement!.getBoundingClientRect()
    // 新书页大屏上整页放大了：浮层的高度也按屏幕上的大小算
    const height = ref.current.offsetHeight * ((ref.current as HTMLElement & { currentCSSZoom?: number }).currentCSSZoom ?? 1)
    setAbove(anchor.bottom + height + 12 > window.innerHeight && anchor.top - height - 12 > 0)
  }, [open])
  useEffect(() => {
    if (!open) return
    const down = (event: MouseEvent) => {
      const anchor = ref.current?.parentElement
      if (anchor && !anchor.contains(event.target as Node)) onClose()
    }
    const key = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', down)
      document.removeEventListener('keydown', key)
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div ref={ref} className={clsx('absolute left-0 z-30 rounded-xl border border-line bg-card p-4 shadow-[var(--shadow-lift)]', above ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]', className)}>
      {children}
    </div>
  )
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid items-center gap-2 py-3.5 sm:grid-cols-[64px_minmax(0,1fr)] sm:gap-4">
      <span className="text-sm text-ink-3">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export const fieldClass = 'flex h-9 items-center rounded-lg border border-line-2 bg-card px-3 text-sm transition-colors hover:border-ink-3/50'
// 浮层里的小按钮用淡一点的焦点框，不用全局那道朱砂线
export const softFocus = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/15'

export type MetaQuery = ReturnType<typeof useBookMeta>

export function ChannelToggle({ value, onChange }: { value: Channel; onChange: (channel: Channel) => void }) {
  return (
    <div role="radiogroup" aria-label="频道" className="inline-flex gap-0.5 rounded-lg bg-line/60 p-0.5">
      {(['男频', '女频'] as const).map((key) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} onClick={() => onChange(key)}
          className={clsx('rounded-md px-3.5 py-1 text-[13px] transition-colors', softFocus, value === key ? 'bg-card font-medium text-ink shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-ink-2 hover:text-ink')}>
          {key}
        </button>
      ))}
    </div>
  )
}

/** 类别、标签的选项还没读到：读不到时给个重试，别只剩一个输入框。 */
export function MetaState({ meta }: { meta: MetaQuery }) {
  if (meta.isPending) return <p className="py-4 text-center text-[13px] text-ink-3">正在读选项…</p>
  return (
    <p className="py-4 text-center text-[13px] text-ink-3">
      选项没读出来。<button type="button" onClick={() => void meta.refetch()} className="text-chief hover:underline">再读一次</button>
    </p>
  )
}

export function CategoryPicker({ meta, value, onChange }: { meta: MetaQuery; value: Pick<NewBookFields, 'channel' | 'genre'>; onChange: (next: Pick<NewBookFields, 'channel' | 'genre'>) => void }) {
  const [open, setOpen] = useState(false)
  const [channel, setChannel] = useState<Channel>(value.channel || '男频')
  const [custom, setCustom] = useState('')
  const categories = meta.data?.channels.find((c) => c.key === channel)?.categories ?? []
  const pick = (genre: string) => {
    onChange({ channel, genre })
    setOpen(false)
  }
  return (
    <div className="relative inline-block">
      <button type="button" onClick={() => { setChannel(value.channel || '男频'); setOpen(!open) }} className={clsx(fieldClass, 'min-w-[11rem] justify-between gap-3')} aria-haspopup="dialog" aria-expanded={open}>
        {value.genre ? <span className="text-ink">{value.channel && <span className="text-ink-3">{value.channel} · </span>}{value.genre}</span> : <span className="text-ink-3">选一个</span>}
        <ChevronDown className="size-4 text-ink-3" />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} className="w-[min(26rem,calc(100vw-4rem))]">
        <div className="mb-3 flex items-center justify-between">
          <ChannelToggle value={channel} onChange={setChannel} />
          {value.genre && <button type="button" onClick={() => { onChange({ channel: '', genre: '' }); setOpen(false) }} className="text-xs text-ink-3 hover:text-ink">不选了</button>}
        </div>
        {!meta.data && <MetaState meta={meta} />}
        <div className="grid grid-cols-3 gap-1 sm:grid-cols-4">
          {categories.map((genre) => (
            <button key={genre} type="button" onClick={() => pick(genre)}
              className={clsx('rounded-md px-2 py-1.5 text-[13px] transition-colors', softFocus, value.genre === genre && value.channel === channel ? 'bg-ink text-paper-2' : 'text-ink-2 hover:bg-subtle hover:text-ink')}>
              {genre}
            </button>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <input value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={20} placeholder="都不对？自己写一个，回车用它"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && custom.trim()) { e.preventDefault(); pick(custom.trim()); setCustom('') } }}
            className="h-8 flex-1 rounded-md bg-subtle px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-line-2" />
        </div>
      </Popover>
    </div>
  )
}

export function TagPicker({ meta, channel, value, onChange }: { meta: MetaQuery; channel: Channel | ''; value: string[]; onChange: (tags: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [viewing, setViewing] = useState<Channel>(channel || '男频')
  const [custom, setCustom] = useState('')
  const max = meta.data?.max_tags ?? 10
  const groups = meta.data?.channels.find((c) => c.key === (channel || viewing))?.tag_groups ?? []
  const toggle = (tag: string) => onChange(value.includes(tag) ? value.filter((t) => t !== tag) : value.length < max ? [...value, tag] : value)
  const addCustom = () => {
    const tag = custom.trim().slice(0, 20)
    if (tag && !value.includes(tag) && value.length < max) onChange([...value, tag])
    setCustom('')
  }
  return (
    <div className="relative flex flex-wrap items-center gap-1.5">
      {value.map((tag) => (
        <span key={tag} className="inline-flex h-8 items-center gap-0.5 rounded-full border border-line bg-subtle pr-1 pl-3 text-[13px] text-ink">
          {tag}
          <button type="button" onClick={() => onChange(value.filter((t) => t !== tag))} aria-label={`去掉标签${tag}`} className="rounded-full p-1 text-ink-3 hover:bg-line/70 hover:text-ink">
            <X className="size-3" />
          </button>
        </span>
      ))}
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        className="inline-flex h-8 items-center gap-1 rounded-full border border-dashed border-line-2 px-3 text-[13px] text-ink-3 transition-colors hover:border-ink-3/60 hover:text-ink">
        <Plus className="size-3.5" />
        {value.length ? '再加' : '加标签'}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} className="w-[min(36rem,calc(100vw-4rem))]">
        {!channel && (
          <div className="mb-3">
            <ChannelToggle value={viewing} onChange={setViewing} />
          </div>
        )}
        {!meta.data && <MetaState meta={meta} />}
        <div className="space-y-2.5">
          {groups.map((group) => (
            <div key={group.name} className="grid grid-cols-[3.25rem_minmax(0,1fr)] items-baseline gap-2">
              <span className="text-xs text-ink-3">{group.name}</span>
              <div className="flex flex-wrap gap-1">
                {group.tags.map((tag) => {
                  const on = value.includes(tag)
                  return (
                    <button key={tag} type="button" onClick={() => toggle(tag)} aria-pressed={on}
                      className={clsx('rounded-full px-2.5 py-1 text-[13px] transition-colors', softFocus, on ? 'bg-ink text-paper-2' : 'text-ink-2 hover:bg-line/60 hover:text-ink')}>
                      {tag}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <input value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={20} placeholder="自己写一个，回车加上"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); addCustom() } }}
            className="h-8 flex-1 rounded-md bg-subtle px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-line-2" />
          <span className="text-xs text-ink-3 tabular-nums">{value.length}/{max}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => { addCustom(); setOpen(false) }}>好了</Button>
        </div>
      </Popover>
    </div>
  )
}

/** 篇幅：填万字，旁边按每章字数算出大约多少章。 */
export function LengthInput({ text, chapterWords, onChange, onBlur }: { text: string; chapterWords: number; onChange: (text: string, value: number | null) => void; onBlur?: () => void }) {
  const value = text ? Number(text) : null
  const chapters = value ? Math.round((value * 10000) / chapterWords) : null
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className={clsx(fieldClass, 'gap-1.5 px-2.5 focus-within:border-ink-3')}>
        <input
          value={text}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, '').slice(0, 4)
            const next = digits ? Math.min(Number(digits), MAX_LENGTH) : null
            onChange(next ? String(next) : '', next)
          }}
          onBlur={onBlur}
          inputMode="numeric"
          aria-label="篇幅（万字）"
          placeholder="200"
          className="w-10 bg-transparent text-right text-sm text-ink tabular-nums placeholder:text-ink-3/70 focus:outline-none"
        />
        <span className="text-ink-3">万字</span>
      </label>
      {chapters
        ? <span className="text-[13px] text-ink-2 tabular-nums" title={`按每章 ${chapterWords} 字算`}>约 {chapters.toLocaleString()} 章</span>
        : <span className="text-[13px] text-ink-3">没想好可以空着</span>}
    </div>
  )
}
