import { Flag, Flame, Swords, Target } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useOutline, useUpdateUnit, useUpdateVolume } from '../../../api/hooks'
import type { PlotUnit } from '../../../api/types'
import { EditableList, EditableText } from '../../../components/Editable'
import { Badge, Card, Reveal, Skeleton } from '../../../components/ui'
import { useBookContext } from '../context'
import { FieldBlock, Locked, PageHeader } from './common'

const STATUS = { planned: ['概要', 'idle'], detailed: ['已拆单元', 'busy'], approved: ['已批准', 'ok'] } as const

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

function UnitCard({ unit, bookId, locked, delay, last }: { unit: PlotUnit; bookId: string; locked: boolean; delay: number; last: boolean }) {
  const update = useUpdateUnit(bookId)
  const save = (patch: Partial<PlotUnit>) => update.mutateAsync({ id: unit.id, ...patch })
  return (
    <Reveal delay={delay} className={last ? 'relative pl-12' : 'relative pb-8 pl-12'}>
      {!last && <span className="absolute top-5 bottom-0 left-[15px] w-px bg-line-2" />}
      <span className="absolute top-1 left-0 flex size-8 items-center justify-center rounded-md bg-seal font-serif text-sm font-bold text-paper-2 shadow-[0_6px_14px_-8px_rgb(180_67_46/0.9)]">
        {unit.index}
      </span>
      <Card hover className="p-5 sm:p-6">
        <div className="mb-4 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <EditableText value={unit.title} onSave={(title) => save({ title })} locked={locked} className="font-serif text-xl font-bold" />
          <span className="text-sm text-ink-3">约 {unit.chapter_count} 章</span>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2">
          <Beat icon={<Target className="size-3.5" />} label="目标">
            <EditableText value={unit.goal} onSave={(goal) => save({ goal })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Swords className="size-3.5" />} label="冲突">
            <EditableText value={unit.conflict} onSave={(conflict) => save({ conflict })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Flame className="size-3.5 text-seal" />} label="高潮">
            <EditableText value={unit.climax} onSave={(climax) => save({ climax })} locked={locked} multiline />
          </Beat>
          <Beat icon={<Flag className="size-3.5" />} label="结果与钩子">
            <EditableText value={unit.outcome} onSave={(outcome) => save({ outcome })} locked={locked} multiline />
          </Beat>
        </div>
        <div className="mt-4">
          <FieldBlock label="关键事件">
            <EditableList items={unit.key_events} onSave={(key_events) => save({ key_events })} locked={locked} ordered />
          </FieldBlock>
        </div>
      </Card>
    </Reveal>
  )
}

export function VolumePage() {
  const { index = '1' } = useParams()
  const { bookId, working } = useBookContext()
  const { data, isLoading } = useOutline(bookId)
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
  const [label, tone] = STATUS[volume.status]
  const chapters = volume.units.reduce((sum, u) => sum + u.chapter_count, 0) || volume.chapter_count

  return (
    <div>
      <PageHeader
        eyebrow={`第${volume.index}卷`}
        title={
          <EditableText
            value={volume.title}
            onSave={(title) => update.mutateAsync({ id: volume.id, title })}
            locked={working}
            inputClassName="font-serif text-3xl font-bold"
          />
        }
        action={
          <div className="flex items-center gap-2">
            <Badge tone={tone}>{label}</Badge>
            {chapters > 0 && <span className="text-sm text-ink-3">共约 {chapters} 章</span>}
          </div>
        }
        subtitle={
          <EditableText
            value={volume.summary}
            onSave={(summary) => update.mutateAsync({ id: volume.id, summary })}
            locked={working}
            multiline
          />
        }
      />
      <Locked locked={working} />
      <Reveal>
        <div className="mb-10 flex gap-3 rounded-xl bg-card/70 px-5 py-4 ring-1 ring-line">
          <span className="shrink-0 pt-0.5 text-xs tracking-[0.15em] text-ink-3">卷末目标</span>
          <EditableText
            value={volume.goal}
            onSave={(goal) => update.mutateAsync({ id: volume.id, goal })}
            locked={working}
            multiline
            className="flex-1 font-serif text-[16px]"
          />
        </div>
      </Reveal>
      {volume.units.length > 0 ? (
        <div>
          {volume.units.map((unit, i) => (
            <UnitCard key={unit.id} unit={unit} bookId={bookId} locked={working} delay={0.06 * i} last={i === volume.units.length - 1} />
          ))}
        </div>
      ) : (
        <Card className="px-6 py-10 text-center">
          <p className="font-serif text-lg text-ink-2">这一卷还没有拆成剧情单元</p>
          <p className="mt-1 text-sm text-ink-3">
            {volume.chapter_count > 0 ? `这一卷计划约 ${volume.chapter_count} 章。` : ''}写到这一卷之前，主编会按主线骨架把它拆细，再请你拍板。
          </p>
        </Card>
      )}
    </div>
  )
}
