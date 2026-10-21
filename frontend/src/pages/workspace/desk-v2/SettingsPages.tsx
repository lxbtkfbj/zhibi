import { useQuery } from '@tanstack/react-query'
import { Lock, Pencil, Pin, Plus, SlidersHorizontal, Trash2, Unlock, X } from 'lucide-react'
import { Fragment, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { get } from '../../../api/client'
import { useBookMeta } from '../../../api/newBook'
import { CategoryPicker, LengthInput, Row, TagPicker } from '../../../components/BookFields'
import { teardownAddedText, teardownAppendEntryText } from '../../../lib/teardownAppend'
import { useSave, useWorkspace, type CategoryStyle } from '../actions'
import {
  chapterNodes, cn, findEntry, isLadder, nounOf, splitTitle, templateOf, valueOf,
  type VBook, type VCategory, type VEntry,
} from '../model'
import { AskPanel, CardTemplateEditor } from '../Workspace'
import { useTeardownControl } from '../TeardownProgress'
import { More, Refs } from './shared'
import { DeskEdit } from './settingsEditing'
import { characterFieldLabel, clean, currentRead, emptyTeardownSettingsMeta, isOneLineCharacter, momentLines, nodes, orderedCharacters, spans, wan } from './settingsData'
import './settingsEditing.css'

export interface DeskNav {
  openEntry: (id: string) => void
  openNode: (id: string) => void
  openChapter: (id: string) => void
  toast: (text: string) => void
}

type Accept = (items: { name: string; text: string }[]) => void
const css = (value: Record<string, string | number>) => value as CSSProperties

function field(entry: VEntry, key: string): string {
  return clean(valueOf(entry, key))
}


function Ladder({ entry }: { entry?: VEntry }) {
  const levels = entry?.levels ?? []
  const current = levels.findLast(level => level.protagonistChapter != null)
  return levels.length ? <div className="ladder">{levels.map((level, index) => <Fragment key={index}>
    {index ? <em>›</em> : null}<span className={level === current ? 'me' : undefined}>{level.name}</span>
  </Fragment>)}</div> : null
}

function Rhythm({ book, nav }: { book: VBook; nav: DeskNav }) {
  const last = currentRead(book)
  const units = nodes(book.outline).filter(node => node.kind === '单元' && node.range && (!book.teardown || node.range[0] <= last))
  if (!units.length) return null
  let index = 0
  return <div className="rhythm">{units.map(unit => {
    const end = book.teardown ? Math.min(unit.range![1], last) : unit.range![1]
    const label = unit.virtual ? '…' : cn(++index)
    return <i key={unit.id} className={unit.virtual ? 'wait' : undefined} style={css({ '--w': end - unit.range![0] + 1 })}
      title={unit.virtual ? `第 ${unit.range![0]}–${end} 章还没归单元` : `第 ${unit.range![0]}–${end} 章「${splitTitle(unit.title)[1] || unit.title}」`}
      onClick={() => nav.openNode(unit.id)}>{label}</i>
  })}</div>
}

function BasicInfo({ book, close }: { book: VBook; close: () => void }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const meta = useBookMeta()
  const [length, setLength] = useState(book.length ? String(book.length) : '')
  return <div className="settings-sheet desk-legacy"><div className="settings-close"><button className="btn seal-line" onClick={close}>收起</button></div>
    <div className="label">基本信息</div>
    <Row label="类别"><CategoryPicker meta={meta} value={{ channel: book.channel as '男频' | '女频' | '', genre: book.genre }}
      onChange={next => save(actions.saveBook({ channel: next.channel, genre: next.genre }))} /></Row>
    <Row label="标签"><TagPicker meta={meta} channel={book.channel as '男频' | '女频' | ''} value={book.tags}
      onChange={tags => save(actions.saveBook({ tags }))} /></Row>
    <Row label="篇幅"><LengthInput text={length} chapterWords={book.chapterWords} onChange={setLength}
      onBlur={() => { const next = length ? Number(length) : null; if (next !== (book.length ?? null)) save(actions.saveBook({ length: next })) }} /></Row>
  </div>
}

export function DeskIntro({ book, nav }: { book: VBook; nav: DeskNav }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [info, setInfo] = useState(false)
  const teardown = book.source === 'teardown'
  const data = book.teardown
  const characters = book.categories.find(category => category.name === '角色列表')?.entries ?? []
  const cast = orderedCharacters(characters, teardown).slice(0, 6)
  const goldfingers = book.categories.find(category => category.name === '金手指')?.entries ?? []
  const ladder = book.categories.find(category => category.name === '等级体系')?.entries[0]
  const highest = ladder?.levels?.findLast(level => level.protagonistChapter != null)
  const units = nodes(book.outline).filter(node => node.kind === '单元' && !node.virtual)
  const written = chapterNodes(book.outline).filter(node => node.body?.status === 'done').length
  const last = currentRead(book)
  const upto = data?.settings?.upto
  return <section className="page full" style={{ position: 'relative' }}>
    {!teardown && <div className="settings-tools"><div className="settings-buttons"><button aria-label="基本信息" title="基本信息" onClick={() => setInfo(true)}><SlidersHorizontal /></button></div></div>}
    <div className="intro-top">
      <div className="hero">
        <div className="cover"><span className="lbl">{book.title}</span><span className="stamp">执笔</span></div>
        <div>
          <div className="kicker">{teardown ? '拆的书' : '我的书'}</div>
          <DeskEdit as="h1" value={book.title} placeholder="书名" onSave={title => { if (title.trim()) save(actions.saveBook({ title: title.trim() })) }} />
          {teardown ? <><div className="meta">原书作者 {data?.author} · {wan(data?.chars ?? 0)} · {data?.chapters ?? 0} 章 · {data?.original_volumes === false ? '原书没有分卷' : `原书分了 ${data?.volumes ?? 0} 卷`}</div>
            <div className="meta" style={{ marginTop: 2 }}>{(data?.imported_at ?? '').slice(0, 10)} 导入{teardownAddedText(data)}{data?.number_issue_total ? ` · 原书章号对不上 ${data.number_issue_total} 处` : ''}</div></>
            : <><div className="meta">{book.genre || '未分类'} · 计划 {book.length ?? 0} 万字 · 已写 {written} 章</div><div className="meta" style={{ marginTop: 2 }}>{(book.createdAt ?? '').slice(0, 10)} 开书</div></>}
          <div className="statline">{teardown ? <><span className="chip seal">已拆 {last} / {data?.chapters ?? 0} 章</span><span className="chip ochre">{units.length} 个单元</span>{upto != null && <span className="chip jade">设定整理到第 {upto} 章</span>}<a className="btn seal-line" data-testid="teardown-append-entry" href={`/teardown/${book.id}/append`}>{teardownAppendEntryText(data)}</a></> : book.tags.map(tag => <span className="chip plain" key={tag}>{tag}</span>)}</div>
          {!!units.length && <><div className="small" style={{ marginTop: 12 }}>{teardown ? '已拆部分的节奏（一格一个单元）' : '全书的节奏（一格一个单元）'}</div><Rhythm book={book} nav={nav} /></>}
        </div>
      </div>
      {!!cast.length && <div className="side-box"><div className="label">主要人物<span className="n">{teardown ? '出场多的在前' : '置顶的在前'}</span></div><ul className="plist one">{cast.map(entry => <li key={entry.id} title={entry.oneLine} onClick={() => nav.openEntry(entry.id)}><span className="nm">{entry.name}</span><span className="ds">{clean(entry.oneLine)}</span></li>)}</ul></div>}
      {(goldfingers.length > 0 || ladder) && <div className="side-box"><div className="label">金手指和等级</div>
        {!!goldfingers.length && <ul className="plist">{goldfingers.map(entry => <li key={entry.id} onClick={() => nav.openEntry(entry.id)}><span className="nm">{entry.name}</span><span className="ct">{entry.createdChapter ? `第 ${entry.createdChapter} 章` : ''}</span></li>)}</ul>}
        {ladder && <><div style={{ marginTop: 8 }}><Ladder entry={ladder} /></div><div className="small" style={{ marginTop: 6 }}>红色是主角到过的最高一级{highest ? `（第 ${highest.protagonistChapter} 章到）` : ''}</div></>}
      </div>}
    </div>
    {!teardown && <><div className="label" style={{ marginTop: 22 }}>简介</div><DeskEdit as="p" className="lead" value={book.blurb} placeholder="写给读者看的那段话" spot="b" onSave={blurb => save(actions.saveBook({ blurb }))} /></>}
    {info && <BasicInfo book={book} close={() => setInfo(false)} />}
  </section>
}

function Names({ entries, nav, cap = 8 }: { entries: VEntry[]; nav: DeskNav; cap?: number }) {
  return <div className="names"><More items={entries} cap={cap} unit="个">{entry => <span key={entry.id} onClick={event => { event.stopPropagation(); nav.openEntry(entry.id) }}>{entry.name}</span>}</More></div>
}

function NewCategory({ book, nav, close }: { book: VBook; nav: DeskNav; close: () => void }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [name, setName] = useState(''), [style, setStyle] = useState<CategoryStyle>('card'), [fields, setFields] = useState('')
  const [busy, setBusy] = useState(false)
  const title = name.trim()
  const duplicate = book.categories.some(category => category.name === title)
  const create = () => {
    if (!title || duplicate || busy) return
    const columns = style === 'card' ? [...new Set(fields.split(/[、,，;；\s]+/).map(value => value.trim()).filter(Boolean))] : []
    const about = style === 'card' ? columns.length ? `每条有这几栏：${columns.join('、')}。` : '每条有哪几栏，自己定。' : style === 'ladder' ? '一级一级往上排，每级一个名称加一段介绍。' : '一个名字加一段话。'
    setBusy(true)
    save(actions.createCategory(title, style, columns, about).then(() => { close(); nav.openEntry(`cat:${title}`) }).finally(() => setBusy(false)))
  }
  return <Sheet close={close}><div className="label">新建类别</div><div className="settings-form">
    <label>类名<input aria-label="类名" autoFocus maxLength={20} value={name} placeholder="比如：厉鬼、剧本、副本" onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) create() }} /></label>
    <label>样式<select aria-label="样式" value={style} onChange={event => setStyle(event.target.value as CategoryStyle)}><option value="card">卡片 · 一栏一栏填，栏目自己定</option><option value="paragraph">段落 · 一个名字加一段话</option><option value="ladder">阶梯 · 一级一级往上排</option></select></label>
    {style === 'card' && <label>字段<input aria-label="字段" value={fields} placeholder="用顿号隔开：杀人规律、关押方法、等级" onChange={event => setFields(event.target.value)} /></label>}
    {duplicate && <div className="state">已经有这一类了</div>}
    <div className="settings-actions"><button className="btn seal-line" onClick={close}>取消</button><button className="btn solid" disabled={!title || duplicate || busy} onClick={create}>{busy ? '正在建' : '建好这一类'}</button></div>
  </div></Sheet>
}

