/** 本书设置：书页上居中的弹窗，背景糊掉；书页大屏放大时跟着放大。三块：写正文（人称、亲密戏、每章字数、文风参考）、
 *  写作要求、编辑部写得多仔细。改了就存，编辑部正在写也能改，从下一步起照新的来。
 *  写到哪停下来请你看在开写页（正文首页）定，篇幅在简介页改；书名风格、题材打法不在这里（设计说明 9.12「本书设置精简」）。 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { del, patch, post } from '../../api/client'
import { useUpdateBook } from '../../api/hooks'
import { type AuthorRequirement, type SettingsResponse, type WritingSettings, settingsKeys, useAuthorRequirements, useBookSettings, useSettingsEditor } from '../../api/settings'
import { ErrorText } from '../../components/ui'
import { REQUIREMENT_SCOPES, type RequirementScope } from '../../lib/chat'
import { CHAPTER_WORDS_HINT, EFFORT_OPTIONS, EFFORT_PRESETS, INTIMACY_HINTS, INTIMACY_OPTIONS, PERSON_OPTIONS, effortHint, parseChapterWords, unusedCustomNote } from '../../lib/writingSettings'
import { useBookContext } from '../book/context'
import { scheduleAutoSave } from './liveActions'
import { smallButton } from './styles'

const primarySmall = 'h-8 rounded-lg bg-ink px-4 text-[13px] text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-40'
const field = 'rounded-lg border border-line-2 bg-card text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-ink-3'

/** 写作要求条数到了这么多，才出「整理一下」 */
const TIDY_FROM = 5

interface TidyItem { id: string; text: string; action: string; reason: string; rewrite: string }

export function BookSettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return createPortal(<AnimatePresence>{open && <Dialog onClose={onClose} />}</AnimatePresence>, document.body)
}

function Dialog({ onClose }: { onClose: () => void }) {
  const panel = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  // Esc 关上（在改的那一处先自己收起）；Tab 只在弹窗里转；关上以后回到齿轮
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    panel.current?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) {
        event.preventDefault()
        closeRef.current()
      }
      if (event.key !== 'Tab' || !panel.current) return
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)')).filter((el) => el.getClientRects().length > 0)
      const first = items[0]
      const last = items.at(-1)
      if (!first) return
      if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      previous?.focus()
    }
  }, [])
  return (
    <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-overlay)] p-4 backdrop-blur-[6px]"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <motion.div ref={panel} role="dialog" aria-modal="true" aria-labelledby="book-settings-title" tabIndex={-1}
        initial={{ opacity: 0, y: 16, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12, scale: 0.98 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        className="flex w-[720px] flex-col overflow-hidden rounded-2xl border border-line bg-paper shadow-[var(--shadow-lift)] outline-none"
        // 和书页一样按屏幕宽度、外观里的「界面大小」放大；宽高上限先除回去
        style={{
          zoom: 'calc(var(--desk-zoom) * var(--desk-scale))',
          maxWidth: 'calc((100vw - 32px) / var(--desk-zoom) / var(--desk-scale))',
          maxHeight: 'calc(88dvh / var(--desk-zoom) / var(--desk-scale))',
        }}>
        <header className="flex shrink-0 items-start gap-4 border-b border-line px-9 pt-7 pb-5">
          <div className="min-w-0 flex-1">
            <h2 id="book-settings-title" className="font-serif text-[26px] leading-tight font-bold">本书设置</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-3">改了就存，编辑部正在写也能改，从下一步起照新的来。写到哪停下来请你看，在「正文」的开写页定；篇幅在简介页改。</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关上本书设置" title="关上（Esc）"
            className="-mt-1 -mr-3 rounded-lg p-2 text-ink-3 transition-colors hover:bg-line/50 hover:text-ink"><X className="size-5" /></button>
        </header>
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-9 pb-9">
          <Content />
        </div>
      </motion.div>
    </motion.div>
  )
}

function Content() {
  const { bookId } = useBookContext()
  const query = useBookSettings(bookId)
  if (query.isLoading) return <p className="py-12 text-center text-[15px] text-ink-3">正在读设置……</p>
  if (!query.data) {
    return (
      <div className="py-10">
        <ErrorText error={query.error} />
        <button type="button" className={clsx(smallButton, 'mt-3')} onClick={() => void query.refetch()}>再读一次</button>
      </div>
    )
  }
  return <Editor key={bookId} bookId={bookId} initial={query.data} />
}

