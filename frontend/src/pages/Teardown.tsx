import { useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { ArrowLeft, Upload } from 'lucide-react'
import { type DragEvent, type ReactNode, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, del, get, patch } from '../api/client'
import { keys } from '../api/hooks'
import { cancelTeardownAppend, changeTeardownAppendEncoding, changeTeardownEncoding, getTeardownAppendPreview, getTeardownPreview, importTeardown, importTeardownAppend, type TeardownEncoding, uploadTeardown, uploadTeardownAppend, useTeardownModel } from '../api/teardown'
import type { BookDetail, Chapter } from '../api/types'
import { BookCover } from '../components/BookCover'
import { TeardownOptions } from '../components/TeardownStart'
import { Button, ErrorText, Spinner, inputClass } from '../components/ui'
import { createTeardownFieldSaver, teardownCleaningText, teardownNumberIssueText, teardownPreviewTotals, teardownSplitText, type TeardownAppendPreview, type TeardownFields, type TeardownPreview } from '../lib/teardownPreview'
import { teardownAppendJunctionText, teardownAppendNotes, teardownAppendSelection, teardownAppendSplitText, teardownAppendVolumeText } from '../lib/teardownAppend'
import { parseTeardownUpto } from '../lib/teardownStart'

const ENCODINGS: readonly (readonly [TeardownEncoding, string])[] = [['auto', '自动'], ['utf-8', 'UTF-8'], ['gb18030', 'GB18030'], ['utf-16', 'UTF-16'], ['big5', 'BIG5']]

function TeardownPage({ title, children, back }: { title: string; children: ReactNode; back?: { to: string; label: string } }) {
  return (
    <div className="mx-auto flex min-h-[calc(100dvh-72px)] max-w-[980px] flex-col justify-center px-5 pt-4 pb-16 sm:px-8">
      <Link to={back?.to ?? '/'} className="-ml-2 inline-flex w-fit items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-ink-3 transition-colors hover:bg-line/50 hover:text-ink">
        <ArrowLeft className="size-4" />{back?.label ?? '回书房'}
      </Link>
      <div className="mt-3 grid rounded-2xl border border-line bg-card shadow-[var(--shadow-lift)] md:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="hidden flex-col items-center justify-start rounded-l-2xl border-r border-line bg-paper-2 px-7 py-12 md:flex">
          <BookCover title={title || '拆一本书'} seed="拆一本书" size="lg" className="shadow-[0_22px_34px_-18px_rgb(40_25_10/0.55)]" />
          <p className="mt-8 max-w-full text-center font-serif text-xl leading-relaxed font-bold break-words">{title || '拆一本书'}</p>
        </aside>
        <div className="min-w-0 px-6 py-9 sm:px-10 sm:pt-10 sm:pb-9">{children}</div>
      </div>
    </div>
  )
}

export function TeardownUploadPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const uploading = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => () => controller.current?.abort(), [])

  const upload = async (file?: File) => {
    if (!file || uploading.current) return
    setError(null)
    if (!file.name.toLowerCase().endsWith('.txt')) { setError('只能导入 TXT 文件'); return }
    if (file.size > 52_428_800) { setError('文件超过 50MB'); return }
    uploading.current = true
    setBusy(true)
    setProgress(0)
    const current = new AbortController()
    controller.current = current
    try {
      const preview = await uploadTeardown(file, setProgress, current.signal)
      void queryClient.invalidateQueries({ queryKey: keys.books })
      navigate(`/teardown/${preview.book_id}`)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(reason)
    } finally {
      uploading.current = false
      setBusy(false)
    }
  }


  return (
    <TeardownPage title="拆一本书">
      <h1 className="font-serif text-3xl font-bold">拆一本书</h1>
      <p className="mt-4 text-sm leading-relaxed text-ink-3">选一本小说的 TXT 文件，50MB 以内。程序先分好卷和章，你看一眼对不对再导入。</p>
      <TeardownFilePicker busy={busy} progress={progress} upload={upload} />
      <div role="alert"><ErrorText error={error} /></div>
    </TeardownPage>
  )
}

