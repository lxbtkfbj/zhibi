import clsx from 'clsx'
import { ChevronDown, ChevronLeft, ChevronRight, PenLine } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useChapter, useChapters, useOutline, useUpdateChapter } from '../../../api/hooks'
import type { ChapterBrief } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Badge, Button, Card, ErrorText, inputClass, Reveal, Skeleton } from '../../../components/ui'
import { cleanVolumeTitle } from '../../../lib/status'
import { useBookContext } from '../context'
import { WritingControls } from '../Decision'
import { Locked, PageHeader } from './common'
import { ForeshadowChips } from './VolumePage'

const STATUS: Record<ChapterBrief['status'], [string, 'idle' | 'busy' | 'ok']> = {
  planned: ['只有章纲', 'idle'],
  drafting: ['写作中', 'busy'],
  final: ['已定稿', 'ok'],
}

/** 正文目录：按卷列出全部章节。 */
export function ContentsPage() {
  const { bookId, book, job } = useBookContext()
  const { data: chapters, isLoading } = useChapters(bookId)
  const { data: outline } = useOutline(bookId)
  const idle = !job || job.status === 'succeeded'
  const volumes = outline?.volumes ?? []

  return (
    <div>
      <PageHeader
        eyebrow="正文"
        title={book.chapters_final ? `已定稿 ${book.chapters_final} 章` : '还没有开写'}
        subtitle={
          book.chapters_final
            ? `共 ${(book.words_final / 10000).toFixed(1)} 万字。章纲是编辑部写到那一段之前才出的，点开任何一章都能看到它的章纲和审稿意见。`
            : '开写后，主编会按卷纲逐个单元出章纲，写手逐章写作，写好的章节都在这里。'
        }
      />
      {idle && (book.status === 'ready' || book.status === 'writing') && (
        <Reveal>
          <Card className="mb-8 p-5">
            <WritingControls />
          </Card>
        </Reveal>
      )}
      {isLoading && <Skeleton className="h-48" />}
      <div className="space-y-8">
        {volumes.map((v) => {
          const list = (chapters ?? []).filter((c) => c.volume_id === v.id)
          if (!list.length) return null
          return (
            <section key={v.id}>
              <h3 className="mb-2 flex items-baseline gap-2 font-serif text-lg font-bold">
                <span className="text-sm font-normal text-ink-3">第{v.index}卷</span>
                {cleanVolumeTitle(v.title)}
              </h3>
              <ul className="divide-y divide-line rounded-2xl bg-card ring-1 ring-line">
                {list.map((c) => {
                  const [label, tone] = STATUS[c.status]
                  const body = (
                    <div className="flex items-start gap-3 px-4 py-3">
                      <span className="w-16 shrink-0 pt-0.5 text-xs text-ink-3">第{c.index}章</span>
                      <div className="min-w-0 flex-1">
                        <p className={clsx('text-[15px]', c.status === 'final' ? 'text-ink' : 'text-ink-2')}>{c.title}</p>
                        {c.summary && <p className="mt-0.5 line-clamp-1 text-[13px] text-ink-3">{c.summary}</p>}
                      </div>
                      <Badge tone={tone} className="shrink-0">
                        {label}
                        {c.status === 'final' && ` · ${c.word_count}字`}
                      </Badge>
                    </div>
                  )
                  return (
                    <li key={c.id}>
                      <Link to={`/books/${bookId}/chapter/${c.index}`} className="block transition-colors hover:bg-paper-2">
                        {body}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </section>
          )
        })}
      </div>
    </div>
  )
}

function Fold({ title, children, defaultOpen }: { title: string; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen)
  return (
    <div className="overflow-hidden rounded-xl bg-card ring-1 ring-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm font-medium" aria-expanded={open}>
        {title}
        <ChevronDown className={clsx('size-4 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }}>
            <div className="border-t border-line px-4 py-3 text-[14px] leading-relaxed text-ink-2">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

const SEVERITY: Record<string, string> = { high: '严重', medium: '中等', low: '轻微' }

/** 读一章：正文、章纲、审稿意见；前后翻页。 */
export function ChapterPage() {
  const { index = '1' } = useParams()
  const n = Number(index)
  const { bookId, working, book } = useBookContext()
  const { data: chapter, isLoading, error } = useChapter(bookId, n)
  const update = useUpdateChapter(bookId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const total = book.chapters_final

  if (isLoading) return <Skeleton className="h-96" />
  if (error || !chapter) {
    return <PageHeader eyebrow="正文" title="这一章还不存在" subtitle={<Link to={`/books/${bookId}/chapters`} className="text-seal underline">回到目录</Link>} />
  }
  const [label, tone] = STATUS[chapter.status]
  const o = chapter.outline ?? {}
  const review = chapter.review?.review
  const issues = [...(review?.issues ?? []), ...(chapter.review?.consistency?.issues ?? [])]
  const nav = (
    <div className="flex items-center justify-between text-sm">
      {n > 1 ? (
        <Link to={`/books/${bookId}/chapter/${n - 1}`} className="flex items-center gap-1 text-ink-2 hover:text-ink">
          <ChevronLeft className="size-4" />
          上一章
        </Link>
      ) : (
        <span />
      )}
      <Link to={`/books/${bookId}/chapters`} className="text-ink-3 hover:text-ink">
        目录
      </Link>
      {n < Math.max(total, n + (chapter.status === 'final' ? 1 : 0)) ? (
        <Link to={`/books/${bookId}/chapter/${n + 1}`} className="flex items-center gap-1 text-ink-2 hover:text-ink">
          下一章
          <ChevronRight className="size-4" />
        </Link>
      ) : (
        <span />
      )}
    </div>
  )

  return (
    <div>
      <PageHeader
        eyebrow={`第${chapter.index}章`}
        title={<EditableText value={chapter.title} onSave={(title) => update.mutateAsync({ index: n, title })} locked={working} inputClassName="font-serif text-3xl font-bold" />}
        action={
          <div className="flex items-center gap-2">
            <Badge tone={tone}>{label}</Badge>
            {chapter.word_count > 0 && <span className="text-sm text-ink-3">{chapter.word_count} 字</span>}
            {chapter.content && !working && !editing && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDraft(chapter.content)
                  setEditing(true)
                }}
              >
                <PenLine className="size-3.5" />
                修改正文
              </Button>
            )}
          </div>
        }
      />
      <Locked locked={working} />
      <div className="mb-8 space-y-2">
        <Fold title="章纲" defaultOpen={chapter.status === 'planned'}>
          <div className="space-y-1.5">
            {o.goal && <p><span className="text-ink-3">目标：</span>{o.goal}</p>}
            {o.scenes && o.scenes.length > 0 && (
              <ol className="list-inside list-decimal space-y-0.5">
                {o.scenes.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            )}
            {o.conflict && <p><span className="text-ink-3">冲突：</span>{o.conflict}</p>}
            {o.cool_point && <p><span className="text-seal">爽点：</span>{o.cool_point}</p>}
            {o.hook && <p><span className="text-ink-3">结尾钩子：</span>{o.hook}</p>}
            {o.characters && o.characters.length > 0 && <p><span className="text-ink-3">出场：</span>{o.characters.join('、')}</p>}
            {o.foreshadow_actions && o.foreshadow_actions.length > 0 && <ForeshadowChips actions={o.foreshadow_actions} />}
          </div>
        </Fold>
        {review && (
          <Fold title={`审稿意见${chapter.attempts ? `（重写过 ${chapter.attempts} 次）` : ''}`}>
            {review.highlights.map((h) => (
              <p key={h} className="text-lore">✓ {h}</p>
            ))}
            {issues.map((issue, i) => (
              <div key={i} className="mt-2 rounded-lg bg-paper px-3 py-2">
                <p className="text-xs text-ink-3">{SEVERITY[issue.severity] ?? issue.severity}</p>
                <p className="text-ink">{issue.problem}</p>
                <p>→ {issue.suggestion}</p>
              </div>
            ))}
          </Fold>
        )}
        {chapter.summary && (
          <Fold title="本章摘要">
            <p>{chapter.summary}</p>
          </Fold>
        )}
      </div>
      {chapter.content && editing ? (
        <div className="paper p-4 sm:p-6">
          <textarea value={draft} onChange={(e) => setDraft(e.target.value)} className={clsx(inputClass, 'min-h-[65vh] font-serif text-[16px] leading-[1.9]')} />
          <div className="mt-3 flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              取消
            </Button>
            <Button
              size="sm"
              variant="primary"
              loading={update.isPending}
              onClick={async () => {
                await update.mutateAsync({ index: n, content: draft })
                setEditing(false)
              }}
            >
              保存
            </Button>
          </div>
          <ErrorText error={update.error} />
        </div>
      ) : chapter.content ? (
        <Reveal>
          <article className="paper px-6 py-8 sm:px-12 sm:py-12">
            {chapter.content
              .split(/\n+/)
              .filter((p) => p.trim())
              .map((p, i) => (
                <p key={i} className="mb-4 indent-8 font-serif text-[17px] leading-[2.05] text-ink last:mb-0">
                  {p.trim()}
                </p>
              ))}
          </article>
        </Reveal>
      ) : (
        <Card className="px-6 py-10 text-center">
          <p className="font-serif text-lg text-ink-2">这一章还没写</p>
          <p className="mt-1 text-sm text-ink-3">章纲已经出好，写到这一章时写手会按章纲来写。</p>
        </Card>
      )}
      <div className="mt-8">{nav}</div>
    </div>
  )
}
