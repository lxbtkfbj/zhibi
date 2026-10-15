import clsx from 'clsx'
import { AlertTriangle, ChevronDown } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import type { Concept, InterviewQuestion, MeetingMessage, PlotUnit, Speaker, Spine, StoryThread } from '../../api/types'
import { TypingDots } from '../../components/ui'
import { ROLE_META } from '../../lib/roles'
import { isFresh, useTypewriter } from '../../lib/team'

export function RoleAvatar({
  speaker,
  size = 'md',
  working,
}: {
  speaker: Speaker
  size?: 'sm' | 'md' | 'lg'
  working?: boolean
}) {
  const meta = ROLE_META[speaker] ?? ROLE_META.system
  return (
    <span
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center rounded-full font-serif font-bold ring-1',
        meta.bg,
        meta.text,
        meta.ring,
        working && 'breath',
        { sm: 'size-7 text-xs', md: 'size-9 text-sm', lg: 'size-11 text-base' }[size],
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
  characters: { name: string; role_type: string; abilities?: string; goal?: string }[]
}
interface OutlineData {
  volumes: { index: number; title: string; summary: string; stage?: string; antagonist?: string; chapter_count?: number }[]
  foreshadowings?: { seq: number; description: string; plant_volume?: number; payoff_volume?: number }[]
}
interface VolumePlanData {
  volume: number
  units: Pick<PlotUnit, 'index' | 'title' | 'chapter_count' | 'climax'>[]
  new_foreshadowings: { seq: number; description: string }[]
}
interface ChapterPlanData {
  unit: string
  chapters: { index: number; title: string; hook: string }[]
}
interface ChapterData {
  index: number
  title: string
  words: number
  excerpt?: string
  summary?: string
  characters_updated?: number
  characters_created?: number
  foreshadowings?: number
}
interface CritiqueData {
  verdict: 'pass' | 'revise'
  highlights: string[]
  issues: { target: string; problem: string; suggestion: string; severity: 'high' | 'medium' | 'low' }[]
}

const TARGET_NAME: Record<string, string> = {
  concept: '概念',
  lore: '世界观与人物',
  spine: '主线骨架',
  threads: '线索',
  outline: '全书总纲',
  first_volume: '第一卷卷纲',
}
const SEVERITY: Record<string, string> = { high: '严重', medium: '中等', low: '轻微' }

function ArtifactBody({ message }: { message: MeetingMessage }) {
  const { type, data } = message.payload ?? { type: '', data: null }
  if (type === 'questions') {
    const questions = data as InterviewQuestion[]
    return (
      <ol className="space-y-2">
        {questions.map((q, i) => (
          <li key={i}>
            <p className="text-ink">
              {i + 1}. {q.question}
            </p>
            <p className="text-ink-3">{q.options.map((o, j) => (j === q.recommended ? `${o}（推荐）` : o)).join(' / ')}</p>
          </li>
        ))}
      </ol>
    )
  }
  if (type === 'spine') {
    const sp = data as Spine
    return (
      <div className="space-y-2 text-ink-2">
        <p>
          <span className="font-medium text-ink">开篇：</span>
          {sp.opening}
        </p>
        <ol className="space-y-1 border-l border-line-2 pl-3">
          {sp.milestones?.map((m) => (
            <li key={m.index}>
              <span className="font-medium text-chief">{m.title}</span>
              <span className="text-xs text-ink-3">（第{m.volume}卷）</span> {m.event}
            </li>
          ))}
        </ol>
        <p>
          <span className="font-medium text-seal">结局：</span>
          {sp.ending}
        </p>
      </div>
    )
  }
  if (type === 'concept') {
    const c = data as Concept
    return (
      <div className="space-y-2">
        <p className="text-ink-2">{c.logline}</p>
        <ul className="space-y-1 text-ink-2">
          {c.selling_points?.map((p) => (
            <li key={p} className="flex gap-2">
              <span className="text-seal">◆</span>
              {p}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  if (type === 'lore') {
    const l = data as LoreData
    const hero = l.characters.find((c) => c.role_type === '主角')
    return (
      <div className="space-y-2">
        {hero && (
          <p className="text-ink-2">
            <span className="font-medium text-ink">主角 {hero.name}</span>
            {hero.abilities && <>：{hero.abilities}</>}
          </p>
        )}
        <div className="flex flex-wrap gap-1.5">
          {l.characters.map((c) => (
            <span key={c.name} className="rounded-full bg-lore-soft px-2.5 py-0.5 text-lore">
              {c.name}
              <span className="ml-1 text-xs opacity-70">{c.role_type}</span>
            </span>
          ))}
        </div>
        <p className="text-ink-3">世界观：{l.world_entries.map((w) => w.name).join('、')}</p>
      </div>
    )
  }
  if (type === 'outline') {
    const o = data as OutlineData
    return (
      <div className="space-y-1.5 text-ink-2">
        {o.volumes.map((v) => (
          <p key={v.index}>
            <span className="font-medium text-ink">第{v.index}卷《{v.title}》</span>
            {v.chapter_count ? <span className="text-xs text-ink-3">约 {v.chapter_count} 章</span> : null}
            {v.stage ? <span className="text-xs text-ink-3"> · {v.stage}</span> : null} {v.summary}
          </p>
        ))}
        {o.foreshadowings && o.foreshadowings.length > 0 && (
          <p className="text-ink-3">
            长线伏笔：{o.foreshadowings.map((f) => `F${f.seq}（第${f.plant_volume}卷埋→第${f.payoff_volume}卷收）`).join('、')}
          </p>
        )}
      </div>
    )
  }
  if (type === 'threads') {
    const t = data as { threads: Pick<StoryThread, 'name' | 'kind' | 'summary'>[] }
    return (
      <ul className="space-y-1.5 text-ink-2">
        {t.threads.map((thread) => (
          <li key={thread.name}>
            <span className="mr-1.5 rounded bg-chief-soft px-1.5 py-px text-xs text-chief">{thread.kind}</span>
            <span className="font-medium text-ink">{thread.name}</span>：{thread.summary}
          </li>
        ))}
      </ul>
    )
  }
  if (type === 'volume_plan') {
    const v = data as VolumePlanData
    return (
      <ol className="space-y-1.5 text-ink-2">
        {v.units.map((u) => (
          <li key={u.index}>
            <span className="font-medium text-ink">
              {u.index}. {u.title}
            </span>
            <span className="text-xs text-ink-3"> 约 {u.chapter_count} 章</span> {u.climax}
          </li>
        ))}
      </ol>
    )
  }
  if (type === 'chapter_plan') {
    const c = data as ChapterPlanData
    return (
      <ol className="space-y-1 text-ink-2">
        {c.chapters.map((ch) => (
          <li key={ch.index}>
            <span className="font-medium text-ink">第{ch.index}章 {ch.title}</span>
            {ch.hook && <span className="text-ink-3"> —— {ch.hook}</span>}
          </li>
        ))}
      </ol>
    )
  }
  if (type === 'chapter_draft' || type === 'chapter_final') {
    const c = data as ChapterData
    return (
      <div className="space-y-1.5 text-ink-2">
        <p className="font-serif leading-relaxed">{c.summary ?? `${c.excerpt ?? ''}…`}</p>
        {type === 'chapter_final' && (
          <p className="text-xs text-ink-3">
            设定库：人物状态更新 {c.characters_updated ?? 0} 处，新人物 {c.characters_created ?? 0} 位，伏笔进展 {c.foreshadowings ?? 0} 条
          </p>
        )}
      </div>
    )
  }
  if (type === 'chapter_review') {
    const c = data as CritiqueData
    return (
      <div className="space-y-2">
        {c.highlights.map((h) => (
          <p key={h} className="text-lore">✓ {h}</p>
        ))}
        {c.issues.map((issue, i) => (
          <div key={i} className="rounded-lg bg-paper px-3 py-2">
            <p className="text-xs text-ink-3">{SEVERITY[issue.severity]}</p>
            <p className="text-ink">{issue.problem}</p>
            <p className="text-ink-2">→ {issue.suggestion}</p>
          </div>
        ))}
      </div>
    )
  }
  if (type === 'critique') {
    const c = data as CritiqueData
    return (
      <div className="space-y-2">
        {c.highlights.map((h) => (
          <p key={h} className="text-lore">✓ {h}</p>
        ))}
        {c.issues.map((issue, i) => (
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
  if (type === 'triage') {
    return (
      <ul className="space-y-1.5">
        {Object.entries(data as Record<string, string>).map(([target, text]) => (
          <li key={target}>
            <span className="font-medium">{TARGET_NAME[target]}：</span>
            <span className="whitespace-pre-wrap text-ink-2">{text}</span>
          </li>
        ))}
      </ul>
    )
  }
  return null
}

// 审稿意见、主线骨架、修改分工这类需要作者留意的，默认展开；提问在页面中间作答，这里收起
const OPEN_BY_DEFAULT = new Set(['critique', 'spine', 'triage', 'threads'])

function ArtifactCard({ message }: { message: MeetingMessage }) {
  const [open, setOpen] = useState(OPEN_BY_DEFAULT.has(message.payload?.type ?? ''))
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-card shadow-[var(--shadow-paper)]">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left text-sm">
        <span className="flex items-center gap-2 font-medium">
          <span className="h-3.5 w-0.5 rounded-full bg-seal" />
          {message.content}
        </span>
        <ChevronDown className={clsx('size-4 shrink-0 text-ink-3 transition-transform duration-300', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="border-t border-line px-3.5 py-3 text-[13px] leading-relaxed">
              <ArtifactBody message={message} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Speech({ message }: { message: MeetingMessage }) {
  const [fresh] = useState(() => isFresh(message.created_at))
  const { shown, typing } = useTypewriter(message.content, fresh)
  return (
    <div className="inline-block rounded-2xl rounded-tl-md bg-card px-3.5 py-2.5 text-[14px] leading-relaxed shadow-[var(--shadow-paper)] ring-1 ring-line">
      <span className={clsx(typing && 'caret')}>{shown}</span>
    </div>
  )
}

function MessageRow({ message, live }: { message: MeetingMessage; live: boolean }) {
  const meta = ROLE_META[message.speaker] ?? ROLE_META.system

  if (message.kind === 'status') {
    return (
      <div className="flex items-center gap-2 py-0.5 pl-12 text-[13px] text-ink-3">
        <span className={clsx('size-1.5 rounded-full', meta.dot)} />
        <span>{message.content}</span>
        {live && <TypingDots className={meta.text} />}
      </div>
    )
  }
  if (message.kind === 'error') {
    return (
      <div className="ml-12 flex gap-2 rounded-xl border border-seal/30 bg-seal-soft px-3 py-2 text-sm text-seal">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <span className="break-all">{message.content}</span>
      </div>
    )
  }
  if (message.speaker === 'author') {
    return (
      <div className="flex justify-end gap-2.5">
        <div className="max-w-[85%]">
          <p className="mb-1 text-right text-xs text-ink-3">
            {{ decision: '作者拍板', note: '作者插话' }[message.kind as string] ?? '作者'} · {time(message.created_at)}
          </p>
          <div className="rounded-2xl rounded-tr-md bg-ink px-3.5 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap text-paper-2 shadow-[0_8px_18px_-10px_rgb(38_35_32/0.6)]">
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
    <div className="flex gap-2.5">
      <RoleAvatar speaker={message.speaker} />
      <div className="min-w-0 flex-1">
        <p className="mb-1 text-xs text-ink-3">
          <span className={clsx('font-medium', meta.text)}>{meta.name}</span> · {time(message.created_at)}
        </p>
        {message.kind === 'artifact' ? <ArtifactCard message={message} /> : <Speech message={message} />}
      </div>
    </div>
  )
}

export function MeetingFeed({
  messages,
  working,
  className,
  autoScroll = true,
}: {
  messages: MeetingMessage[]
  working: boolean
  className?: string
  autoScroll?: boolean
}) {
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const reduce = useReducedMotion()

  useEffect(() => {
    const el = scroller.current
    if (el && autoScroll && stick.current) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  }, [messages.length, autoScroll, reduce])

  const lastIndex = messages.length - 1
  const liveStatus = working && messages[lastIndex]?.kind === 'status'

  return (
    <div
      ref={scroller}
      onScroll={(e) => {
        const el = e.currentTarget
        stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120
      }}
      className={clsx('scroll-thin space-y-3.5 overflow-y-auto', className)}
    >
      {messages.map((m, i) => (
        <motion.div
          key={m.id}
          initial={reduce || !isFresh(m.created_at, 30) ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        >
          <MessageRow message={m} live={liveStatus && i === lastIndex} />
        </motion.div>
      ))}
      {working && !liveStatus && (
        <div className="flex items-center gap-2 pl-12 text-ink-3">
          <TypingDots />
        </div>
      )}
    </div>
  )
}
