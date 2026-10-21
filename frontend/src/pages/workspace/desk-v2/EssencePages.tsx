import { Fragment, useState, type ReactNode } from 'react'
import type { VBook } from '../model'
import { useSave, useWorkspace } from '../actions'
import { DeskEdit } from './settingsEditing'
import {
  ESSENCE_GROUPS, ESSENCE_LEADS, ESSENCE_NAMES, emptyEssenceText, essenceCount, essenceNumber, hasEssence, introOutline, introSteps, introVolumes,
  type EssenceBars, type EssenceKey, type EssencePoint, type TeardownEssence,
} from './essenceData'

export function EssenceRefs({ text, onChapter }: { text: string; onChapter: (chapter: number) => void }) {
  return <>{text.split(/(第\s?\d+(?:\s?[–\-、]\s?\d+)*\s?章)/g).map((part, index) => /^第\s?\d/.test(part)
    ? <span className="ref" key={index} onClick={() => onChapter(Number(part.match(/\d+/)?.[0]))}>{part}</span> : part)}</>
}

function KnowledgePoint({ point, index, onChapter }: { point: EssencePoint; index: number; onChapter: (chapter: number) => void }) {
  const at = point.title.indexOf('：')
  const name = at >= 0 ? point.title.slice(0, at) : ''
  const rest = at >= 0 ? point.title.slice(at + 1) : point.title
  return <div className="kp"><h3><span className="seal-no">{index + 1}</span><span>{name && <><em>{name}</em>：</>}{rest}</span></h3>
    <ol className="steps">{point.steps.map((step, i) => <li key={i}><EssenceRefs text={step} onChapter={onChapter} /></li>)}</ol>
    <p className="ev"><b>这本书里</b><EssenceRefs text={point.evidence} onChapter={onChapter} /></p>{point.note && <p className="nt"><b>注意</b>{point.note}</p>}</div>
}

function Bars({ rows, unit }: { rows: EssenceBars; unit: string }) {
  const max = Math.max(...rows.map(row => row[1]), 1)
  return <ul className="bars">{rows.map(([key, value], index) => <li key={index}><span>{key}</span><i style={{ width: `${Math.max(6, value / max * 100)}%` }} /><span>{value}{unit}</span></li>)}</ul>
}
function RailBox({ heading, number, children }: { heading: string; number?: string; children: ReactNode }) {
  return <div className="rb"><h3>{heading}{number && <span className="n">{number}</span>}</h3>{children}</div>
}
function FeelStrip({ essence }: { essence: TeardownEssence }) {
  return <><div className="feelstrip">{essence.rails.strip.map((feel, i) => <i className={feel === '大爽' ? 'b' : feel === '爽' ? 's' : feel === '憋屈' ? 'd' : ''} title={`第 ${i + 1} 章 · ${feel}`} key={i} />)}</div><div className="legend"><span>第 1 章</span><span>深红大爽 · 浅红爽 · 蓝憋屈</span><span>第 {essence.upto} 章</span></div></>
}
function UnitList({ essence }: { essence: TeardownEssence }) {
  const rail = essence.rails
  return <ul className="plist">{rail.units.map(unit => <li key={unit.n}><span className="nm">{essenceNumber(unit.n)} · {unit.title}</span><span className="ct">{unit.first}–{unit.last}</span></li>)}{rail.tail && <li><span className="nm">… 还没收尾</span><span className="ct">{rail.tail[0]}–{rail.tail[1]}</span></li>}</ul>
}
function EssenceRail({ essence, selected }: { essence: TeardownEssence; selected: EssenceKey }) {
  const rail = essence.rails
  const units = <RailBox heading="单元" number={`${rail.units.length} 个`}><UnitList essence={essence} /></RailBox>
  const people = <RailBox heading="出场最多的人"><Bars rows={rail.people} unit=" 章" /></RailBox>
  return <aside className="rail">
    {selected === 'overview' && <><RailBox heading="这本书的数字" number={`前 ${essence.upto} 章`}><ul className="plist"><li><span className="nm">单元</span><span className="ct">{rail.units.length} 个</span></li><li><span className="nm">过瘾的章</span><span className="ct">{(rail.feel['爽'] || 0) + (rail.feel['大爽'] || 0)} 章（大爽 {rail.feel['大爽'] || 0}）</span></li><li><span className="nm">读者在等的事</span><span className="ct">{rail.waits.total} 件，还吊着 {rail.waits.open}</span></li></ul></RailBox><RailBox heading="各类爽点出现几章"><Bars rows={rail.tags.slice(0, 6)} unit=" 章" /></RailBox></>}
    {selected === 'source' && <><RailBox heading="每个单元的事从哪来" number="逐单元拆的"><Bars rows={rail.triggers} unit=" 个" /></RailBox>{units}</>}
    {selected === 'skeleton' && units}
    {selected === 'link' && <><RailBox heading="读者在等的事"><div className="small">一共 {rail.waits.total} 件，还吊着 {rail.waits.open} 件。</div></RailBox>{units}</>}
    {selected === 'fresh' && <RailBox heading="赌注比上一单元"><Bars rows={rail.stakes} unit=" 次" /></RailBox>}
    {selected === 'setting' && <RailBox heading="拆出来的设定" number="逐章记录里新冒出来的"><Bars rows={rail.things} unit=" 条" /></RailBox>}
    {selected === 'shuang' && <><RailBox heading="各类爽点出现几章" number="一章可以算几类"><Bars rows={rail.tags} unit=" 章" /></RailBox><RailBox heading="靠旁观者放大"><div className="small">过瘾的章里，有 {rail.crowd} 章有人在旁边看着、靠旁观者的反应把爽放大。</div></RailBox></>}
    {selected === 'hero' && people}
    {selected === 'cast' && <>{people}{rail.merges.length > 0 && <RailBox heading="并成同一个人的">{rail.merges.map((merge, i) => <div className="small" key={i}>{merge.names.join('、')} → <b>{merge.keep}</b>（{merge.why}）</div>)}</RailBox>}</>}
    {selected === 'rhythm' && <><RailBox heading="逐章的读者感觉" number="模型判的"><FeelStrip essence={essence} /></RailBox><RailBox heading="章末钩子"><Bars rows={rail.hooks} unit=" 章" /></RailBox></>}
  </aside>
}