function SettingsOverview({ book, nav }: { book: VBook; nav: DeskNav }) {
  const [creating, setCreating] = useState(false)
  const control = useTeardownControl()
  const emptyMeta = emptyTeardownSettingsMeta(book, control?.job ?? null)
  const entries = (name: string) => book.categories.find(category => category.name === name)?.entries ?? []
  const people = orderedCharacters(entries('角色列表'), book.source === 'teardown'), goldfingers = entries('金手指'), ladders = entries('等级体系'), places = entries('地点列表')
  const factions = entries('势力列表'), items = entries('物品功法'), secrets = entries('往事秘密'), rules = entries('特殊规则')
  const placeIds = new Set(places.map(entry => entry.id))
  const roots = places.filter(entry => !entry.parent || !placeIds.has(entry.parent))
  const groups = new Map<string, VEntry[]>()
  for (const entry of places) if (entry.parent && placeIds.has(entry.parent)) groups.set(entry.parent, [...groups.get(entry.parent) ?? [], entry])
  const open = (name: string) => () => nav.openEntry(`cat:${name}`)
  const teardown = book.source === 'teardown'
  const upto = book.teardown?.settings?.upto
  return <section className="page full"><div className="kicker">设定总览</div><h1>设定</h1>
    <div className="meta">{emptyMeta ?? (teardown ? upto != null ? `拆书整理到第 ${upto} 章 · 你改过的条目以后接着拆也不会被盖掉` : '设定还没整理' : '这本书的人物、世界和规矩')}</div>
    <div className="rule1" />{emptyMeta === null && <div className="tiles">
      <div className="tile" onClick={open('角色列表')}><div className="hd"><b>角色列表</b><span>{people.length} 人写了全卡</span></div><Names entries={people} nav={nav} /></div>
      <div className="tile" onClick={open('金手指')}><div className="hd"><b>金手指</b><span>{goldfingers.length} 条</span></div><div className="kv">{goldfingers.map(entry => <Fragment key={entry.id}><b onClick={event => { event.stopPropagation(); nav.openEntry(entry.id) }}>{entry.name}</b><span className="ell" title={field(entry, '是什么')}>{entry.createdChapter ? `第 ${entry.createdChapter} 章出现 · ` : ''}{field(entry, '是什么')}</span></Fragment>)}</div></div>
      <div className="tile" onClick={open('等级体系')}>{ladders.length ? ladders.map(entry => <Fragment key={entry.id}><div className="hd"><b>等级体系</b><span className="ell" title={entry.overview}>{entry.name} · {entry.levels?.length ?? 0} 级 · {entry.overview}</span></div><Ladder entry={entry} /></Fragment>) : <div className="hd"><b>等级体系</b><span>还没有</span></div>}</div>
      <div className="tile" onClick={open('地点列表')}><div className="hd"><b>地点列表</b><span>{places.length} 处，按属于哪里排</span></div><div className="ptree">{roots.map((entry, index) => <Fragment key={entry.id}>{index ? '、' : ''}{entry.name}{entry.createdChapter ? <small>第 {entry.createdChapter} 章</small> : null}</Fragment>)}{[...groups].map(([parent, children]) => <div className="sub" key={parent}>{places.find(entry => entry.id === parent)?.name} › {children.map((entry, index) => <Fragment key={entry.id}>{index ? '、' : ''}{entry.name}{entry.createdChapter ? <small>{entry.createdChapter}</small> : null}</Fragment>)}</div>)}</div></div>
      <div className="tile" onClick={open('势力列表')}><div className="hd"><b>势力列表</b><span>{factions.length} 个</span></div><Names entries={factions} nav={nav} /></div>
      <div className="tile" onClick={open('物品功法')}><div className="hd"><b>物品功法</b><span>{items.length} 样</span></div><Names entries={items} nav={nav} /></div>
      <div className="tile" onClick={open('往事秘密')}><div className="hd"><b>往事秘密</b><span>{secrets.length} 条</span></div><div className="kv"><More items={secrets} cap={3}>{entry => <Fragment key={entry.id}><b>{entry.name}</b><span>{entry.createdChapter ? `第 ${entry.createdChapter} 章埋下` : '埋下的章没记'} · {/第\s*\d+\s*章揭开/.exec(field(entry, '打算何时揭开'))?.[0] || '还没揭开'}</span></Fragment>}</More></div></div>
      <div className="tile" onClick={open('特殊规则')}><div className="hd"><b>特殊规则</b><span>{rules.length} 条</span></div><Names entries={rules} nav={nav} /></div>
      {book.categories.filter(category => category.custom).map(category => <div className="tile" key={category.key} onClick={open(category.name)}><div className="hd"><b>{category.name}</b><span>{category.entries.length} 条</span></div><Names entries={category.entries} nav={nav} /></div>)}
    </div>}
    {!teardown && <div className="settings-actions"><button className="btn seal-line" onClick={() => setCreating(true)}>新建类别</button></div>}
    {creating && <NewCategory book={book} nav={nav} close={() => setCreating(false)} />}
  </section>
}

