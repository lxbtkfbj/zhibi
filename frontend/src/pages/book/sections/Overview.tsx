import { ArrowRight, BookMarked, Flag, Lightbulb, MessageCircleQuestion, Route, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useBible, useOutline } from '../../../api/hooks'
import { Cloud } from '../../../components/decor'
import { Button, Card, CountUp, Reveal, TypingDots } from '../../../components/ui'
import { cleanTitle, cleanVolumeTitle, totalChapters } from '../../../lib/status'
import { computeStages } from '../../../lib/team'
import { useBookContext } from '../context'
import { DecisionControls, InterviewForm, ResumeControls, RunningControls, WritingControls } from '../Decision'
import { decisionCopy } from '../../../lib/decision'
import { PageHeader } from './common'

function NextStep() {
  const { book, job, waiting, working, messages, setTeamOpen, bookId } = useBookContext()
  const base = `/books/${bookId}`
  const current = computeStages(book.status, job, messages).find((s) => s.state === 'current')
  const writingPhase = book.status === 'ready' || book.status === 'writing' || book.status === 'completed'

  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions') {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-chief/25 bg-card p-6 shadow-[var(--shadow-lift)] sm:p-8">
        <span className="absolute inset-y-0 left-0 w-1.5 bg-chief" />
        <p className="mb-1 flex items-center gap-1.5 text-xs tracking-[0.25em] text-chief">
          <MessageCircleQuestion className="size-3.5" />
          动笔之前
        </p>
        <h3 className="font-serif text-2xl font-bold">主编想先跟你对几件事</h3>
        <p className="mt-2 mb-6 text-[15px] leading-relaxed text-ink-2">
          这几件事会决定整本书的走向。已经替你选好了主编推荐的答案，改你想改的就行；再点一次可以取消，交给编辑部决定。
        </p>
        <InterviewForm job={job} questions={job.pending.questions} />
      </div>
    )
  }
  if (waiting && job) {
    const copy = decisionCopy(job.pending, bookId)
    return (
      <div className="relative overflow-hidden rounded-2xl border border-seal/25 bg-card p-6 shadow-[var(--shadow-lift)] sm:p-8">
        <span className="absolute inset-y-0 left-0 w-1.5 bg-seal" />
        <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-seal/[0.07]" />
        <p className="mb-1 text-xs tracking-[0.25em] text-seal">{copy.eyebrow}</p>
        <h3 className="font-serif text-2xl font-bold">{copy.title}</h3>
        <p className="mt-2 mb-4 text-[15px] leading-relaxed text-ink-2">{copy.hint}</p>
        {copy.issues && copy.issues.length > 0 && (
          <ul className="mb-4 space-y-1.5 rounded-xl bg-paper-2 px-4 py-3 text-[14px] leading-relaxed text-ink-2 ring-1 ring-line/80">
            {copy.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        <div className="mb-5 flex flex-wrap gap-2 text-sm">
          {copy.links.map(([label, to]) => (
            <Link key={to} to={to} className="group flex items-center gap-1 rounded-full bg-paper-2 px-3 py-1 text-ink-2 ring-1 ring-line hover:text-ink hover:ring-line-2">
              {label}
              <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>
          ))}
        </div>
        <DecisionControls job={job} />
      </div>
    )
  }
  if (working && job) {
    const last = [...messages].reverse().find((m) => m.kind === 'status' && m.job_id === job.id)
    return (
      <div className="relative overflow-hidden rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
        <p className="mb-1 text-xs tracking-[0.25em] text-chief">进行中</p>
        <h3 className="flex items-center gap-3 font-serif text-2xl font-bold">
          {job.kind === 'write_book' ? '编辑部正在写作' : `编辑部正在讨论「${current?.label ?? '方案'}」`}
          <TypingDots className="text-chief" />
        </h3>
        <p className="mt-2 mb-4 text-[15px] leading-relaxed text-ink-2">
          {job.kind === 'write_book'
            ? `${last ? `${last.content} ` : ''}每一章都会经过写手、审稿和设定师；写好的章节在「正文」里随时可以读。想到什么随时在右侧插话，编辑部写完手头这一步就照办。`
            : '这一步通常需要几分钟。右侧编辑部在直播讨论过程；想到什么随时在那儿插话，比如「主角叫云澈」，编辑部做完手头这一步就照办。也可以先离开，回来时进度都在。'}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => setTeamOpen(true)}>
            看编辑部直播
          </Button>
          <div className="min-w-56 flex-1">
            <RunningControls job={job} />
          </div>
        </div>
      </div>
    )
  }
  if (job && (job.status === 'failed' || job.status === 'cancelled')) {
    return (
      <div className="rounded-2xl border border-seal/25 bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
        <p className="mb-2 text-xs tracking-[0.25em] text-seal">需要处理</p>
        <ResumeControls job={job} />
      </div>
    )
  }
  if (book.status === 'completed') {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
        <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-lore/[0.08]" />
        <p className="mb-1 text-xs tracking-[0.25em] text-lore">全书完结</p>
        <h3 className="font-serif text-2xl font-bold">
          共 {book.chapters_final} 章，{(book.words_final / 10000).toFixed(1)} 万字
        </h3>
        <div className="mt-5">
          <Link to={`${base}/chapters`}>
            <Button variant="primary">从头读起</Button>
          </Link>
        </div>
      </div>
    )
  }
  if (writingPhase) {
    const started = book.chapters_final > 0
    return (
      <div className="relative overflow-hidden rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
        <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-lore/[0.08]" />
        <p className="mb-1 text-xs tracking-[0.25em] text-lore">{started ? '连载中' : '方案已定稿'}</p>
        <h3 className="font-serif text-2xl font-bold">{started ? `已写到第 ${book.chapters_final} 章，接着写？` : '下一步：开写第一章'}</h3>
        <p className="mt-2 mb-5 text-[15px] leading-relaxed text-ink-2">
          编辑部按卷纲逐个单元出章纲，再逐章写作、审稿、更新设定库。每一卷开写前，主编会先把这一卷拆成剧情单元请你拍板。
        </p>
        <WritingControls />
        {started && (
          <div className="mt-5 flex flex-wrap gap-2 text-sm">
            <Link to={`${base}/chapters`} className="group flex items-center gap-1 rounded-full bg-paper-2 px-3 py-1 text-ink-2 ring-1 ring-line hover:text-ink hover:ring-line-2">
              正文目录
              <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </div>
        )}
      </div>
    )
  }
  return null
}

