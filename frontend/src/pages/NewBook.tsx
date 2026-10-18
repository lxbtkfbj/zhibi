import clsx from 'clsx'
import { ArrowLeft, ArrowRight, ChevronDown, Plus, X } from 'lucide-react'
import { type FormEvent, type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { type Channel, type NewBookFields, useBookMeta, useCreateBlankBook, useDraftBook } from '../api/newBook'
import { BookCover } from '../components/BookCover'
import { Button, ErrorText, TypingDots } from '../components/ui'

const EMPTY: NewBookFields = { title: '', blurb: '', channel: '', genre: '', tags: [], target_length: null }
const MAX_LENGTH = 5000

/** 点外面或按 Esc 就收起的小浮层，贴在触发按钮下面；下面放不下就翻到上面。 */
function Popover({ open, onClose, children, className }: { open: boolean; onClose: () => void; children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [above, setAbove] = useState(false)
  useLayoutEffect(() => {
    if (!open || !ref.current) return
    const anchor = ref.current.parentElement!.getBoundingClientRect()
    const height = ref.current.offsetHeight
    setAbove(anchor.bottom + height + 12 > window.innerHeight && anchor.top - height - 12 > 0)
  }, [open])
  useEffect(() => {
    if (!open) return
    const down = (event: MouseEvent) => {
      const anchor = ref.current?.parentElement
      if (anchor && !anchor.contains(event.target as Node)) onClose()
    }
    const key = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('mousedown', down)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', down)
      document.removeEventListener('keydown', key)
    }
  }, [open, onClose])
  if (!open) return null
  return (
    <div ref={ref} className={clsx('absolute left-0 z-30 rounded-xl border border-line bg-card p-4 shadow-[var(--shadow-lift)]', above ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]', className)}>
      {children}
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid items-center gap-2 py-3.5 sm:grid-cols-[64px_minmax(0,1fr)] sm:gap-4">
      <span className="text-sm text-ink-3">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

const fieldClass = 'flex h-9 items-center rounded-lg border border-line-2 bg-card px-3 text-sm transition-colors hover:border-ink-3/50'
// 浮层里的小按钮用淡一点的焦点框，不用全局那道朱砂线
const softFocus = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/15'

type MetaQuery = ReturnType<typeof useBookMeta>

function ChannelToggle({ value, onChange }: { value: Channel; onChange: (channel: Channel) => void }) {
  return (
    <div role="radiogroup" aria-label="频道" className="inline-flex gap-0.5 rounded-lg bg-line/60 p-0.5">
      {(['男频', '女频'] as const).map((key) => (
        <button key={key} type="button" role="radio" aria-checked={value === key} onClick={() => onChange(key)}
          className={clsx('rounded-md px-3.5 py-1 text-[13px] transition-colors', softFocus, value === key ? 'bg-card font-medium text-ink shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-ink-2 hover:text-ink')}>
          {key}
        </button>
      ))}
    </div>
  )
}

/** 类别、标签的选项还没读到：读不到时给个重试，别只剩一个输入框。 */
function MetaState({ meta }: { meta: MetaQuery }) {
  if (meta.isPending) return <p className="py-4 text-center text-[13px] text-ink-3">正在读选项…</p>
  return (
    <p className="py-4 text-center text-[13px] text-ink-3">
      选项没读出来。<button type="button" onClick={() => void meta.refetch()} className="text-chief hover:underline">再读一次</button>
    </p>
  )
}

function CategoryPicker({ meta, value, onChange }: { meta: MetaQuery; value: Pick<NewBookFields, 'channel' | 'genre'>; onChange: (next: Pick<NewBookFields, 'channel' | 'genre'>) => void }) {
  const [open, setOpen] = useState(false)
  const [channel, setChannel] = useState<Channel>(value.channel || '男频')
  const [custom, setCustom] = useState('')
  const categories = meta.data?.channels.find((c) => c.key === channel)?.categories ?? []
  const pick = (genre: string) => {
    onChange({ channel, genre })
    setOpen(false)
  }
  return (
    <div className="relative inline-block">
      <button type="button" onClick={() => { setChannel(value.channel || '男频'); setOpen(!open) }} className={clsx(fieldClass, 'min-w-[11rem] justify-between gap-3')} aria-haspopup="dialog" aria-expanded={open}>
        {value.genre ? <span className="text-ink">{value.channel && <span className="text-ink-3">{value.channel} · </span>}{value.genre}</span> : <span className="text-ink-3">选一个</span>}
        <ChevronDown className="size-4 text-ink-3" />
      </button>
      <Popover open={open} onClose={() => setOpen(false)} className="w-[min(26rem,calc(100vw-4rem))]">
        <div className="mb-3 flex items-center justify-between">
          <ChannelToggle value={channel} onChange={setChannel} />
          {value.genre && <button type="button" onClick={() => { onChange({ channel: '', genre: '' }); setOpen(false) }} className="text-xs text-ink-3 hover:text-ink">不选了</button>}
        </div>
        {!meta.data && <MetaState meta={meta} />}
        <div className="grid grid-cols-3 gap-1 sm:grid-cols-4">
          {categories.map((genre) => (
            <button key={genre} type="button" onClick={() => pick(genre)}
              className={clsx('rounded-md px-2 py-1.5 text-[13px] transition-colors', softFocus, value.genre === genre && value.channel === channel ? 'bg-ink text-paper-2' : 'text-ink-2 hover:bg-subtle hover:text-ink')}>
              {genre}
            </button>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <input value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={20} placeholder="都不对？自己写一个，回车用它"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && custom.trim()) { e.preventDefault(); pick(custom.trim()); setCustom('') } }}
            className="h-8 flex-1 rounded-md bg-subtle px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-line-2" />
        </div>
      </Popover>
    </div>
  )
}

function TagPicker({ meta, channel, value, onChange }: { meta: MetaQuery; channel: Channel | ''; value: string[]; onChange: (tags: string[]) => void }) {
  const [open, setOpen] = useState(false)
  const [viewing, setViewing] = useState<Channel>(channel || '男频')
  const [custom, setCustom] = useState('')
  const max = meta.data?.max_tags ?? 10
  const groups = meta.data?.channels.find((c) => c.key === (channel || viewing))?.tag_groups ?? []
  const toggle = (tag: string) => onChange(value.includes(tag) ? value.filter((t) => t !== tag) : value.length < max ? [...value, tag] : value)
  const addCustom = () => {
    const tag = custom.trim().slice(0, 20)
    if (tag && !value.includes(tag) && value.length < max) onChange([...value, tag])
    setCustom('')
  }
  return (
    <div className="relative flex flex-wrap items-center gap-1.5">
      {value.map((tag) => (
        <span key={tag} className="inline-flex h-8 items-center gap-0.5 rounded-full border border-line bg-subtle pr-1 pl-3 text-[13px] text-ink">
          {tag}
          <button type="button" onClick={() => onChange(value.filter((t) => t !== tag))} aria-label={`去掉标签${tag}`} className="rounded-full p-1 text-ink-3 hover:bg-line/70 hover:text-ink">
            <X className="size-3" />
          </button>
        </span>
      ))}
      <button type="button" onClick={() => setOpen(!open)} aria-haspopup="dialog" aria-expanded={open}
        className="inline-flex h-8 items-center gap-1 rounded-full border border-dashed border-line-2 px-3 text-[13px] text-ink-3 transition-colors hover:border-ink-3/60 hover:text-ink">
        <Plus className="size-3.5" />
        {value.length ? '再加' : '加标签'}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} className="w-[min(36rem,calc(100vw-4rem))]">
        {!channel && (
          <div className="mb-3">
            <ChannelToggle value={viewing} onChange={setViewing} />
          </div>
        )}
        {!meta.data && <MetaState meta={meta} />}
        <div className="space-y-2.5">
          {groups.map((group) => (
            <div key={group.name} className="grid grid-cols-[3.25rem_minmax(0,1fr)] items-baseline gap-2">
              <span className="text-xs text-ink-3">{group.name}</span>
              <div className="flex flex-wrap gap-1">
                {group.tags.map((tag) => {
                  const on = value.includes(tag)
                  return (
                    <button key={tag} type="button" onClick={() => toggle(tag)} aria-pressed={on}
                      className={clsx('rounded-full px-2.5 py-1 text-[13px] transition-colors', softFocus, on ? 'bg-ink text-paper-2' : 'text-ink-2 hover:bg-line/60 hover:text-ink')}>
                      {tag}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 border-t border-line pt-3">
          <input value={custom} onChange={(e) => setCustom(e.target.value)} maxLength={20} placeholder="自己写一个，回车加上"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); addCustom() } }}
            className="h-8 flex-1 rounded-md bg-subtle px-2.5 text-[13px] text-ink placeholder:text-ink-3 focus:outline-none focus:ring-1 focus:ring-line-2" />
          <span className="text-xs text-ink-3 tabular-nums">{value.length}/{max}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => { addCustom(); setOpen(false) }}>好了</Button>
        </div>
      </Popover>
    </div>
  )
}

export function NewBookPage() {
  const [fields, setFields] = useState<NewBookFields>(EMPTY)
  const [lengthText, setLengthText] = useState('')
  const [idea, setIdea] = useState('')
  const [feedback, setFeedback] = useState('')
  const [reply, setReply] = useState('')
  // 这次叫编辑部是起草还是按意见改，等待时的提示跟着变
  const [asking, setAsking] = useState<'draft' | 'revise'>('draft')
  const meta = useBookMeta()
  const draft = useDraftBook()
  const create = useCreateBlankBook()
  const navigate = useNavigate()
  const location = useLocation()
  const started = useRef(false)
  const set = (patch: Partial<NewBookFields>) => setFields((f) => ({ ...f, ...patch }))

  const applyDraft = (result: NewBookFields & { reply: string }) => {
    const { reply: said, ...rest } = result
    setFields(rest)
    setLengthText(rest.target_length ? String(rest.target_length) : '')
    setReply(said)
  }

  const startDraft = (text: string) => {
    setIdea(text)
    setAsking('draft')
    draft.mutate({ idea: text }, { onSuccess: (result) => { applyDraft(result); setFeedback('') } })
  }

  // 从首页带着点子过来：编辑部先起草一版。只起一次，刷新后就是空白页。
  useEffect(() => {
    const fromHome = (location.state as { idea?: string } | null)?.idea?.trim()
    if (!fromHome || started.current) return
    started.current = true
    navigate(location.pathname, { replace: true, state: null })
    startDraft(fromHome)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const length = fields.target_length
  const chapterWords = meta.data?.chapter_words ?? 2500
  const chapters = length ? Math.round((length * 10000) / chapterWords) : null
  const shownTitle = fields.title.trim() || '未命名'
  const facts = [fields.genre, ...fields.tags].join(' · ')

  const filled = Boolean(fields.title.trim() || fields.blurb.trim() || fields.genre || fields.tags.length || fields.target_length)
  // 空白页第一次叫编辑部：这句话就当点子，让它起草
  const freshAsk = !idea && !filled

  const ask = () => {
    const text = feedback.trim()
    if (!text || draft.isPending) return
    if (freshAsk) return startDraft(text)
    setAsking('revise')
    draft.mutate({ idea, current: fields, feedback: text }, { onSuccess: (result) => { applyDraft(result); setFeedback('') } })
  }

  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    // 快捷键会绕过按钮的加载状态，这里再拦一次，避免重复建书
    if (create.isPending || draft.isPending) return
    try {
      const result = await create.mutateAsync({ ...fields, title: fields.title.trim(), blurb: fields.blurb.trim() })
      navigate(`/books/${result.book.id}`)
    } catch { /* 错误显示在按钮下面，填的内容保留 */ }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-72px)] max-w-[980px] flex-col justify-center px-5 pt-4 pb-16 sm:px-8">
      <Link to="/" className="-ml-2 inline-flex w-fit items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />
        回书房
      </Link>

      <form
        onSubmit={submit}
        onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && void submit()}
        className="mt-3 grid rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)] md:grid-cols-[300px_minmax(0,1fr)]"
      >
        {/* 左边：跟着填写变的封面 */}
        <aside className="hidden flex-col items-center justify-center rounded-l-2xl border-r border-line bg-paper-2 px-8 py-12 md:flex">
          <BookCover title={shownTitle} seed="开新书" size="lg" className="shadow-[0_22px_34px_-18px_rgb(40_25_10/0.55)]" />
          <p className={clsx('mt-8 max-w-full truncate font-serif text-xl font-bold', !fields.title.trim() && 'text-ink-3')}>{shownTitle}</p>
          <p className="mt-1.5 max-w-full text-center text-[13px] leading-relaxed text-ink-3">{facts || '还没分类'}</p>
          {chapters && <p className="mt-0.5 text-[13px] text-ink-3">{length} 万字 · 约 {chapters} 章</p>}
        </aside>

        {/* 右边：一张书页 */}
        <div className="relative px-6 py-9 sm:px-12 sm:pt-10 sm:pb-9">
          <p className="text-[13px] tracking-[0.3em] text-ink-3">开一本新书</p>
          <input
            value={fields.title}
            onChange={(e) => set({ title: e.target.value })}
            maxLength={200}
            autoFocus={!idea}
            aria-label="书名"
            placeholder="书名"
            className="mt-3 w-full border-b border-line bg-transparent pb-3 font-serif text-[30px] leading-tight font-bold text-ink placeholder:font-medium placeholder:text-ink-3/45 focus:border-ink-3 focus:outline-none sm:text-[34px]"
          />

          <div className="mt-7">
            <div className="mb-2.5 flex items-baseline justify-between">
              <label htmlFor="blurb" className="text-sm text-ink-3">简介</label>
              {fields.blurb.trim() && <span className="text-xs text-ink-3 tabular-nums">{fields.blurb.trim().length} 字</span>}
            </div>
            <textarea
              id="blurb"
              value={fields.blurb}
              onChange={(e) => set({ blurb: e.target.value })}
              maxLength={5000}
              placeholder="写给读者看的那段话。一句话也行，想到哪写到哪。"
              className="block max-h-[22rem] min-h-[150px] w-full resize-none rounded-xl border border-line bg-paper/45 px-5 py-4 font-serif text-[16px] leading-[1.95] text-ink transition-colors [field-sizing:content] placeholder:text-ink-3/70 focus:border-line-2 focus:bg-card focus:outline-none"
            />
          </div>

          <div className="mt-5 divide-y divide-line border-y border-line">
            <Row label="类别">
              <CategoryPicker meta={meta} value={fields} onChange={(next) => set(next)} />
            </Row>
            <Row label="标签">
              <TagPicker meta={meta} channel={fields.channel} value={fields.tags} onChange={(tags) => set({ tags })} />
            </Row>
            <Row label="篇幅">
              <div className="flex flex-wrap items-center gap-3">
                <label className={clsx(fieldClass, 'gap-1.5 px-2.5 focus-within:border-ink-3')}>
                  <input
                    value={lengthText}
                    onChange={(e) => {
                      const digits = e.target.value.replace(/\D/g, '').slice(0, 4)
                      const value = digits ? Math.min(Number(digits), MAX_LENGTH) : null
                      setLengthText(value ? String(value) : '')
                      set({ target_length: value })
                    }}
                    inputMode="numeric"
                    aria-label="篇幅（万字）"
                    placeholder="200"
                    className="w-10 bg-transparent text-right text-sm text-ink tabular-nums placeholder:text-ink-3/70 focus:outline-none"
                  />
                  <span className="text-ink-3">万字</span>
                </label>
                {chapters
                  ? <span className="text-[13px] text-ink-2 tabular-nums" title={`按每章 ${chapterWords} 字算`}>约 {chapters.toLocaleString()} 章</span>
                  : <span className="text-[13px] text-ink-3">没想好可以空着</span>}
              </div>
            </Row>
          </div>

          <div className="mt-6">
            <div className="flex items-center gap-2 rounded-xl border border-line bg-subtle/70 py-1.5 pr-1.5 pl-2 focus-within:border-line-2">
              <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-chief font-serif text-[13px] text-on-role">编</span>
              <input
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask() } }}
                maxLength={2000}
                aria-label="告诉编辑部"
                placeholder={freshAsk ? '想让编辑部帮你写？说说你想写个什么故事' : idea ? '不满意？告诉编辑部怎么改，比如：书名再短一点' : '想让编辑部帮忙？比如：帮我把简介写完整'}
                className="h-8 min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-3 focus:outline-none"
              />
              <Button type="button" size="sm" variant="outline" onClick={ask} disabled={!feedback.trim()} loading={draft.isPending}>{freshAsk ? '帮我写' : '改一改'}</Button>
            </div>
            {reply && !draft.isPending && <p className="mt-2 pl-1 text-xs leading-relaxed text-ink-3">编辑部：{reply}</p>}
            {draft.isError && filled && <div className="mt-2 pl-1"><ErrorText error={draft.error} /></div>}
          </div>

          <div className="mt-7 flex flex-wrap items-center justify-between gap-4">
            <p className="text-[13px] text-ink-3">每一项都可以先空着，进去以后随时改。</p>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" size="lg" onClick={() => navigate('/')}>取消</Button>
              <Button type="submit" variant="primary" size="lg" loading={create.isPending} disabled={draft.isPending}>
                下一步
                <ArrowRight className="size-4" />
              </Button>
            </div>
          </div>
          <ErrorText error={create.error} />

          {/* 编辑部起草或改的时候盖一层，免得作者改到一半被换掉 */}
          {draft.isPending && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 rounded-2xl bg-card/85 px-10 text-center backdrop-blur-[2px] md:rounded-l-none">
              <span className="flex size-10 items-center justify-center rounded-full bg-chief font-serif text-base text-on-role">编</span>
              <p className="flex items-center gap-2 text-[15px] text-ink">
                {asking === 'revise' ? '编辑部正在按你的意见改' : '编辑部正在按你的点子起草'}
                <TypingDots className="text-ink-3" />
              </p>
              <p className="line-clamp-2 max-w-md font-serif text-sm leading-relaxed text-ink-3">「{asking === 'revise' ? feedback : idea}」</p>
            </div>
          )}
          {asking === 'draft' && draft.isError && !filled && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 rounded-2xl bg-card/90 px-10 text-center md:rounded-l-none">
              <p className="text-[15px] text-ink">编辑部这次没起草出来</p>
              <ErrorText error={draft.error} />
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={() => startDraft(idea)}>再试一次</Button>
                <Button type="button" variant="ghost" onClick={() => { draft.reset(); setIdea('') }}>我自己写</Button>
              </div>
            </div>
          )}
        </div>
      </form>
    </div>
  )
}
