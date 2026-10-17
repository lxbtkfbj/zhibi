import { BookMarked, Flag, Lightbulb, MessageCircleQuestion, Route, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useBible, useChapters, useNodes, useOutline } from '../../../api/hooks'
import { Cloud } from '../../../components/decor'
import { StoryMapStrip } from '../../../components/StoryMapStrip'
import { Button, Card, CountUp, Reveal } from '../../../components/ui'
import { cleanTitle, cleanVolumeTitle } from '../../../lib/status'
import { needsSetupRestart, setupOverviewStats } from '../../../lib/setupPresentation'
import { segmentBands, writingTotalChapters } from '../../../lib/storyMap'
import { directionProgressText } from '../../../lib/workspace'
import { useBookContext } from '../context'
import { InterviewForm, ResumeControls } from '../Decision'
import { PitchSelection } from '../PitchSelection'
import { SetupRestartCard } from '../SetupRestartCard'
import { PageHeader } from './common'

function NextStep() {
  const { book, job, bookId, messages } = useBookContext()
  if (needsSetupRestart(book, job)) return <div data-testid="restart-setup-overview"><p className="mb-2 text-xs text-ink-2">下一步</p><SetupRestartCard /></div>
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_pitches') {
    return <PitchSelection key={`${job.id}-${job.pending.round}`} job={job} pending={job.pending} />
  }
  if (job?.kind === 'book_setup' && ['queued', 'running'].includes(job.status) && book.setup_progress.mode === 'puzzle' && !book.concept.title) {
    return <p role="status" className="border-b border-line pb-6 text-sm text-chief">{directionProgressText(job.id, messages)}</p>
  }
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions') {
    return (
      <section className="border-b border-line pb-8">
        <p className="mb-2 flex items-center gap-1.5 text-xs tracking-[0.25em] text-chief">
          <MessageCircleQuestion className="size-3.5" />动笔之前
        </p>
        <h3 className="font-serif text-xl font-bold">主编想先跟你对几件事</h3>
        <p className="mt-2 mb-6 text-[15px] leading-relaxed text-ink-2">
          这些答案会决定整本书的走向。已替你选好推荐答案，改你想改的就行；再点一次可以取消，交给编辑部决定。
        </p>
        <InterviewForm job={job} questions={job.pending.questions} />
      </section>
    )
  }
  if (job && (job.status === 'failed' || job.status === 'cancelled')) {
    return <section className="border-b border-line pb-8"><ResumeControls job={job} /></section>
  }
  if (book.status === 'completed') {
    return (
      <section className="relative overflow-hidden border-b border-line pb-8">
        <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-lore/[0.06]" />
        <p className="mb-2 text-xs tracking-[0.25em] text-lore">全书完结</p>
        <p className="font-serif text-xl">共 {book.chapters_final} 章，{(book.words_final / 10000).toFixed(1)} 万字</p>
        <Link to={`/books/${bookId}/chapters`} className="mt-4 inline-block"><Button variant="soft">从头读起</Button></Link>
      </section>
    )
  }
  return null
}

function Stat({ value, label, suffix, prefix }: { value: number; label: string; suffix: string; prefix?: string }) {
  return (
    <div className="px-1 py-2">
      <p className="text-xs text-ink-2">{label}</p>
      <p className="mt-1 font-serif text-3xl font-bold">
        {prefix && <span className="mr-1 text-sm font-normal text-ink-2">{prefix}</span>}
        <CountUp value={value} />
        <span className="ml-1 text-sm font-normal text-ink-2">{suffix}</span>
      </p>
    </div>
  )
}

