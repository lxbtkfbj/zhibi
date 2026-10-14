import { ArrowRight, BookMarked, Lightbulb, PenLine, Users } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useBible, useOutline } from '../../../api/hooks'
import { Cloud } from '../../../components/decor'
import { Button, Card, CountUp, Reveal, TypingDots } from '../../../components/ui'
import { cleanTitle, cleanVolumeTitle } from '../../../lib/status'
import { computeStages } from '../../../lib/team'
import { useBookContext } from '../context'
import { DecisionControls, ResumeControls, RunningControls } from '../Decision'
import { PageHeader } from './common'

function NextStep() {
  const { book, job, waiting, working, messages, setTeamOpen, bookId } = useBookContext()
  const base = `/books/${bookId}`
  const current = computeStages(book.status, job?.status, messages).find((s) => s.state === 'current')

  if (waiting && job) {
    return (
      <div className="relative overflow-hidden rounded-2xl border border-seal/25 bg-card p-6 shadow-[var(--shadow-lift)] sm:p-8">
        <span className="absolute inset-y-0 left-0 w-1.5 bg-seal" />
        <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-seal/[0.07]" />
        <p className="mb-1 text-xs tracking-[0.25em] text-seal">下一步 · 拍板</p>
        <h3 className="font-serif text-2xl font-bold">开书方案已就绪，等你过目</h3>
        <p className="mt-2 mb-4 text-[15px] leading-relaxed text-ink-2">
          先看看概念、大纲和人物，觉得哪里不对可以直接改。满意就盖章批准；想让编辑部改，就写下你的意见。
        </p>
        <div className="mb-5 flex flex-wrap gap-2 text-sm">
          {[
            ['书的概念', `${base}/concept`],
            ['第一卷大纲', `${base}/volume/1`],
            ['人物', `${base}/characters`],
          ].map(([label, to]) => (
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
    return (
      <div className="relative overflow-hidden rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
        <p className="mb-1 text-xs tracking-[0.25em] text-chief">进行中</p>
        <h3 className="flex items-center gap-3 font-serif text-2xl font-bold">
          编辑部正在讨论「{current?.label ?? '方案'}」
          <TypingDots className="text-chief" />
        </h3>
        <p className="mt-2 mb-4 text-[15px] leading-relaxed text-ink-2">这一步通常需要几分钟。你可以打开右侧的编辑部看直播，也可以先离开，回来时进度都在。</p>
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
  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)] sm:p-8">
      <Cloud className="pointer-events-none absolute -right-4 -bottom-3 w-44 text-lore/[0.08]" />
      <p className="mb-1 text-xs tracking-[0.25em] text-lore">方案已定稿</p>
      <h3 className="font-serif text-2xl font-bold">下一步：开写第一章</h3>
      <p className="mt-2 mb-5 text-[15px] leading-relaxed text-ink-2">
        编辑部将按第一卷的剧情单元逐章写作。写章节的功能正在开发中（第 2 步），先看看定稿的方案吧。
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" disabled>
          <PenLine className="size-4" />
          开写第一章（开发中）
        </Button>
        <Link to={`${base}/volume/1`}>
          <Button variant="outline">查看第一卷</Button>
        </Link>
      </div>
    </div>
  )
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
  const first = outline?.volumes[0]
  const chapters = first?.units.reduce((sum, u) => sum + u.chapter_count, 0) ?? 0

  return (
    <div>
      <PageHeader eyebrow="概览" title={cleanTitle(book.title)} subtitle={book.logline || book.idea} />
      <Reveal>
        <NextStep />
      </Reveal>

      {outline && outline.volumes.length > 0 && (
        <Reveal delay={0.08} className="mt-8 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat value={outline.volumes.length} label="计划" suffix="卷" />
          <Stat value={chapters} label="第一卷" suffix="章" />
          <Stat value={bible?.characters.length ?? 0} label="主要人物" suffix="位" />
          <Stat value={bible?.foreshadowings.length ?? 0} label="伏笔" suffix="条" />
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
                    <p className="font-serif text-[17px] font-bold">{cleanVolumeTitle(v.title)}</p>
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