/** 导入与补章节共用同一个上传框，拖放、进度和文案保持一致。 */
function TeardownFilePicker({ busy, progress, upload }: { busy: boolean; progress: number; upload: (file?: File) => Promise<void> }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const drop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    if (!busy) void upload(event.dataTransfer.files[0])
  }
  return <>
      <input ref={fileInput} type="file" accept=".txt" aria-label="选择 TXT 文件" className="hidden" onChange={event => { void upload(event.target.files?.[0]); event.target.value = '' }} />
      <button
        type="button"
        disabled={busy}
        onClick={() => fileInput.current?.click()}
        onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={clsx('mt-8 flex min-h-56 w-full flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed bg-paper/45 px-6 py-10 text-center transition-colors disabled:cursor-wait', dragging ? 'border-seal bg-seal-soft' : 'border-line-2 hover:border-ink-3/50 hover:bg-paper-2')}
      >
        {busy ? <Spinner className="size-7 text-ink-3" /> : <Upload className="size-7 text-ink-3" />}
        <span className="font-serif text-lg">{busy ? '正在分章……' : '选择 TXT 文件，或拖到这里'}</span>
        {busy && progress > 0 && (
          <div className="w-full max-w-56">
            <div role="progressbar" aria-label="上传进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} className="h-1.5 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-ink-3 transition-[width]" style={{ width: `${progress}%` }} />
            </div>
            <span className="mt-2 block text-xs text-ink-3 tabular-nums">{progress}%</span>
          </div>
        )}
      </button>
  </>
}

export function TeardownConfirmPage() {
  const { bookId = '' } = useParams()
  return <TeardownConfirmBook key={bookId} bookId={bookId} />
}

