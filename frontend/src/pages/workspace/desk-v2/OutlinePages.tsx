/* oxlint-disable react/only-export-components -- 大纲和正文共用的纯取数及排版工具。 */
import { useQuery } from '@tanstack/react-query'
import { createElement, type CSSProperties, type ReactNode, useEffect, useState } from 'react'
import { get } from '../../../api/client'
import type { TeardownChapterData } from '../../../api/types'
import { readingChapterNumber } from '../../../lib/teardownReading'
import { childKind, useSave, useWorkspace } from '../actions'
import { CountField, WriteHelp } from '../Workspace'
import { PendingNote } from '../Inbox'
import { GateCard, type ManuscriptNav } from '../Manuscript'
import { chapterNodes, cn, findEntry, findNode, splitTitle, type VBook, type VNode } from '../model'
import { SplitPanel } from '../Split'
import { useSplit } from '../useSplit'
import { gateTarget, type ChapterDetail, type WritingControl } from '../writing'
import { Chip, Icon, More, clean } from './shared'

export interface DeskDigest {
  people: { name: string; chapters: number; first: number }[]
  things: { chapter: number; kind: string; name: string; note: string; belongs?: string; secret?: string }[]
  waits: { chapter: number; action: string; what: string }[]
  hero: string | null
  changes: { chapter: number; change: string }[]
}

export const nodeName = (node: VNode) => splitTitle(node.title)[1] || splitTitle(node.title)[0]
export const editableNodeName = (node: VNode) => node.title.includes('　') ? splitTitle(node.title)[1] : nodeName(node)
export const nodePrefix = (node: VNode) => splitTitle(node.title)[0]
export const rangeLength = (node: VNode) => node.range ? node.range[1] - node.range[0] + 1 : node.chapters ?? 0
export const chapterKind = (value: string) => value.includes('：') ? value.slice(0, value.indexOf('：')) : ''
export const chapterRest = (value: string) => value.includes('：') ? value.slice(value.indexOf('：') + 1) : value
export const outlineOf = (node: VNode) => {
  const happen = node.sections?.find(field => field.label === '发生什么')?.text ?? node.text
  const [goal = '', ...scenes] = happen.split('\n').filter(Boolean)
  return {
    goal, scenes,
    cool: node.sections?.find(field => field.label === '看点')?.text ?? '',
    hook: node.sections?.find(field => field.label === '结尾钩子')?.text ?? '',
  }
}

