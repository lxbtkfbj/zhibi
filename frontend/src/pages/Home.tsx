import clsx from 'clsx'
import { ArrowRight, Check, Feather, MessageCircleQuestion, Plus, Sparkles, Trash2 } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useBooks, useCreateBook, useDeleteBook, useProfiles } from '../api/hooks'
import type { BookSummary } from '../api/types'
import { useNewBookDefaults } from '../api/settings'
import { Segmented } from '../components/settings/SettingsList'
import { BookCover } from '../components/BookCover'
import { Cloud, Diamond, FretDivider, InkMountains } from '../components/decor'
import { Badge, Button, ErrorText, Modal, Reveal, Skeleton, Spinner } from '../components/ui'
import { cleanTitle, displayStatus, greeting } from '../lib/status'

const ASK_KEY = 'zhibi:ask-first'

function readAskPref() {
  try {
    return localStorage.getItem(ASK_KEY) !== '0'
  } catch {
    return true
  }
}

const IDEAS = [
  '一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营',
  '末世第三年，我在丧尸围城的城中村开了家奶茶店',
  '穿越成反派大小姐身边的狗，我决定改写她的结局',
  '民国上海，一个替死人画遗像的画师发现画里的人在变老',
  '重生回高考前一晚，这次我只想安安静静当个学渣',
]

function Composer({ autoFocus, flat }: { autoFocus?: boolean; flat?: boolean }) {
  const [idea, setIdea] = useState('')
  const [style, setStyle] = useState('')
  const [showStyle, setShowStyle] = useState(false)
  const [ask, setAskState] = useState(readAskPref)
  const defaults = useNewBookDefaults()
  const [selectedMode, setSelectedMode] = useState<'puzzle' | 'oneshot' | null>(null)
  const mode = selectedMode ?? defaults.data?.settings.setup_mode ?? 'puzzle'
  const [placeholder, setPlaceholder] = useState(0)
  const create = useCreateBook()
  const navigate = useNavigate()
  const { data: profiles } = useProfiles()
  const demoOnly = profiles !== undefined && profiles.every((p) => p.provider === 'demo')
  const ref = useRef<HTMLTextAreaElement>(null)
  const ready = idea.trim().length >= 4

  useEffect(() => {
    const timer = setInterval(() => setPlaceholder((i) => (i + 1) % IDEAS.length), 4000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (autoFocus) ref.current?.focus()
  }, [autoFocus])

  const setAsk = (value: boolean) => {
    setAskState(value)
    try {
      localStorage.setItem(ASK_KEY, value ? '1' : '0')
    } catch {
      /* 浏览器禁用存储时忽略 */
    }
  }

  const submit = async () => {
    // 快捷键会绕过按钮的禁用状态，这里再拦一次，避免重复建书
    if (!ready || create.isPending || !defaults.data) return
    try {
      const result = await create.mutateAsync({ idea: idea.trim(), style_reference: style.trim(), ask: mode === 'oneshot' && ask, mode })
      navigate(`/books/${result.book.id}`)
    } catch { /* 错误在创建区显示，保留点子 */ }
  }

  return (
    <div
      className={clsx(
        'relative overflow-hidden p-2',
        flat ? 'rounded-2xl bg-card ring-1 ring-line' : 'paper transition-shadow focus-within:shadow-[var(--shadow-lift)]',
      )}
    >
      <textarea
        ref={ref}
        value={idea}
        onChange={(e) => setIdea(e.target.value)}
        rows={3}
        placeholder={IDEAS[placeholder]}
        onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && void submit()}
        className="w-full resize-none rounded-xl bg-transparent px-4 pt-3 font-serif text-lg leading-relaxed text-ink placeholder:text-ink-3/70 focus:outline-none"
      />
      {showStyle && (
        <textarea
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          rows={3}
          autoFocus
          placeholder="贴一段你喜欢的文字，编辑部会参考它的文风"
          className="mx-2 mb-2 w-[calc(100%-1rem)] resize-none rounded-xl bg-paper-2 px-3 py-2 text-sm leading-relaxed ring-1 ring-line focus:ring-line-2 focus:outline-none"
        />
      )}
      <div className="flex flex-wrap items-center gap-3 border-t border-line/70 px-3 py-3">
        <span className="text-sm text-ink-2">开书方式</span>
        <Segmented label="开书方式" value={mode} options={[{ value: 'puzzle', label: '逐块确认（推荐）' }, { value: 'oneshot', label: '一口气出方案' }]} onChange={setSelectedMode} />
      </div>
      <div className="flex flex-wrap items-center gap-2 px-2 pb-1">
        <button
          onClick={() => setShowStyle(!showStyle)}
          className={clsx('rounded-lg px-2.5 py-1.5 text-[13px] transition-colors', showStyle ? 'bg-line/60 text-ink' : 'text-ink-3 hover:bg-line/50 hover:text-ink')}
        >
          {showStyle ? '收起文风参考' : '+ 文风参考'}
        </button>
        <button
          onClick={() => setIdea(IDEAS[Math.floor(Math.random() * IDEAS.length)])}
          className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[13px] text-ink-3 transition-colors hover:bg-line/50 hover:text-ink"
        >
          <Sparkles className="size-3.5" />
          给我一个灵感
        </button>
        {mode === 'oneshot' && <button
          onClick={() => setAsk(!ask)}
          aria-pressed={ask}
          title="篇幅、主角名字、金手指、结局……主编动笔前先跟你对一下，免得写完整套方案才发现方向不对"
          className={clsx(
            'flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors',
            ask ? 'bg-chief-soft text-chief' : 'text-ink-3 hover:bg-line/50 hover:text-ink',
          )}
        >
          {ask ? <Check className="size-3.5" /> : <MessageCircleQuestion className="size-3.5" />}
          先问我几个问题
        </button>}
        <span className="ml-auto hidden text-xs text-ink-3 sm:inline">Ctrl + Enter</span>
        <Button variant="seal" size="lg" onClick={submit} loading={create.isPending} disabled={!ready || !defaults.data}>
          交给编辑部
          <ArrowRight className="size-4" />
        </Button>
      </div>
      {demoOnly && (
        <p className="mx-2 mt-2 mb-1 rounded-lg bg-writer-soft px-3 py-2 text-xs text-writer">
          还没有配置模型，编辑部会用「演示模式」生成一本示例书。<Link to="/settings" className="underline underline-offset-2">去添加模型</Link>
        </p>
      )}
      <div className="px-2">
        <ErrorText error={create.error} />
        <ErrorText error={defaults.error} />
        {defaults.isError && <button className="text-sm text-seal underline" onClick={() => void defaults.refetch()}>重试读取新书默认</button>}
      </div>
    </div>
  )
}

function NewBookDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="开一本新书" wide>
      <p className="mb-4 text-sm leading-relaxed text-ink-2">
        写下你的点子，一句话就够。先选方向，再一起完成定调、关键节点、人物上轴、填中间和第一卷。
      </p>
      <Composer autoFocus flat />
      <p className="mt-3 text-xs leading-relaxed text-ink-3">
        逐块确认会在每一块做完后停下来；一口气模式可选择「先问我几个问题」。编辑部工作时，你也可以随时在讨论里插话。
      </p>
    </Modal>
  )
}

function ContinueCard({ book }: { book: BookSummary }) {
  const status = displayStatus(book.status, book.job_status)
  return (
    <Link to={`/books/${book.id}`} className="paper lift group flex items-center gap-6 overflow-hidden p-5 sm:p-6">
      <BookCover title={book.title} seed={book.id} size="sm" className="transition-transform duration-500 group-hover:-rotate-3" />
      <div className="min-w-0 flex-1">
        <p className="mb-1 flex items-center gap-2 text-xs tracking-wider text-ink-3">
          <Diamond /> 继续写作
        </p>
        <h3 className="truncate font-serif text-2xl font-bold">{cleanTitle(book.title)}</h3>
        <p className="mt-1 line-clamp-1 text-sm text-ink-2">{book.logline || book.idea}</p>
        <div className="mt-3 flex items-center gap-2">
          <Badge tone={status.tone}>
            {status.tone === 'busy' && <Spinner className="size-3" />}
            {status.label}
          </Badge>
          {book.genre && <span className="text-xs text-ink-3">{book.genre}</span>}
        </div>
      </div>
      <span className="hidden items-center gap-1 rounded-xl bg-ink px-4 py-2.5 text-sm font-medium text-paper-2 transition-transform duration-300 group-hover:translate-x-1 sm:flex">
        {status.action}
        <ArrowRight className="size-4" />
      </span>
    </Link>
  )
}