export function Overview() {
  const { book, bookId, manualNavigate } = useBookContext()
  const { data: outline } = useOutline(bookId)
  const { data: bible } = useBible(bookId)
  const { data: nodes = [] } = useNodes(bookId)
  const { data: chapterList = [] } = useChapters(bookId)
  const base = `/books/${bookId}`
  const concept = book.concept
  const opening = nodes.find((node) => node.kind === 'opening')
  const ending = nodes.find((node) => node.kind === 'ending')
  const first = outline?.volumes[0]
  const chapters = first?.units.reduce((sum, u) => sum + u.chapter_count, 0) || first?.chapter_count || 0
  const overviewStats = setupOverviewStats(concept, outline?.volumes ?? [], nodes)
  const total = overviewStats.segmented ? writingTotalChapters(nodes, outline?.volumes ?? [], concept) : overviewStats.chapters
  const segmented = overviewStats.segmented
  const endpoint = [...nodes].sort((a, b) => a.index - b.index).find(node => node.kind !== 'opening')
  const protagonist = book.protagonist
  const hasProtagonist = !!protagonist && Object.keys(protagonist).length > 0
  const volumes = outline?.volumes.length ?? 0
  const writing = book.chapters_final > 0
  const currentSegment = segmentBands(nodes, outline?.volumes ?? [], chapterList).find(band => band.status === 'writing')
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
        ? { value: total, label: overviewStats.volumeLabel, prefix: segmented ? '全书约' : undefined, suffix: '章' }
        : { value: volumes, label: '计划', suffix: '卷' },
    writing && total ? { value: total, label: overviewStats.volumeLabel, prefix: segmented ? '全书约' : undefined, suffix: '章' } : { value: chapters, label: '第一卷', suffix: '章' },
    { value: bible?.characters.length ?? 0, label: '人物', suffix: '位' },
  ]

  return (
    <div>
      <PageHeader eyebrow="概览" title={cleanTitle(book.title)} subtitle={book.logline || book.idea} />
      <Reveal>
        <NextStep />
      <div className="mt-5 flex flex-wrap gap-4 text-sm text-chief"><Link to={`${base}/concept`}>定调 →</Link><Link to={`${base}/library?view=focus`}>设定库 · 重点 →</Link></div>
      </Reveal>

      {outline && outline.volumes.length > 0 && (
        <Reveal delay={0.08} className="mt-8 grid grid-cols-2 gap-5 border-b border-line pb-8 @2xl/manuscript:grid-cols-4">
          {stats.map((s) => (
            <Stat key={s.label} {...s} />
          ))}
        </Reveal>
      )}

      {(hasProtagonist || concept.protagonist_hook || !!concept.selling_points?.length) && (
        <Reveal delay={0.14} className="mt-8 grid gap-8 border-b border-line pb-8 @2xl/manuscript:grid-cols-5">
          <section className="@2xl/manuscript:col-span-3">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex flex-wrap items-center gap-2 font-serif text-lg font-bold">
                <Lightbulb className="size-4 text-seal" />
                核心卖点
              </h3>
              <Link to={`${base}/concept`} className="text-sm text-ink-2 hover:text-ink">
                完整概念 →
              </Link>
            </div>
            <ul className="space-y-2.5 text-[15px] leading-relaxed">
              {concept.selling_points?.map((p) => (
                <li key={p} className="flex gap-2.5">
                  <span className="mt-[9px] size-1.5 shrink-0 rotate-45 bg-seal" />
                  {p}
                </li>
              ))}
            </ul>
          </section>
          <section className="@2xl/manuscript:col-span-2">
            <h3 className="mb-3 flex flex-wrap items-center gap-2 font-serif text-lg font-bold">
              <Users className="size-4 text-lore" />
              {hasProtagonist ? '设定库 · 重点' : concept.protagonist_hook ? '主角钩子' : '基调与文风'}
            </h3>
            {hasProtagonist ? <div className="space-y-2 text-sm leading-relaxed text-ink-2" data-testid="overview-protagonist">
              <p><span className="text-ink">姓名：</span><Link to={`${base}/library?view=focus`} className="text-chief underline-offset-4 hover:underline">{protagonist.name || '（未定）'}</Link></p>
              <p><span className="text-ink">长线追求：</span>{protagonist.pursuit || '（未定）'}</p>
              <p><span className="text-ink">开局动机：</span>{protagonist.trigger || '（未定）'}</p>
            </div> : <p className="font-serif text-[17px] leading-relaxed text-ink-2">{concept.protagonist_hook || concept.tone}</p>}
            <p className="mt-4 text-sm text-ink-2">基调：{concept.tone}</p>
          </section>
        </Reveal>
      )}

      {(nodes.length > 0 || writing) && (
        <Reveal delay={0.17} className="mt-8">
          <section className="border-b border-line pb-8">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h3 className="flex flex-wrap items-center gap-2 font-serif text-lg font-bold">
                <Route className="size-4 text-chief" />
                大纲
                <span className="text-sm font-normal text-ink-2">{nodes.filter((node) => node.kind === 'milestone').length} 个关键转折</span>
              </h3>
              <Link to={`${base}/outline?view=map`} className="text-sm text-ink-2 hover:text-ink">
                完整地图 →
              </Link>
            </div>
            {writing ? <><StoryMapStrip nodes={nodes} volumes={outline?.volumes ?? []} chapters={chapterList} concept={concept} onNodeSelect={node => manualNavigate(`${base}/outline?view=map#story-node-${node.id}`)} />{currentSegment && <p data-testid="current-segment-goal" className="mt-4 border-l-2 border-chief/30 pl-3 text-sm leading-relaxed text-ink-2">第 {currentSegment.number} 篇 · 想做成：{currentSegment.plan?.goal || '（未定）'}</p>}</> : <div data-testid="overview-map" className={`grid gap-4 ${segmented ? '@2xl/manuscript:grid-cols-3' : '@2xl/manuscript:grid-cols-2'}`}>
              <div className="border-l border-line pl-4">
                <p className="mb-1 flex items-center gap-1.5 text-xs text-ink-2">
                  <Flag className="size-3.5" />
                  开篇
                </p>
                <p className="line-clamp-4 text-[14px] leading-relaxed">{opening?.event || '（未定）'}</p>
              </div>
              {segmented && <div className="border-l border-line pl-4"><p className="mb-1 text-xs text-chief">第一篇的终点</p><p className="line-clamp-4 text-sm leading-relaxed">{endpoint?.event || '（未定）'}</p></div>}
              <div className="border-l border-line pl-4">
                <p className="mb-1 flex items-center gap-1.5 text-xs text-seal">
                  <Flag className="size-3.5" />
                  {segmented ? '结局方向' : '结局'}
                </p>
                <p className="line-clamp-4 text-[14px] leading-relaxed">{ending?.event || '（未定）'}</p>
              </div>
            </div>}
          </section>
        </Reveal>
      )}

      {outline && outline.volumes.length > 0 && (
        <Reveal delay={0.2} className="mt-8">
          <h3 className="mb-3 flex flex-wrap items-center gap-2 font-serif text-lg font-bold">
            <BookMarked className="size-4 text-chief" />
            分卷
          </h3>
          <div className="grid gap-3 @lg/manuscript:grid-cols-2">
            {outline.volumes.map((v) => (
              <Link key={v.id} to={`${base}/volume/${v.index}`}>
                <Card hover className="flex h-full gap-4 p-5">
                  <span className="font-serif text-3xl leading-none font-bold text-ink-2">{String(v.index).padStart(2, '0')}</span>
                  <div className="min-w-0">
                    <p className="font-serif text-[17px] font-bold">
                      {cleanVolumeTitle(v.title)}
                      {v.chapter_count > 0 && <span className="ml-2 font-sans text-xs font-normal text-ink-2">约 {v.chapter_count} 章</span>}
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
