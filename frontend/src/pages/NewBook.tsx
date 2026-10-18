import clsx from 'clsx'
import { ArrowLeft, ArrowRight, X } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useCreateBlankBook } from '../api/hooks'
import { BookCover } from '../components/BookCover'
import { Button, ErrorText } from '../components/ui'

const GENRES = ['玄幻', '仙侠', '武侠', '都市', '历史', '科幻', '悬疑', '游戏', '古言', '现言', '幻言']

// 只是顺手点的常见标签，作者可以自己加任何标签
const TAG_HINTS: Record<string, string[]> = {
  '': ['系统', '重生', '穿越', '无敌', '扮猪吃虎'],
  玄幻: ['系统', '苟道', '宗门', '废柴流', '无敌'],
  仙侠: ['凡人流', '苟道', '宗门', '长生', '洪荒'],
  武侠: ['江湖', '门派', '复仇', '扮猪吃虎'],
  都市: ['系统', '神豪', '重生', '异能', '医生'],
  历史: ['穿越', '争霸', '权谋', '种田', '架空'],
  科幻: ['末世', '星际', '机甲', '赛博朋克'],
  悬疑: ['规则怪谈', '刑侦', '灵异', '推理'],
  游戏: ['网游', '无限流', '全民转职', '副本'],
  古言: ['宫斗', '宅斗', '重生', '种田', '甜宠'],
  现言: ['甜宠', '豪门', '先婚后爱', '娱乐圈'],
  幻言: ['穿书', '快穿', '仙侠恋', '系统'],
}

const LENGTHS = [50, 100, 200, 300, 500] as const
const RECOMMENDED_LENGTH = 200

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        'press h-8 rounded-full border px-3.5 text-[13px] transition-colors',
        active ? 'border-ink bg-ink text-paper-2' : 'border-line-2 bg-card text-ink-2 hover:border-ink-3/60 hover:text-ink',
      )}
    >
      {children}
    </button>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 py-4 sm:grid-cols-[64px_minmax(0,1fr)] sm:gap-4">
      <span className="text-sm text-ink-3 sm:pt-1.5">{label}</span>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

