import { Lightbulb, ListChecks, LockKeyhole, MessageCircleQuestion, PenLine } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { patch } from '../../../api/client'
import { useUpdateBook } from '../../../api/hooks'
import { useLibrary, useInvalidateLibrary, useRewrite } from '../../../api/library'
import { useAuthorRequirements, useBookSettings, settingsKeys } from '../../../api/settings'
import { EditableText } from '../../../components/Editable'
import { RewriteField, TargetHistory } from '../../../components/RewriteField'
import { Button, ErrorText, inputClass, Skeleton } from '../../../components/ui'
import { cleanTitle } from '../../../lib/status'
import { directionProgressText } from '../../../lib/workspace'
import { useBookContext } from '../context'
import { InterviewForm } from '../Decision'
import { PitchSelection } from '../PitchSelection'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'

/** 作者自己交代的写作要求（开书时选方向、篇幅这类回答不列）。 */
function Requirements() {
  const { bookId } = useBookContext()
  const { data } = useAuthorRequirements(bookId)
  const rows = (data ?? []).filter(row => row.active && row.source !== 'answer')
  if (!rows.length) return null
  return <section aria-label="你的写作要求" className="rounded-2xl border border-line bg-card px-6 py-5 shadow-[var(--shadow-paper)]">
    <h2 className="mb-3 flex items-center gap-2 text-[13px] font-normal text-ink-3"><ListChecks className="size-4" />你的写作要求<span className="ml-auto"><Link to={`/books/${bookId}/settings`} className="text-chief hover:underline">在本书设置里管理</Link></span></h2>
    <ul className="space-y-2">{rows.slice(0, 6).map(row => <li key={row.id} className="flex gap-3 text-sm leading-relaxed"><span className="mt-0.5 shrink-0 rounded bg-subtle px-1.5 text-xs leading-5 text-ink-2 ring-1 ring-line">{row.label || '一直有效'}</span><span className="min-w-0">{row.text}</span></li>)}</ul>
    {rows.length > 6 && <p className="mt-2 text-xs text-ink-3">还有 {rows.length - 6} 条，在本书设置里看。</p>}
  </section>
}