// 换书时由 key 换一张确认页；不把上一本的输入、勾选或未完成请求带到下一本。
function TeardownConfirmBook({ bookId }: { bookId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [preview, setPreview] = useState<TeardownPreview | null>(null)
  const [fields, setFields] = useState<TeardownFields>({ title: '', author: '' })
  const fieldsRef = useRef(fields)
  const saver = useRef<ReturnType<typeof createTeardownFieldSaver> | null>(null)
  const operating = useRef(false)
  const [busy, setBusy] = useState<'encoding' | 'import' | 'start' | 'delete' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [encodingError, setEncodingError] = useState<unknown>(null)
  const [fieldError, setFieldError] = useState<unknown>(null)
  const fieldAttempt = useRef(0)
  const [include, setInclude] = useState<number[]>([])
  const [expandedVolumes, setExpandedVolumes] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [uptoInput, setUptoInput] = useState('')
  const model = useTeardownModel()
  const total = preview ? teardownPreviewTotals(preview, include).chapters : 0
  const upto = parseTeardownUpto(uptoInput, total)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const data = await getTeardownPreview(bookId)
        if (!active) return
        const initial = { title: data.title, author: data.author }
        fieldsRef.current = initial
        setFields(initial)
        setPreview(data)
        saver.current = createTeardownFieldSaver(initial, async changes => {
          await patch(`/books/${bookId}`, changes)
          void queryClient.invalidateQueries({ queryKey: keys.books })
        })
      } catch (reason) {
        if (!active) return
        if (reason instanceof ApiError && reason.status === 409) navigate(`/desk/${bookId}`, { replace: true, state: { teardownHome: true } })
        else setError(reason)
      } finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false }
  }, [bookId, navigate, queryClient])

  const updateField = (name: keyof TeardownFields, value: string) => {
    const next = { ...fieldsRef.current, [name]: value }
    fieldsRef.current = next
    setFields(next)
    setConfirmDelete(false)
  }

  const saveFields = async () => {
    const attempt = ++fieldAttempt.current
    try {
      await saver.current?.save(fieldsRef.current)
      if (fieldAttempt.current === attempt) setFieldError(null)
    } catch (reason) {
      if (fieldAttempt.current === attempt) setFieldError(reason)
      throw reason
    }
  }

  const switchEncoding = async (encoding: TeardownEncoding) => {
    if (operating.current || !preview) return
    operating.current = true
    setBusy('encoding')
    setEncodingError(null)
    setError(null)
    setConfirmDelete(false)
    let fieldsSaved = false
    try {
      // 鼠标点击先触发离焦；这里仍排队等待并补存一次，键盘操作也不会漏掉手改。
      await saveFields()
      fieldsSaved = true
      const result = await changeTeardownEncoding(bookId, encoding)
      const next = { title: result.title, author: result.author }
      fieldsRef.current = next
      saver.current?.accept(next)
      setFields(next)
      setPreview(result)
      setInclude([])
      setExpandedVolumes(false)
    } catch (reason) { if (fieldsSaved) setEncodingError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  const importBook = async (start: boolean) => {
    if (operating.current || !preview || upto === undefined || (start && !model.ready)) return
    operating.current = true
    setBusy(start ? 'start' : 'import')
    setError(null)
    setConfirmDelete(false)
    let fieldsSaved = false
    try {
      await saveFields()
      fieldsSaved = true
      const result = await importTeardown(bookId, fieldsRef.current, include, start ? { upto } : undefined)
      queryClient.setQueryData(keys.book(bookId), result)
      void queryClient.invalidateQueries({ queryKey: keys.books })
      navigate(`/desk/${bookId}`, { state: { teardownHome: true } })
    } catch (reason) { if (fieldsSaved) setError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  const cancel = async () => {
    if (operating.current) return
    if (!confirmDelete) { setConfirmDelete(true); return }
    operating.current = true
    setBusy('delete')
    setError(null)
    try {
      // 已在途的离焦保存先结束；不要让它在删书以后再请求旧书。
      await saver.current?.settled().catch(() => {})
      await del(`/books/${bookId}`)
      void queryClient.invalidateQueries({ queryKey: keys.books })
      queryClient.removeQueries({ queryKey: keys.book(bookId) })
      navigate('/')
    } catch (reason) { setError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  return (
    <TeardownPage title={fields.title || '拆一本书'}>
      {loading && <div className="flex items-center justify-center gap-2 py-24 text-sm text-ink-3"><Spinner />正在分章……</div>}
      {!loading && !preview && <ErrorText error={error} />}
      {preview && (
        <form onSubmit={event => { event.preventDefault(); void importBook(true) }} className="space-y-7">
          <div>
            <label htmlFor="teardown-title" className="text-[13px] tracking-[0.3em] text-ink-3">书名</label>
            <input id="teardown-title" value={fields.title} maxLength={200} disabled={busy !== null} onChange={event => updateField('title', event.target.value)} onBlur={() => { void saveFields().catch(() => {}) }} className="mt-3 w-full border-b border-line bg-transparent pb-3 font-serif text-3xl leading-tight font-bold focus:border-ink-3 focus:outline-none" />
            <p className="mt-2 text-xs text-ink-3">猜的，可以改</p>
            <label htmlFor="teardown-author" className="mt-5 mb-2 block text-sm text-ink-3">作者</label>
            <input id="teardown-author" value={fields.author} maxLength={200} disabled={busy !== null} onChange={event => updateField('author', event.target.value)} onBlur={() => { void saveFields().catch(() => {}) }} className={inputClass} />
            <div role="alert"><ErrorText error={fieldError} /></div>
          </div>

          <div className="border-y border-line py-4">
            <p className="text-[15px] leading-relaxed text-ink-2" data-testid="teardown-split-summary">{teardownSplitText(preview, include)}</p>
            {preview.first && preview.last && <p className="mt-2 text-xs leading-relaxed text-ink-3">第 {preview.first.index} 章 {preview.first.title} …… 第 {preview.last.index} 章 {preview.last.title}</p>}
          </div>

          <section aria-label="开头几行原文">
            <div className="rounded-xl border border-line bg-paper/45 px-5 py-4 font-serif text-[15px] leading-[1.95] whitespace-pre-wrap">{preview.opening.split('\n').map((line, index) => <p key={index} className="indent-[2em]">{line || '\u00a0'}</p>)}</div>
            <p className="mt-3 text-xs text-ink-3">看着是乱码？换一种编码：</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="编码">
              {ENCODINGS.map(([encoding, label]) => {
                const selected = encoding === 'auto' ? preview.encoding_auto : !preview.encoding_auto && preview.encoding.toLowerCase() === encoding
                return <Button key={encoding} type="button" size="sm" variant={selected ? 'primary' : 'soft'} aria-pressed={selected} disabled={busy !== null} onClick={() => { void switchEncoding(encoding) }}>{label}</Button>
              })}
              {preview.encoding_auto && <span className="ml-1 text-xs text-ink-3">{preview.encoding}</span>}
              {busy === 'encoding' && <Spinner className="ml-1 size-3.5 text-ink-3" />}
            </div>
            <div role="alert"><ErrorText error={encodingError} /></div>
          </section>

          {preview.volumes.length > 0 && (
            <section aria-label="分卷">
              <h2 className="mb-3 font-serif text-lg font-bold">分卷</h2>
              <div className="space-y-2 text-sm text-ink-2">{(expandedVolumes ? preview.volumes : preview.volumes.slice(0, 8)).map(volume => <p key={volume.index}>第 {volume.index} 卷 {volume.title} · {volume.chapters} 章</p>)}</div>
              {!expandedVolumes && preview.volumes.length > 8 && <button type="button" className="mt-3 text-xs text-ink-3 underline underline-offset-4 hover:text-ink" onClick={() => setExpandedVolumes(true)}>还有 {preview.volumes.length - 8} 卷，展开</button>}
            </section>
          )}

          {preview.excluded.length > 0 && (
            <section>
              <h2 className="mb-3 font-serif text-lg font-bold">这几章看着不像正文，默认不导入</h2>
              <div className="divide-y divide-line rounded-xl border border-line bg-paper/30 px-4">
                {preview.excluded.map(chapter => (
                  <label key={chapter.order} className="flex cursor-pointer items-start gap-3 py-3">
                    <input type="checkbox" checked={include.includes(chapter.order)} disabled={busy !== null} className="mt-1 accent-ink" onChange={event => { setInclude(current => event.target.checked ? [...current, chapter.order] : current.filter(order => order !== chapter.order)); setConfirmDelete(false) }} />
                    <span className="min-w-0"><span className="text-sm text-ink-2">{chapter.title} · {chapter.chars.toLocaleString('zh-CN')} 字 · {chapter.reason}</span><span className="mt-1 block text-xs leading-relaxed text-ink-3">{chapter.head}</span></span>
                  </label>
                ))}
              </div>
            </section>
          )}

          {preview.number_issues.length > 0 && (
            <section>
              <h2 className="font-serif text-lg font-bold">原书章号对不上的地方</h2>
              <p className="mt-2 text-xs leading-relaxed text-ink-3">不影响导入：章号按顺序从 1 重新编，这里只是让你知道原书哪里缺了、乱了</p>
              <div className="mt-3 space-y-2 text-sm text-ink-2">{preview.number_issues.map((issue, index) => <p key={`${issue.index}:${index}`}>{teardownNumberIssueText(issue)}</p>)}</div>
              {preview.number_issue_total > preview.number_issues.length && <p className="mt-2 text-xs text-ink-3">还有 {preview.number_issue_total - preview.number_issues.length} 处没列</p>}
            </section>
          )}

          <p className="text-xs leading-relaxed text-ink-3">{teardownCleaningText(preview)}</p>
          <TeardownOptions total={total} value={uptoInput} onChange={setUptoInput} disabled={busy !== null} />
          <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-5">
            <Button type="button" variant="ghost" size="lg" disabled={busy !== null} loading={busy === 'delete'} onClick={() => { void cancel() }}>{confirmDelete ? '确定不导入？再点一次' : '不导入了'}</Button>
            <Button type="button" variant="outline" size="lg" disabled={busy !== null || upto === undefined} loading={busy === 'import'} onClick={() => { void importBook(false) }}>先只导入，不拆</Button>
            <Button type="submit" variant="primary" size="lg" disabled={busy !== null || upto === undefined || !model.ready} loading={busy === 'start'}>开始拆</Button>
          </div>
          <div role="alert"><ErrorText error={error} /></div>
        </form>
      )}
    </TeardownPage>
  )
}

export function TeardownAppendPage() {
  const { bookId = '' } = useParams()
  return <TeardownAppendBook key={bookId} bookId={bookId} />
}

function TeardownAppendBook({ bookId }: { bookId: string }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [book, setBook] = useState<BookDetail | null>(null)
  const [last, setLast] = useState<{ index: number; title: string } | null>(null)
  const [rawPreview, setPreview] = useState<TeardownAppendPreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'upload' | 'encoding' | 'import' | 'start' | 'delete' | null>(null)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<unknown>(null)
  const [encodingError, setEncodingError] = useState<unknown>(null)
  const [include, setInclude] = useState<number[]>([])
  const [expandedVolumes, setExpandedVolumes] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [uptoInput, setUptoInput] = useState('')
  const operating = useRef(false)
  const controller = useRef<AbortController | null>(null)
  const model = useTeardownModel()
  const preview = rawPreview ? teardownAppendSelection(rawPreview, include) : null
  const added = preview ? teardownPreviewTotals(preview, include).chapters : 0
  const total = preview ? preview.previous.chapters + added : book?.teardown?.chapters ?? 0
  const upto = parseTeardownUpto(uptoInput, total)
  const notes = preview ? teardownAppendNotes(preview) : []

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [data, pending] = await Promise.all([
          get<BookDetail>(`/books/${bookId}`),
          getTeardownAppendPreview(bookId).then(value => ({ value, error: null }), error => ({ value: null, error })),
        ])
        if (!active) return
        setBook(data)
        if (pending.value) setPreview(pending.value)
        else {
          const count = data.teardown?.chapters ?? data.chapters_final
          const chapter = count > 0 ? await get<Chapter>(`/books/${bookId}/chapters/${count}`) : { index: 0, title: '' }
          if (!active) return
          setLast({ index: chapter.index, title: chapter.title })
          if (!(pending.error instanceof ApiError && pending.error.status === 404 && pending.error.message === '没有待确认的补章节')) setError(pending.error)
        }
      } catch (reason) { if (active) setError(reason) }
      finally { if (active) setLoading(false) }
    }
    void load()
    return () => { active = false; controller.current?.abort() }
  }, [bookId])

  const refreshBook = () => {
    for (const queryKey of [keys.books, keys.book(bookId), keys.chapters(bookId), keys.outline(bookId), ['workspace', bookId], ['outline-tree', bookId], ['desk-v2-chapter', bookId], ['desk-v2-digest', bookId], ['saves', bookId]]) {
      void queryClient.invalidateQueries({ queryKey })
    }
  }

  const upload = async (file?: File) => {
    if (!file || operating.current) return
    setError(null)
    if (!file.name.toLowerCase().endsWith('.txt')) { setError('只能导入 TXT 文件'); return }
    if (file.size > 52_428_800) { setError('文件超过 50MB'); return }
    operating.current = true
    setBusy('upload')
    setProgress(0)
    const current = new AbortController()
    controller.current = current
    try {
      setPreview(await uploadTeardownAppend(bookId, file, setProgress, current.signal))
      setInclude([])
      refreshBook()
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(reason)
    } finally { operating.current = false; setBusy(null) }
  }

  const switchEncoding = async (encoding: TeardownEncoding) => {
    if (operating.current || !preview) return
    operating.current = true
    setBusy('encoding')
    setEncodingError(null)
    setError(null)
    setConfirmDelete(false)
    try {
      setPreview(await changeTeardownAppendEncoding(bookId, encoding))
      setInclude([])
      setExpandedVolumes(false)
      refreshBook()
    } catch (reason) { setEncodingError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  const appendBook = async (start: boolean) => {
    if (operating.current || !preview || upto === undefined || (start && !model.ready)) return
    operating.current = true
    setBusy(start ? 'start' : 'import')
    setError(null)
    setConfirmDelete(false)
    try {
      const result = await importTeardownAppend(bookId, include, start ? { upto } : undefined)
      queryClient.setQueryData(keys.book(bookId), result)
      refreshBook()
      navigate(`/desk/${bookId}`)
    } catch (reason) { setError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  const cancel = async () => {
    if (operating.current) return
    if (!confirmDelete) { setConfirmDelete(true); return }
    operating.current = true
    setBusy('delete')
    setError(null)
    try {
      await cancelTeardownAppend(bookId)
      refreshBook()
      navigate(`/desk/${bookId}`)
    } catch (reason) { setError(reason) }
    finally { operating.current = false; setBusy(null) }
  }

  return <TeardownPage title={book?.title ?? preview?.title ?? ''} back={{ to: `/desk/${bookId}`, label: '回书页' }}>
    {loading && <div className="flex items-center justify-center gap-2 py-24 text-sm text-ink-3"><Spinner />正在分章……</div>}
    {!loading && !preview && book && last && <>
      <h1 className="font-serif text-3xl font-bold">补后面的章节</h1>
      <p className="mt-4 text-sm leading-relaxed text-ink-3">选后面几章的 TXT 文件，50MB 以内。程序照导入时一样分好章，接在第 {last.index} 章「{last.title}」后面，你看一眼对不对再补上。</p>
      <TeardownFilePicker busy={busy !== null} progress={progress} upload={upload} />
    </>}
    {preview && <form onSubmit={event => { event.preventDefault(); void appendBook(true) }} className="space-y-7">
      {preview.junction.kind === '倒回去了' && <p className="text-sm leading-relaxed text-seal" role="note">{teardownAppendJunctionText(preview)}</p>}
      <h1 className="font-serif text-3xl font-bold">补后面的章节</h1>
      <div className="border-y border-line py-4">
        <p className="text-[15px] leading-relaxed text-ink-2" data-testid="teardown-append-summary">{teardownAppendSplitText(preview, include)}</p>
        {preview.first && preview.last && <p className="mt-2 text-xs leading-relaxed text-ink-3">第 {preview.first.index} 章 {preview.first.title} …… 第 {preview.previous.chapters + added} 章 {preview.last.title}。</p>}
      </div>
      <section aria-label="开头几行原文">
        <div className="rounded-xl border border-line bg-paper/45 px-5 py-4 font-serif text-[15px] leading-[1.95] whitespace-pre-wrap">{preview.opening.split('\n').map((line, index) => <p key={index} className="indent-[2em]">{line || '\u00a0'}</p>)}</div>
        <p className="mt-3 text-xs text-ink-3">看着是乱码？换一种编码：</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5" aria-label="编码">
          {ENCODINGS.map(([encoding, label]) => {
            const selected = encoding === 'auto' ? preview.encoding_auto : !preview.encoding_auto && preview.encoding.toLowerCase() === encoding
            return <Button key={encoding} type="button" size="sm" variant={selected ? 'primary' : 'soft'} aria-pressed={selected} disabled={busy !== null} onClick={() => { void switchEncoding(encoding) }}>{label}</Button>
          })}
          {preview.encoding_auto && <span className="ml-1 text-xs text-ink-3">{preview.encoding}</span>}
          {busy === 'encoding' && <Spinner className="ml-1 size-3.5 text-ink-3" />}
        </div>
        <div role="alert"><ErrorText error={encodingError} /></div>
      </section>
      {notes.length > 0 && <section aria-label="接的地方">
        <h2 className="mb-3 font-serif text-lg font-bold">接的地方</h2>
        <div className="space-y-2 text-sm leading-relaxed text-ink-2">{notes.map((note, index) => <p key={index}>{note}</p>)}</div>
      </section>}
      {preview.previous.original_volumes && preview.volumes.length > 0 && <section aria-label="分卷">
        <h2 className="mb-3 font-serif text-lg font-bold">分卷</h2>
        <div className="space-y-2 text-sm text-ink-2">{(expandedVolumes ? preview.volumes : preview.volumes.slice(0, 8)).map(volume => <p key={volume.index}>{teardownAppendVolumeText(volume)}</p>)}</div>
        {!expandedVolumes && preview.volumes.length > 8 && <button type="button" className="mt-3 text-xs text-ink-3 underline underline-offset-4 hover:text-ink" onClick={() => setExpandedVolumes(true)}>还有 {preview.volumes.length - 8} 卷，展开</button>}
      </section>}
      {preview.excluded.length > 0 && <section>
        <h2 className="mb-3 font-serif text-lg font-bold">这几章看着不像正文，默认不导入</h2>
        <div className="divide-y divide-line rounded-xl border border-line bg-paper/30 px-4">{preview.excluded.map(chapter => <label key={chapter.order} className="flex cursor-pointer items-start gap-3 py-3">
          <input type="checkbox" checked={include.includes(chapter.order)} disabled={busy !== null} className="mt-1 accent-ink" onChange={event => { setInclude(current => event.target.checked ? [...current, chapter.order] : current.filter(order => order !== chapter.order)); setConfirmDelete(false) }} />
          <span className="min-w-0"><span className="text-sm text-ink-2">{chapter.title} · {chapter.chars.toLocaleString('zh-CN')} 字 · {chapter.reason}</span><span className="mt-1 block text-xs leading-relaxed text-ink-3">{chapter.head}</span></span>
        </label>)}</div>
      </section>}
      {preview.number_issues.length > 0 && <section>
        <h2 className="font-serif text-lg font-bold">原书章号对不上的地方</h2>
        <p className="mt-2 text-xs leading-relaxed text-ink-3">不影响导入：章号按顺序从 1 重新编，这里只是让你知道原书哪里缺了、乱了</p>
        <div className="mt-3 space-y-2 text-sm text-ink-2">{preview.number_issues.map((issue, index) => <p key={`${issue.index}:${index}`}>{teardownNumberIssueText(issue)}</p>)}</div>
        {preview.number_issue_total > preview.number_issues.length && <p className="mt-2 text-xs text-ink-3">还有 {preview.number_issue_total - preview.number_issues.length} 处没列</p>}
      </section>}
      <p className="text-xs leading-relaxed text-ink-3">{teardownCleaningText(preview)}</p>
      <TeardownOptions total={total} value={uptoInput} onChange={setUptoInput} disabled={busy !== null} />
      <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-5">
        <Button type="button" variant="ghost" size="lg" disabled={busy !== null} loading={busy === 'delete'} onClick={() => { void cancel() }}>{confirmDelete ? '确定不补了？再点一次' : '不补了'}</Button>
        <Button type="button" variant="outline" size="lg" disabled={busy !== null || upto === undefined} loading={busy === 'import'} onClick={() => { void appendBook(false) }}>先只补上，不拆</Button>
        <Button type="submit" variant="primary" size="lg" disabled={busy !== null || upto === undefined || !model.ready} loading={busy === 'start'}>补上并接着拆</Button>
      </div>
    </form>}
    {!loading && <div role="alert"><ErrorText error={error} /></div>}
  </TeardownPage>
}