function Editor({ bookId, initial }: { bookId: string; initial: SettingsResponse }) {
  const { book } = useBookContext()
  const editor = useSettingsEditor(initial, `/books/${bookId}/settings`, 'PATCH')
  const s = editor.value
  const st = editor.statuses
  // 设置也算作者手改了书：停手 3 分钟自动存一档
  const change = (changes: Partial<WritingSettings>, debounce?: boolean) => {
    editor.update(changes, debounce)
    scheduleAutoSave(bookId)
  }
  const intimacyNote = unusedCustomNote(s.intimacy, s.intimacy_custom)
  const words = s.chapter_words ?? book.chapter_words ?? (typeof book.concept.chapter_words === 'number' ? book.concept.chapter_words : 2500)
  return (
    <>
      {!!editor.error && (
        <div role="alert" className="mt-6 flex flex-wrap items-center gap-3 rounded-lg bg-seal-soft/60 px-4 py-2.5">
          <span className="flex-1 text-[13px] text-seal-dark">刚才那一处没存上：{editor.error instanceof Error ? editor.error.message : String(editor.error)}</span>
          <button type="button" className={smallButton} onClick={editor.retry}>再存一次</button>
        </div>
      )}
      <Section title="写正文">
        <Row label="人称" status={st.person}>
          <Choice label="人称" value={s.person} options={PERSON_OPTIONS} onChange={(person) => change({ person })} />
        </Row>
        <Row label="亲密戏写到哪一步" status={st.intimacy || st.intimacy_custom}
          hint={<>{INTIMACY_HINTS[s.intimacy]}{intimacyNote && <span className="mt-0.5 block text-ink-2">{intimacyNote}</span>}</>}
          below={s.intimacy === 'custom' && (
            <input aria-label="自己写的亲密戏规矩" placeholder="比如：可以写到床戏，但不写露骨的细节" value={s.intimacy_custom}
              onChange={(e) => change({ intimacy_custom: e.target.value }, true)} className={clsx(field, 'h-9 w-full px-3 text-[14px]')} />
          )}>
          <Choice label="亲密戏写到哪一步" value={s.intimacy} options={INTIMACY_OPTIONS} onChange={(intimacy) => change({ intimacy })} />
        </Row>
        <ChapterWords value={words} status={st.chapter_words} onSave={(chapter_words) => change({ chapter_words })} />
        <StyleReference bookId={bookId} />
      </Section>
      <Requirements bookId={bookId} />
      <Section title="编辑部写得多仔细">
        <div className="py-4">
          <div className="flex flex-wrap items-center gap-3">
            <Choice label="编辑部写得多仔细" value={s.effort_preset} options={EFFORT_OPTIONS}
              onChange={(effort_preset) => { if (effort_preset !== 'custom') change({ effort_preset, ...EFFORT_PRESETS[effort_preset] }) }} />
            <Saved status={st.effort_preset} />
          </div>
          <p className="mt-2.5 text-[13px] leading-relaxed text-ink-3">{effortHint(s)}</p>
        </div>
      </Section>
    </>
  )
}

/* ---------------- 小部件 ---------------- */

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-8">
      <div className="flex min-h-8 items-center justify-between gap-3 border-b border-line pb-2">
        <h3 className="text-[13px] tracking-[0.15em] text-ink-3">{title}</h3>
        {action}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  )
}

function Saved({ status }: { status?: string }) {
  if (!status) return null
  return <span role="status" className={clsx('text-xs', status === '未保存' ? 'text-seal' : 'text-lore')}>{status}</span>
}

function Row({ label, hint, status, children, below }: { label: string; hint?: ReactNode; status?: string; children: ReactNode; below?: ReactNode }) {
  return (
    <div className="py-4">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2.5">
        <div className="min-w-0">
          <p className="flex items-baseline gap-2 text-[15px] text-ink">{label}<Saved status={status} /></p>
          {hint && <p className="mt-1 text-[13px] leading-relaxed text-ink-3">{hint}</p>}
        </div>
        {children}
      </div>
      {below && <div className="mt-3">{below}</div>}
    </div>
  )
}