export function NewBookPage() {
  const [title, setTitle] = useState('')
  const [blurb, setBlurb] = useState('')
  const [genre, setGenre] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [tagDraft, setTagDraft] = useState('')
  const [length, setLength] = useState<number | null>(null)
  const create = useCreateBlankBook()
  const navigate = useNavigate()

  const addTag = (text: string) => {
    const tag = text.trim().slice(0, 20)
    if (tag && !tags.includes(tag) && tags.length < 20) setTags([...tags, tag])
    setTagDraft('')
  }
  const hints = (TAG_HINTS[genre] ?? TAG_HINTS['']).filter((tag) => !tags.includes(tag))
  const shownTitle = title.trim() || '未命名'
  const facts = [genre, ...tags].join(' · ')

  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    // 快捷键会绕过按钮的加载状态，这里再拦一次，避免重复建书
    if (create.isPending) return
    try {
      const result = await create.mutateAsync({ title: title.trim(), blurb: blurb.trim(), genre, tags, target_length: length })
      navigate(`/books/${result.book.id}`)
    } catch { /* 错误显示在按钮旁，填的内容保留 */ }
  }

  return (
    <div className="mx-auto max-w-[980px] px-5 pt-2 pb-24 sm:px-8">
      <Link to="/" className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 -ml-2 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />
        回书房
      </Link>

      <form
        onSubmit={submit}
        onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && void submit()}
        className="mt-4 grid overflow-hidden rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)] md:grid-cols-[300px_minmax(0,1fr)]"
      >
        {/* 左边：跟着填写变的封面 */}
        <aside className="hidden flex-col items-center justify-center border-r border-line bg-paper-2 px-8 py-12 md:flex">
          <BookCover title={shownTitle} seed="开新书" size="lg" className="shadow-[0_22px_34px_-18px_rgb(40_25_10/0.55)]" />
          <p className={clsx('mt-8 max-w-full truncate font-serif text-xl font-bold', !title.trim() && 'text-ink-3')}>{shownTitle}</p>
          <p className="mt-1.5 max-w-full text-center text-[13px] leading-relaxed text-ink-3">{facts || '还没分类'}</p>
          {length && <p className="mt-0.5 text-[13px] text-ink-3">计划 {length} 万字</p>}
        </aside>

        {/* 右边：一张书页 */}
        <div className="px-6 py-9 sm:px-12 sm:pt-10 sm:pb-9">
          <p className="text-[13px] tracking-[0.3em] text-ink-3">开一本新书</p>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
            autoFocus
            aria-label="书名"
            placeholder="书名"
            className="mt-3 w-full border-b border-line bg-transparent pb-3 font-serif text-[30px] leading-tight font-bold text-ink placeholder:font-medium placeholder:text-ink-3/45 focus:border-ink-3 focus:outline-none sm:text-[34px]"
          />

          <div className="mt-7">
            <div className="mb-2.5 flex items-baseline justify-between">
              <label htmlFor="blurb" className="text-sm text-ink-3">简介</label>
              {blurb.trim() && <span className="text-xs text-ink-3 tabular-nums">{blurb.trim().length} 字</span>}
            </div>
            <textarea
              id="blurb"
              value={blurb}
              onChange={(e) => setBlurb(e.target.value)}
              maxLength={5000}
              placeholder="写给读者看的那段话。一句话也行，想到哪写到哪。"
              className="block min-h-[150px] w-full resize-none rounded-xl border border-line bg-paper/45 px-5 py-4 font-serif text-[16px] leading-[1.95] text-ink transition-colors [field-sizing:content] placeholder:text-ink-3/70 focus:border-line-2 focus:bg-card focus:outline-none"
            />
          </div>

          <div className="mt-6 divide-y divide-line border-y border-line">
            <Row label="类别">
              <div className="flex flex-wrap gap-2">
                {GENRES.map((item) => (
                  <Chip key={item} active={genre === item} onClick={() => setGenre(genre === item ? '' : item)}>{item}</Chip>
                ))}
              </div>
            </Row>

            <Row label="标签">
              <div className="flex flex-wrap items-center gap-2">
                {tags.map((tag) => (
                  <span key={tag} className="inline-flex h-8 items-center gap-1 rounded-full border border-ink bg-ink pr-1.5 pl-3.5 text-[13px] text-paper-2">
                    {tag}
                    <button type="button" onClick={() => setTags(tags.filter((t) => t !== tag))} aria-label={`去掉标签${tag}`} className="rounded-full p-0.5 text-paper-2/70 hover:bg-paper-2/15 hover:text-paper-2">
                      <X className="size-3.5" />
                    </button>
                  </span>
                ))}
                <input
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.nativeEvent.isComposing) return
                    if ((e.key === 'Enter' && !e.ctrlKey && !e.metaKey) || e.key === '，' || e.key === ',') {
                      e.preventDefault()
                      addTag(tagDraft)
                    } else if (e.key === 'Backspace' && !tagDraft && tags.length) {
                      setTags(tags.slice(0, -1))
                    }
                  }}
                  onBlur={() => tagDraft.trim() && addTag(tagDraft)}
                  aria-label="加标签"
                  placeholder={tags.length ? '再加一个' : '自己写一个，回车加上'}
                  className="h-8 min-w-[9em] flex-1 bg-transparent px-1 text-[13px] text-ink placeholder:text-ink-3/80 focus:outline-none"
                />
              </div>
              {hints.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-x-1 gap-y-1.5 text-[13px]">
                  <span className="mr-1 text-ink-3">常见</span>
                  {hints.map((tag) => (
                    <button key={tag} type="button" onClick={() => addTag(tag)} className="rounded-md px-2 py-0.5 text-ink-2 transition-colors hover:bg-line/60 hover:text-ink">
                      + {tag}
                    </button>
                  ))}
                </div>
              )}
            </Row>

            <Row label="篇幅">
              <div className="flex flex-wrap items-center gap-2">
                {LENGTHS.map((value) => (
                  <Chip key={value} active={length === value} onClick={() => setLength(length === value ? null : value)}>
                    {value} 万
                    {value === RECOMMENDED_LENGTH && <span className={clsx('ml-1.5 text-[11px]', length === value ? 'text-paper-2/70' : 'text-ink-3')}>推荐</span>}
                  </Chip>
                ))}
              </div>
            </Row>
          </div>

          <div className="mt-7 flex flex-wrap items-center justify-between gap-4">
            <p className="text-[13px] text-ink-3">每一项都可以先空着，进去以后随时改。</p>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" size="lg" onClick={() => navigate('/')}>取消</Button>
              <Button type="submit" variant="primary" size="lg" loading={create.isPending}>
                建好这本书
                <ArrowRight className="size-4" />
              </Button>
            </div>
          </div>
          <ErrorText error={create.error} />
        </div>
      </form>
    </div>
  )
}
