import clsx from 'clsx'
import { AlertTriangle, ChevronDown, Flag, Flame, Pin, Repeat2, Swords, Target } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useBible, useChapters, useNodes, useOutline, useUpdateUnit, useUpdateVolume } from '../../../api/hooks'
import type { ChapterBrief, Foreshadowing, ForeshadowStep, PlotUnit, ThreadStep, Volume } from '../../../api/types'
import { EditableList, EditableText } from '../../../components/Editable'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, QuestionField, QuestionSection } from '../../../components/QuestionSection'
import { firstSegment, OPENING_FIELDS } from '../../../lib/setupSegment'
import { EmotionCurve } from '../../../components/EmotionCurve'
import { EditorAnnotations, RevealChips, WritingHint } from '../../../components/WritingLabels'
import { Badge, Card, Reveal, Skeleton } from '../../../components/ui'
import { useReducedMotion } from '../../../lib/appearance'
import type { Tone } from '../../../lib/status'
import { emotionText, foreshadowAction } from '../../../lib/writingUi'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
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
  planned: ['章纲', 'text-ink-2'],
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

const ACTION_TONE: Record<string, string> = { 埋下: 'bg-lore-soft text-lore', 立下: 'bg-chief-soft text-chief', 提醒: 'bg-line/70 text-ink-2', 回收: 'bg-seal-soft text-seal-dark', 兑现: 'bg-seal-soft text-seal-dark' }

export function ForeshadowChips({ actions, ledger = [] }: { actions: ForeshadowStep[]; ledger?: Foreshadowing[] }) {
  if (!actions.length) return null
  return (
    <ul aria-label="期待与伏笔动作" className="flex flex-wrap gap-1.5">
      {actions.map((action, i) => {
        const { label, code, hint } = foreshadowAction(action, ledger)
        return <li key={i}><WritingHint label={`${label} ${code}`} hint={hint} className={clsx('rounded-full px-2.5 py-0.5 text-xs', ACTION_TONE[label] ?? 'bg-line/70 text-ink-2')}>{label} {code}</WritingHint></li>
      })}
    </ul>
  )
}

function Beat({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line pt-3">
      <p className="mb-1 flex items-center gap-1.5 text-xs text-ink-2">
        {icon}
        {label}
      </p>
      <div className="text-[14px] leading-relaxed">{children}</div>
    </div>
  )
}