/** 几个选项挑一个：和开写页「这一轮写多少」一个样子 */
function Choice<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly { value: T; label: string }[]; onChange: (value: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={clsx('h-8 rounded-lg border px-3.5 text-[13px] transition-colors', value === o.value ? 'border-ink bg-ink text-paper-2' : 'border-line-2 bg-card text-ink-2 hover:border-ink-3/50 hover:text-ink')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ---------------- 每章字数 ---------------- */

/** 每章字数：显示实际按多少写；离开或回车才存，Esc 撤回这次改的。 */
function ChapterWords({ value, status, onSave }: { value: number; status?: string; onSave: (words: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState(false)
  const commit = () => {
    if (draft === null) return
    const words = parseChapterWords(draft)
    if (words === null && draft.trim()) {
      setError(true)
      return
    }
    setDraft(null)
    setError(false)
    if (words !== null && words !== value) onSave(words)
  }
  return (
    <Row label="每章字数" status={status}
      hint={error ? <span className="text-seal">填 500～20000 之间的整数</span> : CHAPTER_WORDS_HINT}>
      <span className="flex items-center gap-2">
        <input type="number" min={500} max={20000} step={100} aria-label="每章字数" aria-invalid={error} value={draft ?? String(value)}
          onChange={(e) => { setDraft(e.target.value); setError(false) }} onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); commit() }
            if (e.key === 'Escape' && draft !== null) { e.preventDefault(); setDraft(null); setError(false) }
          }}
          className={clsx(field, 'h-8 w-24 px-2.5 text-right text-[14px] tabular-nums', error && 'border-seal')} />
        <span className="text-[13px] text-ink-3">字</span>
      </span>
    </Row>
  )
}

/* ---------------- 文风参考 ---------------- */

/** 文风参考：写每一章都带给写手（太长只带前 3000 字）。离开就存；编辑部干活时也能改。 */
function StyleReference({ bookId }: { bookId: string }) {
  const { book } = useBookContext()
  const qc = useQueryClient()
  const update = useUpdateBook(bookId)
  const [draft, setDraft] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const current = book.style_reference ?? ''
  const value = draft ?? current
  // 没离开输入框就关了弹窗：照样存上
  const pending = useRef<string | null>(null)
  useEffect(() => { pending.current = draft !== null && draft !== current ? draft : null }, [draft, current])
  useEffect(() => () => {
    const text = pending.current
    if (text === null) return
    void patch(`/books/${bookId}`, { style_reference: text }).then(() => {
      void qc.invalidateQueries({ queryKey: ['book', bookId] })
      scheduleAutoSave(bookId)
    }).catch(() => undefined)
  }, [bookId, qc])
  const save = async () => {
    if (draft === null) return
    if (draft === current) { setDraft(null); return }
    setSaved(false)
    try {
      await update.mutateAsync({ style_reference: draft })
      setDraft(null)
      setSaved(true)
      scheduleAutoSave(bookId)
    } catch { /* 字留在框里，下面报错 */ }
  }
  const length = value.trim().length
  return (
    <div className="py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <p className="flex items-baseline gap-2 text-[15px] text-ink">文风参考<Saved status={update.isPending ? '保存中…' : update.isError ? '未保存' : saved ? '已保存' : undefined} /></p>
        {length > 0 && <span className="text-xs text-ink-3 tabular-nums">{length} 字{length > 3000 ? '，写手只看前 3000 字' : ''}</span>}
      </div>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-3">贴一段你喜欢的文字，几百字就够。写手照这个味道写：句子长短、对话多少、用词。</p>
      <textarea aria-label="文风参考" value={value} rows={4} placeholder="比如：你喜欢的那本书里的一段"
        onChange={(e) => { setDraft(e.target.value); setSaved(false) }} onBlur={() => void save()}
        onKeyDown={(e) => { if (e.key === 'Escape' && draft !== null) { e.preventDefault(); e.currentTarget.blur() } }}
        className={clsx(field, 'mt-3 block w-full resize-y px-3.5 py-2.5 font-serif text-[15px] leading-relaxed')} />
      <ErrorText error={update.error} />
    </div>
  )
}

/* ---------------- 写作要求 ---------------- */

