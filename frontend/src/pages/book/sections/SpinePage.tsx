import { Flag } from 'lucide-react'
import type { ReactNode } from 'react'
import { useNodeMutations, useNodes, useUpdateBook } from '../../../api/hooks'
import type { Spine } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Button, Card, ErrorText, Reveal, Skeleton } from '../../../components/ui'
import { NODE_STATUS } from '../../../lib/storyMap'
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
  const query = useNodes(bookId)
  const { update: updateNode } = useNodeMutations(bookId)
  const spine: Spine = book.spine ?? {}
  const nodes = query.data ?? []
  const save = (patch: Partial<Spine>) => update.mutateAsync({ spine: patch })

  if (query.isLoading) return <Skeleton className="h-64" />
  if (query.isError) return <div><ErrorText error={query.error} /><Button variant="soft" onClick={() => void query.refetch()}>重新加载节点</Button></div>

  if (!nodes.length) {
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

      {nodes.map((node, i) => (
        <Node
          key={node.id}
          delay={0.04 + 0.04 * i}
          last={i === nodes.length - 1}
          marker={node.kind === 'opening' ? endMarker('ink') : node.kind === 'ending' ? endMarker('seal') :
            <span className="flex size-8 items-center justify-center rounded-md bg-chief font-serif text-sm font-bold text-paper-2">{node.index}</span>
          }
        >
          <div data-testid={`story-node-${node.id}`}>
            <Card hover className={node.kind === 'ending' ? 'border-seal/25 p-5' : 'p-5'}>
              <div className="mb-3 flex items-start justify-between gap-4 text-xs text-ink-2">
                <span>节点 {node.index}{node.kind === 'opening' ? ' · 开篇' : node.kind === 'ending' ? ' · 结局' : ''}{node.volume != null ? ` · 约第 ${node.volume} 卷` : ''}</span>
                <span className="shrink-0 text-chief">{NODE_STATUS[node.status]}</span>
              </div>
              <div className="mb-4">
                <EditableText value={node.title} onSave={(title) => updateNode.mutateAsync({ id: node.id, title })} locked={working} placeholder="（未命名节点）" className="font-serif text-lg font-bold" />
              </div>
              <FieldBlock label="发生什么">
                <EditableText value={node.event} onSave={(event) => updateNode.mutateAsync({ id: node.id, event })} locked={working} multiline />
              </FieldBlock>
              <div className="mt-4 grid gap-4 border-t border-line pt-3">
                <FieldBlock label="之前得先有">
                  <EditableText value={node.prerequisite} onSave={(prerequisite) => updateNode.mutateAsync({ id: node.id, prerequisite })} locked={working} multiline className="text-ink-2" />
                </FieldBlock>
                <FieldBlock label="之后变成">
                  <EditableText value={node.consequence} onSave={(consequence) => updateNode.mutateAsync({ id: node.id, consequence })} locked={working} multiline className="text-ink-2" />
                </FieldBlock>
              </div>
            </Card>
          </div>
        </Node>
      ))}
    </div>
  )
}