export function EssenceDirectory({ essence, selected, onSelect, footer }: { essence: TeardownEssence | null; selected: EssenceKey; onSelect: (key: EssenceKey) => void; footer?: ReactNode }) {
  const [query, setQuery] = useState('')
  essence = hasEssence(essence) ? essence : null
  const q = query.trim()
  return <aside className="toc"><div className="toc-head"><div className="search"><input aria-label="找知识点……" placeholder="找知识点……" value={query} onChange={event => setQuery(event.target.value)} /></div></div><div className="tree">
    {(!q || essenceCount(essence, 'overview', q) > 0) && <div className={`row top1 ${selected === 'overview' ? 'on' : ''}`} onClick={() => onSelect('overview')}>核心要点<span className="n">{essenceCount(essence, 'overview', q)}</span></div>}
    {ESSENCE_GROUPS.map(([group, keys]) => {
      const visible = keys.filter(key => essence?.sections[key] && (!q || essenceCount(essence, key, q) > 0))
      return visible.length ? <Fragment key={group}><div className="row unit">{group}{group === '剧情' && <span className="chip seal" style={{ marginLeft: 4, height: 18 }}>重点</span>}</div><div className="kids">{visible.map(key => <div className={`row ${selected === key ? 'on' : ''}`} key={key} onClick={() => onSelect(key)}>{ESSENCE_NAMES[key]}<span className="n">{essenceCount(essence, key, q)}</span></div>)}</div></Fragment> : null
    })}
  </div>{footer ?? <div className="toc-foot">存档<span className="muted">还没存过</span></div>}</aside>
}

