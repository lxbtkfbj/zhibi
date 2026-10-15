import clsx from 'clsx'
import { ChevronDown, Flag, Flame, MapPin, Skull, Swords, Target, TrendingUp, UserPlus } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useChapters, useOutline, useUpdateUnit, useUpdateVolume } from '../../../api/hooks'
import type { ChapterBrief, ForeshadowStep, PlotUnit, ThreadStep, Volume } from '../../../api/types'
import { EditableList, EditableText } from '../../../components/Editable'
import { Badge, Card, Reveal, Skeleton } from '../../../components/ui'
import type { Tone } from '../../../lib/status'
import { useBookContext } from '../context'
import { DecisionControls } from '../Decision'
import { FieldBlock, Locked, PageHeader } from './common'

const VOLUME_STATUS: Record<Volume['status'], [string, Tone]> = {
  planned: ['只有总纲', 'idle'],
  detailed: ['卷纲待拍板', 'wait'],
  approved: ['已批准', 'ok'],
  done: ['已写完', 'ok'],
}
const UNIT_STATUS: Record<PlotUnit['status'], [string, Tone]> = {
  planned: ['待出章纲', 'idle'],
  outlined: ['写作中', 'busy'],
  done: ['已写完', 'ok'],
}
const CHAPTER_STATUS: Record<ChapterBrief['status'], [string, string]> = {
  planned: ['章纲', 'text-ink-3'],
  drafting: ['写作中', 'text-chief'],
  final: ['已定稿', 'text-lore'],
}

export function ThreadChips({ steps }: { steps: ThreadStep[] }) {
  if (!steps.length) return null
  return (
    <ul className="space-y-1.5">
      {steps.map((s, i) => (
        <li key={i} className="flex gap-2 text-[14px] leading-relaxed">
          <span className="mt-0.5 h-fit shrink-0 rounded-md bg-chief-soft px-1.5 py-px text-xs text-chief">{s.thread.replace(/^[^：:]+[：:]/, '')}</span>
          <span className="text-ink-2">{s.beat}</span>
        </li>
      ))}
    </ul>
  )
}

const ACTION_TONE: Record<string, string> = { 埋下: 'bg-lore-soft text-lore', 提醒: 'bg-line/70 text-ink-2', 回收: 'bg-seal-soft text-seal' }

export function ForeshadowChips({ actions }: { actions: ForeshadowStep[] }) {
  if (!actions.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5">
      {actions.map((a, i) => (
        <li key={i} title={a.detail} className={clsx('rounded-full px-2.5 py-0.5 text-xs', ACTION_TONE[a.action] ?? 'bg-line/70 text-ink-2')}>
          {a.action} {a.ref}
          {a.detail && <span className="ml-1 opacity-75">· {a.detail.length > 18 ? `${a.detail.slice(0, 18)}…` : a.detail}</span>}
        </li>
      ))}
    </ul>
  )
}

function Beat({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl bg-paper-2 px-4 py-3 ring-1 ring-line/80">
      <p className="mb-1 flex items-center gap-1.5 text-xs text-ink-3">
        {icon}
        {label}
      </p>
      <div className="text-[14px] leading-relaxed">{children}</div>
    </div>
  )
}

