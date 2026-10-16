import { useUpdateBook } from '../../../api/hooks'
import { useBookSettings } from '../../../api/settings'
import type { Concept } from '../../../api/types'
import { EditableList, EditableText } from '../../../components/Editable'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, QuestionField, QuestionSection } from '../../../components/QuestionSection'
import { StageLadder } from '../../../components/StageLadder'
import { Badge, ErrorText, Reveal } from '../../../components/ui'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
import { Locked, PageHeader } from './common'

export function ConceptPage() {
  const { book, bookId, working, job } = useBookContext()
  const update = useUpdateBook(bookId)
  const settings = useBookSettings(bookId)
  const concept = book.concept
  const pending = job?.status === 'waiting_author' ? job.pending : null
  const save = (patch: Partial<Concept>) => update.mutateAsync({ concept: patch })
  // 估算使用同一张表里可编辑的概念值，不拿已规划的第一段章数冒充全书。
  const chapterWords = concept.chapter_words
  const chapters = concept.target_length && chapterWords ? Math.round(concept.target_length * 10000 / chapterWords) : 0
  const person = settings.data ? { first: '第一人称', second: '第二人称', third: '第三人称' }[settings.data.settings.person] : '读取中'
  const text = (key: keyof Concept, placeholder?: string) => <EditableText value={String(concept[key] ?? '')} onSave={value => save({ [key]: value })} locked={working} multiline placeholder={placeholder} />
  const number = (key: 'target_length' | 'target_volumes' | 'chapter_words') => <EditableText value={String(concept[key] ?? '')} locked={working} onSave={value => {
    const parsed = Number(value)
    if (!value.trim() || !Number.isSafeInteger(parsed) || parsed <= 0) return Promise.reject(new Error('请填写大于 0 的整数'))
    return save({ [key]: parsed })
  }} />
  const title = <EditableText value={concept.title ?? book.title} onSave={title => update.mutateAsync({ title })} locked={working} />

  if (!concept.title) return <PageHeader eyebrow="书的概念" title="主编还在构思" subtitle="概念定下来之后会出现在这里。" />

  return <div>
    <PageHeader eyebrow="书的概念" title={title} subtitle={<div className="flex flex-wrap items-center gap-1.5">
      {concept.genre && <Badge tone="busy">{concept.genre}</Badge>}{concept.tags?.map((tag, index) => <Badge key={`${index}-${tag}`}>{tag}</Badge>)}
    </div>} />
    <PieceDecisions piece="concept" />
    <FocusQuestions piece="concept" />
    <Locked locked={working} />
    <Reveal>
      <QuestionSection piece="concept" questionKey="positioning" pending={pending}>
        <FactTable rows={[
          { label: '题材', value: text('genre') },
          { label: '标签', value: <EditableList items={concept.tags ?? []} onSave={tags => save({ tags })} locked={working} /> },
          { label: '写给谁', value: text('target_reader') },
          { label: '对标', value: text('benchmark', '没有对标作品') },
        ]} />
      </QuestionSection>
      <QuestionSection piece="concept" questionKey="logline" pending={pending}>
        <EditableText value={concept.logline ?? ''} onSave={logline => save({ logline })} locked={working} multiline className="font-serif text-xl" inputClassName="font-serif text-xl" />
      </QuestionSection>
      <QuestionSection piece="concept" questionKey="selling_points" pending={pending}><EditableList items={concept.selling_points ?? []} onSave={selling_points => save({ selling_points })} locked={working} /></QuestionSection>
      <QuestionSection piece="concept" questionKey="core_loop" pending={pending}>{text('core_loop')}</QuestionSection>
      <QuestionSection piece="concept" questionKey="tone" pending={pending}>
        {text('tone')}<p className="text-xs text-ink-2">人称：{person}（在本书设置里改）</p><ErrorText error={settings.error} />
      </QuestionSection>
      <QuestionSection piece="concept" questionKey="length_title" pending={pending}>
        <FactTable rows={[
          { label: '全书篇幅（万字）', value: number('target_length') },
          { label: '粗估卷数', value: number('target_volumes') },
          { label: '每章字数', value: number('chapter_words') },
          { label: '书名', value: title },
          { label: '备选书名', value: <EditableList items={concept.alt_titles ?? []} onSave={alt_titles => save({ alt_titles })} locked={working} /> },
        ]} />
        <QuestionField label="舞台阶梯"><StageLadder value={concept.stage_ladder ?? ''} onSave={stage_ladder => save({ stage_ladder })} locked={working} /></QuestionField>
        {!!chapters && <p className="border-t border-dashed border-line pt-4 text-xs text-ink-2" data-testid="chapter-estimate">按每章约 {chapterWords} 字估算，全书约 {chapters} 章。</p>}
      </QuestionSection>
      {concept.protagonist_hook && !Object.keys(book.protagonist ?? {}).length && <section className="border-t border-line py-6"><h2 className="mb-3 font-serif text-lg">主角钩子（旧版概念）</h2><p className="text-[15px] leading-relaxed whitespace-pre-wrap">{concept.protagonist_hook}</p></section>}
    </Reveal>
    {book.idea && <p className="mt-7 border-t border-line pt-5 text-sm leading-relaxed whitespace-pre-wrap text-ink-2">作者最初的点子：{book.idea}</p>}
  </div>
}
