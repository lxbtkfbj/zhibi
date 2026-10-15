import { useOutline, useUpdateBook } from '../../../api/hooks'
import type { Concept } from '../../../api/types'
import { EditableList, EditableText } from '../../../components/Editable'
import { Badge, Reveal } from '../../../components/ui'
import { totalChapters } from '../../../lib/status'
import { useBookContext } from '../context'
import { FieldBlock, Locked, PageHeader } from './common'

export function ConceptPage() {
  const { book, bookId, working } = useBookContext()
  const update = useUpdateBook(bookId)
  const { data: outline } = useOutline(bookId)
  const concept = book.concept
  const chapters = totalChapters(concept, outline?.volumes ?? [])
  const save = (patch: Partial<Concept>) => update.mutateAsync({ concept: patch })

  if (!concept.title) {
    return <PageHeader eyebrow="书的概念" title="主编还在构思" subtitle="概念定下来之后会出现在这里。" />
  }

  return (
    <div>
      <PageHeader
        eyebrow="书的概念"
        title={
          <EditableText
            value={concept.title ?? ''}
            onSave={(title) => update.mutateAsync({ title })}
            locked={working}
            inputClassName="font-serif text-[26px] font-bold"
          />
        }
        subtitle={
          <div className="flex flex-wrap items-center gap-1.5">
            {concept.genre && <Badge tone="busy">{concept.genre}</Badge>}
            {concept.tags?.map((t) => (
              <Badge key={t}>{t}</Badge>
            ))}
            {concept.alt_titles && concept.alt_titles.length > 0 && (
              <span className="ml-2 text-sm text-ink-2">备选书名：{concept.alt_titles.join(' / ')}</span>
            )}
          </div>
        }
      />
      <Locked locked={working} />
      <Reveal>
        <section className="pb-7">
          <FieldBlock label="一句话简介">
            <EditableText
              value={concept.logline ?? ''}
              onSave={(logline) => save({ logline })}
              locked={working}
              multiline
              className="font-serif text-xl leading-relaxed"
              inputClassName="font-serif text-xl"
            />
          </FieldBlock>
          <div className="my-7 h-px bg-line" />
          <div className="grid gap-7 @2xl/manuscript:grid-cols-2">
            <FieldBlock label="核心卖点">
              <EditableList items={concept.selling_points ?? []} onSave={(selling_points) => save({ selling_points })} locked={working} />
            </FieldBlock>
            <div className="space-y-7">
              <FieldBlock label="主角钩子">
                <EditableText value={concept.protagonist_hook ?? ''} onSave={(protagonist_hook) => save({ protagonist_hook })} locked={working} multiline />
              </FieldBlock>
              <FieldBlock label="基调与文风">
                <EditableText value={concept.tone ?? ''} onSave={(tone) => save({ tone })} locked={working} multiline />
              </FieldBlock>
              <FieldBlock label="篇幅">
                <span className="text-ink-2">
                  {concept.target_length ? `全书约 ${concept.target_length} 万字，` : ''}计划 {concept.target_volumes ?? '-'} 卷，每章约 {concept.chapter_words ?? '-'} 字
                  {chapters > 0 && `，合计约 ${chapters} 章`}
                </span>
              </FieldBlock>
            </div>
          </div>
        </section>
      </Reveal>
      {book.idea && (
        <Reveal delay={0.08}>
          <p className="mt-6 text-sm leading-relaxed text-ink-2">作者最初的点子：{book.idea}</p>
        </Reveal>
      )}
    </div>
  )
}