function ShelfBook({ book, index }: { book: BookSummary; index: number }) {
  const status = displayStatus(book.status, book.job_status)
  const remove = useDeleteBook()
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.05 * index, ease: [0.22, 1, 0.36, 1] }}
      className="group relative"
    >
      <Link to={`/books/${book.id}`} className="block">
        <div className="flex justify-center rounded-2xl px-4 pt-6 pb-4 transition-colors duration-300 group-hover:bg-card/70">
          <div className="transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:-translate-y-2 group-hover:-rotate-2">
            <BookCover title={book.title} seed={book.id} size="md" className="shadow-[0_14px_24px_-14px_rgb(40_25_10/0.6)]" />
          </div>
        </div>
        <div className="px-3 pt-1 text-center">
          <p className="truncate font-serif text-[15px] font-bold">{cleanTitle(book.title)}</p>
          <div className="mt-1.5 flex justify-center">
            <Badge tone={status.tone}>
              {status.tone === 'busy' && <Spinner className="size-3" />}
              {status.label}
            </Badge>
          </div>
        </div>
      </Link>
      <button
        onClick={() => confirm(`确定删除《${book.title}》？设定库、大纲和会议记录都会一起删除。`) && remove.mutate(book.id)}
        className="absolute top-2 right-2 rounded-lg p-1.5 text-ink-3 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-seal-soft hover:text-seal"
        aria-label="删除"
      >
        <Trash2 className="size-4" />
      </button>
    </motion.div>
  )
}

export function Home() {
  const { data: books, isLoading, error } = useBooks()
  const [creating, setCreating] = useState(false)
  const latest = books?.[0]

  return (
    <div className="pb-20">
      {/* 开头 */}
      <section className="relative isolate overflow-hidden">
        <Cloud className="pointer-events-none absolute top-6 right-[8%] w-40 text-ink/[0.06]" />
        <Cloud className="pointer-events-none absolute top-40 left-[4%] w-28 text-ink/[0.05]" />
        <InkMountains sun={false} className="pointer-events-none absolute inset-x-0 bottom-0 h-56 w-full" />
        <span aria-hidden className="pointer-events-none absolute right-[7%] bottom-36 hidden size-16 rounded-full bg-seal/75 xl:block" />
        <div className="relative mx-auto max-w-3xl px-5 pt-14 pb-40 sm:px-8 sm:pt-20">
          <Reveal>
            <p className="mb-3 text-sm tracking-[0.3em] text-ink-3">{greeting()}，作者</p>
          </Reveal>
          <Reveal delay={0.08}>
            <h1 className="mb-8 font-serif text-4xl leading-tight font-bold sm:text-5xl">今天想写一个什么故事？</h1>
          </Reveal>
          <Reveal delay={0.16}>
            <Composer />
          </Reveal>
          <Reveal delay={0.24}>
            <p className="mt-4 text-center text-[13px] text-ink-3">
              定调 · 钉关键节点 · 人物上轴 · 填中间 · 第一卷 —— 随时插话，每块由你确认
            </p>
          </Reveal>
        </div>
      </section>

      {/* 继续写作卡片与山水重叠：固定前景层级，避免 Reveal 动画结束后背景盖住卡片。 */}
      <div className="relative z-10 mx-auto max-w-6xl px-5 sm:px-8">
        {isLoading && (
          <div className="grid grid-cols-2 gap-6 pt-10 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="aspect-[3/4] w-full" />
            ))}
          </div>
        )}
        <ErrorText error={error} />

        {latest && (
          <Reveal delay={0.3} className="-mt-16 mb-14">
            <ContinueCard book={latest} />
          </Reveal>
        )}

        {books && books.length > 0 && (
          <section>
            <div className="mb-2 flex items-end justify-between gap-4">
              <h2 className="font-serif text-2xl font-bold">
                书架 <span className="ml-1 text-base font-normal text-ink-3">{books.length} 本</span>
              </h2>
            </div>
            <FretDivider className="mb-4" />
            <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-5">
              {books.map((book, i) => (
                <ShelfBook key={book.id} book={book} index={i} />
              ))}
              <button onClick={() => setCreating(true)} className="group flex flex-col items-center">
                <div className="flex justify-center px-4 pt-6 pb-4">
                  <div className="flex aspect-[3/4] w-[150px] flex-col items-center justify-center gap-2 rounded-[4px] border-2 border-dashed border-line-2 text-ink-3 transition-all duration-300 group-hover:-translate-y-2 group-hover:border-seal/50 group-hover:text-seal">
                    <Plus className="size-7" />
                    <span className="text-sm">开新书</span>
                  </div>
                </div>
              </button>
            </div>
          </section>
        )}

        {books && books.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-6 text-center text-ink-3">
            <Feather className="size-8" />
            <p className="text-sm">书架还空着。写下第一个点子，编辑部会把它变成一本书的完整方案。</p>
          </div>
        )}
      </div>
      <NewBookDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
