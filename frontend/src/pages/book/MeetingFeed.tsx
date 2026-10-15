import { useReducedMotion } from '../../lib/appearance'
import clsx from 'clsx'
import { AlertTriangle, Check, ChevronDown, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import type { Concept, InterviewQuestion, LiveDraft, MeetingMessage, PlotUnit, Speaker, Spine, StoryThread } from '../../api/types'
import { TypingDots } from '../../components/ui'
import { ROLE_META } from '../../lib/roles'
import { isFresh, useTypewriter } from '../../lib/team'
import { artifactTarget } from '../../lib/workspace'
import { useBookContext } from './context'

export function RoleAvatar({
  speaker,
  size = 'md',
  working,
}: {
  speaker: Speaker | 'group'
  size?: 'sm' | 'md' | 'lg'
  working?: boolean
}) {
  const meta = speaker === 'group' ? { ...ROLE_META.chief, name: '编辑部群聊', short: '群' } : ROLE_META[speaker] ?? ROLE_META.system
  return (
    <span
      className={clsx(
        'relative inline-flex shrink-0 items-center justify-center rounded-full font-serif font-bold text-on-role',
        meta.dot,
        working && 'breath',
        { sm: 'size-7 text-xs', md: 'size-8 text-sm', lg: 'size-11 text-base' }[size],
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
type UnitBrief = Pick<PlotUnit, 'index' | 'title' | 'chapter_count' | 'climax'> & Partial<Pick<PlotUnit, 'tropes' | 'resolution'>>
interface VolumePlanData {
  volume: number
  units: UnitBrief[]
  new_foreshadowings: { seq: number; description: string }[]
}
interface DirectionsData {
  volume: number
  directions: { name: string; idea: string; difference?: string }[]
}
interface PitchData {
  volume: number
  pitch: number
  name: string
  idea: string
  remark?: string
  units: UnitBrief[]
}
interface ScoreRow {
  pitch: number
  name: string
  cool?: number
  weaving?: number
  villain?: number
  novelty?: number
  total?: number
  comment?: string
}
interface ScoresData {
  volume: number
  winner: number
  merge: string
  scores: ScoreRow[]
}
interface AuditData {
  volume: number
  verdict: 'pass' | 'revise'
  checks: { aspect: string; ok: boolean; comment: string }[]
  issues: { aspect: string; unit: number; problem: string; suggestion: string; severity: 'high' | 'medium' | 'low' }[]
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
interface MaterialsData {
  index: number
  characters: string[]
  world: string[]
  chapters: number[]
  notes: string[]
}
interface PolishData {
  index: number
  action: 'extend' | 'ending'
  before?: number
  after?: number | string
  reason?: string
}
interface RecapData {
  recap: string
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
const ASPECT_NAME: Record<string, string> = { villain: '反派智商', rhythm: '爽点节奏', foreshadow: '伏笔排期', repetition: '套路重复' }
const SCORE_COLUMNS: [keyof ScoreRow, string][] = [
  ['cool', '爽点'],
  ['weaving', '线索'],
  ['villain', '反派'],
  ['novelty', '新意'],
]

function TropeTags({ tropes, resolution }: { tropes?: string[]; resolution?: string }) {
  if (!tropes?.length && !resolution) return null
  return (
    <span className="mx-1 inline-flex flex-wrap gap-1 align-middle">
      {tropes?.map((t) => (
        <span key={t} className="rounded bg-chief-soft px-1.5 py-px text-xs text-chief">
          {t}
        </span>
      ))}
      {resolution && <span className="rounded px-1.5 py-px text-xs text-ink-2 ring-1 ring-line">破局·{resolution}</span>}
    </span>
  )
}

function UnitList({ units }: { units: UnitBrief[] }) {
  return (
    <ol className="space-y-1.5 text-ink-2">
      {units.map((u) => (
        <li key={u.index}>
          <span className="font-medium text-ink">
            {u.index}. {u.title}
          </span>
          <span className="text-xs text-ink-2"> 约 {u.chapter_count} 章</span>
          <TropeTags tropes={u.tropes} resolution={u.resolution} /> {u.climax}
        </li>
      ))}
    </ol>
  )
}

function PitchScores({ data }: { data: ScoresData }) {
  const best = Math.max(1, ...data.scores.map((r) => r.total ?? 0))
  return (
    <div className="space-y-2.5">
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full text-left tabular-nums">
          <thead className="text-xs whitespace-nowrap text-ink-2">
            <tr>
              <th className="py-1 pr-2 font-normal">方案</th>
              {SCORE_COLUMNS.map(([key, label]) => (
                <th key={key} className="px-1.5 py-1 text-center font-normal">
                  {label}
                </th>
              ))}
              <th className="py-1 pl-2 font-normal">总分</th>
            </tr>
          </thead>
          <tbody>
            {data.scores.map((row) => {
              const win = row.pitch === data.winner
              return (
                <tr key={row.pitch} className="border-t border-line">
                  <td className="py-1.5 pr-2">
                    <span className="flex items-center gap-1 whitespace-nowrap">
                      <span className={clsx('font-medium', win ? 'text-seal' : 'text-ink')}>方案{row.pitch}</span>
                      {win && <span className="rounded-sm border border-seal/40 px-1 text-xs leading-4 text-seal">胜出</span>}
                    </span>
                    <span className="block text-xs text-ink-2">{row.name}</span>
                  </td>
                  {SCORE_COLUMNS.map(([key]) => (
                    <td key={key} className="px-1.5 text-center text-ink-2">
                      {row[key] ?? '–'}
                    </td>
                  ))}
                  <td className="py-1.5 pl-2">
                    <span className="flex items-center gap-1.5">
                      <span className={clsx('w-5 font-medium', win ? 'text-seal' : 'text-ink')}>{row.total ?? '–'}</span>
                      <span className="h-1 w-12 overflow-hidden rounded-full bg-line">
                        <span
                          className={clsx('block h-full rounded-full transition-[width] duration-700', win ? 'bg-seal' : 'bg-line-2')}
                          style={{ width: `${((row.total ?? 0) / best) * 100}%` }}
                        />
                      </span>
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {data.scores
        .filter((row) => row.comment)
        .map((row) => (
          <p key={row.pitch} className="text-ink-2">
            <span className="text-ink-2">方案{row.pitch}：</span>
            {row.comment}
          </p>
        ))}
      {data.merge && (
        <p className="rounded-lg bg-paper px-3 py-2 text-ink-2">
          <span className="font-medium text-ink">融合：</span>
          {data.merge}
        </p>
      )}
    </div>
  )
}

function VolumeAudit({ data }: { data: AuditData }) {
  return (
    <div className="space-y-2">
      <ul className="grid gap-1.5 @sm:grid-cols-2">
        {data.checks.map((c) => (
          <li key={c.aspect} className="flex gap-2">
            {c.ok ? <Check className="mt-1 size-3.5 shrink-0 text-lore" /> : <X className="mt-1 size-3.5 shrink-0 text-seal" />}
            <span>
              <span className="font-medium text-ink">{ASPECT_NAME[c.aspect] ?? c.aspect}</span>
              <span className="text-ink-2"> · {c.comment}</span>
            </span>
          </li>
        ))}
      </ul>
      {data.issues.map((issue, i) => (
        <div key={i} className="rounded-lg bg-paper px-3 py-2">
          <p className="text-xs text-ink-2">
            {ASPECT_NAME[issue.aspect] ?? issue.aspect}
            {issue.unit ? ` · 第${issue.unit}单元` : ''} · {SEVERITY[issue.severity]}
          </p>
          <p className="text-ink">{issue.problem}</p>
          <p className="text-ink-2">→ {issue.suggestion}</p>
        </div>
      ))}
    </div>
  )
}

export function ArtifactBody({ message }: { message: MeetingMessage }) {
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
            <p className="text-ink-2">{q.options.map((o, j) => (j === q.recommended ? `${o}（推荐）` : o)).join(' / ')}</p>
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
              <span className="text-xs text-ink-2">（第{m.volume}卷）</span> {m.event}
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
        <p className="text-ink-2">世界观：{l.world_entries.map((w) => w.name).join('、')}</p>
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
            {v.chapter_count ? <span className="text-xs text-ink-2">约 {v.chapter_count} 章</span> : null}
            {v.stage ? <span className="text-xs text-ink-2"> · {v.stage}</span> : null} {v.summary}
          </p>
        ))}
        {o.foreshadowings && o.foreshadowings.length > 0 && (
          <p className="text-ink-2">
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
    return <UnitList units={(data as VolumePlanData).units} />
  }
  if (type === 'volume_directions') {
    const d = data as DirectionsData
    return (
      <ol className="space-y-2">
        {d.directions.map((dir, i) => (
          <li key={i} className="flex gap-2.5">
            <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-chief-soft font-serif text-xs text-chief">
              {i + 1}
            </span>
            <div>
              <p className="font-medium text-ink">{dir.name}</p>
              <p className="text-ink-2">{dir.idea}</p>
              {dir.difference && <p className="text-xs text-ink-2">{dir.difference}</p>}
            </div>
          </li>
        ))}
      </ol>
    )
  }
  if (type === 'volume_pitch') {
    const p = data as PitchData
    return (
      <div className="space-y-2">
        {p.remark && <p className="text-ink-2">{p.remark}</p>}
        <UnitList units={p.units} />
      </div>
    )
  }
  if (type === 'pitch_scores') return <PitchScores data={data as ScoresData} />
  if (type === 'volume_audit') return <VolumeAudit data={data as AuditData} />
  if (type === 'chapter_plan') {
    const c = data as ChapterPlanData
    return (
      <ol className="space-y-1 text-ink-2">
        {c.chapters.map((ch) => (
          <li key={ch.index}>
            <span className="font-medium text-ink">第{ch.index}章 {ch.title}</span>
            {ch.hook && <span className="text-ink-2"> —— {ch.hook}</span>}
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
          <p className="text-xs text-ink-2">
            设定库：人物状态更新 {c.characters_updated ?? 0} 处，新人物 {c.characters_created ?? 0} 位，伏笔进展 {c.foreshadowings ?? 0} 条
          </p>
        )}
      </div>
    )
  }
  if (type === 'chapter_materials') {
    const c = data as MaterialsData
    return (
      <div className="space-y-1.5 text-ink-2">
        {c.characters.length > 0 && <p><span className="text-ink-2">人物：</span>{c.characters.join('、')}</p>}
        {c.world.length > 0 && <p><span className="text-ink-2">设定：</span>{c.world.join('、')}</p>}
        {c.chapters.length > 0 && <p><span className="text-ink-2">回顾前文：</span>{c.chapters.map((i) => `第${i}章`).join('、')}</p>}
        {c.notes.length > 0 && (
          <ul className="list-inside list-disc space-y-0.5">
            {c.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  if (type === 'chapter_polish') {
    const c = data as PolishData
    return c.action === 'extend' ? (
      <p className="text-ink-2">初稿只有 {c.before} 字，写手对照章纲把没写足的场景补上，现在 {c.after} 字。</p>
    ) : (
      <div className="space-y-1.5 text-ink-2">
        <p>原来的结尾是总结式的（「{c.reason}」），改成停在钩子上：</p>
        <p className="font-serif leading-relaxed">…{String(c.after ?? '')}</p>
      </div>
    )
  }
  if (type === 'unit_recap' || type === 'volume_recap') {
    return <p className="font-serif leading-relaxed whitespace-pre-wrap text-ink-2">{(data as RecapData).recap}</p>
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
            <p className="text-xs text-ink-2">{SEVERITY[issue.severity]}</p>
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
            <p className="text-xs text-ink-2">
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

function ArtifactCard({ message }: { message: MeetingMessage }) {
  const { bookId, outline, manualNavigate } = useBookContext()
  const [open, setOpen] = useState(false)
  const reduce = useReducedMotion()
  const target = artifactTarget(message, bookId, outline)
  return (
    <div className="min-w-0 border-l-2 border-seal bg-paper/70">
      <div className="flex items-start gap-1">
        <button
          type="button"
          onClick={() => target ? manualNavigate(target.path) : setOpen((value) => !value)}
          className="min-w-0 flex-1 px-3 py-2 text-left hover:bg-paper"
        >
          <span className="block text-[13px] font-medium text-ink">{message.content}</span>
          <span className="mt-1 block text-xs text-seal">{target ? '在右边打开 →' : '查看产出内容'}</span>
        </button>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? '收起' : '展开'}${message.content}`}
          title={open ? '收起内容' : '展开内容'}
          className="m-1 rounded p-2 text-ink-2 hover:bg-paper"
        >
          <ChevronDown className={clsx('size-4 transition-transform duration-300', open && 'rotate-180')} />
        </button>
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="@container border-t border-divider px-3 py-3 text-sm leading-[1.75] text-ink-2">
              <ArtifactBody message={message} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Speech({ message }: { message: MeetingMessage }) {
  const reduce = useReducedMotion()
  const [fresh] = useState(() => isFresh(message.created_at))
  const { shown, typing } = useTypewriter(message.content, fresh && !reduce)
  return <span className={clsx('whitespace-pre-wrap break-words', typing && 'caret')}>{shown}</span>
}

const DRAFT_MODE: Record<LiveDraft['mode'], string> = { write: '正在写', extend: '字数不够，正在接着写', ending: '正在改写结尾' }

/** 正文在右边实时显示，会话只保留短小的同步预览。 */
function LiveDraftRow({ draft, fromGroup }: { draft: LiveDraft; fromGroup?: boolean }) {
  const { bookId, manualNavigate } = useBookContext()
  const tail = draft.text.slice(-160)
  return (
    <div className="flex gap-2.5">
      <RoleAvatar speaker="writer" working />
      <div className="min-w-0 flex-1">
        <p className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-2">
          <span className="font-medium text-writer">写手</span>
          {fromGroup && <GroupTag />}
          <span>{DRAFT_MODE[draft.mode]}第 {draft.chapter} 章 · {draft.text.replace(/\s/g, '').length} 字</span>
        </p>
        <div className="rounded-[2px_12px_12px_12px] border border-divider bg-card px-3 py-2.5">
          <p className="font-serif chat-text leading-[1.75] whitespace-pre-wrap text-ink">
            <span className="caret">{tail.length < draft.text.length && '…'}{tail}</span>
          </p>
          <button type="button" onClick={() => manualNavigate(`/books/${bookId}/chapter/${draft.chapter}`)} className="mt-2 text-xs text-seal hover:underline">
            在右边看全文 →
          </button>
        </div>
      </div>
    </div>
  )
}

function GroupTag() {
  return <span className="rounded-sm border border-divider px-1 text-xs text-ink-2">群聊</span>
}

function MessageRow({ message, fromGroup }: { message: MeetingMessage; fromGroup?: boolean }) {
  const meta = ROLE_META[message.speaker] ?? ROLE_META.system
  const author = message.speaker === 'author'
  if (message.kind === 'error') {
    return (
      <div className="flex gap-2 rounded border border-seal/30 bg-seal-soft px-3 py-2 text-sm text-seal">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <span className="break-words">{message.content}</span>
      </div>
    )
  }
  if (message.kind === 'decision' && !author) {
    return <p className="py-1 text-center text-xs text-ink-2">{message.content}</p>
  }
  return (
    <div className={clsx('flex gap-2.5', author && 'flex-row-reverse', fromGroup && 'opacity-80')}>
      <RoleAvatar speaker={message.speaker} />
      <div className={clsx('min-w-0 max-w-[calc(100%-42px)]', message.kind === 'artifact' && 'flex-1')}>
        <p className={clsx('mb-1.5 flex flex-wrap items-center gap-1.5 text-xs', author && 'justify-end')}>
          <span className={clsx('font-medium', author ? 'text-ink-2' : meta.text)}>{author ? '你' : meta.name}</span>
          {fromGroup && <GroupTag />}
          <time className="text-ink-3">{time(message.created_at)}</time>
        </p>
        <div className={clsx(
          'border border-divider px-3 py-2.5 chat-text leading-[1.75] text-ink',
          author ? 'rounded-[12px_2px_12px_12px] bg-author-bubble whitespace-pre-wrap break-words' : 'rounded-[2px_12px_12px_12px] bg-card',
        )}>
          {message.kind === 'artifact' ? <ArtifactCard message={message} /> : author ? message.content : <Speech message={message} />}
        </div>
      </div>
    </div>
  )
}

type Conversation = 'group' | Exclude<Speaker, 'author' | 'system'>
type TeamRole = Exclude<Conversation, 'group'>

function threadOf(message: MeetingMessage): TeamRole | null {
  const thread = message.payload?.thread
  return thread === 'chief' || thread === 'lorekeeper' || thread === 'writer' || thread === 'reviewer' ? thread : null
}

interface FeedEntry {
  message: MeetingMessage
  statuses?: MeetingMessage[]
  privateThread?: TeamRole
  fromGroup?: boolean
}

function visibleEntries(messages: MeetingMessage[], conversation: Conversation, showGroup: boolean): FeedEntry[] {
  const entries: FeedEntry[] = []
  for (const message of messages) {
    const thread = threadOf(message)
    if (conversation !== 'group' && thread !== conversation && !(showGroup && !thread && message.speaker === conversation)) continue
    if (conversation === 'group' && thread) {
      entries.push({ message, privateThread: thread })
      continue
    }
    const fromGroup = conversation !== 'group' && !thread
    const previous = entries.at(-1)
    if (message.kind === 'status') {
      if (previous?.statuses && previous.fromGroup === fromGroup) previous.statuses.push(message)
      else entries.push({ message, statuses: [message], fromGroup })
    } else entries.push({ message, fromGroup })
  }
  return entries
}

function StatusGroup({ messages, live, fromGroup }: { messages: MeetingMessage[]; live: boolean; fromGroup?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const latest = messages[messages.length - 1]
  return (
    <div className="space-y-1.5 py-1 text-center text-xs leading-relaxed text-ink-2">
      {expanded && messages.slice(0, -1).map((message) => <p key={message.id}>{message.content}</p>)}
      <div className="flex flex-wrap items-center justify-center gap-1.5">
        {fromGroup && <GroupTag />}
        <span>{latest.content}</span>
        {live && <TypingDots />}
        {messages.length > 1 && (
          <button type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} className="underline underline-offset-2 hover:text-ink">
            {expanded ? '收起' : `展开 ${messages.length} 条`}
          </button>
        )}
      </div>
    </div>
  )
}

export function MeetingFeed({
  messages,
  working,
  className,
  autoScroll = true,
  draft,
  conversation = 'group',
  showGroup = true,
}: {
  messages: MeetingMessage[]
  working: boolean
  className?: string
  autoScroll?: boolean
  draft?: LiveDraft | null
  conversation?: Conversation
  showGroup?: boolean
}) {
  const { setConversation } = useBookContext()
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  const reduce = useReducedMotion()
  const entries = visibleEntries(messages, conversation, showGroup)
  const showWriting = conversation === 'group' || (conversation === 'writer' && showGroup)
  const writing = working && draft && !draft.done && showWriting ? draft : null
  const lastEntry = entries.at(-1)
  const latestStatus = lastEntry?.statuses?.at(-1)
  const liveStatus = working && !writing && latestStatus?.id === messages.at(-1)?.id

  useEffect(() => {
    const element = scroller.current
    stick.current = true
    if (element && autoScroll) element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
  }, [conversation, showGroup, autoScroll])

  useEffect(() => {
    const element = scroller.current
    if (element && autoScroll && stick.current) element.scrollTo({ top: element.scrollHeight, behavior: reduce ? 'auto' : 'smooth' })
  }, [messages.length, autoScroll, reduce, writing?.text.length])

  return (
    <div
      ref={scroller}
      aria-label={conversation === 'group' ? '编辑部群聊消息' : `${ROLE_META[conversation].name}的会话消息`}
      onScroll={(event) => {
        const element = event.currentTarget
        stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 120
      }}
      className={clsx('scroll-thin space-y-4 overflow-y-auto', className)}
    >
      {entries.length === 0 && !writing && (
        <div className="px-4 py-12 text-center">
          <p className="font-serif text-lg text-ink-2">{conversation === 'group' ? '编辑部，等你开口' : `和${ROLE_META[conversation].name}说说你的想法`}</p>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{conversation === 'group' ? '讨论和产出会留在这里，书稿在右边展开。' : '点名插话会记入作者要求，并由编辑部在工作时处理。'}</p>
        </div>
      )}
      {entries.map((entry, index) => (
        <motion.div
          key={entry.message.id}
          initial={reduce || !isFresh(entry.message.created_at, 30) ? false : { opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduce ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
        >
          {entry.privateThread ? (
            <button type="button" onClick={() => setConversation(entry.privateThread!)} title={entry.message.speaker === 'author' ? entry.message.content : undefined} className="block w-full truncate py-1 text-center text-xs leading-relaxed text-ink-2 hover:text-ink hover:underline">
              {entry.message.speaker === 'author'
                ? `你私聊了${ROLE_META[entry.privateThread].name}：${entry.message.content.length > 45 ? `${entry.message.content.slice(0, 45)}…` : entry.message.content}`
                : `${ROLE_META[entry.privateThread].name}回复了你`}
            </button>
          ) : entry.statuses ? (
            <StatusGroup messages={entry.statuses} live={liveStatus && index === entries.length - 1} fromGroup={entry.fromGroup} />
          ) : <MessageRow message={entry.message} fromGroup={entry.fromGroup} />}
        </motion.div>
      ))}
      {writing && <LiveDraftRow draft={writing} fromGroup={conversation !== 'group'} />}
      {working && conversation === 'group' && !liveStatus && !writing && <div className="flex justify-center py-2 text-ink-2"><TypingDots /></div>}
    </div>
  )
}
