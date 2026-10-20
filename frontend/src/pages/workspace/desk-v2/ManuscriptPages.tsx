import { type CSSProperties, useEffect, useState } from 'react'
import { readTeardownReading, readingArrow, readingChapterNumber, writeTeardownReading } from '../../../lib/teardownReading'
import { teardownProgressView } from '../../../lib/teardownProgress'
import { useSave, useWorkspace } from '../actions'
import { ChapterText, GateCard, GateToggles, LiveText, RewritePanel, type ManuscriptNav } from '../Manuscript'
import { chapterNodes, countWords, findEntry, findNode, type VBook, type VNode, type WritePlan } from '../model'
import { useTeardownControl } from '../TeardownProgress'
import { placeOf, readyToWrite, upcomingSteps, writePlans, type WritingControl } from '../writing'
import { ChapterFoot, NodeEdit, chapterKind, chapterRest, editableNodeName, nodeName, nodePrefix, outlineOf, rangeLength, useDeskChapter } from './OutlinePages'
import { Chip, Icon } from './shared'

interface ManuscriptProps { book: VBook; id: string; nav: ManuscriptNav; writing?: WritingControl; searchWord?: string; searchToken?: number }
const wan = (value: number) => value >= 10000 ? `${Math.round(value / 10000)} 万字` : `${value} 字`
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error)
const perform = (nav: ManuscriptNav, task: Promise<unknown>) => { task.then(result => { if (typeof result === 'string' && result) nav.toast(result) }).catch(error => nav.toast(errorText(error))) }
const everyUnit = (root: VNode): VNode[] => root.kind === '单元' ? [root] : (root.children ?? []).flatMap(everyUnit)

function RetryRead({ nav, book }: { nav: ManuscriptNav; book: VBook }) {
  const control = useTeardownControl(), [open, setOpen] = useState(false)
  const failed = teardownProgressView(book, control?.job ?? null).failed
  if (!failed.length) return null
  return <div className="state"><a onClick={() => setOpen(!open)}>{failed.length} 章没读成</a>{' '}<button type="button" className="btn seal-line" disabled={control?.starting || control?.stopping} onClick={() => { if (control) perform(nav, control.retry()) }}>再试一次</button>{open && <p>{failed.map(index => `第 ${index} 章`).join('、')}</p>}</div>
}

function AuthorStart({ book, writing, nav }: { book: VBook; writing: WritingControl; nav: ManuscriptNav }) {
  const chapters = chapterNodes(book.outline), done = chapters.filter(chapter => chapter.body?.status === 'done')
  const next = chapters.find(chapter => chapter.body?.status !== 'done'), where = next ? placeOf(book.outline, next.id) : {}
  const plans = writePlans(book.outline)
  const [plan, setPlan] = useState<WritePlan>(done.length < 3 && writing.gates.trial && !writing.trialDone ? '3' : 'unit')
  const picked = plans.find(item => item.key === plan) ?? plans[0], missing = readyToWrite(book.outline), status = writing.status
  const busy = status.state === 'working' || status.state === 'waiting', stopped = status.state === 'stopped' || status.state === 'failed'
  return <>
    <div className="continue"><div><div className="k">{done.length ? '接着写' : '开写'}</div><h2>{book.title}</h2><p>{done.length ? `已写 ${done.length} 章 · ${done.reduce((sum, chapter) => sum + (chapter.body?.words ?? 0), 0).toLocaleString()} 字${where.volume ? ` · 写到 ${[where.volume, where.unit].filter(Boolean).map(node => node!.title.replace('　', ' ')).join(' / ')}` : ''}` : busy ? '第一章还在写，写完一章这里记一章。' : '还没开写。点了开写，编辑部照大纲一层层往下拆，再一章章写正文。'}</p></div>
      {missing ? <a className="btn solid" onClick={() => nav.openNode(book.outline.children?.[0]?.id ?? 'book')}>去大纲<Icon name="go" /></a>
        : busy ? <button type="button" className="btn seal-line" disabled={status.stopping} onClick={() => perform(nav, writing.stop())}>{status.stopping ? '正在停' : '停下这一轮'}</button>
          : <button type="button" className="btn solid" disabled={!!writing.blocked} onClick={() => perform(nav, stopped ? writing.resume() : writing.start(plan))}>{done.length || stopped ? '接着写' : '开写'}<Icon name="go" /></button>}
    </div>
    {missing ? <p className="state">{missing}</p> : busy ? <p className="state">{status.state === 'working' ? `编辑部正在写：${status.doing ?? ''}。` : `编辑部在等你拍板：${status.gate?.title ?? ''}。`}这一轮写完或停下以后，才能开新的一轮。{status.gate && <a onClick={() => status.gate && (status.gate.kind === 'trial' || status.gate.kind === 'stuck' ? nav.openChapter(status.gate.node) : nav.openNode(status.gate.node))}>去看看</a>}</p>
      : stopped ? <p className="state">{status.state === 'failed' ? `出错停下了：${status.error} ` : ''}{status.note}</p>
        : <div className="sec"><div className="label">这一轮写多少</div><div className="names">{plans.map(item => <button type="button" key={item.key} className={`btn ${item.key === plan ? 'solid' : 'seal-line'}`} aria-pressed={item.key === plan} onClick={() => setPlan(item.key)}>{item.label}</button>)}</div><p className="small">{picked.hint}</p>{writing.blocked && <p className="state">{writing.blocked}</p>}<div className="label">开写以后会这样走</div><ol className="tl">{upcomingSteps(book.outline, writing.gates, writing.trialDone, writing.rewrites).map(step => <li key={step}>{step}</li>)}</ol></div>}
    <div className="sec"><div className="desk-legacy" style={{ display: 'contents' }}><GateToggles writing={writing} nav={nav} /></div></div>
  </>
}

