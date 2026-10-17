import clsx from 'clsx'
import { useThreads, useUpdateThread } from '../../../api/hooks'
import type { StoryThread } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Card, Reveal, Skeleton } from '../../../components/ui'
import { useBookContext } from '../context'
import { Locked, PageHeader } from './common'

const KIND_TONE: Record<string, string> = {
  主线: 'bg-seal text-paper-2',
  感情线: 'bg-seal-soft text-seal',
  反派线: 'bg-ink text-paper-2',
  谜团线: 'bg-chief-soft text-chief',
  成长线: 'bg-lore-soft text-lore',
}

function ThreadCard({ thread, locked, delay }: { thread: StoryThread; locked: boolean; delay: number }) {
  const { bookId } = useBookContext()
  const update = useUpdateThread(bookId)
  const save = (patch: Partial<StoryThread>) => update.mutateAsync({ id: thread.id, ...patch })
  const saveBeat = (i: number, beat: string) => save({ beats: thread.beats.map((b, j) => (j === i ? { ...b, beat } : b)) })
  return (
    <Reveal delay={delay}>
      <Card hover className="p-5 @lg/manuscript:p-6">
        <div className="mb-3 flex flex-wrap items-center gap-2.5">
          <span className={clsx('rounded-md px-2 py-0.5 text-xs font-medium', KIND_TONE[thread.kind] ?? 'bg-line/70 text-ink-2')}>{thread.kind}</span>
          <EditableText value={thread.name} onSave={(name) => save({ name })} locked={locked} className="font-serif text-xl font-bold" />
          {thread.characters.length > 0 && <span className="text-sm text-ink-2">{thread.characters.join('、')}</span>}
        </div>
        <EditableText value={thread.summary} onSave={(summary) => save({ summary })} locked={locked} multiline className="text-[15px] leading-relaxed text-ink-2" />
        {thread.beats.length > 0 && (
          <ol className="mt-4 space-y-2 border-l border-line-2 pl-4">
            {thread.beats.map((b, i) => (
              <li key={i} className="relative">
                <span className="absolute top-2 -left-[21px] size-2 rounded-full bg-chief" />
                <p className="text-xs text-ink-2">第 {b.volume} 卷</p>
                <EditableText value={b.beat} onSave={(beat) => saveBeat(i, beat)} locked={locked} multiline className="text-[14px] leading-relaxed" />
              </li>
            ))}
          </ol>
        )}
      </Card>
    </Reveal>
  )
}

/** 线索：主线、感情线、反派线、谜团线、成长线各走到哪一卷。 */
export function ThreadsPage({ embedded = false }: { embedded?: boolean }) {
  const { bookId, book, working } = useBookContext()
  const { data: threads, isLoading } = useThreads(bookId)

  if (isLoading) return <Skeleton className="h-64" />
  if (!threads?.length) {
    if (embedded) return <p className="rounded-xl border border-dashed border-line-2 p-5 text-sm text-ink-2">{book.status === 'setting_up' ? '主编还没排线索，排大纲时会一起排。' : '这本书还没有线索，开写时主编会排好这一篇的线索。'}</p>
    return (
      <PageHeader
        eyebrow="线索"
        title={book.status === 'setting_up' ? '主编还没做线索规划' : '这本书还没有线索'}
        subtitle="开写时主编会排好这一篇的线索"
      />
    )
  }
  return (
    <div>
      {embedded ? <h2 className="mb-3.5 flex flex-wrap items-center gap-2.5 text-[17px] font-semibold">{threads.length} 条线<span className="text-[13px] font-normal text-ink-3">长篇靠几条线轮流推进，任何一条都不会长时间断掉</span></h2> : <PageHeader
        eyebrow="线索"
        title={`${threads.length} 条线交织成一本书`}
        subtitle="长篇靠几条线轮流推进、互相牵动：每一卷、每个剧情单元都会标明推进了哪几条线，任何一条都不会长时间断掉。"
      />}
      <Locked locked={working} />
      <div className="space-y-4">
        {threads.map((t, i) => (
          <ThreadCard key={t.id} thread={t} locked={working} delay={0.05 * i} />
        ))}
      </div>
    </div>
  )
}
