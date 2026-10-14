import clsx from 'clsx'
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { useOutline, useUpdateBook, useUpdateUnit, useUpdateVolume } from '../../api/hooks'
import type { Concept, PlotUnit, Volume } from '../../api/types'
import { EditableList, EditableText } from '../../components/Editable'
import { Badge, Card, EmptyState, Spinner } from '../../components/ui'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[5.5rem_1fr] sm:gap-3">
      <span className="pt-0.5 text-xs text-ink-3">{label}</span>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  )
}

function ConceptCard({ bookId, concept, locked }: { bookId: string; concept: Concept; locked: boolean }) {
  const update = useUpdateBook(bookId)
  const save = (patch: Partial<Concept>) => update.mutateAsync({ concept: patch })
  return (
    <Card className="p-5">
      <div className="mb-4">
        <EditableText
          value={concept.title ?? ''}
          onSave={(title) => update.mutateAsync({ title })}
          locked={locked}
          className="font-serif text-2xl font-bold"
          inputClassName="font-serif text-2xl font-bold"
        />
        {concept.alt_titles && concept.alt_titles.length > 0 && (
          <p className="mt-1 text-xs text-ink-3">备选书名：{concept.alt_titles.join(' / ')}</p>
        )}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {concept.genre && <Badge tone="busy">{concept.genre}</Badge>}
          {concept.tags?.map((t) => (
            <Badge key={t}>{t}</Badge>
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <Field label="一句话简介">
          <EditableText value={concept.logline ?? ''} onSave={(logline) => save({ logline })} locked={locked} multiline />
        </Field>
        <Field label="核心卖点">
          <EditableList items={concept.selling_points ?? []} onSave={(selling_points) => save({ selling_points })} locked={locked} />
        </Field>
        <Field label="主角钩子">
          <EditableText
            value={concept.protagonist_hook ?? ''}
            onSave={(protagonist_hook) => save({ protagonist_hook })}
            locked={locked}
            multiline
          />
        </Field>
        <Field label="基调文风">
          <EditableText value={concept.tone ?? ''} onSave={(tone) => save({ tone })} locked={locked} multiline />
        </Field>
        <Field label="篇幅">
          <span className="text-ink-2">
            计划 {concept.target_volumes ?? '-'} 卷，每章约 {concept.chapter_words ?? '-'} 字
          </span>
        </Field>
      </div>
    </Card>
  )
}

function UnitCard({ bookId, unit, locked }: { bookId: string; unit: PlotUnit; locked: boolean }) {
  const update = useUpdateUnit(bookId)
  const save = (patch: Partial<PlotUnit>) => update.mutateAsync({ id: unit.id, ...patch })
  return (
    <div className="relative border-l-2 border-line-2 pb-5 pl-5 last:pb-0">
      <span className="absolute top-0.5 -left-[9px] flex size-4 items-center justify-center rounded-full bg-seal text-[10px] font-bold text-paper-2">
        {unit.index}
      </span>
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
        <EditableText value={unit.title} onSave={(title) => save({ title })} locked={locked} className="font-serif font-semibold" />
        <span className="text-xs text-ink-3">约 {unit.chapter_count} 章</span>
      </div>
      <div className="space-y-2">
        <Field label="目标">
          <EditableText value={unit.goal} onSave={(goal) => save({ goal })} locked={locked} multiline />
        </Field>
        <Field label="冲突">
          <EditableText value={unit.conflict} onSave={(conflict) => save({ conflict })} locked={locked} multiline />
        </Field>
        <Field label="高潮">
          <EditableText value={unit.climax} onSave={(climax) => save({ climax })} locked={locked} multiline />
        </Field>
        <Field label="结果与钩子">
          <EditableText value={unit.outcome} onSave={(outcome) => save({ outcome })} locked={locked} multiline />
        </Field>
        <Field label="关键事件">
          <EditableList items={unit.key_events} onSave={(key_events) => save({ key_events })} locked={locked} ordered />
        </Field>
      </div>
    </div>
  )
}

const VOLUME_STATUS: Record<Volume['status'], { label: string; tone: 'idle' | 'busy' | 'ok' }> = {
  planned: { label: '概要', tone: 'idle' },
  detailed: { label: '已拆单元', tone: 'busy' },
  approved: { label: '已批准', tone: 'ok' },
}

function VolumeCard({ bookId, volume, locked }: { bookId: string; volume: Volume; locked: boolean }) {
  const update = useUpdateVolume(bookId)
  const [open, setOpen] = useState(volume.units.length > 0)
  const status = VOLUME_STATUS[volume.status]
  const chapters = volume.units.reduce((sum, u) => sum + u.chapter_count, 0)
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 p-5">
        <span className="font-serif text-3xl leading-none font-bold text-line-2">{String(volume.index).padStart(2, '0')}</span>
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <EditableText
              value={volume.title}
              onSave={(title) => update.mutateAsync({ id: volume.id, title })}
              locked={locked}
              className="font-serif text-lg font-semibold"
            />
            <Badge tone={status.tone}>{status.label}</Badge>
            {chapters > 0 && <span className="text-xs text-ink-3">共约 {chapters} 章</span>}
          </div>
          <EditableText
            value={volume.summary}
            onSave={(summary) => update.mutateAsync({ id: volume.id, summary })}
            locked={locked}
            multiline
            className="text-sm text-ink-2"
          />
          <p className="flex gap-2 text-sm">
            <span className="shrink-0 text-xs leading-6 text-ink-3">卷末目标</span>
            <EditableText
              value={volume.goal}
              onSave={(goal) => update.mutateAsync({ id: volume.id, goal })}
              locked={locked}
              multiline
              className="flex-1"
            />
          </p>
        </div>
        {volume.units.length > 0 && (
          <button onClick={() => setOpen(!open)} className="rounded-md p-1 text-ink-3 hover:bg-line/60" aria-label="展开剧情单元">
            <ChevronDown className={clsx('size-5 transition-transform', open && 'rotate-180')} />
          </button>
        )}
      </div>
      {open && volume.units.length > 0 && (
        <div className="border-t border-line bg-paper-2/60 px-5 py-5 sm:pl-16">
          <p className="mb-4 text-xs font-medium tracking-wider text-ink-3">剧情单元</p>
          {volume.units.map((unit) => (
            <UnitCard key={unit.id} bookId={bookId} unit={unit} locked={locked} />
          ))}
        </div>
      )}
    </Card>
  )
}

export function OutlinePanel({ bookId, locked }: { bookId: string; locked: boolean }) {
  const { data, isLoading } = useOutline(bookId)
  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-3">
        <Spinner />
      </div>
    )
  }
  if (!data || (!data.concept.title && data.volumes.length === 0)) {
    return <EmptyState title="大纲还在写">编辑部写好后会出现在这里，你可以直接点文字修改。</EmptyState>
  }
  return (
    <div className="space-y-4">
      <ConceptCard bookId={bookId} concept={data.concept} locked={locked} />
      {data.volumes.map((volume) => (
        <VolumeCard key={volume.id} bookId={bookId} volume={volume} locked={locked} />
      ))}
    </div>
  )
}