function ManuscriptHome({ book, writing, nav }: ManuscriptProps) {
  const chapters = chapterNodes(book.outline), saved = readTeardownReading(book.id)
  const resume = saved ? chapters.find(chapter => readingChapterNumber(chapter) === saved.chapter) : undefined
  const selected = resume ?? chapters[0], readAt = resume ? readingChapterNumber(resume) : 0
  const units = everyUnit(book.outline).filter(unit => !unit.virtual), allUnits = everyUnit(book.outline)
  const volume = selected ? placeOf(book.outline, selected.id).volume : undefined
  const firstVolume = units[0] ? placeOf(book.outline, units[0].id).volume : volume
  const hangStart = allUnits.filter(unit => unit.virtual).map(unit => unit.range?.[0]).filter((value): value is number => value !== undefined).sort((a, b) => a - b)[0]
  const teardown = book.source === 'teardown', total = book.teardown?.chapters ?? chapters.length
  const done = chapters.filter(chapter => chapter.body?.status === 'done')
  return <section className="page"><div className="kicker">正文</div><h1>{book.title}</h1><div className="meta">{teardown ? <>已导入 {total} 章 · {wan(book.teardown?.chars ?? 0)}{readAt ? ` · 读到第 ${readAt} 章` : ''}</> : <>已写 {done.length} 章 · {wan(done.reduce((sum, chapter) => sum + (chapter.body?.words ?? 0), 0))}</>}</div><div className="rule1" />
    {teardown ? <>{selected && <div className="continue"><div><div className="k">{resume ? '接着读' : '从头读'}</div><h2>第 {readingChapterNumber(selected)} 章 {nodeName(selected)}</h2>{outlineOf(selected).goal && <p>这一章：{outlineOf(selected).goal}</p>}</div><a className="btn solid" onClick={() => nav.openChapter(selected.id)}>{resume ? '接着读' : '从第 1 章读起'}<Icon name="go" /></a></div>}<RetryRead nav={nav} book={book} /></> : writing && <AuthorStart book={book} writing={writing} nav={nav} />}
    {!!units.length && <div className="sec" style={{ marginTop: 24 }}><div className="label">{teardown ? '按单元读' : '按单元看'}<span className="n">{firstVolume ? nodeName(firstVolume) : ''}{teardown ? ' · 已拆部分' : ''}</span></div>
      {units.map((unit, index) => {
        const count = rangeLength(unit), read = teardown ? Math.max(0, Math.min(readAt, unit.range?.[1] ?? 0) - (unit.range?.[0] ?? 1) + 1) : chapterNodes(unit).filter(chapter => chapter.body?.status === 'done').length
        const target = teardown && readAt >= (unit.range?.[0] ?? 1) && readAt <= (unit.range?.[1] ?? 0) ? chapters.find(chapter => readingChapterNumber(chapter) === readAt) : chapterNodes(unit)[0]
        return <div className="urow" key={unit.id} onClick={() => target ? nav.openChapter(target.id) : nav.openNode(unit.id)}><span className="seal-no">{['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'][index] ?? index + 1}</span><span className="t">{nodeName(unit)}<small>第 {unit.range?.[0]}–{unit.range?.[1]} 章</small></span><span className="pg"><b style={{ width: `${count ? read / count * 100 : 0}%` }} /></span><span className="r">{teardown ? read ? `读到第 ${readAt} 章` : '还没读到' : `已写 ${read} / ${count} 章`}</span></div>
      })}
      {teardown && hangStart !== undefined && <div className="urow" onClick={() => { const first = chapters.find(chapter => readingChapterNumber(chapter) === hangStart); if (first) nav.openChapter(first.id) }}><span className="seal-no" style={{ borderStyle: 'dashed', color: 'var(--ink-3)' }}>…</span><span className="t" style={{ color: 'var(--ink-3)' }}>还没归单元、还没拆的<small>第 {hangStart}–{total} 章</small></span><span className="pg" /><span className="r">{readAt >= hangStart ? `读到第 ${readAt} 章` : '还没读到'}</span></div>}
    </div>}
    {!units.length && teardown && <p className="state">还没归单元</p>}
  </section>
}