function Sheet({ children, close }: { children: ReactNode; close: () => void }) {
  return <div className="settings-sheet desk-legacy"><div className="settings-close"><button className="btn seal-line" onClick={close}>收起</button></div>{children}</div>
}

function EntryButtons({ entry, nav, edit }: { entry: VEntry; nav: DeskNav; edit: () => void }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [confirm, setConfirm] = useState(false)
  if (entry.readonly) return null
  const draft = entry.id.startsWith('draft-')
  return <div className="settings-tools"><div className="settings-buttons">
    <button title="编辑资料和空栏目" aria-label="编辑资料和空栏目" onClick={edit}><Pencil /></button>
    {!draft && entry.kind === 'character' && actions.pinEntry && <button title={entry.pinnedAt ? '取消置顶' : '置顶'} aria-label={entry.pinnedAt ? '取消置顶' : '置顶'} onClick={() => save(actions.pinEntry!(entry, !entry.pinnedAt))}><Pin fill={entry.pinnedAt ? 'currentColor' : 'none'} /></button>}
    {!draft && <button title={entry.locked ? '解锁' : '锁住'} aria-label={entry.locked ? '解锁' : '锁住'} onClick={() => save(actions.saveEntry(entry, { locked: !entry.locked }))}>{entry.locked ? <Lock /> : <Unlock />}</button>}
    <button title={confirm ? '再点一次删掉' : '删掉这一条'} aria-label={confirm ? '再点一次删掉' : '删掉这一条'} onClick={() => { if (!confirm) { setConfirm(true); return } save(actions.deleteEntry(entry).then(() => nav.openEntry(`cat:${entry.category}`))) }}><Trash2 /></button>
  </div></div>
}