/** 后台记的范围 → 改的时候下拉框里选中哪一个 */
const scopeOf = (row: AuthorRequirement): RequirementScope => (row.scope === 'chapter' ? 'next_chapter' : row.scope === 'volume' ? 'this_volume' : 'always')

/** 写作要求：以后排大纲、写正文都要照着做的话（以前的「其他规矩」「作者要求清单」都在这里）。群聊里说「以后……」也记到这里。 */
function Requirements({ bookId }: { bookId: string }) {
  const qc = useQueryClient()
  const query = useAuthorRequirements(bookId)
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: settingsKeys.requirements(bookId) })
    scheduleAutoSave(bookId)
  }
  // 整理一下：主编看一遍哪些重复、过时、能合并，摆在清单上面，勾上的才改
  const [tidyItems, setTidyItems] = useState<TidyItem[] | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const tidy = useMutation({
    mutationFn: () => post<{ items: TidyItem[] }>(`/books/${bookId}/requirements/tidy`),
    onSuccess: (res) => {
      const changes = res.items.filter((item) => item.action !== '保留')
      setTidyItems(changes)
      setSelected(changes.map((item) => item.id))
    },
  })
  const apply = useMutation({
    mutationFn: () => post(`/books/${bookId}/requirements/apply`, {
      delete: tidyItems?.filter((item) => selected.includes(item.id) && item.action === '删掉').map((item) => item.id),
      rewrite: tidyItems?.filter((item) => selected.includes(item.id) && item.action === '改写').map((item) => ({ id: item.id, text: item.rewrite })),
    }),
    onSuccess: async () => {
      setTidyItems(null)
      await refresh()
    },
  })
  const rows = query.data ?? []
  const active = rows.filter((r) => r.active)
  const old = rows.filter((r) => !r.active)
  const row = (item: AuthorRequirement) => editing === item.id ? (
    <RequirementEditor key={item.id} initial={item.text} scope={scopeOf(item)} onCancel={() => setEditing(null)}
      onSave={async (text, scope) => {
        await patch(`/requirements/${item.id}`, { text, ...(scope ? { scope } : {}) })
        await refresh()
        setEditing(null)
      }}
      onDelete={async () => {
        await del(`/requirements/${item.id}`)
        await refresh()
        setEditing(null)
      }} />
  ) : (
    <li key={item.id}>
      <button type="button" onClick={() => { setEditing(item.id); setAdding(false) }} title="点了改"
        className="-mx-2.5 flex w-[calc(100%+20px)] items-start gap-4 rounded-md px-2.5 py-3 text-left transition-colors hover:bg-line/40">
        <span className="min-w-0 flex-1 text-[15px] leading-relaxed whitespace-pre-wrap text-ink">{item.text}</span>
        <span className="shrink-0 pt-1 text-xs text-ink-3">{item.label}</span>
      </button>
    </li>
  )
  return (
    <Section title="写作要求" action={
      <div className="flex gap-2">
        {active.length >= TIDY_FROM && (
          <button type="button" className={smallButton} disabled={tidy.isPending} onClick={() => { tidy.mutate(); setAdding(false); setEditing(null) }}>
            {tidy.isPending ? '主编正在看……' : '整理一下'}
          </button>
        )}
        <button type="button" className={smallButton} onClick={() => { setAdding(true); setEditing(null) }}>加一条</button>
      </div>
    }>
      <div>
        {rows.length > 0 && <p className="pt-3 text-[13px] leading-relaxed text-ink-3">编辑部以后排大纲、写正文都照着做。在群聊里说「以后……」，也会记到这里。</p>}
        {query.error && <ErrorText error={query.error} />}
        {(tidyItems || tidy.error) && (
          <div className="mt-3 rounded-xl border border-line bg-card px-4 py-3.5">
            <p className="text-[14px] text-ink">主编的整理建议</p>
            <ErrorText error={tidy.error} />
            {tidyItems && (tidyItems.length === 0
              ? <p className="mt-1.5 text-[14px] text-ink-2">看过了，没有要整理的。</p>
              : (
                <div className="mt-2.5 space-y-2">
                  {tidyItems.map((item) => (
                    <label key={item.id} className="flex cursor-pointer gap-3 rounded-lg border border-line bg-paper/60 p-3">
                      <input type="checkbox" className="mt-1 size-4 shrink-0 accent-[var(--color-ink)]" checked={selected.includes(item.id)}
                        onChange={(e) => setSelected((prev) => (e.target.checked ? [...prev, item.id] : prev.filter((id) => id !== item.id)))} />
                      <span className="text-[14px] leading-relaxed">
                        <span className="block text-ink">{item.text}</span>
                        <span className="block text-seal-dark">{item.action === '删掉' ? '删掉' : `改成「${item.rewrite}」`}</span>
                        <span className="text-[13px] text-ink-3">{item.reason}</span>
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            <ErrorText error={apply.error} />
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className={smallButton} disabled={apply.isPending} onClick={() => { setTidyItems(null); tidy.reset() }}>{tidyItems?.length ? '算了' : '好'}</button>
              {!!tidyItems?.length && <button type="button" className={primarySmall} disabled={apply.isPending || !selected.length} onClick={() => apply.mutate()}>照勾的改</button>}
            </div>
          </div>
        )}
        <ul className="divide-y divide-line/70">
          {adding && (
            <RequirementEditor initial="" scope="always" onCancel={() => setAdding(false)}
              onSave={async (text, scope) => {
                await post(`/books/${bookId}/requirements`, { text, scope: scope ?? 'always' })
                await refresh()
                setAdding(false)
              }} />
          )}
          {active.map(row)}
        </ul>
        {!rows.length && !adding && !query.isLoading && (
          <div className="py-4 text-[14px] leading-relaxed text-ink-3">
            <p>还没有。在群聊里说「以后……」，编辑部会记到这里；也可以自己加一条。比如：</p>
            <p className="mt-1.5 text-ink-2">主角说话要贫、爱吐槽</p>
            <p className="text-ink-2">别写「嘴角勾起一抹弧度」这种套话</p>
          </div>
        )}
        {old.length > 0 && (
          <div className="pt-1 pb-3">
            <button type="button" onClick={() => setExpired(!expired)} className="text-[13px] text-ink-3 transition-colors hover:text-ink">
              {expired ? '收起过期的' : `已经过期的 ${old.length} 条`}
            </button>
            {expired && <ul className="mt-1 divide-y divide-line/70 opacity-60">{old.map(row)}</ul>}
          </div>
        )}
      </div>
    </Section>
  )
}

/** 改一条（或者新加一条）：字、管多久；改的时候范围不动就不送，免得「只管第 12 章」被挪到下一章。 */
function RequirementEditor({ initial, scope, onSave, onCancel, onDelete }: {
  initial: string
  scope: RequirementScope
  onSave: (text: string, scope: RequirementScope | null) => Promise<void>
  onCancel: () => void
  onDelete?: () => Promise<void>
}) {
  const [text, setText] = useState(initial)
  const [picked, setPicked] = useState<RequirementScope | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const run = async (task: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await task()
    } catch (cause) {
      setError(cause)
      setBusy(false)
    }
  }
  const save = () => { if (text.trim() && !busy) void run(() => onSave(text.trim(), picked)) }
  return (
    <li className="py-3">
      <textarea autoFocus aria-label={onDelete ? '改这条写作要求' : '新的写作要求'} value={text} rows={2} placeholder="比如：主角说话要贫、爱吐槽"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { e.preventDefault(); onCancel() }
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save() }
        }}
        className={clsx(field, 'block w-full resize-y px-3 py-2 text-[15px] leading-relaxed')} />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select aria-label="管多久" value={picked ?? scope} onChange={(e) => setPicked(e.target.value as RequirementScope)}
          className={clsx(field, 'h-8 px-2 text-[13px] text-ink-2')}>
          {REQUIREMENT_SCOPES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        {onDelete && <button type="button" disabled={busy} onClick={() => void run(onDelete)} className="h-8 px-2 text-[13px] text-seal transition-colors hover:text-seal-dark disabled:opacity-40">删掉这条</button>}
        <span className="ml-auto flex gap-2">
          <button type="button" className={smallButton} disabled={busy} onClick={onCancel}>算了</button>
          <button type="button" className={primarySmall} disabled={busy || !text.trim()} onClick={save}>{onDelete ? '存好' : '记下'}</button>
        </span>
      </div>
      <ErrorText error={error} />
    </li>
  )
}