function OutlineRail({ node }: { node: VNode }) {
  const outline = outlineOf(node)
  if (!outline.goal && !outline.scenes.length && !outline.cool && !outline.hook) return null
  return <aside className="rail">
    {(!!outline.goal || !!outline.scenes.length) && <div className="rb"><h3>对照章纲<span className="n">边读边看</span></h3><div style={{ font: '15px/1.75 var(--serif)', color: 'var(--ink)' }}>{outline.goal}</div><ul className="tl" style={{ marginTop: 10 }}>{outline.scenes.map((scene, index) => <li key={index}><b>{index + 1}</b>{scene}</li>)}</ul></div>}
    {!!outline.cool && <div className="rb"><h3>看点</h3><div style={{ font: '14.5px/1.75 var(--serif)' }}><Chip text={chapterKind(outline.cool)} />{chapterRest(outline.cool)}</div></div>}
    {!!outline.hook && <div className="rb"><h3>结尾钩子</h3><div style={{ font: '14.5px/1.75 var(--serif)' }}><Chip text={chapterKind(outline.hook)} />{chapterRest(outline.hook)}</div></div>}
  </aside>
}

function ManuscriptChapter({ book, id, nav, writing, searchWord, searchToken }: ManuscriptProps) {
  const { actions } = useWorkspace(), save = useSave()
  const path = findNode(book.outline, id), node = path?.at(-1), query = useDeskChapter(book, node, writing)
  const [rewriting, setRewriting] = useState(false), [previous, setPrevious] = useState<string>()
  const teardown = book.source === 'teardown', chapters = chapterNodes(book.outline), at = chapters.findIndex(chapter => chapter.id === id)
  const chapterNumber = node ? readingChapterNumber(node) : 0, previousChapter = chapters[at - 1], nextChapter = chapters[at + 1]
  useEffect(() => { if (teardown && chapterNumber) writeTeardownReading(book.id, chapterNumber) }, [book.id, chapterNumber, teardown])
  useEffect(() => {
    if (!teardown) return
    const turn = (event: KeyboardEvent) => { const direction = readingArrow(event), target = direction === -1 ? previousChapter : direction === 1 ? nextChapter : undefined; if (target) { event.preventDefault(); nav.openChapter(target.id) } }
    window.addEventListener('keydown', turn)
    return () => window.removeEventListener('keydown', turn)
  }, [nav, nextChapter, previousChapter, teardown])
  if (!node || node.kind !== '章') return <section className="page"><p className="state">这一章找不到了。</p></section>
  const { volume, unit } = placeOf(book.outline, id), body = node.body, state = writing?.status
  const text = body?.text ?? query.data?.text, live = !teardown && state?.chapter === id ? state.live : undefined
  const gate = !teardown && state?.state === 'waiting' && state.gate && (state.gate.kind === 'trial' ? chapters.slice(0, 3).some(chapter => chapter.id === id) : state.gate.node === id) ? state.gate : undefined
  const busy = state?.state === 'working' || state?.state === 'waiting', done = body?.status === 'done'
  const meta = live !== undefined ? `写手在写 · 已写 ${countWords(live)} 字` : `${(body?.words ?? 0).toLocaleString()} 字`
  const review = body?.review ?? query.data?.review, changes = body?.changes ?? query.data?.changes
  const cast = node.uses.map(entryId => findEntry(book, entryId)).filter(entry => !!entry)
  const exportText = () => {
    const blob = new Blob([`${node.title.replace('　', ' ')}\n\n${text ?? ''}\n`], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = `${node.title.replace('　', ' ')}.txt`; link.click(); URL.revokeObjectURL(url)
  }
  return <><section className="page reader"><div className="head"><div className="kicker">{volume ? nodeName(volume) : ''}{unit && !unit.virtual ? ` · ${nodePrefix(unit)} ${nodeName(unit)}` : unit?.virtual ? ' · 还没归单元' : ''}</div>
    <NodeEdit as="h1" value={editableNodeName(node)} label="给这一章起个名字" save={actions.canEdit(node, 'name') ? value => { if (value.trim()) save(actions.saveNode(node, { name: value.trim() })) } : undefined}>第 {chapterNumber} 章 {nodeName(node)}</NodeEdit>
    <div className="meta">{meta} · <a onClick={() => nav.openNode(id)}>去大纲看章纲</a></div></div>
    {!teardown && writing && <>
      {gate && <div className="desk-legacy" style={{ display: 'contents' }}><GateCard gate={gate} writing={writing} nav={nav} where={gate.kind === 'trial' ? `这是第 ${at + 1} 章` : undefined} /></div>}
      {rewriting && <div className="desk-legacy" style={{ display: 'contents' }}><RewritePanel node={node} later={chapters.slice(at + 1).filter(chapter => chapter.body?.status === 'done').length} onCancel={() => setRewriting(false)} onGo={request => { setRewriting(false); writing.rewrite(node, request).then(before => before === null ? nav.toast('交给写手了：写好会在这里换上，照样过审稿') : setPrevious(before)).catch(error => nav.toast(errorText(error))) }} /></div>}
      {previous !== undefined && done && state?.state !== 'working' && <p className="small">这是照你的意见重写的一版。<a onClick={() => { perform(nav, writing.setText(node, previous).then(() => '换回了原来的')); setPrevious(undefined) }}>换回原来的</a></p>}
    </>}
    <div className="reading-prose" style={{ marginTop: 26 } as CSSProperties}>
      {live !== undefined ? <><p className="state">写手正在写这一章，写完先过审稿，再由设定师记下变化。</p><div className="desk-legacy" style={{ display: 'contents' }}><LiveText text={live} /></div></>
        : text !== undefined && body?.status !== 'planned' ? <div className="desk-legacy" style={{ display: 'contents' }}><ChapterText text={text} spot={`t|${id}`} readOnly={teardown} searchWord={searchWord} searchToken={searchToken} onSave={!teardown && writing ? value => perform(nav, writing.setText(node, value).then(() => '存好了')) : undefined} /></div>
          : query.isError ? <div className="state"><p role="alert">{errorText(query.error)}</p><button type="button" className="btn seal-line" onClick={() => void query.refetch()}>重新加载</button></div>
            : body?.status !== 'planned' ? <p className="state">正在读这一章…</p> : <div className="state"><p>这一章还没写</p><p>{chapters.find(chapter => chapter.body?.status !== 'done')?.id === id ? '接着写就从这一章开始。' : '写到这里时，正文会在这里一句句出来。'}章纲在大纲里，想改去那里改。</p>{!teardown && !busy && <a className="btn solid" onClick={() => nav.openChapter('home')}>去开写</a>}</div>}
    </div>
    {!teardown && writing && <>
      {done && text && <div className="sec"><div className="names"><button type="button" className="btn seal-line" onClick={() => busy ? nav.toast('编辑部手上还有活，停下或写完以后再重写') : writing.blocked ? nav.toast(writing.blocked) : setRewriting(true)}>按意见重写这一章</button>{writing.redigest && <button type="button" className="btn seal-line" onClick={() => perform(nav, writing.redigest!(node))}>让设定师照改过的重看一遍</button>}<button type="button" className="btn seal-line" onClick={exportText}>导出这一章 TXT</button></div></div>}
      {!!body?.attempts && <p className="small">审稿退回重写过 {body.attempts} 次</p>}
      {!!changes?.length && <details className="sec"><summary className="label">设定师记下的变化 · {changes.length} 处</summary><ul className="tl">{changes.map(change => <li key={change}>{change}</li>)}</ul></details>}
      {review && (!!review.good.length || !!review.issues.length) && <details className="sec"><summary className="label">审稿</summary><ul className="tl">{review.good.map(item => <li key={item}>✓{item}</li>)}{review.issues.map(item => <li key={item}>→{item}</li>)}</ul></details>}
      {!!cast.length && <div className="sec"><div className="label">用到的设定</div><div className="names">{cast.map(entry => <span key={entry!.id} onClick={() => nav.openEntry(entry!.id)}>{entry!.name}</span>)}</div></div>}
    </>}
    <ChapterFoot book={book} node={node} nav={nav} manuscript />
  </section><OutlineRail node={node} /></>
}

export function DeskManuscript(props: ManuscriptProps) {
  return props.id === 'home' ? <ManuscriptHome {...props} /> : <ManuscriptChapter key={`${props.book.id}/${props.id}`} {...props} />
}