function EntryEditor({ entry, close, relations }: { entry: VEntry; close: () => void; relations?: () => void }) {
  const { actions } = useWorkspace()
  const save = useSave()
  return <Sheet close={close}><div className="label">{entry.name || '起个名字'}</div><div className="settings-form">
    <label>一句话<DeskEdit value={entry.oneLine} onSave={oneLine => save(actions.saveEntry(entry, { oneLine }))} placeholder="一句话说清这是谁、这是什么" spot={`e|${entry.id}|@oneLine`} /></label>
    {entry.facts.map(([label, text, placeholder, key]) => <label key={key ?? label}>{label}<DeskEdit value={text} placeholder={placeholder || '写一下'} onSave={value => save(actions.saveEntry(entry, { fields: { [key ?? label]: value } }))} /></label>)}
    {entry.sections.map(section => <label key={section.key ?? section.label}>{section.label}<DeskEdit as="p" value={section.text} placeholder={section.placeholder || '还没写'} onSave={text => save(actions.saveEntry(entry, { fields: { [section.key ?? section.label]: text } }))} spot={`e|${entry.id}|${section.key ?? section.label}`} /></label>)}
  </div>{relations && <div className="settings-actions"><button className="btn seal-line" onClick={relations}>和别人的关系</button></div>}</Sheet>
}

