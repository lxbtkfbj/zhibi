import { ArrowRight, Feather, Plus, Trash2 } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useBooks, useDeleteBook, useProfiles } from '../api/hooks'
import type { BookSummary } from '../api/types'
import { BookCover } from '../components/BookCover'
import { Cloud, Diamond, FretDivider, InkMountains } from '../components/decor'
import { Badge, Button, ErrorText, Reveal, Skeleton, Spinner } from '../components/ui'
import { cleanTitle, displayStatus, greeting } from '../lib/status'
import { teardownWords } from '../lib/teardownPreview'

const IDEAS = [
  '一个能看见别人剩余寿命的杂役弟子，在吃人的宗门里步步为营',
  '末世第三年，我在丧尸围城的城中村开了家奶茶店',
  '穿越成反派大小姐身边的狗，我决定改写她的结局',
  '民国上海，一个替死人画遗像的画师发现画里的人在变老',
  '重生回高考前一晚，这次我只想安安静静当个学渣',
]

function Composer() {
  const [idea, setIdea] = useState('')
  const [placeholder, setPlaceholder] = useState(0)
  const navigate = useNavigate()
  const { data: profiles } = useProfiles()
  const demoOnly = profiles !== undefined && profiles.every((p) => p.provider === 'demo')

  useEffect(() => {
    const timer = setInterval(() => setPlaceholder((i) => (i + 1) % IDEAS.length), 4000)
    return () => clearInterval(timer)
  }, [])

  // 写了点子就带到新建页，由编辑部先起草一版；没写就是空白新建页
  const submit = () => navigate('/new', { state: idea.trim() ? { idea: idea.trim() } : null })

  return (
    <div className="paper relative overflow-hidden p-2 transition-shadow focus-within:shadow-[var(--shadow-lift)]">
      <textarea
        value={idea}
        onChange={(e) => setIdea(e.target.value)}
        rows={3}
        placeholder={IDEAS[placeholder]}
        onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && submit()}
        className="w-full resize-none rounded-xl bg-transparent px-4 pt-3 font-serif text-lg leading-relaxed text-ink placeholder:text-ink-3/70 focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-2 px-2 pb-1">
        <button
          onClick={() => setIdea(IDEAS[Math.floor(Math.random() * IDEAS.length)])}
          className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[13px] text-ink-3 transition-colors hover:bg-line/50 hover:text-ink"
        >
          给我一个灵感
        </button>
        <span className="ml-auto hidden text-xs text-ink-3 sm:inline">Ctrl + Enter</span>
        <Button variant="ghost" size="lg" onClick={() => navigate('/teardown/new')}>拆一本书</Button>
        <Button variant="seal" size="lg" onClick={submit}>
          开新书
          <ArrowRight className="size-4" />
        </Button>
      </div>
      {demoOnly && (
        <p className="mx-2 mt-2 mb-1 rounded-lg bg-writer-soft px-3 py-2 text-xs text-writer">
          还没有配置模型，编辑部会用「演示模式」起草示例内容。<Link to="/settings" className="underline underline-offset-2">去添加模型</Link>
        </p>
      )}
    </div>
  )
}

function ContinueCard({ book }: { book: BookSummary }) {
  const status = displayStatus(book.status, book.job_status)
  return (
    <Link to={`/desk/${book.id}`} className="paper lift group flex items-center gap-6 overflow-hidden p-5 sm:p-6">
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
  const teardown = book.source === 'teardown'
  const confirming = teardown && book.teardown?.stage === 'confirming'
  const remove = useDeleteBook()
  const reduce = useReducedMotion()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay: 0.05 * index, ease: [0.22, 1, 0.36, 1] }}
      className="group relative"
    >
      <Link to={confirming ? `/teardown/${book.id}` : `/desk/${book.id}`} state={teardown && !confirming ? { teardownHome: true } : undefined} className="block">
        <div className="flex justify-center rounded-2xl px-4 pt-6 pb-4 transition-colors duration-300 group-hover:bg-card/70">
          <div className="transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:-translate-y-2 group-hover:-rotate-2">
            <BookCover title={book.title} seed={book.id} size="md" className="shadow-[0_14px_24px_-14px_rgb(40_25_10/0.6)]" />
          </div>
        </div>
        <div className="px-3 pt-1 text-center">
          <p className="truncate font-serif text-[15px] font-bold">{cleanTitle(book.title)}</p>
          {teardown ? <>
            <p className="mt-1.5 truncate text-xs text-ink-3">{book.teardown?.author ? `${book.teardown.author} · ` : ''}{teardownWords(book.teardown?.chars ?? 0)}</p>
            <p className="mt-1.5 text-xs text-ink-2">{confirming ? '还没确认分章' : book.teardown?.stage === 'queued' ? '排队中：前面还有书在拆' : book.teardown?.stage === 'running' ? '正在拆' : book.teardown?.stage === 'stopped' ? book.teardown.stop_note || '停了' : book.teardown?.stage === 'done' ? `拆完了 · ${book.teardown.chapters} 章` : `已导入 ${book.teardown?.chapters ?? 0} 章 · 还没开拆`}</p>
          </> : <div className="mt-1.5 flex justify-center">
            <Badge tone={status.tone}>
              {status.tone === 'busy' && <Spinner className="size-3" />}
              {status.label}
            </Badge>
          </div>}
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
  const ownBooks = books?.filter(book => book.source !== 'teardown')
  const teardownBooks = books?.filter(book => book.source === 'teardown')
  const latest = ownBooks?.[0]
  const navigate = useNavigate()

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

        {books && (
          <section>
            <div className="mb-2 flex items-end justify-between gap-4">
              <h2 className="font-serif text-2xl font-bold">
                书架 <span className="ml-1 text-base font-normal text-ink-3">{ownBooks?.length ?? 0} 本</span>
              </h2>
              <div className="flex shrink-0 gap-1.5">
                <Button variant="ghost" size="sm" onClick={() => navigate('/teardown/new')}>拆一本书</Button>
                <Button variant="seal" size="sm" onClick={() => navigate('/new')}>开新书<Plus className="size-3.5" /></Button>
              </div>
            </div>
            <FretDivider className="mb-4" />
            <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-5">
              {ownBooks?.map((book, i) => (
                <ShelfBook key={book.id} book={book} index={i} />
              ))}
              <Link to="/new" className="group flex flex-col items-center">
                <div className="flex justify-center px-4 pt-6 pb-4">
                  <div className="flex aspect-[3/4] w-[150px] flex-col items-center justify-center gap-2 rounded-[4px] border-2 border-dashed border-line-2 text-ink-3 transition-all duration-300 group-hover:-translate-y-2 group-hover:border-seal/50 group-hover:text-seal">
                    <Plus className="size-7" />
                    <span className="text-sm">开新书</span>
                  </div>
                </div>
              </Link>
            </div>
          </section>
        )}

        {ownBooks && ownBooks.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-6 text-center text-ink-3">
            <Feather className="size-8" />
            <p className="text-sm">书架还空着。写下第一个点子，编辑部会把它变成一本书的完整方案。</p>
          </div>
        )}

        {teardownBooks && teardownBooks.length > 0 && (
          <section className="mt-12" aria-label="拆的书">
            <h2 className="mb-2 font-serif text-2xl font-bold">拆的书 <span className="ml-1 text-base font-normal text-ink-3">{teardownBooks.length} 本</span></h2>
            <FretDivider className="mb-4" />
            <div className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-3 lg:grid-cols-5">
              {teardownBooks.map((book, index) => <ShelfBook key={book.id} book={book} index={index} />)}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