export function EssencePage({ essence, selected, book, active = false, onChapter }: { essence: TeardownEssence | null; selected: EssenceKey; book: VBook; active?: boolean; onChapter: (chapter: number) => void }) {
  essence = hasEssence(essence) ? essence : null
  if (!essence) return <><section className="page"><div className="kicker">精髓</div><h1>核心要点</h1><div className="rule1" /><div className="state">{emptyEssenceText(book, active)}</div></section><aside className="rail" /></>
  const section = selected === 'overview' ? null : essence.sections[selected]
  // A saved section can disappear after a partial rebuild; the same core page is
  // the initial destination rather than rendering an invented missing-page UI.
  const key = selected !== 'overview' && !section ? 'overview' : selected
  const overview = essence.overview
  const group = ESSENCE_GROUPS.find(([, keys]) => keys.includes(key as Exclude<EssenceKey, 'overview'>))?.[0]
  return <><section className="page"><div className="kicker">{key === 'overview' ? '精髓' : `精髓 · ${group}`}</div><h1>{key === 'overview' ? '核心要点' : ESSENCE_NAMES[key]}</h1><div className="meta">{ESSENCE_LEADS[key]} · 基于前 {essence.upto} 章</div><div className="rule1" />
    {key === 'overview' ? <><p className="genre">{overview?.genre}</p><p className="engine">{overview?.engine}</p>{overview?.points.map((point, i) => <KnowledgePoint point={point} index={i} onChapter={onChapter} key={i} />)}</>
      : section && <>{section.figures ? <><div className="sec"><div className="label">重要人物<span className="n">{section.figures.length} 个</span></div><div className="figs">{section.figures.map((figure, i) => <div className="fig" key={i}><div><span className="nm">{figure.name}</span><span className="chip ochre">{figure.archetype}</span></div><dl><dt>怎么立</dt><dd><EssenceRefs text={figure.build} onChapter={onChapter} /></dd><dt>作用</dt><dd><EssenceRefs text={figure.role} onChapter={onChapter} /></dd>{figure.arc && <><dt>变化</dt><dd><EssenceRefs text={figure.arc} onChapter={onChapter} /></dd></>}</dl></div>)}</div></div><div className="sec"><div className="label">人设怎么搭、怎么立</div>{section.points.map((point, i) => <KnowledgePoint point={point} index={i} onChapter={onChapter} key={i} />)}</div></>
        : <div>{section.points.map((point, i) => <KnowledgePoint point={point} index={i} onChapter={onChapter} key={i} />)}</div>}{!!section.missing?.length && <p className="state miss">还看不出来：{section.missing.join('；')}</p>}</>}
  </section><EssenceRail essence={essence} selected={key} /></>
}