function Stat({ value, label, suffix }: { value: number; label: string; suffix: string }) {
  return (
    <Card className="px-5 py-4">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="mt-1 font-serif text-3xl font-bold">
        <CountUp value={value} />
        <span className="ml-1 text-sm font-normal text-ink-3">{suffix}</span>
      </p>
    </Card>
  )
}

export function Overview() {
  const { book, bookId } = useBookContext()
  const { data: outline } = useOutline(bookId)
  const { data: bible } = useBible(bookId)
  const base = `/books/${bookId}`
  const concept = book.concept
  const spine = book.spine ?? {}
  const first = outline?.volumes[0]
  const chapters = first?.units.reduce((sum, u) => sum + u.chapter_count, 0) || first?.chapter_count || 0
  const total = totalChapters(concept, outline?.volumes ?? [])
  const volumes = outline?.volumes.length ?? 0
  const writing = book.chapters_final > 0
  const stats = [
    writing
      ? { value: book.chapters_final, label: '已定稿', suffix: '章' }
      : concept.target_length
        ? { value: concept.target_length, label: '篇幅', suffix: '万字' }
        : { value: bible?.foreshadowings.length ?? 0, label: '伏笔', suffix: '条' },
    writing
      ? book.words_final >= 10000
        ? { value: Math.round(book.words_final / 10000), label: '已写', suffix: '万字' }
        : { value: book.words_final, label: '已写', suffix: '字' }
      : total
        ? { value: total, label: `全书 ${volumes} 卷`, suffix: '章' }
        : { value: volumes, label: '计划', suffix: '卷' },
    writing && total ? { value: total, label: `全书 ${volumes} 卷`, suffix: '章' } : { value: chapters, label: '第一卷', suffix: '章' },
    { value: bible?.characters.length ?? 0, label: '人物', suffix: '位' },
  ]

  return (
    <div>
      <PageHeader eyebrow="概览" title={cleanTitle(book.title)} subtitle={book.logline || book.idea} />
      <Reveal>
        <NextStep />
      </Reveal>

      {outline && outline.volumes.length > 0 && (
        <Reveal delay={0.08} className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">
          {stats.map((s) => (
            <Stat key={s.label} {...s} />
          ))}
        </Reveal>
      )}

      {concept.selling_points && concept.selling_points.length > 0 && (
        <Reveal delay={0.14} className="mt-8 grid gap-4 md:grid-cols-5">
          <Card hover className="p-6 md:col-span-3">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 font-serif text-lg font-bold">
                <Lightbulb className="size-4 text-seal" />
                核心卖点
              </h3>
              <Link to={`${base}/concept`} className="text-sm text-ink-3 hover:text-ink">
                完整概念 →
              </Link>
            </div>
            <ul className="space-y-2.5 text-[15px] leading-relaxed">
              {concept.selling_points.map((p) => (
                <li key={p} className="flex gap-2.5">
                  <span className="mt-[9px] size-1.5 shrink-0 rotate-45 bg-seal" />
                  {p}
                </li>
              ))}
            </ul>
          </Card>
          <Card hover className="p-6 md:col-span-2">
            <h3 className="mb-3 flex items-center gap-2 font-serif text-lg font-bold">
              <Users className="size-4 text-lore" />
              主角钩子
            </h3>
            <p className="font-serif text-[17px] leading-relaxed text-ink-2">「{concept.protagonist_hook}」</p>
            <p className="mt-4 text-sm text-ink-3">基调：{concept.tone}</p>
          </Card>
        </Reveal>
      )}

      {spine.ending && (
        <Reveal delay={0.17} className="mt-8">
          <Card hover className="p-6">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 font-serif text-lg font-bold">
                <Route className="size-4 text-chief" />
                主线骨架
                <span className="text-sm font-normal text-ink-3">{spine.milestones?.length ?? 0} 个关键转折</span>
              </h3>
              <Link to={`${base}/spine`} className="text-sm text-ink-3 hover:text-ink">
                完整主线 →
              </Link>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="rounded-xl bg-paper-2 px-4 py-3 ring-1 ring-line/80">
                <p className="mb-1 flex items-center gap-1.5 text-xs text-ink-3">
                  <Flag className="size-3.5" />
                  开篇
                </p>
                <p className="line-clamp-4 text-[14px] leading-relaxed">{spine.opening}</p>
              </div>
              <div className="rounded-xl bg-paper-2 px-4 py-3 ring-1 ring-line/80">
                <p className="mb-1 flex items-center gap-1.5 text-xs text-seal">
                  <Flag className="size-3.5" />
                  结局
                </p>
                <p className="line-clamp-4 text-[14px] leading-relaxed">{spine.ending}</p>
              </div>
            </div>
          </Card>
        </Reveal>
      )}

      {outline && outline.volumes.length > 0 && (
        <Reveal delay={0.2} className="mt-8">
          <h3 className="mb-3 flex items-center gap-2 font-serif text-lg font-bold">
            <BookMarked className="size-4 text-chief" />
            分卷
          </h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {outline.volumes.map((v) => (
              <Link key={v.id} to={`${base}/volume/${v.index}`}>
                <Card hover className="flex h-full gap-4 p-5">
                  <span className="font-serif text-3xl leading-none font-bold text-line-2">{String(v.index).padStart(2, '0')}</span>
                  <div className="min-w-0">
                    <p className="font-serif text-[17px] font-bold">
                      {cleanVolumeTitle(v.title)}
                      {v.chapter_count > 0 && <span className="ml-2 font-sans text-xs font-normal text-ink-3">约 {v.chapter_count} 章</span>}
                    </p>
                    <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-ink-2">{v.summary}</p>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </Reveal>
      )}
    </div>
  )
}
