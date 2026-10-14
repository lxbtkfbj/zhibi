import clsx from 'clsx'
import { AlertTriangle, ChevronDown, Radio } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { Concept, MeetingMessage, Speaker } from '../../api/types'
import { EmptyState, TypingDots } from '../../components/ui'
import { ROLE_META } from '../../lib/roles'

export function RoleAvatar({ speaker, size = 'md' }: { speaker: Speaker; size?: 'sm' | 'md' }) {
  const meta = ROLE_META[speaker] ?? ROLE_META.system
  return (
    <span
      className={clsx(
        'inline-flex shrink-0 items-center justify-center rounded-md font-serif font-bold ring-1',
        meta.bg,
        meta.text,
        meta.ring,
        size === 'sm' ? 'size-6 text-xs' : 'size-8 text-sm',
      )}
      title={meta.name}
    >
      {meta.short}
    </span>
  )
}

function time(iso: string | null) {
  return iso ? new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''
}

// ---------- 产出卡片 ----------

interface LoreData {
  world_entries: { category: string; name: string }[]
  characters: { name: string; role_type: string }[]
}
interface OutlineData {
  volumes: { index: number; title: string; summary: string }[]
  first_volume_units: { index: number; title: string; chapter_count: number; climax: string }[]
}
interface CritiqueData {
  verdict: 'pass' | 'revise'
  highlights: string[]
  issues: { target: string; problem: string; suggestion: string; severity: 'high' | 'medium' | 'low' }[]
}

const TARGET_NAME: Record<string, string> = { concept: '概念', lore: '世界观与人物', outline: '大纲' }
const SEVERITY: Record<string, string> = { high: '严重', medium: '中等', low: '轻微' }

function ConceptView({ data }: { data: Concept }) {
  return (
    <div className="space-y-2 text-sm">
      <p className="font-serif text-base font-semibold">《{data.title}》<span className="ml-2 text-xs font-normal text-ink-3">{data.genre}</span></p>
      <p className="text-ink-2">{data.logline}</p>
      <ul className="space-y-1 text-ink-2">
        {data.selling_points?.map((p) => (
          <li key={p} className="flex gap-1.5">
            <span className="text-seal">✦</span>
            {p}
          </li>
        ))}
      </ul>
    </div>
  )
}

function LoreView({ data }: { data: LoreData }) {
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-1.5">
        {data.characters.map((c) => (
          <span key={c.name} className="rounded-md bg-lore-soft px-2 py-0.5 text-lore">
            {c.name}
            <span className="ml-1 text-xs opacity-70">{c.role_type}</span>
          </span>
        ))}
      </div>
      <p className="text-ink-3">世界观：{data.world_entries.map((w) => w.name).join('、')}</p>
    </div>
  )
}

function OutlineView({ data }: { data: OutlineData }) {
  return (
    <div className="space-y-2 text-sm">
      <ol className="space-y-1 text-ink-2">
        {data.volumes.map((v) => (
          <li key={v.index}>
            <span className="font-medium text-ink">第{v.index}卷《{v.title}》</span> {v.summary}
          </li>
        ))}
      </ol>
      <p className="text-xs text-ink-3">
        第一卷单元：{data.first_volume_units.map((u) => `${u.title}（${u.chapter_count}章）`).join(' → ')}
      </p>
    </div>
  )
}

function CritiqueView({ data }: { data: CritiqueData }) {
  return (
    <div className="space-y-2 text-sm">
      <p>
        结论：
        <span className={data.verdict === 'pass' ? 'font-medium text-lore' : 'font-medium text-seal'}>
          {data.verdict === 'pass' ? '可以交给作者' : '需要修改'}
        </span>
      </p>
      {data.highlights.length > 0 && (
        <ul className="space-y-0.5 text-ink-2">
          {data.highlights.map((h) => (
            <li key={h}>✓ {h}</li>
          ))}
        </ul>
      )}
      {data.issues.map((issue, i) => (
        <div key={i} className="rounded-lg bg-paper px-3 py-2">
          <p className="text-xs text-ink-3">
            {TARGET_NAME[issue.target]} · {SEVERITY[issue.severity]}
          </p>
          <p className="text-ink">{issue.problem}</p>
          <p className="text-ink-2">→ {issue.suggestion}</p>
        </div>
      ))}
    </div>
  )
}