function RelationEditor({ book, entry, close }: { book: VBook; entry: VEntry; close: () => void }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const people = book.categories.find(category => category.name === '角色列表')?.entries.filter(person => person.id !== entry.id && !person.id.startsWith('draft-')) ?? []
  const [target, setTarget] = useState(''), [kind, setKind] = useState(''), [description, setDescription] = useState('')
  return <Sheet close={close}><div className="label">和别人的关系</div><ul className="plist">{entry.relations?.map(relation => <li key={relation.id ?? relation.to + relation.kind}><span className="nm">{findEntry(book, relation.to)?.name}</span><button className="btn seal-line" onClick={() => save(actions.deleteRelation(entry, relation))}>删掉</button><DeskEdit as="span" className="ds" value={relation.text} placeholder="怎么个关系，一句话" onSave={text => save(actions.saveRelation(entry, relation, text))} /></li>)}</ul>
    <div className="settings-form"><select aria-label="和谁" value={target} onChange={event => setTarget(event.target.value)}><option value="">和谁</option>{people.map(person => <option value={person.id} key={person.id}>{person.name}</option>)}</select><input aria-label="什么关系" placeholder="什么关系：师父、仇人" value={kind} onChange={event => setKind(event.target.value)} /><input aria-label="关系说明" placeholder="一句话说说（可以不写）" value={description} onChange={event => setDescription(event.target.value)} /><button className="btn solid" disabled={!target || !kind.trim()} onClick={() => { save(actions.addRelation(entry, target, kind.trim(), description.trim())); setTarget(''); setKind(''); setDescription('') }}>新增关系</button></div>
  </Sheet>
}

const LONG_FIELDS = ['外貌', '性格与说话方式', '身世', '想要什么', '软肋', '能力', '成长与结局']
const EMPTY_FIELDS = ['所属', '性别', '年龄', '别名', ...LONG_FIELDS]