/** 默认画的就是样张标签；进入手改时才临时换为输入框。 */
export function NodeEdit({ as = 'p', className, style, value, children, save, label, spot, spotOffset }: {
  as?: 'h1' | 'p' | 'div' | 'span'; className?: string; style?: CSSProperties; value: string; children?: ReactNode
  save?: (value: string) => void; label?: string; spot?: string; spotOffset?: number
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  if (editing && save) return <textarea autoFocus aria-label={label} value={draft} rows={as === 'h1' ? 1 : 4}
    onChange={event => setDraft(event.target.value)} onBlur={() => { setEditing(false); if (draft !== value) save(draft) }}
    onKeyDown={event => { if (event.key === 'Escape') { setEditing(false); setDraft(value) } }} />
  return createElement(as, {
    className, style: spot ? { ...style, whiteSpace: 'pre-wrap' } : style,
    // 拖选正文时保留原来的 DOM 和选区，交给 SelectionActions；单击才进入手改。
    onClick: save ? () => { const selection = window.getSelection(); if (selection && !selection.isCollapsed && selection.toString().trim()) return; setDraft(value); setEditing(true) } : undefined,
    'data-editable': save ? label : undefined,
    'data-spot': spot,
    'data-spot-offset': spotOffset,
  }, children ?? value)
}

export function ChapterFoot({ book, node, nav, manuscript = false, unfinished = false }: {
  book: VBook; node: VNode; nav: ManuscriptNav; manuscript?: boolean; unfinished?: boolean
}) {
  const chapters = chapterNodes(book.outline), at = chapters.findIndex(chapter => chapter.id === node.id)
  const previous = chapters[at - 1], next = chapters[at + 1]
  const open = (target: VNode) => manuscript ? nav.openChapter(target.id) : nav.openNode(target.id)
  return <div className="foot" style={manuscript ? { marginTop: 'auto' } : undefined}>
    {previous ? <a onClick={() => open(previous)}><Icon name="l" /><small>上一章</small>第 {readingChapterNumber(previous)} 章 {nodeName(previous)}</a> : <span />}
    {next ? <a onClick={() => open(next)}><small>下一章</small>第 {readingChapterNumber(next)} 章{unfinished ? '' : ` ${nodeName(next)}`}<Icon name="r" /></a> : <span />}
  </div>
}

export function useDeskChapter(book: VBook, node: VNode | undefined, writing?: WritingControl) {
  return useQuery<ChapterDetail>({
    queryKey: ['desk-v2-chapter', book.id, node?.id, node?.body?.words, node?.teardown?.read],
    queryFn: async () => writing?.loadChapter
      ? writing.loadChapter(node!)
      : get<{ content: string; teardown?: TeardownChapterData }>(`/books/${book.id}/chapters/${node!.ref!.id}`).then(result => ({ text: result.content, teardown: result.teardown })),
    enabled: !!node && node.kind === '章' && !!node.ref && (book.source === 'teardown' || node.body?.text === undefined && node.body?.status !== 'planned'),
    retry: false,
  })
}

function DigestRail({ node, digest, nav, book }: { node: VNode; digest?: DeskDigest; nav: ManuscriptNav; book: VBook }) {
  if (!digest || !digest.people.length && !digest.changes.length && !digest.waits.length && !digest.things.length) return null
  const volume = node.kind === '卷', people = volume ? digest.people.slice(0, 8) : digest.people
  const entries = book.categories.flatMap(category => category.entries)
  const openPerson = (name: string) => { const entry = entries.find(item => item.name === name || item.facts.some(([label, value]) => label === '别名' && value.split('、').includes(name))); if (entry) nav.openEntry(entry.id) }
  const person = (item: DeskDigest['people'][number]) => <li key={item.name}>
    <span className="nm" onClick={() => openPerson(item.name)}>{item.name}</span><span className="ct">{item.chapters} 章</span>
    <span className="bar"><b style={{ width: `${item.chapters / (volume ? people[0]?.chapters || 1 : rangeLength(node) || 1) * 100}%` }} /></span>
  </li>
  return <aside className="rail">
    {!!people.length && <div className="rb"><h3>{volume ? '这一卷的人' : '这一单元的人'}<span className="n">出场章数</span></h3><ul className="plist">
      {volume ? people.map(person) : <More items={people} cap={6} unit="人">{person}</More>}
    </ul></div>}
    {volume ? !!digest.changes.length && <div className="rb"><h3>主角这一卷怎么变的<span className="n">{digest.changes.length} 条，框里往下翻</span></h3><ul className="tl scrollbox">
      {digest.changes.map((item, index) => <li key={index}><b onClick={() => nav.openNode(`c${item.chapter}`)}>第 {item.chapter} 章</b>{item.change}</li>)}
    </ul></div> : <>
      {!!digest.waits.length && <div className="rb"><h3>读者在等的事<span className="n">{digest.waits.length} 条</span></h3><ul className="tl"><More items={digest.waits} cap={4}>{(item, index) => <li key={index}><b onClick={() => nav.openNode(`c${item.chapter}`)}>第 {item.chapter} 章{item.action}</b>{item.what}</li>}</More></ul></div>}
      {!!digest.things.length && <div className="rb"><h3>新冒出来的<span className="n">{digest.things.length} 样</span></h3><div className="names"><More items={digest.things} cap={10} unit="样">{(item, index) => <span key={index} title={`第 ${item.chapter} 章 · ${item.kind}：${item.note}`}>{item.name}</span>}</More></div></div>}
    </>}
  </aside>
}

function ChapterRail({ data }: { data?: TeardownChapterData | null }) {
  const read = data?.read
  if (!read || !read.people?.length && !read.moments?.length && !read.things?.length && !read.waits?.length && !read.tropes?.length) return null
  return <aside className="rail">
    {!!read.people?.length && <div className="rb"><h3>这一章出场的人<span className="n">{read.people.length} 人</span></h3><ul className="plist"><More items={read.people} cap={3} unit="人">{(person, index) => <li key={index}><span className="nm">{person.name}{!!person.also_called?.length && <small className="aka">也叫 {person.also_called.join('、')}</small>}</span><span className="ct" /><span className="ds">{person.shown}{person.change ? `（${person.change}）` : ''}</span></li>}</More></ul></div>}
    {!!read.moments?.length && <div className="rb"><h3>名场面</h3>{read.moments.map((moment, index) => <div className="mm" key={index}><b>{moment.who}</b>：{moment.what}<div className="sh">立住了：{moment.shows}</div></div>)}</div>}
    {(!!read.things?.length || !!read.waits?.length || !!read.tropes?.length) && <div className="rb"><h3>新冒出来的 · 读者在等的</h3><ul className="tl">
      {read.things?.map((item, index) => <li key={`thing-${index}`}><b>{item.kind}{item.secret ? `（${item.secret}）` : ''}</b>{item.name}：{item.note}{item.belongs ? `（属于 ${item.belongs}）` : ''}</li>)}
      {read.waits?.map((item, index) => <li key={`wait-${index}`}><b>{item.action}</b>{item.what}</li>)}
    </ul>{!!read.tropes?.length && <div className="names" style={{ marginTop: 4 }}>{read.tropes.map((trope, index) => <span key={index}>{trope}</span>)}</div>}</div>}
  </aside>
}

function AuthorControls({ node, book, nav, onAdd, onInsert, onMove, writing }: OutlineProps & { node: VNode }) {
  const { actions } = useWorkspace(), save = useSave(), split = useSplit(node)
  const child = childKind(node), status = writing?.status
  const gate = status?.state === 'waiting' && status.gate && gateTarget(status.gate).node === node.id ? status.gate : undefined
  return <>
    {gate && writing && <div className="desk-legacy" style={{ display: 'contents' }}><GateCard gate={gate} writing={writing} nav={nav} /></div>}
    {node.locked && <p className="state">锁住，AI 规划时不改</p>}
    {node.later && <p className="state">写到再定</p>}
    {node.count !== undefined && actions.canEdit(node, 'name') && (node.kind === '单元' || node.kind === '卷') && <div className="desk-legacy" style={{ display: 'contents' }}><CountField node={node} /></div>}
    <div className="desk-legacy" style={{ display: 'contents' }}><WriteHelp node={node} /></div>
    <div className="sec"><div className="names">
      {child && actions.canAdd(node) && <button type="button" className="btn solid" onClick={() => onAdd(node.id)}>新增{child}</button>}
      {split.available && split.state.step === 'idle' && <button type="button" className="btn seal-line" onClick={split.open}>{split.label}</button>}
      {actions.canArrange(node) && <>
        <button type="button" className="btn seal-line" onClick={() => onInsert(node, 'before')}>在前面插{node.kind === '单元' ? '一个' : '一'}{node.kind}</button>
        <button type="button" className="btn seal-line" onClick={() => onInsert(node, 'after')}>在后面插{node.kind === '单元' ? '一个' : '一'}{node.kind}</button>
        <button type="button" className="btn seal-line" onClick={() => onMove(node, 'up')}>上移</button><button type="button" className="btn seal-line" onClick={() => onMove(node, 'down')}>下移</button>
      </>}
      {actions.canDelete(node) && <button type="button" className="btn seal-line" onClick={() => { nav.openNode(findNode(book.outline, node.id)?.at(-2)?.id ?? 'book'); save(actions.deleteNode(node)) }}>删掉这{node.kind === '单元' ? '一个' : '一'}{node.kind}</button>}
    </div><div className="desk-legacy" style={{ display: 'contents' }}><SplitPanel node={node} split={split} /></div></div>
    {!!node.uses.length && <div className="sec"><div className="label">用到的设定</div><div className="names">{node.uses.map(id => { const entry = findEntry(book, id); return entry && <span key={id} onClick={() => nav.openEntry(id)}>{entry.name}</span> })}</div></div>}
  </>
}

interface OutlineProps {
  book: VBook; id: string; nav: ManuscriptNav; onAdd: (id: string) => void
  onInsert: (node: VNode, where: 'before' | 'after') => void; onMove: (node: VNode, direction: 'up' | 'down') => void
  fresh: boolean; writing?: WritingControl
}

export function DeskOutline(props: OutlineProps) {
  const { book, id, nav, writing } = props
  const { actions } = useWorkspace(), save = useSave()
  const path = findNode(book.outline, id) ?? [book.outline], node = path[path.length - 1]
  const teardown = book.source === 'teardown', outline = outlineOf(node)
  const chapter = useDeskChapter(book, node.kind === '章' ? node : undefined, writing)
  const readCount = chapterNodes(book.outline).filter(item => item.teardown?.read).length
  const digest = useQuery({ queryKey: ['desk-v2-digest', book.id, node.id, readCount], queryFn: () => get<DeskDigest>(`/books/${book.id}/teardown/digest?${node.kind === '卷' ? 'volume' : 'unit'}=${encodeURIComponent(node.ref!.id)}`), enabled: teardown && (node.kind === '卷' || node.kind === '单元') && !!node.ref, retry: false })
  const parent = path.at(-2), volume = path.find(item => item.kind === '卷'), unit = path.find(item => item.kind === '单元')
  const units = (node.children ?? []).filter(item => !item.virtual), hang = node.children?.find(item => item.virtual)
  const number = readingChapterNumber(node), body = node.body, count = rangeLength(node)
  const notRead = teardown && node.kind === '章' && !node.teardown?.read && !outline.goal && !outline.cool && !outline.hook
  // 旧作者章可能只有「这一章写了什么」，不能当成空章纲藏掉已经存下的摘要。
  const extraFields = teardown ? [] : node.sections?.filter(field => !['发生什么', '看点', '结尾钩子'].includes(field.label)) ?? []
  const showOutline = teardown || !extraFields.length || node.sections?.some(field => ['发生什么', '看点', '结尾钩子'].includes(field.label))
  const edits = (label: string) => actions.canEdit(node, 'text') ? (value: string) => save(actions.saveNode(node, { sections: { [label]: value } })) : undefined
  const title = <NodeEdit as="h1" value={editableNodeName(node)} label={`给${node.kind}起个名字`} save={actions.canEdit(node, 'name') && !node.virtual && node.kind !== '全书' ? value => { if (node.kind !== '章' || value.trim()) save(actions.saveNode(node, { name: value.trim() })) } : undefined}>{nodeName(node)}</NodeEdit>
  useEffect(() => { if (!props.fresh) return; document.querySelector<HTMLElement>('.page [data-editable]')?.click() }, [props.fresh, node.id])
  if (node.kind === '章') return <>
    <section className="page">
      <div className="kicker">第 {number} 章 · {unit && !unit.virtual ? `${nodePrefix(unit)} 第 ${number - (unit.range?.[0] ?? number) + 1} / ${rangeLength(unit)} 章` : `${volume ? `${nodePrefix(volume)} ${nodeName(volume)} · ` : ''}还没归单元`}</div>
      {!teardown && node.ref && <PendingNote id={node.ref.id} />}{title}<div className="meta">{teardown ? '原文 ' : ''}{(body?.words ?? 0).toLocaleString()} 字<a onClick={() => nav.openChapter(node.id)}>去读这一章<Icon name="go" /></a></div>
      <div className="rule1" />
      {notRead ? <p className="state">这一章还没拆：拆到第 {number} 章时，这里会出章纲（发生什么、看点、结尾钩子），右边出这一章的人和事。现在拆到第 {book.teardown?.upto ?? readCount} 章，点顶上的「接着拆」往下拆。</p> : <>
        {showOutline && <><section className="sec"><div className="label">发生什么</div><NodeEdit className="lead" value={node.sections?.find(field => field.label === '发生什么')?.text ?? node.text} save={edits('发生什么')} label="发生什么">{outline.goal || (!teardown ? '还没写' : '')}</NodeEdit><ol className="scenes">{outline.scenes.map((scene, index) => <li key={index} onClick={event => { event.stopPropagation(); document.querySelector<HTMLElement>('.page [data-editable="发生什么"]')?.click() }}>{scene}</li>)}</ol></section>
        <section className="sec twin">{(['看点', '结尾钩子'] as const).map((label, index) => { const text = index ? outline.hook : outline.cool; return <div className="note" key={label}><div className="label">{label}</div><NodeEdit value={text} save={edits(label)} label={label}><Chip text={chapterKind(text)} />{chapterRest(text) || (!teardown ? '还没写' : '')}</NodeEdit></div> })}</section></>}
        {extraFields.map(field => <section className="sec" key={field.label}><div className="label">{field.label}</div><NodeEdit className="lead" value={field.text} label={field.label} /></section>)}
      </>}
      {!teardown && <AuthorControls {...props} node={node} />}
      <ChapterFoot book={book} node={node} nav={nav} unfinished={notRead} />
    </section>
    {teardown && !notRead && <ChapterRail data={chapter.data?.teardown ?? body?.teardown} />}
  </>
  if (node.kind === '单元' && !node.virtual) {
    const parts = node.text.replace(/。$/, '').split('；'), four = parts.length === 4
    return <><section className="page">{!teardown && node.ref && <PendingNote id={node.ref.id} />}<div className="kicker">{nodePrefix(node)} · {parent ? nodeName(parent) : '全书'}</div>{title}<div className="meta">{node.range ? `第 ${node.range[0]}–${node.range[1]} 章 · ` : ''}{count} 章</div><div className="rule1" />
      {four ? <div className="beats4">{['什么事找上门', '主角怎么应对', '叫好的那一下', '拿到什么'].map((label, index) => <div className="beat" key={label}><b style={!teardown ? { userSelect: 'none' } : undefined}>{label}</b><NodeEdit as="span" value={node.text} label="单元那段话" spot={!teardown ? `n|${node.id}` : undefined} spotOffset={!teardown ? parts.slice(0, index).reduce((sum, part) => sum + part.length + 1, 0) : undefined} save={actions.canEdit(node, 'text') ? value => save(actions.saveNode(node, { text: value })) : undefined}>{parts[index]}</NodeEdit></div>)}</div> : <NodeEdit className="lead" value={node.text} label="单元那段话" spot={!teardown ? `n|${node.id}` : undefined} save={actions.canEdit(node, 'text') ? value => save(actions.saveNode(node, { text: value })) : undefined}>{node.text || (!teardown ? '还没写' : '')}</NodeEdit>}
      <div className="sec" style={{ marginTop: 22 }}><div className="label">各章<span className="n">看点 · 结尾钩子</span></div><table className="ctable"><tbody>{(node.children ?? []).map((item, index) => { const details = outlineOf(item); return <tr key={item.id} className={index === 3 ? 'on' : ''} onClick={() => nav.openNode(item.id)}><td className="no">{readingChapterNumber(item)}</td><td className="tt"><span className="ell" title={nodeName(item)}>{nodeName(item)}</span></td><td className="gl">{details.goal}</td><td className="tp"><Chip text={chapterKind(details.cool)} /><Chip text={chapterKind(details.hook)} /></td></tr> })}</tbody></table></div>
      {!teardown && <AuthorControls {...props} node={node} />}
    </section>{teardown && <DigestRail node={node} digest={digest.data} nav={nav} book={book} />}</>
  }
  return <><section className="page">{!teardown && node.ref && <PendingNote id={node.ref.id} />}<div className="kicker">{nodeName(node)} · {parent ? nodeName(parent) : '全书'}</div>{title}
    <div className="meta">{count} 章{node.range ? ` · 第 ${node.range[0]}–${node.range[1]} 章` : ''} · {units.length} 个{node.kind === '卷' ? '单元' : childKind(node) ?? '单元'}{hang?.range && <> · <span style={{ color: 'var(--ochre)' }}>还没拆完：第 {hang.range[0]}–{hang.range[1]} 章还没归单元，拆完这一卷再写这一卷的那段话</span></>}</div>
    {(!teardown || !!clean(node.text)) && <NodeEdit className="lead" value={node.text} label="那段话" spot={!teardown && !node.virtual ? `n|${node.id}` : undefined} save={actions.canEdit(node, 'text') ? value => save(actions.saveNode(node, { text: value })) : undefined}>{node.text || '还没写'}</NodeEdit>}
    <div className="rule1" /><div className="sec"><div className="label">节奏<span className="n">一格一个单元，宽窄是章数</span></div><div className="rhythm">{units.map((item, index) => <i key={item.id} style={{ '--w': rangeLength(item) } as CSSProperties} title={`第 ${item.range?.[0]}–${item.range?.[1]} 章「${nodeName(item)}」`} onClick={() => nav.openNode(item.id)}>{cn(index + 1)}</i>)}{hang && <i className="wait" style={{ '--w': rangeLength(hang) } as CSSProperties} title={`第 ${hang.range?.[0]}–${hang.range?.[1]} 章还没归单元`} onClick={() => nav.openNode(hang.id)}>…</i>}</div></div>
    <div className="sec"><div className="label">{node.kind === '卷' ? '单元' : childKind(node) ?? '单元'}<span className="n">那段话只显示前三行，点进去看全部</span></div><div className="ugrid">{units.map((item, index) => <div className="ucard" key={item.id} title={item.text} onClick={() => nav.openNode(item.id)}><div className="hd"><span className="seal-no">{cn(index + 1)}</span><span className="ell">{nodeName(item)}</span></div><div className="rg">第 {item.range?.[0]}–{item.range?.[1]} 章 · {rangeLength(item)} 章</div><p>{item.text}</p></div>)}</div></div>
    {node.virtual && <p className="state">这些章还没拆，拆的时候会归进单元。</p>}
    {!teardown && <AuthorControls {...props} node={node} />}
  </section>{teardown && node.kind === '卷' && <DigestRail node={node} digest={digest.data} nav={nav} book={book} />}</>
}