export function TeardownIntro({ book, essence, onChapter, onUnit, onVolume, onPerson, onEssence, onAppend }: { book: VBook; essence: TeardownEssence | null; onChapter: (chapter: number) => void; onUnit: (number: number) => void; onVolume: (id: string) => void; onPerson: (name: string) => void; onEssence: () => void; onAppend: () => void }) {
  essence = hasEssence(essence) ? essence : null
  const { actions } = useWorkspace()
  const save = useSave()
  const rail = essence?.rails
  const overview = essence?.overview
  const bookOutline = introOutline(book)
  const outline = rail ?? bookOutline
  const byVolume = Math.max(outline.units.length, bookOutline.units.length) > 24
  const volumes = byVolume ? introVolumes(book) : null
  const tail = volumes ? volumes.tail : outline.tail
  const read = book.teardown?.last_read ?? 0
  const total = book.teardown?.chapters ?? 0
  const archetypes = Object.fromEntries((essence?.sections.cast?.figures ?? []).map(figure => [figure.name, figure.archetype]))
  const people = [...(book.categories.find(category => category.name === '角色列表')?.entries ?? [])].sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
  return <section className="page full"><div className="intro2"><div className="main">
    <div className="hero"><div className="cover"><span className="lbl">{book.title}</span><span className="stamp">执笔</span></div><div>
      <div className="kicker">拆的书</div><DeskEdit as="h1" value={book.title} placeholder="书名" onSave={title => { if (title.trim()) save(actions.saveBook({ title: title.trim() })) }} /><div className="meta">原书作者 {book.teardown?.author || '（文件里没写）'} · {total} 章</div>
      <div className="statline"><span className="chip seal">已拆 {read} / {total} 章</span><span className="chip ochre">{outline.units.length} 个单元</span>{essence && <span className="chip jade">精髓基于前 {essence.upto} 章</span>}</div>
      {overview && <p className="genre" style={{ marginTop: 14 }}>{overview.genre}</p>}
      <div className="actions"><a className="btn seal-line" data-testid="teardown-append-entry" onClick={onAppend}>补后面的章节</a></div></div></div>
    {overview && <><div className="sec"><div className="label">一句话看懂<span className="n" onClick={onEssence} style={{ cursor: 'pointer' }}>去精髓页 ›</span></div><p className="lead">{overview.engine}</p></div>
      <div className="sec"><div className="label">最值得学的几件事<span className="n" onClick={onEssence} style={{ cursor: 'pointer' }}>全部知识点 ›</span></div><ol className="learn">{overview.points.slice(0, 4).map((point, i) => <li onClick={onEssence} key={i}><b>{point.title}</b><span>{introSteps(point)}</span></li>)}</ol></div></>}
    {!essence && <div className="state">精髓还没整理：拆书收尾时会整理，整理好以后这里会有一句话看懂和最值得学的几件事。</div>}
    <div className="sec"><div className="label">故事走到哪了<span className="n">{byVolume ? '一格一卷，点进去看这一卷的单元' : '一格一个单元'}</span></div><div className="ugrid">{volumes ? volumes.groups.map((group, index) => <Fragment key={index}>
      {group.arc && <div className="intro-volume-arc"><b>{group.arc.title}</b><small>第 {group.arc.first}–{group.arc.last} 章 · {group.volumes.length} 卷</small></div>}
      {group.volumes.map(volume => <div className="ucard" onClick={() => onVolume(volume.id)} key={volume.id}><b><span className="seal-no">{essenceNumber(volume.n)}</span>{volume.title}</b><small>第 {volume.first}–{volume.last} 章 · {volume.last - volume.first + 1} 章 · {volume.units} 个单元</small></div>)}
    </Fragment>) : outline.units.map(unit => <div className="ucard" onClick={() => onUnit(unit.n)} key={unit.n}><b><span className="seal-no">{essenceNumber(unit.n)}</span>{unit.title}</b><small>第 {unit.first}–{unit.last} 章 · {unit.last - unit.first + 1} 章</small></div>)}{tail && <div className="ucard wait" onClick={() => onChapter(tail[0])}><b><span className="seal-no">…</span>还没收尾</b><small>第 {tail[0]}–{tail[1]} 章</small></div>}</div></div>
    {book.teardown?.intro && <div className="sec"><div className="label">原书简介</div><p className="lead" style={{ fontSize: 16, whiteSpace: 'pre-line' }}>{book.teardown.intro}</p></div>}
  </div><div className="side">
    <div className="side-box"><div className="label">主要人物<span className="n">主角在前，其余按出场</span></div><ul className="plist cast2">{rail ? rail.people.slice(0, 7).map(([name, count], i) => <li key={i}><span className="nm" onClick={() => onPerson(name)}>{name}</span><span>{name === rail.hero ? <span className="chip seal">主角</span> : archetypes[name] ? <span className="chip ochre">{archetypes[name]}</span> : null}</span><span className="ct">{count} 章</span></li>)
      : people.slice(0, 7).map(person => <li key={person.id}><span className="nm" onClick={() => onPerson(person.name)}>{person.name}</span><span /><span className="ct" /></li>)}</ul></div>
    {rail && essence && <><div className="side-box"><div className="label">读者爽在哪<span className="n">各类出现几章</span></div><Bars rows={rail.tags.slice(0, 6)} unit=" 章" /></div>
      {rail.open.length > 0 && <div className="side-box"><div className="label">读者还在等<span className="n">{rail.waits.open} 件还吊着</span></div><ul className="waits2">{rail.open.map((wait, i) => <li onClick={() => onChapter(wait.at)} key={i}><b>第 {wait.at} 章立下</b>{wait.what}</li>)}</ul></div>}
      <div className="side-box"><div className="label">已拆部分的节奏<span className="n">逐章的读者感觉</span></div><FeelStrip essence={essence} /></div></>}
  </div></div></section>
}