function ChapterRow({ chapter, bookId, ledger }: { chapter: ChapterBrief; bookId: string; ledger: Foreshadowing[] }) {
  const [open, setOpen] = useState(false)
  const reduce = useReducedMotion()
  const [label, tone] = CHAPTER_STATUS[chapter.status]
  const o = chapter.outline ?? {}
  return (
    <li className="rounded-lg ring-1 ring-transparent transition-colors hover:bg-paper-2 hover:ring-line/80">
      <div className="flex items-center gap-2 px-2.5 py-1.5 text-[14px]">
        <button onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-center gap-2 text-left" aria-expanded={open}>
          <ChevronDown className={clsx('size-3.5 shrink-0 text-ink-2 transition-transform', open && 'rotate-180')} />
          <span className="w-14 shrink-0 text-xs text-ink-2">第{chapter.index}章</span>
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
          <motion.div initial={reduce ? false : { height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: reduce ? 0 : 0.25 }} className="overflow-hidden">
            <div className="space-y-1.5 px-9 pb-3 text-[14px] leading-relaxed text-ink-2">
              {o.goal && <p><span className="text-ink-2">目标：</span>{o.goal}</p>}
              {o.scenes && o.scenes.length > 0 && (
                <ol className="list-inside list-decimal space-y-0.5">
                  {o.scenes.map((scene, i) => (
                    <li key={i}>{scene}</li>
                  ))}
                </ol>
              )}
              {o.cool_point && <p><span className="text-seal">爽点：</span>{o.cool_point}</p>}
              {o.hook && <p><span className="text-ink-2">结尾钩子：</span>{o.hook}</p>}
              {emotionText(o.emotion) && <p>情绪：{emotionText(o.emotion)}{o.mood ? `（${o.mood}）` : ''}</p>}
              {o.foreshadow_actions && o.foreshadow_actions.length > 0 && <ForeshadowChips actions={o.foreshadow_actions} ledger={ledger} />}
              <RevealChips reveals={o.reveals} />
              {chapter.summary && <p className="border-t border-line pt-1.5"><span className="text-ink-2">实际写了：</span>{chapter.summary}</p>}
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
  ledger,
}: {
  unit: PlotUnit
  chapters: ChapterBrief[]
  bookId: string
  locked: boolean
  delay: number
  last: boolean
  ledger: Foreshadowing[]
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
          unit.status === 'done' ? 'bg-lore' : 'bg-seal shadow-[var(--shadow-paper)]',
        )}
      >
        {unit.index}
      </span>
      <Card hover className="p-5 @lg/manuscript:p-6">
        {!!unit.plan_issues?.length && <details className="mb-4 rounded-lg border border-reviewer/30 bg-reviewer-soft px-3 py-2 text-sm text-seal-dark" data-testid="unit-plan-issues">
          <summary className="flex cursor-pointer items-center gap-2 focus-visible:outline-2 focus-visible:outline-reviewer"><AlertTriangle className="size-4 shrink-0" />章纲还有 {unit.plan_issues.length} 处节奏问题<ChevronDown className="ml-auto size-3.5" /></summary>
          <ul className="mt-2 list-disc space-y-1 border-t border-reviewer/20 pt-2 pl-5 leading-relaxed">{unit.plan_issues.map((issue, i) => <li key={i}>{issue}</li>)}</ul>
        </details>}
        <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <EditableText value={unit.title} onSave={(title) => save({ title })} locked={locked} className="font-serif text-xl font-bold" />
          <span className="text-sm text-ink-2">
            {chapters.length ? `第 ${chapters[0].index}-${chapters[chapters.length - 1].index} 章` : `约 ${unit.chapter_count} 章`}
          </span>
          <Badge tone={tone} className="ml-auto">
            {label}
            {unit.status === 'outlined' && chapters.length > 0 && ` ${finals}/${chapters.length}`}
          </Badge>
        </div>
        <EmotionCurve chapters={chapters} />
        <div className="grid gap-2.5 @lg/manuscript:grid-cols-2">
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
          <Beat icon={<Repeat2 className="size-3.5" />} label="核心循环">
            <EditableText value={unit.loop ?? ''} onSave={(loop) => save({ loop })} locked={locked} multiline />
          </Beat>
        </div>
        <div className="mt-4 grid gap-4 @lg/manuscript:grid-cols-2">
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
                    <li className="rounded-full px-2.5 py-0.5 text-xs text-ink-2 ring-1 ring-line">破局 · {unit.resolution}</li>
                  )}
                </ul>
              </FieldBlock>
            )}
            {unit.foreshadow_actions.length > 0 && (
              <FieldBlock label="期待与伏笔动作">
                <ForeshadowChips actions={unit.foreshadow_actions} ledger={ledger} />
              </FieldBlock>
            )}
            {!!unit.reveals?.length && <FieldBlock label="揭晓"><RevealChips reveals={unit.reveals} /></FieldBlock>}
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
            <p className="mb-1.5 text-xs tracking-[0.15em] text-ink-2">章纲</p>
            <ul className="-mx-2.5 space-y-0.5">
              {chapters.map((c) => (
                <ChapterRow key={c.id} chapter={c} bookId={bookId} ledger={ledger} />
              ))}
            </ul>
          </div>
        )}
        <EditorAnnotations note={unit.editor_note} techniques={unit.techniques} />
      </Card>
    </Reveal>
  )
}