function CharacterPage({ book, entry, nav, fresh }: { book: VBook; entry: VEntry; nav: DeskNav; fresh: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [editing, setEditing] = useState(false), [relations, setRelations] = useState(false)
  const teardown = book.source === 'teardown'
  const appearances = useQuery({ queryKey: ['desk-v2-appearances', book.id, entry.id], queryFn: () => get<{ chapters: number[]; lines: { chapter: number; shown: string; change: string }[] }>(`/books/${book.id}/teardown/appearances?character=${encodeURIComponent(entry.id)}`), enabled: teardown && actions.live && !entry.id.startsWith('draft-'), staleTime: 10000 })
  const seen = appearances.data?.chapters ?? []
  const appearanceLines = [...(appearances.data?.lines ?? [])].sort((a, b) => a.chapter - b.chapter)
  const moments = teardown ? momentLines(entry) : []
  const empty = EMPTY_FIELDS.filter(key => !field(entry, key)).map(key => characterFieldLabel(key, teardown))
  const oneLineOnly = teardown && isOneLineCharacter(entry)
  const last = currentRead(book)
  const now = entry.now?.map(([label, text]) => [label === '想要' ? '此刻想要' : label, text]).filter(([, text]) => clean(text)) ?? []
  const saveField = (key: string) => entry.readonly ? undefined : (text: string) => save(actions.saveEntry(entry, { fields: { [key]: text } }))
  const sections = (teardown ? [...LONG_FIELDS.map(key => entry.sections.find(section => (section.key ?? section.label) === key)).filter(section => section != null), ...entry.sections.filter(section => !LONG_FIELDS.includes(section.key ?? section.label) && (section.key ?? section.label) !== '名场面')] : entry.sections).filter(section => clean(section.text))
  const links = (entry.relations ?? []).filter(relation => findEntry(book, relation.to))
  const hasRail = links.length > 0 || teardown && (seen.length > 0 || empty.length > 0 || oneLineOnly) || !teardown && entry.appears.length > 0
  return <><section className="page" id={`entry-${entry.id}`} data-entry={entry.id} style={{ position: 'relative' }}>
    <EntryButtons entry={entry} nav={nav} edit={() => setEditing(true)} />
    <div className="kicker">角色列表</div><DeskEdit as="h1" value={entry.name} fresh={fresh} placeholder="起个名字" onSave={entry.readonly ? undefined : name => { if (name.trim()) save(actions.saveEntry(entry, { name })) }} />
    {teardown && <div className="meta">{seen.length || entry.firstAppearanceChapter ? `第一次出场 第 ${seen[0] ?? entry.firstAppearanceChapter} 章 · 已拆的各章里出场 ${seen.length} 章 · ${moments.length} 场名场面` : '还没记下出场章号'}</div>}
    {oneLineOnly && <DeskEdit as="p" className="lead" value={entry.oneLine} onSave={entry.readonly ? undefined : oneLine => save(actions.saveEntry(entry, { oneLine }))} spot={`e|${entry.id}|@oneLine`} />}
    <div className="facts">{teardown && clean(entry.role) && <span>定位<b>{entry.role}</b></span>}{teardown ? ['所属', '性别', '年龄', '别名'].map(key => field(entry, key) ? <span key={key}>{key}<DeskEdit as="b" value={field(entry, key)} onSave={saveField(key)} /></span> : null) : entry.facts.filter(([label]) => label !== '定位').map(([label, text, , key]) => clean(text) ? <span key={key ?? label}>{label}<DeskEdit as="b" value={text} onSave={saveField(key ?? label)} /></span> : null)}</div>
    {!teardown && clean(entry.oneLine) && <DeskEdit as="p" className="lead" value={entry.oneLine} onSave={entry.readonly ? undefined : oneLine => save(actions.saveEntry(entry, { oneLine }))} spot={`e|${entry.id}|@oneLine`} />}
    {(now.length > 0 || entry.dead) && <div className="now"><div className="t">{teardown ? `此刻 · 第 ${book.teardown?.settings?.upto ?? last} 章` : '此刻 · 设定师每写完一章更新'}</div>{now.map(([label, text]) => <Fragment key={label}><span>{label}</span><b>{text}</b></Fragment>)}{entry.dead && <><span>是否活着</span><b>已死</b></>}</div>}
    <div className="rule1" />
    {oneLineOnly && <div className="sec" style={{ marginTop: 0 }}><div className="label">出场那几章<span className="n">逐章记录里写的</span></div><ul className="moments">{appearanceLines.map(line => <li key={line.chapter}><span className="ch" onClick={() => nav.openNode(`c${line.chapter}`)}>第 {line.chapter} 章</span><p>{line.shown}{line.change && <span className="shows">变化：{line.change}</span>}</p></li>)}</ul></div>}
    {moments.length > 0 && <div className="sec" style={{ marginTop: 0 }}><div className="label">名场面{teardown && <span className="n">拆书的角色卡多这一栏</span>}</div><ul className="moments">{moments.map((moment, index) => <li key={index}><span className="ch" onClick={moment.chapter ? () => nav.openNode(`c${moment.chapter}`) : undefined}>{moment.chapter ? `第 ${moment.chapter} 章` : ''}</span><p>{moment.what ?? moment.raw}{moment.shows != null && <span className="shows">立住了：{moment.shows}</span>}</p></li>)}</ul></div>}
    {sections.length > 0 && <div className="fields" style={{ marginTop: 18 }}>{sections.map(section => <div className="f" key={section.key ?? section.label}><div className="label">{characterFieldLabel(section.label, teardown)}</div><DeskEdit as="p" value={section.text} refs lines={4} onSave={saveField(section.key ?? section.label)} spot={`e|${entry.id}|${section.key ?? section.label}`} />{['身世', '来历'].includes(section.key ?? section.label) && entry.secret && <a className="link" onClick={() => nav.openEntry(entry.secret!)}>另有秘密：{findEntry(book, entry.secret)?.name}</a>}{(section.key ?? section.label) === '能力' && entry.goldfinger && <a className="link" onClick={() => nav.openEntry(entry.goldfinger!)}>金手指：{findEntry(book, entry.goldfinger)?.name}</a>}</div>)}</div>}
    {!teardown && !entry.readonly && <div className="settings-actions"><button className="btn seal-line" onClick={() => setRelations(true)}>新增关系</button></div>}
    {editing && <EntryEditor entry={entry} close={() => setEditing(false)} relations={() => { setEditing(false); setRelations(true) }} />}{relations && <RelationEditor book={book} entry={entry} close={() => setRelations(false)} />}
  </section>{hasRail && <aside className="rail">
    {links.length > 0 && <div className="rb"><h3 onDoubleClick={() => { if (!entry.readonly) setRelations(true) }}>和别人的关系</h3><ul className="plist">{links.map(relation => <li key={relation.id ?? relation.to + relation.kind}><span className="nm" onClick={() => nav.openEntry(relation.to)}>{findEntry(book, relation.to)?.name}</span><span className="ct">{relation.sinceChapter ? `第 ${relation.sinceChapter} 章起` : ''}</span><DeskEdit as="span" className="ds" refs value={relation.text} onSave={entry.readonly ? undefined : text => save(actions.saveRelation(entry, relation, text))} /></li>)}</ul></div>}
    {teardown && seen.length > 0 && <div className="rb"><h3>出场<span className="n">已拆的各章</span></h3><div className="small">出场 {seen.length} 章：第 {spans(seen)} 章</div><div className="rhythm" style={{ height: 16, marginTop: 10 }}>{Array.from({ length: last }, (_, index) => <i key={index} data-empty={!seen.includes(index + 1) ? 'true' : undefined} style={css({ '--w': 1, minWidth: 0, borderRadius: 2, ...(!seen.includes(index + 1) ? { background: '#efe6d6', borderColor: '#efe6d6' } : {}) })} title={`第 ${index + 1} 章`} onClick={() => nav.openNode(`c${index + 1}`)} />)}</div><div className="rhythm-cap"><span>第 1 章</span><span>第 {last} 章</span></div></div>}
    {oneLineOnly ? <div className="rb"><h3>只记一句话</h3><div className="small">出场 {seen.length} 章。出场 5 章以上或者有名场面的人才写全卡，其余的只记一句话。</div></div> : teardown && empty.length > 0 && <div className="rb"><h3>记录里没有</h3><div className="small">{empty.join('、')}</div></div>}
    {!teardown && entry.appears.length > 0 && <div className="rb"><h3>出场</h3>{entry.appears.map(appearance => <div key={appearance.node}><a className="link" onClick={() => nav.openNode(appearance.node)}>{appearance.label}</a></div>)}</div>}
  </aside>}</>
}

function PlainEntry({ book, entry, nav, fresh }: { book: VBook; entry: VEntry; nav: DeskNav; fresh: boolean }) {
  const { actions } = useWorkspace()
  const save = useSave()
  const [editing, setEditing] = useState(false)
  const levels = entry.levels ?? []
  const saveField = (key: string) => entry.readonly ? undefined : (text: string) => save(actions.saveEntry(entry, { fields: { [key]: text } }))
  return <section className="page" id={`entry-${entry.id}`} data-entry={entry.id} style={{ position: 'relative' }}><EntryButtons entry={entry} nav={nav} edit={() => setEditing(true)} /><div className="kicker">{entry.category}</div><DeskEdit as="h1" value={entry.name} fresh={fresh} placeholder="起个名字" onSave={entry.readonly ? undefined : name => { if (name.trim()) save(actions.saveEntry(entry, { name })) }} />
    {entry.readonly && <div className="state">这一条从「<a className="link" onClick={() => entry.holder && nav.openEntry(entry.holder)}>{findEntry(book, entry.holder ?? '')?.name}</a>」的角色卡推出来，到角色卡上去改。</div>}
    {clean(entry.oneLine) && <DeskEdit as="p" className="lead" value={entry.oneLine} onSave={entry.readonly ? undefined : oneLine => save(actions.saveEntry(entry, { oneLine }))} spot={`e|${entry.id}|@oneLine`} />}
    {entry.createdChapter && <div className="meta">第一次出现 第 {entry.createdChapter} 章</div>}
    <div className="facts">{entry.parent && <span>属于<b onClick={() => nav.openEntry(entry.parent!)}>{findEntry(book, entry.parent)?.name}</b></span>}{entry.facts.map(([label, text, , key]) => clean(text) ? <span key={key ?? label}>{label}<DeskEdit as="b" value={text} onSave={saveField(key ?? label)} /></span> : null)}</div><div className="rule1" />
    {entry.kind === 'ladder' ? <><DeskEdit as="p" className="lead" value={entry.overview ?? ''} onSave={entry.readonly ? undefined : overview => save(actions.saveEntry(entry, { overview }))} spot={`e|${entry.id}|@overview`} /><div>{levels.map((level, index) => <div className="settings-level" key={index}><span>{index + 1}</span><div className="settings-level-content"><DeskEdit className="lead" value={level.name} placeholder="这一级叫什么" onSave={entry.readonly ? undefined : name => save(actions.saveEntry(entry, { levels: levels.map((item, at) => at === index ? { ...item, name } : item) }))} /><DeskEdit as="p" className="prose" refs value={level.text} placeholder="这一级能做到什么" spot={`l|${entry.id}|${index}`} onSave={entry.readonly ? undefined : text => save(actions.saveEntry(entry, { levels: levels.map((item, at) => at === index ? { ...item, text } : item) }))} /></div>{!entry.readonly && <button className="btn seal-line" title="删掉这一级" aria-label="删掉这一级" onClick={() => save(actions.saveEntry(entry, { levels: levels.filter((_, at) => at !== index) }))}><X size={13} /></button>}</div>)}</div>{!entry.readonly && <div className="settings-actions"><button className="btn seal-line" onClick={() => save(actions.saveEntry(entry, { levels: [...levels, { name: '', text: '' }] }))}><Plus size={14} />再往上加一级</button></div>}</>
      : entry.sections.filter(section => clean(section.text) || entry.id.startsWith('draft-')).map(section => <div className="sec" key={section.key ?? section.label}>{entry.sections.length !== 1 && <div className="label">{section.label}</div>}<DeskEdit as="p" className="prose" refs value={clean(section.text)} placeholder={section.placeholder || '写这一条的内容，可以一条条列'} onSave={saveField(section.key ?? section.label)} spot={`e|${entry.id}|${section.key ?? section.label}`} /></div>)}
    {entry.appears.length > 0 && <div className="sec" style={{ marginTop: 22 }}><div className="label">出现在</div>{entry.appears.map(appearance => <div key={appearance.node}><a className="link" onClick={() => nav.openNode(appearance.node)}>{appearance.label}</a></div>)}</div>}
    {editing && <EntryEditor entry={entry} close={() => setEditing(false)} />}
  </section>
}

function CategoryPage({ book, category, nav, onNewEntry, onAccept }: { book: VBook; category: VCategory; nav: DeskNav; onNewEntry?: () => void; onAccept?: Accept }) {
  const [tools, setTools] = useState<'columns' | 'draft' | null>(null)
  const counts = useMemo(() => {
    const result: Record<string, number> = {}
    for (const entry of category.entries) {
      for (const [label, text, , key] of entry.facts) if (text) result[key ?? label] = (result[key ?? label] ?? 0) + 1
      for (const section of entry.sections) if (section.text) result[section.key ?? section.label] = (result[section.key ?? section.label] ?? 0) + 1
    }
    return result
  }, [category.entries])
  const entries = category.name === '角色列表' ? orderedCharacters(category.entries, book.source === 'teardown') : category.entries
  return <section className="page"><div className="kicker">设定</div><h1>{category.name}</h1><div className="meta">{category.entries.length} 条 · {category.about}</div><div className="settings-actions">{!isLadder(category) && <button className="btn seal-line" onClick={() => setTools('columns')}>调整栏目</button>}{book.source !== 'teardown' && <button className="btn seal-line" onClick={() => setTools('draft')}>编辑部帮写</button>}{onNewEntry && <button className="btn solid" onClick={onNewEntry}>新增{nounOf(category.name)}</button>}</div><div className="rule1" />
    {entries.length ? <div>{entries.map(entry => <div className="settings-category-entry" key={entry.id}><div className="label"><a className="link" onClick={() => nav.openEntry(entry.id)}>{entry.name || '未命名'}</a></div>{entry.oneLine && <p className="prose">{entry.oneLine}</p>}<div className="facts">{entry.facts.filter(([, text]) => clean(text)).map(([label, text]) => <span key={label}>{label}<b>{text}</b></span>)}</div>{entry.sections.filter(section => clean(section.text)).map(section => <p className="prose" key={section.key ?? section.label}><Refs text={section.text} /></p>)}</div>)}</div> : <div className="state">{book.source === 'teardown' ? '还没拆出设定。' : '还没有这一类设定，点上面的按钮新增。'}</div>}
    {tools && <Sheet close={() => setTools(null)}>{tools === 'columns' ? <CardTemplateEditor category={category} template={templateOf(book, category)} counts={counts} onClose={() => setTools(null)} /> : <AskPanel book={book} category={category} onAccept={onAccept ?? (() => undefined)} onClose={() => setTools(null)} />}</Sheet>}
  </section>
}

function WorldPage({ book }: { book: VBook }) {
  const { actions } = useWorkspace()
  const save = useSave()
  return <section className="page"><div className="kicker">设定</div><h1>世界概况</h1><div className="rule1" />{clean(book.world) ? <DeskEdit as="p" className="lead" refs value={book.world} onSave={text => save(actions.saveWorld(text))} spot="w" /> : <><div className="state">还没有</div><DeskEdit as="p" className="lead" value="" onSave={text => save(actions.saveWorld(text))} spot="w" placeholder="整个世界一段话说清" /></>}</section>
}

export function DeskSettings({ book, selected, nav, fresh = '', onNewEntry, onAccept, cardKey = id => id }: { book: VBook; selected: string; nav: DeskNav; fresh?: string | boolean; onNewEntry?: (category: string) => void; onAccept?: (category: string, items: { name: string; text: string }[]) => void; cardKey?: (id: string) => string }) {
  if (selected === 'world') return <WorldPage book={book} />
  const entry = findEntry(book, selected)
  const newlyCreated = typeof fresh === 'boolean' ? fresh : fresh === entry?.id
  if (entry) return entry.kind === 'character' ? <CharacterPage key={cardKey(entry.id)} book={book} entry={entry} nav={nav} fresh={newlyCreated} /> : <PlainEntry key={cardKey(entry.id)} book={book} entry={entry} nav={nav} fresh={newlyCreated} />
  const category = book.categories.find(item => selected === `cat:${item.name}` || selected === item.key || selected === `category:${item.key}`)
  if (category) return <CategoryPage key={category.key} book={book} category={category} nav={nav} onNewEntry={onNewEntry ? () => onNewEntry(category.name) : undefined} onAccept={onAccept ? items => onAccept(category.name, items) : undefined} />
  return <SettingsOverview book={book} nav={nav} />
}
