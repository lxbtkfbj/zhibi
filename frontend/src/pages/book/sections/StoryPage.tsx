import { LockKeyhole } from 'lucide-react'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { patch } from '../../../api/client'
import { useUpdateBook } from '../../../api/hooks'
import { useLibrary, useInvalidateLibrary, useRewrite } from '../../../api/library'
import { useBookSettings, settingsKeys } from '../../../api/settings'
import { EditableText } from '../../../components/Editable'
import { RewriteField, TargetHistory } from '../../../components/RewriteField'
import { Button, ErrorText, inputClass } from '../../../components/ui'
import { useBookContext } from '../context'
import { PitchSelection } from '../PitchSelection'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'

export function StoryPage() {
  const { bookId, book, job, manualNavigate } = useBookContext()
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
  return <div data-testid="story-page" className="space-y-6">
    <PageHeader eyebrow="书稿 · 定调" title="这本书的故事" subtitle="先把故事说清楚。想改哪里，就选中哪里；别处只给建议，不替你改。" />
    {job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece' && job.pending.piece === 'settings' && <aside className="rounded-xl border border-chief/20 bg-chief-soft p-4 text-sm"><p>设定库也建好了：{job.pending.summary}</p><Button size="sm" variant="ghost" onClick={() => manualNavigate(`/books/${bookId}/library`)}>去看看</Button>{job.pending.concept_warnings?.map(w => <p key={w} className="text-seal">{w}</p>)}</aside>}
    <section className="rounded-xl border border-line bg-card/50 p-4 @lg/manuscript:p-6" aria-label="定调的一段话">
      <div className="mb-3 flex flex-wrap justify-end gap-2"><Button size="sm" variant="ghost" onClick={() => setDraft(concept.story ?? '')}>自己改</Button><TargetHistory bookId={bookId} targetType="concept" targetId={bookId} /></div>
      {draft !== null ? <form onSubmit={async event => { event.preventDefault(); try { await save({ concept: { story: draft } }); setDraft(null) } catch { /* 保存失败保留作者文本。 */ } }}><textarea autoFocus aria-label="定调的一段话" rows={10} value={draft} onChange={event => setDraft(event.target.value)} className={`${inputClass} leading-loose`} /><div className="mt-3 flex gap-2"><Button type="submit" loading={update.isPending} disabled={!draft.trim() || update.isPending}>保存定调</Button><Button variant="ghost" disabled={update.isPending} onClick={() => setDraft(null)}>取消</Button></div></form>
        : concept.story ? <RewriteField bookId={bookId} targetType="concept" targetId={bookId} path="story" value={concept.story} optionsOnly />
          : <div className="space-y-4"><p className="font-serif text-lg">这本书开书时还没有一段话的定调</p><dl className="space-y-3 text-sm">{[['一句话故事', concept.logline], ['核心卖点', concept.selling_points?.join('；')], ['核心循环', concept.core_loop]].map(([label, value]) => value && <div key={label}><dt className="mb-1 text-ink-2">{label}</dt><dd className="whitespace-pre-wrap leading-relaxed">{value}</dd></div>)}</dl><Button variant="soft" loading={rewrite.isPending} onClick={() => rewrite.mutate({ target_type: 'concept', target_id: bookId, path: 'story', mode: 'instruction', instruction: '按书的概念和设定库，写一段话的定调' })}>让主编按现有内容写一段</Button></div>}
      <ErrorText error={update.error ?? rewrite.error} />
    </section>
    {concept.secret_entry_id ? <button className="flex w-full items-start gap-2 rounded-xl border border-line bg-paper-2 p-4 text-left text-sm leading-relaxed hover:border-chief/40" onClick={() => manualNavigate(`/books/${bookId}/library?cat=${encodeURIComponent('往事与秘密')}&id=${concept.secret_entry_id}`)}><LockKeyhole className="mt-0.5 size-4 shrink-0" /><span>底牌（只有你和编辑部知道）：{secret?.content || secret?.one_line || '正在读取底牌…'}</span></button> : <p className="flex gap-2 text-sm text-ink-2"><LockKeyhole className="size-4" />这本书没有底牌</p>}
    <section aria-label="基本信息" className="rounded-xl border border-line bg-card/40 p-4"><h2 className="mb-4 font-serif text-lg">基本信息</h2><dl className="grid gap-x-6 gap-y-3 @xl/manuscript:grid-cols-2">{[
      ['书名', <EditableText key="title" value={book.title} onSave={title => save({ title })} />], ['类型', text('genre')],
      ['篇幅（万字）', <EditableText key="length" value={String(concept.target_length ?? '')} onSave={value => save({ concept: { target_length: numeric(value) } })} />],
      ['每章字数', <EditableText key="words" value={String(settings.data?.settings.chapter_words ?? concept.chapter_words ?? 3000)} onSave={value => chapterWords.mutateAsync(numeric(value))} />],
      ['基调与文风', text('tone')], ['目标读者', text('target_reader')],
    ].map(([label, editor], index) => <div key={index} className="grid min-w-0 grid-cols-[6rem_minmax(0,1fr)] items-start gap-2 text-sm"><dt className="pt-1 text-ink-2">{label}</dt><dd>{editor}</dd></div>)}</dl><ErrorText error={chapterWords.error ?? settings.error} /></section>
    <SetupGate piece="concept" />
  </div>
}