export function VolumePage() {
  const { index = '1' } = useParams()
  const { bookId, book, job, working, manualNavigate } = useBookContext()
  const { data, isLoading } = useOutline(bookId)
  const { data: chapters = [] } = useChapters(bookId, Number(index))
  const { data: nodes = [] } = useNodes(bookId)
  const { data: bible } = useBible(bookId)
  const update = useUpdateVolume(bookId)
  const volume = data?.volumes.find(v => v.index === Number(index))

  if (isLoading) return <Skeleton className="h-64" />
  if (!volume) return <PageHeader eyebrow="大纲" title="这一卷还不存在" subtitle={<Link to={`/books/${bookId}`} className="text-seal underline">回到概览</Link>} />

  const [label, tone] = VOLUME_STATUS[volume.status] ?? VOLUME_STATUS.planned
  const total = volume.units.reduce((sum, unit) => sum + unit.chapter_count, 0) || volume.chapter_count
  const save = (patch: Parameters<typeof update.mutateAsync>[0]) => update.mutateAsync(patch)
  const locked = working || update.isPending
  const targetNode = nodes.find(node => node.id === volume.target_node_id)
  const firstSetup = volume.index === 1 && (['setting_up', 'awaiting_approval'].includes(book.status) ||
    (job?.kind === 'book_setup' && ['queued', 'running', 'waiting_author'].includes(job.status)))
  const pending = firstSetup && job?.status === 'waiting_author' ? job.pending : null
  const opening = volume.index === 1 ? firstSegment(nodes).endpoint?.segment?.opening : null
  const section = (questionKey: string, children: ReactNode) => <QuestionSection piece="first_volume" questionKey={questionKey} pending={pending}>{children}</QuestionSection>
  const field = (key: 'want' | 'pressure' | 'climax' | 'goal' | 'antagonist' | 'power_range') => <EditableText value={volume[key] ?? ''} onSave={value => save({ id: volume.id, [key]: value })} locked={locked} multiline />

  return <div data-testid="volume-questions">
    <PageHeader
      eyebrow={`第${volume.index}卷`}
      title={<EditableText value={volume.title} onSave={title => save({ id: volume.id, title })} locked={locked} inputClassName="font-serif text-[26px] font-bold" />}
      action={<div className="flex items-center gap-2"><Badge tone={tone}>{label}</Badge>{total > 0 && <span className="text-sm text-ink-2">共约 {total} 章</span>}</div>}
      subtitle={<EditableText value={volume.summary} onSave={summary => save({ id: volume.id, summary })} locked={locked} multiline />}
    />
    {firstSetup && <><PieceDecisions piece="first_volume" /><FocusQuestions piece="first_volume" /></>}
    <Locked locked={working} />
    <FactTable className="mb-6" rows={[
      { label: '舞台', value: <EditableText value={volume.stage} onSave={stage => save({ id: volume.id, stage })} locked={locked} multiline /> },
      { label: '预计章数', value: <div className="flex items-center gap-2"><EditableText value={String(volume.chapter_count || '')} placeholder="（未定）" onSave={value => {
        const chapter_count = Number(value)
        if (!Number.isInteger(chapter_count) || chapter_count < 1) return Promise.reject(new Error('预计章数请填大于 0 的整数'))
        return save({ id: volume.id, chapter_count })
      }} locked={locked} /><span className="text-xs text-ink-2">章{volume.units.length > 0 && ` · 已拆单元共 ${total} 章`}</span></div> },
    ]} />
    {targetNode && <section aria-label="本卷走向" className="mb-6 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-paper-2 px-4 py-3 text-sm">
      <span className="text-ink-2">走向：</span>
      <button type="button" onClick={() => manualNavigate(`/books/${bookId}/spine#story-node-${targetNode.id}`)} className="font-medium text-chief underline decoration-chief/35 underline-offset-4 hover:decoration-chief focus-visible:outline-2 focus-visible:outline-chief">节点 {targetNode.index}「{targetNode.title}」</button>
      <span className={clsx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs', targetNode.status === 'pinned' ? 'border-seal/35 bg-seal-soft text-seal' : 'border-dashed border-chief/50 text-chief')}>{targetNode.status === 'pinned' ? <><Pin className="size-3" />铁钉</> : targetNode.status === 'empty' ? '留空' : '暂定'}</span>
      {volume.reaches_node && <span className="text-xs text-seal">本卷发生</span>}
    </section>}
    {section('want', field('want'))}
    {section('pressure', field('pressure'))}
    {section('climax', <div className="space-y-4"><QuestionField label="卷末高潮">{field('climax')}</QuestionField><QuestionField label="卷末结果">{field('goal')}</QuestionField></div>)}
    {section('rival', field('antagonist'))}
    {(volume.thread_beats.length > 0 || volume.editor_note || volume.techniques?.length > 0) && <section className="mb-7 space-y-4 border-b border-line pb-6">
      {volume.thread_beats.length > 0 && <FieldBlock label="本卷推进的线索"><ThreadChips steps={volume.thread_beats} /></FieldBlock>}
      <EditorAnnotations note={volume.editor_note} techniques={volume.techniques} />
    </section>}
    {volume.recap && <Reveal><section className="mb-8 border-b border-line pb-8"><p className="mb-1.5 text-xs tracking-[0.15em] text-lore">卷回顾 · 这一卷写完后设定师写的，后面各卷规划和写作都靠它记住前情</p><p className="font-serif text-[15px] leading-relaxed whitespace-pre-wrap text-ink-2">{volume.recap}</p></section></Reveal>}
    {section('units', volume.units.length > 0 ? <div>{volume.units.map((unit, i) => <UnitCard key={unit.id} unit={unit} chapters={chapters.filter(chapter => chapter.unit_id === unit.id)} bookId={bookId} locked={working} delay={0.06 * i} last={i === volume.units.length - 1} ledger={bible?.foreshadowings ?? []} />)}</div> : <div className="py-6 text-center"><p className="font-serif text-lg text-ink-2">这一卷还没有拆成剧情单元</p><p className="mt-2 text-sm leading-relaxed text-ink-2">{volume.chapter_count > 0 ? `这一卷计划约 ${volume.chapter_count} 章。` : ''}写到这一卷之前，主编会按总纲和线索把它拆成剧情单元，再请你拍板。</p></div>)}
    {section('growth', field('power_range'))}
    {section('newcomers', <EditableList items={volume.new_characters ?? []} onSave={new_characters => save({ id: volume.id, new_characters })} locked={locked} />)}
    {opening && section('landing', <div className="space-y-4"><FactTable rows={OPENING_FIELDS.map(([key, label]) => ({ label, value: <p className="whitespace-pre-wrap text-sm leading-relaxed">{opening[key] || '（未定）'}</p> }))} /><p className="text-xs text-ink-2">第一个单元出章纲时照这个来</p><button type="button" onClick={() => manualNavigate(`/books/${bookId}/spine#q-opening`)} className="text-sm text-chief underline decoration-chief/35 underline-offset-4 focus-visible:outline-2 focus-visible:outline-chief">去第一段面板查看和修改开篇 →</button></div>)}
  </div>
}
