import { useReducedMotion } from '../../../lib/appearance'
import clsx from 'clsx'
import { ChevronLeft, ChevronRight, Download, MoreHorizontal, PenLine, RotateCcw, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useParams } from 'react-router-dom'
import { useBible, useChapter, useChapters, useJobActions, useOutline, useUpdateChapter } from '../../../api/hooks'
import type { ChapterBrief } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Badge, Button, Card, ErrorText, inputClass, Reveal, Skeleton, TypingDots } from '../../../components/ui'
import { cleanVolumeTitle } from '../../../lib/status'
import { useBookContext } from '../context'
import { PageHeader } from './common'
import { ForeshadowChips } from '../../../components/ForeshadowChips'
import { RevealChips } from '../../../components/WritingLabels'
import { emotionText } from '../../../lib/writingUi'

const STATUS: Record<ChapterBrief['status'], [string, 'idle' | 'busy' | 'ok']> = {
  planned: ['只有章纲', 'idle'],
  drafting: ['写作中', 'busy'],
  final: ['已定稿', 'ok'],
}

/** 正文目录：按卷列出全部章节。 */
export function ContentsPage() {
  const { bookId, book } = useBookContext()
  const { data: chapters, isLoading } = useChapters(bookId)
  const { data: outline } = useOutline(bookId)
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
        action={
          book.chapters_final > 0 && (
            <a
              href={`/api/books/${bookId}/export.txt`}
              download
              className="press inline-flex h-8 items-center gap-1.5 rounded-xl border border-line-2 bg-card px-3 text-[14px] font-medium text-ink transition-colors hover:border-ink-3/50 hover:bg-paper-2"
              title="把已定稿的章节按卷、按章导出成一个 TXT 文件"
            >
              <Download className="size-3.5" />
              导出 TXT
            </a>
          )
        }
      />
      {isLoading && <Skeleton className="h-48" />}
      <div className="space-y-8">
        {volumes.map((v) => {
          const list = (chapters ?? []).filter((c) => c.volume_id === v.id)
          if (!list.length) return null
          return (
            <section key={v.id}>
              <h3 className="mb-2 flex items-baseline gap-2 font-serif text-lg font-bold">
                <span className="text-sm font-normal text-ink-2">第{v.index}卷</span>
                {cleanVolumeTitle(v.title)}
              </h3>
              <ul className="divide-y divide-line border-y border-line">
                {list.map((c) => {
                  const [label, tone] = STATUS[c.status]
                  const body = (
                    <div className="flex flex-wrap items-start gap-3 py-3">
                      <span className="w-16 shrink-0 pt-0.5 text-xs text-ink-2">第{c.index}章</span>
                      <div className="min-w-0 flex-1">
                        <p className={clsx('text-[15px]', c.status === 'final' ? 'text-ink' : 'text-ink-2')}>{c.title}</p>
                        {c.summary && <p className="mt-0.5 line-clamp-1 text-[14px] text-ink-2">{c.summary}</p>}
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

type ChapterPanel = 'outline' | 'materials' | 'review' | 'summary'
const PANEL_LABELS: Record<ChapterPanel, string> = { outline: '章纲', materials: '资料', review: '审稿', summary: '摘要' }

/** This is deliberately a pane-local, non-modal drawer: the editorial conversation stays usable. */
function ManuscriptDrawer({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const reduce = useReducedMotion()
  const closeRef = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeRef.current?.focus()
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('keydown', escape)
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return (
    <motion.div className="absolute inset-0 z-40 overflow-hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: reduce ? 0 : 0.25 }}>
      <button className="absolute inset-0 bg-ink/10" onClick={onClose} aria-label="关闭章节资料" tabIndex={-1} />
      <motion.aside
        role="dialog" aria-label={title}
        className="absolute inset-y-0 right-0 flex w-[420px] max-w-full flex-col border-l border-line-2 bg-card shadow-panel"
        initial={reduce ? false : { x: '100%' }} animate={{ x: 0 }} exit={{ x: reduce ? 0 : '100%' }}
        transition={{ duration: reduce ? 0 : 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-line px-6 py-5">
          <h2 className="font-serif text-xl font-bold">{title}</h2>
          <button ref={closeRef} onClick={onClose} className="rounded-lg p-2 text-ink-2 hover:bg-paper-2" aria-label="关闭抽屉"><X className="size-4" /></button>
        </div>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-6 py-6 text-[14px] leading-[1.8] text-ink-2">{children}</div>
      </motion.aside>
    </motion.div>
  )
}

function chineseNumber(value: number): string {
  const digits = '零一二三四五六七八九'
  if (value < 10) return digits[value] ?? String(value)
  if (value < 100) return `${value < 20 ? '' : digits[Math.floor(value / 10)]}十${value % 10 ? digits[value % 10] : ''}`
  if (value < 1000) {
    const rest = value % 100
    return `${digits[Math.floor(value / 100)]}百${rest ? `${rest < 10 ? '零' : rest < 20 ? '一' : ''}${chineseNumber(rest)}` : ''}`
  }
  return String(value)
}

const SEVERITY: Record<string, string> = { high: '严重', medium: '中等', low: '轻微' }

function Paragraphs({ text, live }: { text: string; live?: boolean }) {
  const paragraphs = text.split(/\n+/).filter((p) => p.trim())
  return (
    <>
      {paragraphs.map((p, i) => (
        <p key={i} className="mb-[0.9em] indent-[2em] reading-prose text-ink last:mb-0">
          <span className={clsx(live && i === paragraphs.length - 1 && 'caret')}>{p.trim()}</span>
        </p>
      ))}
    </>
  )
}

/** 按作者的意见重写这一章：写下意见；后面还有定稿的章节时，要先确认知道后面不会跟着改。 */
function RewritePanel({ index, later, onClose }: { index: number; later: number; onClose: () => void }) {
  const { bookId } = useBookContext()
  const { rewrite } = useJobActions(bookId)
  const [feedback, setFeedback] = useState('')
  const [confirm, setConfirm] = useState(false)
  const ready = feedback.trim() && (!later || confirm)
  return (
    <Card className="mb-8 p-5">
      <p className="mb-1 font-serif text-lg font-bold">按我的意见重写这一章</p>
      <p className="mb-3 text-sm text-ink-2">
        写手会按你的意见重写，照样经过审稿和设定检查。设定师会先撤掉这一章原来记进设定库和伏笔台账的变化，重写完再重新记。
      </p>
      <textarea
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder="例如：打斗再写足一点；苏晚晴的台词冷一些；结尾留一个更大的悬念"
        aria-label="重写意见"
        className={clsx(inputClass, 'min-h-28 text-[15px] leading-relaxed')}
      />
      {later > 0 && (
        <label className="mt-3 flex items-start gap-2 rounded-xl bg-seal-soft/60 px-3 py-2.5 text-sm text-seal">
          <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-1 accent-[var(--color-seal)]" />
          <span>
            这一章后面已经定稿了 {later} 章，后面的章节不会跟着改，改动大的话后文可能接不上。我知道，仍然要重写第{index}章。
          </span>
        </label>
      )}
      <div className="mt-3 flex items-center justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose}>
          取消
        </Button>
        <Button
          size="sm"
          variant="primary"
          loading={rewrite.isPending}
          disabled={!ready}
          onClick={async () => {
            await rewrite.mutateAsync({ index, feedback: feedback.trim(), confirm })
            onClose()
          }}
        >
          <RotateCcw className="size-3.5" />
          开始重写
        </Button>
      </div>
      <ErrorText error={rewrite.error} />
    </Card>
  )
}

/** Key by route so an unsaved editor or open drawer never leaks into another chapter. */
export function ChapterPage() {
  const { index = '1' } = useParams()
  return <ChapterContent key={index} n={Number(index)} />
}

function ChapterContent({ n }: { n: number }) {
  const { bookId, working, waiting, asking, draft } = useBookContext()
  const { data: chapter, isLoading, error } = useChapter(bookId, n)
  const { data: bible } = useBible(bookId)
  const { data: chapters } = useChapters(bookId)
  const update = useUpdateChapter(bookId)
  const [editing, setEditing] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [panel, setPanel] = useState<ChapterPanel | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!menuOpen) return
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setMenuOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setMenuOpen(false); menuButton.current?.focus() }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('keydown', escape)
    }
  }, [menuOpen])

  if (isLoading) return <Skeleton className="h-96" />
  if (error || !chapter) {
    return <PageHeader eyebrow="正文" title="这一章还不存在" subtitle={<Link to={`/books/${bookId}/chapters`} className="text-seal underline">回到目录</Link>} />
  }
  const live = working && draft && draft.chapter === n && !draft.done ? draft : null
  const [label] = live ? (['写作中', 'busy'] as const) : STATUS[chapter.status]
  const o = chapter.outline ?? {}
  const m = chapter.materials ?? {}
  const emotion = emotionText(o.emotion)
  const hasOutline = !!(o.goal || o.scenes?.length || o.conflict || o.cool_point || o.hook || o.characters?.length || o.foreshadow_actions?.length || emotion || o.mood || o.reveals?.length)
  const hasMaterials = !!(m.characters?.length || m.world?.length || m.chapters?.length || m.notes?.length)
  const review = chapter.review?.review
  const consistency = chapter.review?.consistency
  const issues = [...(review?.issues ?? []), ...(consistency?.issues ?? [])]
  const later = (chapters ?? []).filter((c) => c.index > n && c.status === 'final').length
  const canRewrite = chapter.status === 'final' && !working && !waiting && !asking && !editing
  const sorted = [...(chapters ?? [])].sort((a, b) => a.index - b.index)
  const previous = sorted.filter((c) => c.index < n).at(-1)
  const next = sorted.find((c) => c.index > n)
  const drawerHost = document.getElementById('manuscript-pane')
  const exportChapter = () => {
    const blob = new Blob([`第${chapter.index}章 ${chapter.title}\n\n${chapter.content}\n`], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `第${chapter.index}章 ${chapter.title.replace(/[<>:"/\\|?*]/g, '_')}.txt`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setMenuOpen(false)
  }
  const panelContent = {
    outline: (
      <div className="space-y-4">
        {!hasOutline && <p>章纲还没有准备好。</p>}
        {emotion && <p data-testid="chapter-emotion"><span className="font-medium text-ink">情绪：</span>{emotion}{o.mood ? `（${o.mood}）` : ''}</p>}
        {!emotion && o.mood && <p><span className="font-medium text-ink">主情绪：</span>{o.mood}</p>}
        {o.goal && <p><span className="font-medium text-ink">目标：</span>{o.goal}</p>}
        {!!o.scenes?.length && <ol className="list-inside list-decimal space-y-2">{o.scenes.map((scene, i) => <li key={i}>{scene}</li>)}</ol>}
        {o.conflict && <p><span className="font-medium text-ink">冲突：</span>{o.conflict}</p>}
        {o.cool_point && <p><span className="text-seal">爽点：</span>{o.cool_point}</p>}
        {o.hook && <p><span className="font-medium text-ink">结尾钩子：</span>{o.hook}</p>}
        {!!o.characters?.length && <p><span className="font-medium text-ink">出场：</span>{o.characters.join('、')}</p>}
        {!!o.foreshadow_actions?.length && <ForeshadowChips actions={o.foreshadow_actions} ledger={bible?.foreshadowings ?? []} />}
        <RevealChips reveals={o.reveals} />
      </div>
    ),
    materials: (
      <div className="space-y-4">
        {!hasMaterials && <p>设定师还没有为这一章准备资料。</p>}
        {!!m.characters?.length && <p><span className="font-medium text-ink">人物：</span>{m.characters.join('、')}</p>}
        {!!m.world?.length && <p><span className="font-medium text-ink">设定：</span>{m.world.join('、')}</p>}
        {!!m.chapters?.length && <p><span className="font-medium text-ink">回顾前文：</span>{m.chapters.map((chapterIndex, k) => <span key={chapterIndex}>{k > 0 && '、'}<Link onClick={() => setPanel(null)} to={`/books/${bookId}/chapter/${chapterIndex}`} className="text-seal underline underline-offset-4">第{chapterIndex}章</Link></span>)}</p>}
        {!!m.notes?.length && <ul className="list-inside list-disc space-y-2">{m.notes.map((note) => <li key={note}>{note}</li>)}</ul>}
      </div>
    ),
    review: (
      <div className="space-y-4">
        {!review && !consistency && <p>这一章还没有审稿意见。</p>}
        {chapter.attempts > 0 && <p className="text-xs">已重写 {chapter.attempts} 次</p>}
        {review?.highlights?.map((highlight) => <p key={highlight} className="text-lore">✓ {highlight}</p>)}
        {review?.remark && <p>{review.remark}</p>}
        {consistency?.remark && <p>{consistency.remark}</p>}
        {issues.map((issue, i) => <section key={i} className="border-t border-line pt-4"><p className="mb-1 text-xs text-seal">{SEVERITY[issue.severity] ?? issue.severity}</p><p className="text-ink">{issue.problem}</p><p className="mt-1">→ {issue.suggestion}</p></section>)}
      </div>
    ),
    summary: <p className="whitespace-pre-wrap">{chapter.summary || '这一章定稿后，设定师会整理本章摘要。'}</p>,
  }

  return (
    <div className="chapter-page pb-4">
      <header className="relative mb-10 pt-4 text-center">
        <div ref={menuRef} className="absolute top-0 right-0 z-10 text-left">
          <button ref={menuButton} onClick={() => setMenuOpen(!menuOpen)} className="rounded-lg p-2 text-ink-2 hover:bg-paper-2" aria-label="章节操作" aria-expanded={menuOpen} aria-controls="chapter-actions">
            <MoreHorizontal className="size-5" />
          </button>
          {menuOpen && <div id="chapter-actions" className="absolute top-full right-0 mt-1 w-44 rounded-xl border border-line bg-card p-1.5 shadow-paper">
            <button disabled={!chapter.content || working || editing} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-ink-2 hover:bg-paper-2 disabled:opacity-40" onClick={() => { setDraftText(chapter.content); setEditing(true); setRewriting(false); setMenuOpen(false) }}><PenLine className="size-4" />修改正文</button>
            <button disabled={!canRewrite || rewriting} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-ink-2 hover:bg-paper-2 disabled:opacity-40" onClick={() => { setRewriting(true); setMenuOpen(false) }}><RotateCcw className="size-4" />按意见重写</button>
            <button disabled={!chapter.content} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm text-ink-2 hover:bg-paper-2 disabled:opacity-40" onClick={exportChapter}><Download className="size-4" />导出本章 TXT</button>
          </div>}
        </div>
        <p className="mb-3 text-xs tracking-[0.35em] text-ink-3">第 {chineseNumber(chapter.index)} 章</p>
        <div className="mx-auto max-w-[24em] px-6 font-serif text-[26px] font-bold leading-relaxed">
          <EditableText value={chapter.title} onSave={(title) => update.mutateAsync({ index: n, title })} locked={working} inputClassName="text-center font-serif text-[26px] font-bold" />
        </div>
        <p className="my-4 text-sm tracking-[0.35em] text-line-2" aria-hidden="true">— ◆ —</p>
        <nav className="flex items-center justify-center gap-3 text-sm" aria-label="章节资料">
          {(Object.entries(PANEL_LABELS) as [ChapterPanel, string][]).map(([key, text], i) => <span key={key} className="flex items-center gap-3">{i > 0 && <span className="text-line-2" aria-hidden="true">·</span>}<button onClick={() => setPanel(key)} className={clsx('py-1 underline-offset-4 hover:text-seal hover:underline', panel === key ? 'text-seal' : 'text-ink-2')} aria-expanded={panel === key}>{text}</button></span>)}
        </nav>
        <p className="mt-2 text-xs text-ink-2">{label}{(live || chapter.word_count > 0) && ` · ${live ? live.text.replace(/\s/g, '').length : chapter.word_count} 字`}</p>
      </header>
      <div className="mx-auto max-w-[36em] text-[17px]">
        {rewriting && canRewrite && <RewritePanel index={n} later={later} onClose={() => setRewriting(false)} />}
        {live ? (
          <article aria-live="polite">
            <p className="mb-6 flex items-start gap-2 text-sm text-writer"><TypingDots className="mt-1.5 shrink-0" />{{ write: '写手正在写这一章', extend: '字数不够，写手正在接着写', ending: '写手正在改写结尾' }[live.mode]}（实时显示，写完后会经过审稿）</p>
            <Paragraphs text={live.text} live />
          </article>
        ) : chapter.content && editing ? (
          <div>
            <textarea aria-label="修改章节正文" value={draftText} onChange={(e) => setDraftText(e.target.value)} className={clsx(inputClass, 'min-h-[65vh] reading-prose')} />
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
              <Button size="sm" variant="primary" loading={update.isPending} onClick={async () => { await update.mutateAsync({ index: n, content: draftText }); setEditing(false) }}>保存</Button>
            </div>
            <ErrorText error={update.error} />
          </div>
        ) : chapter.content ? <Reveal><article><Paragraphs text={chapter.content} /></article></Reveal> : (
          <div className="py-12 text-center"><p className="font-serif text-lg text-ink-2">这一章还没写</p><p className="mt-2 text-sm leading-relaxed text-ink-2">章纲已经出好。写手动笔时，正文会在这里实时展开。</p></div>
        )}
        <nav className="mt-12 flex items-center justify-between border-t border-line pt-6 text-sm text-ink-2" aria-label="章节翻页">
          {previous ? <Link to={`/books/${bookId}/chapter/${previous.index}`} className="flex items-center gap-1 hover:text-seal"><ChevronLeft className="size-4" />上一章</Link> : <span className="w-16" />}
          <Link to={`/books/${bookId}/chapters`} className="hover:text-seal">目录</Link>
          {next ? <Link to={`/books/${bookId}/chapter/${next.index}`} className="flex items-center gap-1 hover:text-seal">下一章<ChevronRight className="size-4" /></Link> : <span className="w-16" />}
        </nav>
      </div>
      {drawerHost && createPortal(<AnimatePresence>{panel && <ManuscriptDrawer key={panel} title={panel === 'materials' ? '设定师备的资料' : panel === 'review' ? '审稿意见' : panel === 'summary' ? '本章摘要' : '章纲'} onClose={() => setPanel(null)}>{panelContent[panel]}</ManuscriptDrawer>}</AnimatePresence>, drawerHost)}
    </div>
  )
}