function TriageView({ data }: { data: Record<string, string> }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {Object.entries(data).map(([target, text]) => (
        <li key={target}>
          <span className="font-medium">{TARGET_NAME[target]}：</span>
          <span className="whitespace-pre-wrap text-ink-2">{text}</span>
        </li>
      ))}
    </ul>
  )
}

function ArtifactBody({ message }: { message: MeetingMessage }) {
  const { type, data } = message.payload ?? { type: '', data: null }
  switch (type) {
    case 'concept':
      return <ConceptView data={data as Concept} />
    case 'lore':
      return <LoreView data={data as LoreData} />
    case 'outline':
      return <OutlineView data={data as OutlineData} />
    case 'critique':
      return <CritiqueView data={data as CritiqueData} />
    case 'triage':
      return <TriageView data={data as Record<string, string>} />
    default:
      return null
  }
}

function ArtifactCard({ message }: { message: MeetingMessage }) {
  const [open, setOpen] = useState(message.payload?.type === 'critique')
  return (
    <div className="rounded-xl border border-line bg-card">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm">
        <span className="font-medium">{message.content}</span>
        <ChevronDown className={clsx('size-4 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2.5">
          <ArtifactBody message={message} />
        </div>
      )}
    </div>
  )
}

// ---------- 消息 ----------

function MessageRow({ message, live }: { message: MeetingMessage; live: boolean }) {
  const meta = ROLE_META[message.speaker] ?? ROLE_META.system

  if (message.kind === 'status') {
    return (
      <div className="flex items-center gap-2 py-0.5 pl-10 text-xs text-ink-3">
        <span className={clsx('size-1.5 rounded-full', meta.dot)} />
        <span>{message.content}</span>
        {live && <TypingDots />}
      </div>
    )
  }

  if (message.kind === 'error') {
    return (
      <div className="ml-10 flex gap-2 rounded-lg border border-seal/30 bg-seal-soft px-3 py-2 text-sm text-seal">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <span className="break-all">{message.content}</span>
      </div>
    )
  }

  if (message.speaker === 'author') {
    return (
      <div className="flex justify-end gap-2">
        <div className="max-w-[85%]">
          <p className="mb-1 text-right text-xs text-ink-3">
            {message.kind === 'decision' ? '作者拍板' : '作者'} · {time(message.created_at)}
          </p>
          <div className="rounded-2xl rounded-tr-sm bg-ink px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap text-paper-2">
            {message.content}
          </div>
        </div>
        <RoleAvatar speaker="author" />
      </div>
    )
  }

  if (message.kind === 'decision') {
    return (
      <div className="flex justify-center py-2">
        <span className="rounded-full border border-seal/30 bg-seal-soft px-4 py-1 text-xs text-seal">{message.content}</span>
      </div>
    )
  }

  return (
    <div className="flex gap-2">
      <RoleAvatar speaker={message.speaker} />
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs text-ink-3">
          <span className={clsx('font-medium', meta.text)}>{meta.name}</span> · {time(message.created_at)}
        </p>
        {message.kind === 'artifact' ? (
          <ArtifactCard message={message} />
        ) : (
          <div className="inline-block rounded-2xl rounded-tl-sm bg-card px-3.5 py-2 text-sm leading-relaxed ring-1 ring-line">
            {message.content}
          </div>
        )}
      </div>
    </div>
  )
}

export function MeetingRoom({
  messages,
  connected,
  working,
}: {
  messages: MeetingMessage[]
  connected: boolean
  working: boolean
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  useEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [messages.length])

  const lastStatusIndex = working ? messages.map((m) => m.kind).lastIndexOf('status') : -1

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="font-serif font-semibold">编辑部会议室</h2>
        <span className={clsx('flex items-center gap-1 text-xs', connected ? 'text-lore' : 'text-ink-3')}>
          <Radio className="size-3.5" />
          {connected ? '直播中' : '连接中…'}
        </span>
      </div>
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
        className="scroll-thin flex-1 space-y-3 overflow-y-auto px-4 py-4"
      >
        {messages.length === 0 && <EmptyState title="会议还没开始" />}
        {messages.map((m, i) => (
          <MessageRow key={m.id} message={m} live={i === lastStatusIndex && i === messages.length - 1} />
        ))}
        {working && lastStatusIndex !== messages.length - 1 && (
          <div className="flex items-center gap-2 pl-10 text-xs text-ink-3">
            <TypingDots />
          </div>
        )}
      </div>
    </div>
  )
}