export function StoryPage() {
  const { bookId, book, job, messages, manualNavigate } = useBookContext()
  const library = useLibrary(bookId)
  const settings = useBookSettings(bookId)
  const update = useUpdateBook(bookId)
  const rewrite = useRewrite(bookId)
  const invalidate = useInvalidateLibrary(bookId)
  const qc = useQueryClient()
  const [draft, setDraft] = useState<string | null>(null)
  const chapterWords = useMutation({ mutationFn: (value: number) => patch(`/books/${bookId}/settings`, { chapter_words: value }), onSuccess: async () => { await qc.invalidateQueries({ queryKey: settingsKeys.book(bookId) }); await invalidate() } })
  const save = async (body: Parameters<typeof update.mutateAsync>[0]) => { await update.mutateAsync(body); await invalidate() }
  const concept = book.concept
  const secret = library.data?.entries.find(item => item.id === concept.secret_entry_id)
  const numeric = (value: string) => { const number = Number(value); if (!value.trim() || !Number.isSafeInteger(number) || number <= 0) throw new Error('请填写大于 0 的整数'); return number }
  const text = (key: 'genre' | 'tone' | 'target_reader') => <EditableText value={concept[key] ?? ''} multiline onSave={value => save({ concept: { [key]: value } })} />
  if (job?.status === 'waiting_author' && job.pending?.kind === 'setup_pitches') return <PitchSelection key={`${job.id}-${job.pending.round}`} job={job} pending={job.pending} />
  const title = cleanTitle(book.title)
  const meta = [concept.genre, ...(concept.tags ?? []).slice(0, 3), concept.target_length ? `约 ${concept.target_length} 万字` : ''].filter(Boolean).join(' · ')
  const drafting = job?.kind === 'book_setup' && ['queued', 'running'].includes(job.status) && !concept.story
  return <div data-testid="story-page" className="mx-auto max-w-[1320px]">
    {job?.status === 'waiting_author' && job.pending?.kind === 'setup_questions' && <section className="mb-8 rounded-2xl border border-line bg-card p-6 shadow-[var(--shadow-paper)]">
      <p className="mb-2 flex items-center gap-1.5 text-[13px] text-chief"><MessageCircleQuestion className="size-4" />动笔之前</p>
      <h2 className="font-serif text-xl font-bold">主编想先跟你对几件事</h2>
      <p className="mt-2 mb-6 text-[15px] leading-relaxed text-ink-2">已替你选好推荐答案，改你想改的就行；再点一次可以取消，交给编辑部决定。</p>
      <InterviewForm job={job} questions={job.pending.questions} />
    </section>}
    <SetupGate piece="concept" />
    <PageHeader eyebrow="书稿 · 定调" title={title && title !== '未命名' ? title : '定调'} subtitle={meta || '一段话说清这本书。想改哪里就选中哪里；别处只给建议，不替你改。'}
      action={concept.story && draft === null ? <><Button size="sm" variant="outline" onClick={() => setDraft(concept.story ?? '')}><PenLine className="size-3.5" />自己改</Button><TargetHistory bookId={bookId} targetType="concept" targetId={bookId} /></> : undefined} />
    <div className="grid items-start gap-8 @5xl/manuscript:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0 space-y-5">
        {drafting ? <section className="rounded-2xl border border-line bg-card p-8 shadow-[var(--shadow-paper)]" role="status">
          <p className="mb-5 flex items-center gap-2 text-sm text-chief"><span className="size-2 rounded-full bg-chief motion-safe:animate-pulse" />{job ? directionProgressText(job.id, messages) : '主编正在写…'}</p>
          <Skeleton className="h-4 w-11/12" /><Skeleton className="mt-3 h-4 w-full" /><Skeleton className="mt-3 h-4 w-4/5" />
        </section>
          : <section aria-label="定调的一段话" className="rounded-2xl border border-line bg-card px-6 py-6 shadow-[var(--shadow-paper)] @3xl/manuscript:px-9 @3xl/manuscript:py-8">
            <p className="mb-4 flex items-center gap-2 text-[13px] text-ink-3"><Lightbulb className="size-4" />一段话说清这本书</p>
            {draft !== null ? <form onSubmit={async event => { event.preventDefault(); try { await save({ concept: { story: draft } }); setDraft(null) } catch { /* 保存失败保留作者文本。 */ } }}><textarea autoFocus aria-label="定调的一段话" rows={12} value={draft} onChange={event => setDraft(event.target.value)} className={`${inputClass} font-serif text-[17px] leading-loose`} /><div className="mt-3 flex gap-2"><Button type="submit" variant="primary" loading={update.isPending} disabled={!draft.trim() || update.isPending}>保存定调</Button><Button variant="ghost" disabled={update.isPending} onClick={() => setDraft(null)}>取消</Button></div></form>
              : concept.story ? <div className="font-serif text-[17px] [&_[data-selectable-text]]:text-[17px] [&_[data-selectable-text]]:leading-[2.05]"><RewriteField bookId={bookId} targetType="concept" targetId={bookId} path="story" value={concept.story} optionsOnly /></div>
                : <div className="space-y-4"><p className="font-serif text-lg">还没有定调</p><p className="text-sm leading-relaxed text-ink-2">在左边群聊里说你想写什么，聊定了让主编「总结一下」再「按这个来」，就会写到这里；也可以自己写。</p>
                  {(concept.logline || concept.core_loop) && <dl className="space-y-3 text-sm">{[['一句话故事', concept.logline], ['核心卖点', concept.selling_points?.join('；')], ['核心循环', concept.core_loop]].map(([label, value]) => value && <div key={label}><dt className="mb-1 text-ink-3">{label}</dt><dd className="whitespace-pre-wrap leading-relaxed">{value}</dd></div>)}</dl>}
                  <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => setDraft('')}><PenLine className="size-3.5" />自己写</Button>{(concept.logline || library.data?.characters.length) ? <Button variant="outline" size="sm" loading={rewrite.isPending} onClick={() => rewrite.mutate({ target_type: 'concept', target_id: bookId, path: 'story', mode: 'instruction', instruction: '按书的概念和设定库，写一段话的定调' })}>让主编按现有内容写一段</Button> : null}</div></div>}
            <ErrorText error={update.error ?? rewrite.error} />
          </section>}
        {concept.secret_entry_id ? <button className="flex w-full items-start gap-4 rounded-2xl bg-[#2f2a25] p-5 text-left text-[#efe7d8] transition-colors hover:bg-[#38322c]" onClick={() => manualNavigate(`/books/${bookId}/library?cat=${encodeURIComponent('往事与秘密')}&id=${concept.secret_entry_id}`)}>
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-[#463f37]"><LockKeyhole className="size-4" /></span>
          <span className="min-w-0"><span className="block text-[13px] text-[#b7ad9b]">底牌 · 只有你和编辑部知道{secret?.locked ? ' · 已锁住' : ''}</span><span className="mt-1 block text-[15px] leading-relaxed">{secret?.content || secret?.one_line || '正在读取底牌…'}</span></span>
        </button> : concept.story ? <p className="flex items-center gap-2 text-[13px] text-ink-3"><LockKeyhole className="size-3.5" />这本书还没有底牌</p> : null}
        <Requirements />
      </div>
      <aside aria-label="基本信息" className="rounded-2xl border border-line bg-card p-5 shadow-[var(--shadow-paper)] @5xl/manuscript:sticky @5xl/manuscript:top-0">
        <h2 className="mb-2 text-[13px] font-normal text-ink-3">基本信息</h2>
        <dl className="divide-y divide-line">{[
          ['书名', <EditableText key="title" value={book.title} onSave={value => save({ title: value })} />], ['类型', text('genre')],
          ['篇幅（万字）', <EditableText key="length" value={String(concept.target_length ?? '')} onSave={value => save({ concept: { target_length: numeric(value) } })} />],
          ['每章字数', <EditableText key="words" value={String(settings.data?.settings.chapter_words ?? concept.chapter_words ?? 3000)} onSave={value => chapterWords.mutateAsync(numeric(value))} />],
          ['基调与文风', text('tone')], ['目标读者', text('target_reader')],
        ].map(([label, editor], index) => <div key={index} className="grid min-w-0 grid-cols-[5.5rem_minmax(0,1fr)] items-start gap-2 py-2.5 text-sm"><dt className="pt-1 text-ink-3">{label}</dt><dd className="min-w-0">{editor}</dd></div>)}</dl>
        <ErrorText error={chapterWords.error ?? settings.error} />
      </aside>
    </div>
  </div>
}