function ChapterRow({ chapter, bookId }: { chapter: ChapterBrief; bookId: string }) {
  const [open, setOpen] = useState(false)
  const [label, tone] = CHAPTER_STATUS[chapter.status]
  const o = chapter.outline ?? {}
  return (
    <li className="rounded-lg ring-1 ring-transparent transition-colors hover:bg-paper-2 hover:ring-line/80">
      <div className="flex items-center gap-2 px-2.5 py-1.5 text-[14px]">
        <button onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={open}>
          <ChevronDown className={clsx('size-3.5 shrink-0 text-ink-3 transition-transform', open && 'rotate-180')} />
          <span className="w-14 shrink-0 text-xs text-ink-3">第{chapter.index}章</span>
          <span className="truncate">{chapter.title}</span>
        </button>
        <span className={clsx('shrink-0 text-xs', tone)}>
          {label}
          {chapter.status === 'final' && ` · ${chapter.word_count} 字`}
        </span>
        {chapter.status !== 'planned' && (
          <Link to={`/books/${bookId}/chapter/${chapter.index}`} className="shrink-0 text-xs text-seal hover:underline">
            读
          </Link>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }} className="overflow-hidden">
            <div className="space-y-1.5 px-9 pb-3 text-[13px] leading-relaxed text-ink-2">
              {o.goal && <p><span className="text-ink-3">目标：</span>{o.goal}</p>}
              {o.scenes && o.scenes.length > 0 && (
                <ol className="list-inside list-decimal space-y-0.5">
                  {o.scenes.map((scene, i) => (
                    <li key={i}>{scene}</li>
                  ))}
                </ol>
              )}
              {o.cool_point && <p><span className="text-seal">爽点：</span>{o.cool_point}</p>}
              {o.hook && <p><span className="text-ink-3">结尾钩子：</span>{o.hook}</p>}
              {o.foreshadow_actions && o.foreshadow_actions.length > 0 && <ForeshadowChips actions={o.foreshadow_actions} />}
              {chapter.summary && <p className="border-t border-line pt-1.5"><span className="text-ink-3">实际写了：</span>{chapter.summary}</p>}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

function UnitCard({
  unit,
  chapters,
  bookId,
  locked,
  delay,
  last,
}: {
  unit: PlotUnit
  chapters: ChapterBrief[]
  bookId: string
  locked: boolean
  delay: number
  last: boolean
}) {
  const update = useUpdateUnit(bookId)
  const save = (patch: Partial<PlotUnit>) => update.mutateAsync({ id: unit.id, ...patch })
  const [label, tone] = UNIT_STATUS[unit.status] ?? UNIT_STATUS.planned
  const finals = chapters.filter((c) => c.status === 'final').length
  return (
    <Reveal delay={delay} className={last ? 'relative pl-12' : 'relative pb-8 pl-12'}>
      {!last && <span className="absolute top-5 bottom-0 left-[15px] w-px bg-line-2" />}
      <span
        className={clsx(
          'absolute top-1 left-0 flex size-8 items-center justify-center rounded-md font-serif text-sm font-bold text-paper-2',
          unit.status === 'done' ? 'bg-lore' : 'bg-seal shadow-[0_6px_14px_-8px_rgb(180_67_46/0.9)]',
        )}
      >
        {unit.index}
      </span>
      <Card hover className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <EditableText value={unit.title} onSave={(title) => save({ title })} locked={locked} className="font-serif text-xl font-bold" />
          <span className="text-sm text-ink-3">
            {chapters.length ? `第 ${chapters[0].index}-${chapters[chapters.length - 1].index} 章` : `约 ${unit.chapter_count} 章`}
          </span>
          <Badge tone={tone} className="ml-auto">
            {label}
            {unit.status === 'outlined' && chapters.length > 0 && ` ${finals}/${chapters.length}`}
          </Badge>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <Beat icon={<Target className="size-3.5" />} label="目标">
            <EditableText value={unit.goal} onSave={(goal) => save({ goal })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Swords className="size-3.5" />} label="冲突">
            <EditableText value={unit.conflict} onSave={(conflict) => save({ conflict })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Flame className="size-3.5 text-seal" />} label="高潮与爽点">
            <EditableText value={unit.climax} onSave={(climax) => save({ climax })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Flag className="size-3.5" />} label="结果与钩子">
            <EditableText value={unit.outcome} onSave={(outcome) => save({ outcome })} locked={locked} multiline />
          </Beat>
        </div>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <FieldBlock label="关键事件">
            <EditableList items={unit.key_events} onSave={(key_events) => save({ key_events })} locked={locked} ordered />
          </FieldBlock>
          <div className="space-y-4">
            {unit.thread_beats.length > 0 && (
              <FieldBlock label="推进线索">
                <ThreadChips steps={unit.thread_beats} />
              </FieldBlock>
            )}
            {(unit.tropes?.length > 0 || unit.resolution) && (
              <FieldBlock label="套路与破局">
                <ul className="flex flex-wrap gap-1.5">
                  {unit.tropes?.map((t) => (
                    <li key={t} className="rounded-full bg-chief-soft px-2.5 py-0.5 text-xs text-chief">
                      {t}
                    </li>
                  ))}
                  {unit.resolution && (
                    <li className="rounded-full px-2.5 py-0.5 text-xs text-ink-3 ring-1 ring-line">破局 · {unit.resolution}</li>
                  )}
                </ul>
              </FieldBlock>
            )}
            {unit.foreshadow_actions.length > 0 && (
              <FieldBlock label="伏笔">
                <ForeshadowChips actions={unit.foreshadow_actions} />
              </FieldBlock>
            )}
          </div>
        </div>
        {unit.recap && (
          <div className="mt-5 rounded-xl bg-lore-soft/50 px-4 py-3">
            <p className="mb-1 text-xs tracking-[0.15em] text-lore">单元回顾 · 设定师写于这一单元写完时</p>
            <p className="font-serif text-[14px] leading-relaxed text-ink-2">{unit.recap}</p>
          </div>
        )}
        {chapters.length > 0 && (
          <div className="mt-5 border-t border-line pt-3">
            <p className="mb-1.5 text-xs tracking-[0.15em] text-ink-3">章纲</p>
            <ul className="-mx-2.5 space-y-0.5">
              {chapters.map((c) => (
                <ChapterRow key={c.id} chapter={c} bookId={bookId} />
              ))}
            </ul>
          </div>
        )}
      </Card>
    </Reveal>
  )
}

function CardField({ icon, label, value, onSave, locked }: { icon: ReactNode; label: string; value: string; onSave: (v: string) => Promise<unknown>; locked: boolean }) {
  return (
    <div className="flex gap-3">
      <span className="mt-0.5 text-ink-3">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-xs text-ink-3">{label}</p>
        <EditableText value={value} onSave={onSave} locked={locked} multiline className="text-[14px] leading-relaxed" />
      </div>
    </div>
  )
}

export function VolumePage() {
  const { index = '1' } = useParams()
  const { bookId, working, job } = useBookContext()
  const { data, isLoading } = useOutline(bookId)
  const { data: chapters = [] } = useChapters(bookId, Number(index))
  const update = useUpdateVolume(bookId)
  const volume = data?.volumes.find((v) => v.index === Number(index))

  if (isLoading) return <Skeleton className="h-64" />
  if (!volume) {
    return (
      <PageHeader
        eyebrow="大纲"
        title="这一卷还不存在"
        subtitle={<Link to={`/books/${bookId}`} className="text-seal underline">回到概览</Link>}
      />
    )
  }
  const [label, tone] = VOLUME_STATUS[volume.status] ?? VOLUME_STATUS.planned
  const total = volume.units.reduce((sum, u) => sum + u.chapter_count, 0) || volume.chapter_count
  const save = (patch: Parameters<typeof update.mutateAsync>[0]) => update.mutateAsync(patch)
  const reviewing = job?.status === 'waiting_author' && job.pending?.kind === 'volume_review' && job.pending.volume === volume.index

  return (
    <div>
      <PageHeader
        eyebrow={`第${volume.index}卷`}
        title={
          <EditableText
            value={volume.title}
            onSave={(title) => save({ id: volume.id, title })}
            locked={working}
            inputClassName="font-serif text-3xl font-bold"
          />
        }
        action={
          <div className="flex items-center gap-2">
            <Badge tone={tone}>{label}</Badge>
            {total > 0 && <span className="text-sm text-ink-3">共约 {total} 章</span>}
          </div>
        }
        subtitle={<EditableText value={volume.summary} onSave={(summary) => save({ id: volume.id, summary })} locked={working} multiline />}
      />
      <Locked locked={working} />
      {reviewing && job && (
        <Reveal>
          <div className="relative mb-8 overflow-hidden rounded-2xl border border-seal/25 bg-card p-5 shadow-[var(--shadow-lift)]">
            <span className="absolute inset-y-0 left-0 w-1.5 bg-seal" />
            <p className="mb-1 font-serif text-lg font-bold">这一卷的卷纲等你拍板</p>
            <p className="mb-4 text-sm text-ink-2">下面的剧情单元可以直接点开修改；满意就盖章开写，想让主编改就写下意见。</p>
            <DecisionControls job={job} compact />
          </div>
        </Reveal>
      )}
      <Reveal>
        <Card className="mb-10 grid gap-5 p-5 sm:grid-cols-2 sm:p-6">
          <CardField icon={<MapPin className="size-4" />} label="舞台" value={volume.stage} onSave={(stage) => save({ id: volume.id, stage })} locked={working} />
          <CardField icon={<Skull className="size-4" />} label="主要对手" value={volume.antagonist} onSave={(antagonist) => save({ id: volume.id, antagonist })} locked={working} />
          <CardField icon={<TrendingUp className="size-4" />} label="主角实力" value={volume.power_range} onSave={(power_range) => save({ id: volume.id, power_range })} locked={working} />
          <CardField icon={<Flame className="size-4 text-seal" />} label="本卷高潮" value={volume.climax} onSave={(climax) => save({ id: volume.id, climax })} locked={working} />
          <CardField icon={<Flag className="size-4" />} label="卷末目标" value={volume.goal} onSave={(goal) => save({ id: volume.id, goal })} locked={working} />
          <div className="flex gap-3">
            <span className="mt-0.5 text-ink-3">
              <UserPlus className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs text-ink-3">新登场</p>
              <EditableList items={volume.new_characters} onSave={(new_characters) => save({ id: volume.id, new_characters })} locked={working} />
            </div>
          </div>
          {volume.thread_beats.length > 0 && (
            <div className="sm:col-span-2">
              <p className="mb-1.5 text-xs text-ink-3">本卷推进的线索</p>
              <ThreadChips steps={volume.thread_beats} />
            </div>
          )}
        </Card>
      </Reveal>
      {volume.recap && (
        <Reveal>
          <Card className="mb-10 p-5 sm:p-6">
            <p className="mb-1.5 text-xs tracking-[0.15em] text-lore">卷回顾 · 这一卷写完后设定师写的，后面各卷规划和写作都靠它记住前情</p>
            <p className="font-serif text-[15px] leading-relaxed whitespace-pre-wrap text-ink-2">{volume.recap}</p>
          </Card>
        </Reveal>
      )}
      {volume.units.length > 0 ? (
        <div>
          {volume.units.map((unit, i) => (
            <UnitCard
              key={unit.id}
              unit={unit}
              chapters={chapters.filter((c) => c.unit_id === unit.id)}
              bookId={bookId}
              locked={working}
              delay={0.06 * i}
              last={i === volume.units.length - 1}
            />
          ))}
        </div>
      ) : (
        <Card className="px-6 py-10 text-center">
          <p className="font-serif text-lg text-ink-2">这一卷还没有拆成剧情单元</p>
          <p className="mt-1 text-sm text-ink-3">
            {volume.chapter_count > 0 ? `这一卷计划约 ${volume.chapter_count} 章。` : ''}写到这一卷之前，主编会按总纲和线索把它拆成剧情单元，再请你拍板。
          </p>
        </Card>
      )}
    </div>
  )
}
