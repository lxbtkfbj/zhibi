import { type ReactNode, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { searchBookText } from '../../../api/textSearch'
import { readTeardownReading, readingChapterNumber } from '../../../lib/teardownReading'
import { teardownProgressView } from '../../../lib/teardownProgress'
import { teardownStartLabel } from '../../../lib/teardownStart'
import { useTeardownControl } from '../TeardownProgress'
import { chapterNodes, cn, findNode, splitTitle, type VBook, type VNode } from '../model'
import { useWorkspace } from '../actions'
import type { Tab } from '../Workspace'
import type { WritingControl } from '../writing'
import { Icon } from './shared'
import { orderedCharacters } from './settingsData'

function volumeName(node: VNode) {
  const [prefix, name] = splitTitle(node.title)
  return name === prefix ? name : [prefix, name].filter(Boolean).join(' ')
}
const titleOf = (node: VNode) => splitTitle(node.title)[1] || splitTitle(node.title)[0]

export function DeskTop({ book, tab, onTab, right, writing }: { book: VBook; tab: Tab; onTab: (tab: Tab) => void; right: ReactNode; writing?: WritingControl }) {
  const control = useTeardownControl()
  const { report } = useWorkspace()
  const view = teardownProgressView(book, control?.job ?? null)
  const teardown = book.source === 'teardown'
  const total = book.teardown?.chapters ?? chapterNodes(book.outline).length
  const read = view.active ? view.read : book.teardown?.last_read ?? view.read
  const startLabel = teardownStartLabel(view.stage, !!book.teardown?.needs_closing)
  const pending = control?.job?.pending
  const caption = view.active ? pending && 'teardown' in pending && pending.teardown?.doing === 'settings' ? '设定师在整理设定' : view.text : `已拆 ${read} / ${total} 章`
  const perform = (task: Promise<unknown> | undefined) => { void task?.catch(report) }
  return <header className="top">
    <div className="left"><Link className="back" to="/">{teardown && (tab === '简介' || tab === '精髓') ? '‹ 书房' : <><Icon name="l" />书房</>}</Link><span className="sep" /><span className="mini-cover" /><span className="book-name">{book.title}</span>{teardown && <span className="tag">{(tab === '简介' || tab === '精髓') && !book.teardown?.author ? '拆的书' : <>拆的书 · {book.teardown?.author}</>}</span>}</div>
    <nav className="tabs">{(teardown ? ['简介', '精髓', '设定', '大纲', '正文'] as const : ['简介', '设定', '大纲', '正文'] as const).map(item => <a key={item} className={tab === item ? 'on' : undefined} onClick={() => onTab(item)}>{item}</a>)}</nav>
    <div className="right">{teardown ? <><div className="progress"><span className={view.active ? 'ell' : undefined} title={caption}>{caption}</span><span className="track"><b style={{ width: `${total ? read / total * 100 : 0}%` }} /></span>{['model', 'error'].includes(book.teardown?.stop_reason ?? '') && <span className="stop-error" title={book.teardown?.stop_note ?? ''} />}{view.active ? <a className="btn seal-line" aria-disabled={control?.stopping} onClick={() => !control?.stopping && perform(control?.stop())}>{control?.stopping ? '正在停' : '停下'}</a> : startLabel && <a className="btn seal-line" onClick={control?.openStart}>{startLabel}</a>}</div><span className="sep" /></> : writing?.status.state === 'working' ? <><div className="progress">写手在写第 {Number(writing.status.chapter?.replace(/^c/, '') || 0)} 章 · 已写 {chapterNodes(book.outline).filter(c => c.body?.status === 'done').length} 章<a className="btn seal-line" onClick={() => perform(writing.stop())}>停下</a></div><span className="sep" /></> : null}{right}</div>
  </header>
}

interface DirectoryProps {
  book: VBook; tab: Tab; selected: string; open: string[]; onToggle: (id: string) => void; onSelect: (id: string) => void
  footer?: ReactNode; onNewEntry?: (name: string) => void; outlineTools?: ReactNode
  onSearchSelect?: (id: string, word: string) => void
}

export function DeskDirectory({ book, tab, selected, open, onToggle, onSelect, footer, onNewEntry, outlineTools, onSearchSelect }: DirectoryProps) {
  const [query, setQuery] = useState('')
  const { actions } = useWorkspace()
  const q = query.trim()
  const searchResult = useQuery({ queryKey: ['desk-text-search', book.id, q], queryFn: ({ signal }) => searchBookText(book.id, q, signal), enabled: tab === '正文' && !!q && actions.live, retry: false })
  const teardown = book.source === 'teardown'
  const volumes: VNode[] = []
  const collect = (node: VNode) => { if (node.kind === '卷') volumes.push(node); else node.children?.forEach(collect) }
  collect(book.outline)
  const saved = readTeardownReading(book.id)?.chapter ?? 0
  const path = findNode(book.outline, selected) ?? []
  const currentVolume = path.find(n => n.kind === '卷')?.id ?? volumes[0]?.id
  const matches = (node: VNode): boolean => !query || node.title.includes(query) || !!node.children?.some(matches)
  const foot = footer ?? <div className="toc-foot"><Icon name="save" />存档<span className="muted">还没存过</span></div>
  const search = tab === '设定' ? '找人物、地方、规矩……' : tab === '正文' ? '找章节、搜原文……' : '找篇、卷、单元、章……'
  const selectRow = (id: string, expanded: boolean) => { if (expanded && selected === id) onToggle(id); else onSelect(id) }
  const chapterRow = (chapter: VNode) => <div key={chapter.id} className={`row${selected === chapter.id ? ' on' : ''}`} onClick={() => onSelect(chapter.id)}><span className="no">{readingChapterNumber(chapter)}</span><span className="ell" title={titleOf(chapter)}>{titleOf(chapter)}</span></div>
  const outlineVolume = (volume: VNode) => {
    const expanded = open.includes(volume.id)
    return <div key={volume.id} style={{ display: 'contents' }}><div className={`row top1${selected === volume.id ? ' on' : ''}${expanded ? '' : ' closed'}`} onClick={() => selectRow(volume.id, expanded)}><Icon name="chev" onClick={e => { e.stopPropagation(); onToggle(volume.id) }} />{volumeName(volume)}<span className="n">{volume.chapters ?? chapterNodes(volume).length} 章</span></div>{expanded && volume.children?.filter(matches).map((unit, n) => {
      const expandedUnit = open.includes(unit.id)
      return <div key={unit.id} style={{ display: 'contents' }}><div className={`row unit${unit.virtual ? ' virtual' : ''}${selected === unit.id ? ' on' : ''}${expandedUnit ? '' : ' closed'}`} onClick={() => selectRow(unit.id, expandedUnit)}><Icon name="chev" onClick={e => { e.stopPropagation(); onToggle(unit.id) }} /><span className="seal-no">{unit.virtual ? '…' : cn(n + 1)}</span>{unit.virtual ? '还没归单元' : <span className="ell" title={titleOf(unit)}>{titleOf(unit)}</span>}<span className="n">{unit.chapters ?? chapterNodes(unit).length}</span></div>{expandedUnit && <div className="kids">{unit.children?.filter(matches).map(chapterRow)}</div>}</div>
    })}</div>
  }
  return <aside className="toc"><div className="toc-head"><div className="search"><Icon name="search" /><input aria-label={search} placeholder={search} value={query} onChange={e => setQuery(e.target.value)} /></div></div><div className="tree">
    {tab === '正文' && q ? <>
      {chapterNodes(book.outline).filter(c => c.title.includes(q)).map(chapterRow)}
      {actions.live && <section aria-label="原文搜索结果">{searchResult.isPending ? <p className="small">正在搜原文……</p> : searchResult.error ? <p className="small" role="alert">{searchResult.error.message}</p> : searchResult.data?.chapters ? <><div className="grp">原文里有「{q}」的章（{searchResult.data.chapters} 章）</div>{searchResult.data.results.map(hit => <div className="row" key={hit.index} onClick={() => onSearchSelect ? onSearchSelect(`c${hit.index}`, q) : onSelect(`c${hit.index}`)}><span className="no">{hit.index}</span><span className="ell" title={hit.near}>{hit.title} · {hit.times} 次</span></div>)}</> : !chapterNodes(book.outline).some(c => c.title.includes(q)) && <p className="small">没找到「{q}」</p>}</section>}
    </> : tab === '设定' ? <><div className={`row top1${selected === 'overview' || selected === 'settings' ? ' on' : ''}`} onClick={() => onSelect('overview')}>设定总览{book.teardown?.settings?.upto && <span className="n">整理到第 {book.teardown.settings.upto} 章</span>}</div>{[{ name: '世界概况', key: 'world', entries: [] }, ...book.categories].map(category => {
      const id = category.key === 'world' ? 'world' : `cat:${category.name}`
      const expanded = open.includes(id)
      const ordered = category.name === '角色列表' ? orderedCharacters(category.entries, teardown) : category.entries
      const entries = ordered.filter(e => !query || e.name.includes(query))
      return <div key={category.key} style={{ display: 'contents' }}><div className={`row unit${expanded ? '' : ' closed'}${selected === 'world' && category.key === 'world' ? ' on' : ''}`} onClick={() => selectRow(id, expanded)}><Icon name="chev" onClick={e => { e.stopPropagation(); onToggle(id) }} />{category.name}<span className="n">{category.key === 'world' ? book.world ? '' : '还没有' : `${category.entries.length}${category.name === '等级体系' ? ' 套' : ''}`}</span></div>{expanded && <div className="kids">{entries.map(entry => <div key={entry.id} className={`row${selected === entry.id ? ' on' : ''}`} onClick={() => onSelect(entry.id)}>{entry.name}</div>)}{!teardown && onNewEntry && <div className="row" onClick={() => onNewEntry(category.name)}>新建一条</div>}</div>}</div>
    })}</> : tab === '正文' ? <><div className={`row top1${selected === 'home' ? ' on' : ''}`} onClick={() => onSelect('home')}>正文首页{saved > 0 && <span className="n">读到第 {saved} 章</span>}</div>{volumes.filter(matches).map(volume => <div key={volume.id} style={{ display: 'contents' }}><div className={`row top1${volume.id === currentVolume ? '' : ' closed'}`} onClick={() => onToggle(volume.id)}><Icon name="chev" />{volumeName(volume)}<span className="n">{volume.chapters ?? chapterNodes(volume).length} 章</span></div>{(volume.id === currentVolume || open.includes(volume.id)) && volume.children?.filter(matches).map((unit, i) => <div key={unit.id} style={{ display: 'contents' }}><div className="grp">{unit.virtual ? '还没归单元' : `单元${cn(i + 1)} · ${titleOf(unit)}`}</div><div className="kids">{unit.children?.filter(matches).map(chapterRow)}</div></div>)}</div>)}</> : <><div className={`row top1${selected === 'book' ? ' on' : ''}`} onClick={() => onSelect('book')}><Icon name="chev" />全书<span className="n">{chapterNodes(book.outline).length} 章</span></div>{teardown && <div className={`row top1${selected === 'waits' ? ' on' : ''}`} data-testid="teardown-waits-entry" onClick={() => onSelect('waits')}>读者在等的事<span className="n">{book.teardown?.waits ? `${book.teardown.waits.open} 件还吊着` : '还没整理'}</span></div>}{book.outline.children?.filter(n => n.kind === '篇').map(arc => <div key={arc.id} style={{ display: 'contents' }}><div className={`row top1${arc.virtual ? ' virtual' : ''}${teardown && selected === arc.id ? ' on' : ''}`} onClick={() => onSelect(arc.id)}><Icon name="chev" />{arc.title.replace('　', ' ')}</div>{arc.children?.filter(matches).map(outlineVolume)}</div>)}{book.outline.children?.filter(n => n.kind === '卷' && matches(n)).map(outlineVolume)}{!teardown && outlineTools}</>}
  {tab === '正文' && !teardown && chapterNodes(book.outline).some(c => c.body?.status === 'done') && <div className="tools"><button type="button" className="btn seal-line" onClick={() => window.open(`/api/books/${book.id}/export.txt`, '_blank')}>导出全书 TXT</button></div>}</div>{foot}</aside>
}
