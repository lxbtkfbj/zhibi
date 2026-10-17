import { useState } from 'react'
import { useChapters, useJobActions, useNodes, useUpdateBook } from '../../api/hooks'
import { useChooseLibraryCandidate, useLibrary, useLibraryCandidates, useLibrarySuggestions } from '../../api/library'
import type { LibraryItem, LibrarySnapshot } from '../../api/library'
import { Button, ErrorText, inputClass } from '../../components/ui'
import { useBookContext } from './context'
import { Decisions } from './PieceDecisions'
import { FieldBlock, PageHeader } from './sections/common'

/** 只接通任务 3 的三步；完整设定库编辑器和大纲树操作留在任务 4。 */
export function ThreeStepSetup({ piece }: { piece: 'concept' | 'settings' | 'outline' }) {
  const { book, bookId, job, working, outline } = useBookContext()
  const library = useLibrary(bookId)
  const { data: nodes = [] } = useNodes(bookId)
  const { data: chapters = [] } = useChapters(bookId)
  const { pieceAction, setupPending } = useJobActions(bookId)
  const pending = job?.pending?.kind === 'setup_piece' && job.pending.piece === piece ? job.pending : null
  const title = { concept: '定调', settings: '设定库', outline: '大纲' }[piece]
  return <section data-testid={`three-step-${piece}`} className="space-y-6">
    <PageHeader eyebrow="开书三步 · 简版" title={title} subtitle={working ? '编辑部正在完善，已保存的内容会陆续出现在这里。' : '三步都能回头看；回头修改不会推倒后面的内容。'} />
    {piece === 'concept' && <ConceptDraft secret={library.data?.entries.find(item => item.id === book.concept.secret_entry_id)?.content} />}
    {piece === 'settings' && <LibraryDraft library={library.data} summary={pending?.summary} />}
    {piece === 'outline' && <div className="space-y-5" aria-label="篇卷单元与章纲">
      {nodes.filter(node => node.kind === 'milestone').map((arc, index) => <section key={arc.id} className="rounded-xl border border-line bg-card p-4">
        <h2 className="font-serif text-lg font-bold">第 {index + 1} 篇 · {arc.title}{!arc.segment && <span className="ml-2 font-sans text-xs font-normal text-ink-2">写到再定</span>}</h2>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{arc.segment?.text || arc.event}</p>
        {(outline?.volumes ?? []).filter(volume => volume.target_node_id === arc.id).map(volume => <section key={volume.id} className="mt-4 border-l-2 border-chief/25 pl-4">
          <h3 className="font-medium">第 {volume.index} 卷 · {volume.title}<span className="ml-2 text-xs text-ink-2">约 {volume.chapter_count} 章</span></h3><p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{volume.summary}</p>
          {volume.units.map(unit => <section key={unit.id} className="mt-4 border-l border-line pl-4"><h4 className="text-sm font-medium">单元 {unit.index} · {unit.title}<span className="ml-2 font-normal text-ink-2">{unit.chapter_count} 章</span></h4><p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-ink-2">{unit.summary}</p><ul className="mt-2 space-y-1 border-l border-line pl-4 text-sm text-ink-2">{chapters.filter(chapter => chapter.unit_id === unit.id).map(chapter => <li key={chapter.id}>第 {chapter.index} 章 · {chapter.outline?.title || chapter.title}</li>)}</ul></section>)}
        </section>)}
      </section>)}
      <FieldBlock label="结局">{nodes.find(node => node.kind === 'ending')?.event || '正在准备…'}</FieldBlock>
    </div>}
    {!!pending?.decisions?.length && <Decisions key={`${job?.id}-${pending.round}`} decisions={pending.decisions} name={`three-step-${piece}`} disabled={setupPending} loading={pieceAction.isPending} error={pieceAction.error} onRevise={flips => job && pieceAction.mutate({ jobId: job.id, action: 'revise', piece, flips })} />}
    <ErrorText error={library.error} />
  </section>
}

function ConceptDraft({ secret }: { secret?: string }) {
  const { bookId, book, working } = useBookContext()
  const update = useUpdateBook(bookId)
  const [draft, setDraft] = useState<string | null>(null)
  const concept = book.concept
  const save = async () => { if (draft === null) return; try { await update.mutateAsync({ concept: { story: draft } }); setDraft(null) } catch { /* 原文保留，显示错误。 */ } }
  return <div className="space-y-6">
    <FieldBlock label="这本书的故事">{draft === null ? <><p className="whitespace-pre-wrap leading-loose">{concept.story || '主编正在展开定调…'}</p>{concept.story && <Button variant="ghost" size="sm" className="mt-2" onClick={() => setDraft(concept.story!)} disabled={working}>改这一段</Button>}</> : <><textarea aria-label="定调的一段话" rows={9} className={inputClass} value={draft} onChange={event => setDraft(event.target.value)} /><div className="mt-2 flex gap-2"><Button size="sm" loading={update.isPending} disabled={!draft.trim() || working} onClick={() => void save()}>保存定调</Button><Button size="sm" variant="ghost" disabled={update.isPending} onClick={() => setDraft(null)}>取消</Button></div></>}</FieldBlock>
    <FieldBlock label="底牌 · 只有作者和编辑部知道"><p className="whitespace-pre-wrap">{secret || (concept.secret_entry_id ? '正在读取底牌…' : '没有')}</p></FieldBlock>
    <section aria-label="基本信息" className="rounded-xl border border-line bg-card p-4"><h2 className="mb-3 font-serif font-bold">基本信息</h2><dl className="space-y-3 text-sm">{[
      ['书名', concept.title], ['备选书名', concept.alt_titles?.join('、')], ['类型', concept.genre], ['标签', concept.tags?.join('、')], ['篇幅', concept.target_length ? `${concept.target_length} 万字` : ''], ['每章字数', concept.chapter_words ? `${concept.chapter_words} 字` : ''], ['基调与文风', concept.tone], ['目标读者', concept.target_reader],
    ].map(([label, value]) => value && <div key={label} className="grid grid-cols-[6rem_1fr] gap-3"><dt className="text-ink-2">{label}</dt><dd className="whitespace-pre-wrap leading-relaxed">{value}</dd></div>)}</dl></section>
    <ErrorText error={update.error} />
  </div>
}

function LibraryDraft({ library, summary }: { library?: LibrarySnapshot; summary?: string }) {
  const { bookId, working } = useBookContext()
  const suggestions = useLibrarySuggestions(bookId)
  const candidates = useLibraryCandidates(bookId, library)
  const choose = useChooseLibraryCandidate(bookId)
  const list = (items: LibraryItem[]) => <ul className="space-y-3">{items.map(item => <li key={item.id} className="text-sm leading-relaxed"><span className="font-medium">{item.name}</span>{item.one_line && <span className="text-ink-2">：{item.one_line}</span>}</li>)}</ul>
  const focusCharacters = library?.characters.filter(item => library.focus.characters.includes(item.id)) ?? []
  const focusEntries = library?.entries.filter(item => library.focus.entries.includes(item.id)) ?? []
  return <div className="space-y-6">
    <section aria-label="设定库总结" className="rounded-xl border border-chief/20 bg-chief-soft/40 p-4"><p className="text-sm leading-relaxed">{summary || (working ? '重点先出来，其余设定正在补。' : '设定库已保存，先看「重点」就行。')}</p><p className="mt-2 text-sm font-medium text-chief">待处理的建议：{library?.suggestions_pending ?? 0} 条</p></section>
    <section aria-label="重点" className="rounded-xl border border-line bg-card p-4"><h2 className="mb-3 font-serif text-lg font-bold">重点</h2>{list([...focusCharacters, ...focusEntries])}</section>
    {(candidates.data ?? []).map(group => <section key={group.name} aria-label={`${group.name}的候选写法`} className="rounded-xl border border-chief/30 p-4"><h2 className="mb-3 font-medium">{group.name} · 候选写法</h2>{group.candidates.map(candidate => <div key={candidate.id} className="space-y-3">{candidate.options.map((option, index) => <div key={index} className="rounded-lg border border-line bg-card p-3"><h3 className="text-sm font-medium">{option.label || `写法 ${index + 1}`}{index === 0 && <span className="ml-2 text-xs text-chief">推荐</span>}{candidate.chosen === index && <span className="ml-2 text-xs text-lore">已采用</span>}</h3><p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{option.text}</p><Button className="mt-2" size="sm" variant="ghost" disabled={working || choose.isPending || candidate.chosen === index} onClick={() => choose.mutate({ id: candidate.id, index })}>采用这个写法</Button></div>)}</div>)}</section>)}
    {(library?.categories ?? []).map((category, index) => <section key={category.key} aria-label={`类别：${category.name}`} className="border-t border-line pt-4"><h2 className="mb-3 font-serif text-lg font-bold">{category.name}<span className="ml-2 font-sans text-xs font-normal text-ink-2">{category.count} 条</span></h2>{list(index === 0 ? library!.characters : library!.entries.filter(item => item.category === category.key))}</section>)}
    {!!suggestions.data?.length && <section aria-label="待处理的建议" className="rounded-xl border border-line bg-card p-4"><h2 className="mb-3 font-medium">待处理的建议</h2><ul className="space-y-2 text-sm leading-relaxed">{suggestions.data.map(suggestion => <li key={suggestion.id}>{suggestion.title}</li>)}</ul></section>}
    <ErrorText error={suggestions.error ?? candidates.error ?? choose.error} />
  </div>
}
