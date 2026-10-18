import clsx from 'clsx'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { type FormEvent, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { type NewBookFields, useBookMeta, useCreateBlankBook, useDraftBook } from '../api/newBook'
import { CategoryPicker, LengthInput, Row, TagPicker } from '../components/BookFields'
import { BookCover } from '../components/BookCover'
import { Button, ErrorText, TypingDots } from '../components/ui'

const EMPTY: NewBookFields = { title: '', blurb: '', channel: '', genre: '', tags: [], target_length: null }
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
      navigate(`/desk/${result.book.id}`)
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
              <LengthInput text={lengthText} chapterWords={chapterWords} onChange={(text, value) => { setLengthText(text); set({ target_length: value }) }} />
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
