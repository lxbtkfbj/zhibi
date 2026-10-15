import { Flag, Route } from 'lucide-react'
import type { ReactNode } from 'react'
import { useUpdateBook } from '../../../api/hooks'
import type { Milestone, Spine } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Card, Reveal } from '../../../components/ui'
import { useBookContext } from '../context'
import { FieldBlock, Locked, PageHeader } from './common'

function Node({ marker, last, delay, children }: { marker: ReactNode; last?: boolean; delay: number; children: ReactNode }) {
  return (
    <Reveal delay={delay} className={last ? 'relative pl-12' : 'relative pb-6 pl-12'}>
      {!last && <span className="absolute top-5 bottom-0 left-[15px] w-px bg-line-2" />}
      <span className="absolute top-1 left-0">{marker}</span>
      {children}
    </Reveal>
  )
}

const endMarker = (tone: 'ink' | 'seal') => (
  <span
    className={
      tone === 'seal'
        ? 'flex size-8 items-center justify-center rounded-full bg-seal text-paper-2 shadow-[var(--shadow-paper)]'
        : 'flex size-8 items-center justify-center rounded-full bg-ink text-paper-2'
    }
  >
    <Flag className="size-4" />
  </span>
)

/** 主线骨架：开篇 → 关键转折 → 结局。先定首尾，分卷大纲在这副骨架上展开。 */
export function SpinePage() {
  const { book, bookId, working } = useBookContext()
  const update = useUpdateBook(bookId)
  const spine: Spine = book.spine ?? {}
  const milestones = spine.milestones ?? []
  const save = (patch: Partial<Spine>) => update.mutateAsync({ spine: patch })
  const saveMilestone = (index: number, patch: Partial<Milestone>) =>
    save({ milestones: milestones.map((m, i) => (i === index ? { ...m, ...patch } : m)) })

  if (!spine.ending && !milestones.length) {
    const subtitle = {
      setting_up: '设定做完后，主编会先定开篇、结局和中间的关键转折，再写分卷大纲。',
      awaiting_approval: '这本书开书时还没有这一步。可以在拍板时提意见：「补上主线骨架：开篇、结局和关键转折」。',
    }[book.status as string]
    return (
      <PageHeader
        eyebrow="主线骨架"
        title={book.status === 'setting_up' ? '主编还没定主线' : '这本书还没有主线骨架'}
        subtitle={subtitle ?? '这本书开书时还没有「主线骨架」这一步，所以这里是空的。'}
      />
    )
  }

  return (
    <div>
      <PageHeader
        eyebrow="主线骨架"
        title="从开篇到结局"
        subtitle="先定开头和结局，再定中间的关键转折；分卷大纲就在这副骨架上展开，每一卷都要推着主角离结局更近一步。"
      />
      <Locked locked={working} />
      <Reveal>
        <section className="mb-8 grid gap-6 border-b border-line pb-8 @2xl/manuscript:grid-cols-3">
          <FieldBlock label="核心矛盾">
            <EditableText value={spine.core_conflict ?? ''} onSave={(core_conflict) => save({ core_conflict })} locked={working} multiline />
          </FieldBlock>
          <FieldBlock label="主角成长弧">
            <EditableText value={spine.protagonist_arc ?? ''} onSave={(protagonist_arc) => save({ protagonist_arc })} locked={working} multiline />
          </FieldBlock>
          <FieldBlock label="主题">
            <EditableText value={spine.theme ?? ''} onSave={(theme) => save({ theme })} locked={working} multiline className="font-serif" />
          </FieldBlock>
        </section>
      </Reveal>

      <Node marker={endMarker('ink')} delay={0.04}>
        <Card className="p-5">
          <p className="mb-1.5 text-xs tracking-[0.15em] text-ink-2">开篇</p>
          <EditableText value={spine.opening ?? ''} onSave={(opening) => save({ opening })} locked={working} multiline className="text-[15px] leading-relaxed" />
        </Card>
      </Node>
      {milestones.map((m, i) => (
        <Node
          key={m.index}
          delay={0.06 + 0.04 * i}
          marker={
            <span className="flex size-8 items-center justify-center rounded-md bg-chief font-serif text-sm font-bold text-paper-2">{m.index}</span>
          }
        >
          <Card hover className="p-5">
            <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <EditableText value={m.title} onSave={(title) => saveMilestone(i, { title })} locked={working} className="font-serif text-lg font-bold" />
              <span className="text-xs text-ink-2">约第 {m.volume} 卷</span>
            </div>
            <EditableText value={m.event} onSave={(event) => saveMilestone(i, { event })} locked={working} multiline className="text-[15px] leading-relaxed" />
            <div className="mt-4 flex gap-2 border-t border-line pt-3 text-[14px]">
              <Route className="mt-1 size-3.5 shrink-0 text-chief" />
              <EditableText value={m.change} onSave={(change) => saveMilestone(i, { change })} locked={working} multiline className="flex-1 text-ink-2" />
            </div>
          </Card>
        </Node>
      ))}
      <Node marker={endMarker('seal')} delay={0.06 + 0.04 * milestones.length} last>
        <Card className="border-seal/25 p-5">
          <p className="mb-1.5 text-xs tracking-[0.15em] text-seal">结局</p>
          <EditableText value={spine.ending ?? ''} onSave={(ending) => save({ ending })} locked={working} multiline className="font-serif text-[16px] leading-relaxed" />
        </Card>
      </Node>
    </div>
  )
}
