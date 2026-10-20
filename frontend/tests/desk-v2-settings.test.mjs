import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { clean, currentRead, emptyTeardownSettingsMeta, momentLines, spans, wan } from '../src/pages/workspace/desk-v2/settingsData.ts'

const source = readFileSync(new URL('../src/pages/workspace/desk-v2/SettingsPages.tsx', import.meta.url), 'utf8')
const editing = readFileSync(new URL('../src/pages/workspace/desk-v2/settingsEditing.tsx', import.meta.url), 'utf8')
const prototype = readFileSync(new URL('../../docs/界面原型/装修样张.html', import.meta.url), 'utf8')

test('设定数据只把指定的旧空值视为空，不改写正文和缺失日期', () => {
  assert.equal(clean('（记录里没有）'), '')
  assert.equal(clean(undefined), '')
  assert.equal(clean('  作者原文\n第二行  '), '  作者原文\n第二行  ')
  assert.equal(clean('记录里没有，但作者有意写的'), '记录里没有，但作者有意写的')
  assert.equal(wan(9999), '9999 字')
  assert.equal(wan(105000), '11 万字')
  assert.match(source, /\(book\.createdAt \?\? ''\)\.slice\(0, 10\)/)
})

test('出场区间按顺序去重；已拆章数只认已读标记而不拿目标冒充', () => {
  assert.equal(spans([10, 1, 9, 2, 7, 3, 3]), '1–3、7、9–10')
  assert.equal(spans([]), '')
  const book = { teardown: { upto: 100 }, outline: { kind: '全书', children: [{ kind: '卷', children: [
    { kind: '章', range: [1, 1], teardown: { read: true } },
    { kind: '章', range: [2, 2], teardown: { read: true } },
    { kind: '章', range: [100, 100], teardown: { read: false } },
  ] }] } }
  assert.equal(currentRead(book), 2)
  assert.equal(currentRead({ outline: { kind: '全书' } }), 0)
})

const emptyBook = (stage = 'stopped') => ({
  source: 'teardown', teardown: { stage, chapters: 498, read: 2, upto: 100 },
  categories: [{ name: '角色列表', entries: [] }, { name: '作者自建类别', custom: { style: 'paragraph' }, entries: [] }],
  outline: { kind: '全书', children: [{ kind: '卷', children: [
    { kind: '章', range: [1, 1], teardown: { read: true, failed: false } },
    { kind: '章', range: [2, 2], teardown: { read: false, failed: true } },
    { kind: '章', range: [3, 3], teardown: { read: true, failed: false } },
    { kind: '章', range: [100, 100], teardown: { read: false, failed: false } },
  ] }] },
})
const teardownJob = (status, doing) => ({ kind: 'teardown', status, pending: { teardown: { doing, read: 2, target: 100, total: 498 } } })
const stoppedEmptyMeta = '设定还没整理：点右上角「接着拆」，拆到第 3 章不变，只整理设定，不重读原文'

test('小修1空设定页四行现状逐字匹配，最后读过的章不是已读章数或目标', () => {
  assert.equal(emptyTeardownSettingsMeta(emptyBook(), teardownJob('running', 'settings')), '设定师在整理设定，整理完这里就有了')
  for (const doing of ['read', 'units', 'volumes', 'closing']) {
    assert.equal(emptyTeardownSettingsMeta(emptyBook(), teardownJob('running', doing)), '拆书收尾时会整理设定，到时这里就有了')
  }
  for (const stage of ['stopped', 'queued']) assert.equal(emptyTeardownSettingsMeta(emptyBook(stage), null), stoppedEmptyMeta)
  const unread = emptyBook('imported')
  unread.outline.children = []
  assert.equal(emptyTeardownSettingsMeta(unread, null), '还没开拆，拆过的章会整理成角色卡和设定')
  assert.equal(currentRead(emptyBook()), 3)
})

test('小修1空设定页与顶栏共用活动job优先级，排队不当作正在读，运行状态即使未读仍写收尾', () => {
  assert.equal(emptyTeardownSettingsMeta(emptyBook('running'), teardownJob('queued', 'queued')), stoppedEmptyMeta)
  assert.equal(emptyTeardownSettingsMeta(emptyBook('queued'), teardownJob('running', 'read')), '拆书收尾时会整理设定，到时这里就有了')
  assert.equal(emptyTeardownSettingsMeta(emptyBook('stopped'), teardownJob('cancelled', 'settings')), stoppedEmptyMeta)
  const unread = emptyBook('running')
  unread.outline.children = []
  assert.equal(emptyTeardownSettingsMeta(unread, null), '拆书收尾时会整理设定，到时这里就有了')
  for (const stage of ['imported', 'stopped', 'queued']) {
    unread.teardown.stage = stage
    assert.equal(emptyTeardownSettingsMeta(unread, null), '还没开拆，拆过的章会整理成角色卡和设定')
  }
})

test('小修1只对未整理且所有类别为空的拆书隐藏框，整理到0章、有任何条目和作者书均不变', () => {
  for (const upto of [0, 3, 100]) {
    const book = emptyBook()
    book.teardown.settings = { upto }
    assert.equal(emptyTeardownSettingsMeta(book, null), null)
  }
  for (const categoryIndex of [0, 1]) {
    const book = emptyBook()
    book.categories[categoryIndex].entries.push({ id: 'saved', name: '作者内容' })
    assert.equal(emptyTeardownSettingsMeta(book, null), null)
  }
  for (const source of ['new', 'imported', undefined]) assert.equal(emptyTeardownSettingsMeta({ ...emptyBook(), source }, null), null)
  const book = emptyBook()
  book.teardown.settings = { upto: null }
  assert.equal(emptyTeardownSettingsMeta(book, null), stoppedEmptyMeta)
  assert.match(source, /const control = useTeardownControl\(\)/)
  assert.match(source, /const emptyMeta = emptyTeardownSettingsMeta\(book, control\?\.job \?\? null\)/)
  assert.match(source, /<div className="rule1" \/>\{emptyMeta === null && <div className="tiles">/)
  assert.match(source, /<div className="meta">\{emptyMeta \?\? \(teardown/)
})

test('名场面按现存栏目拆章号、动作、立住的东西；不认识的旧行原样保留', () => {
  const raw = '第 12 章：反手救人——立住了果断\n第 41 章：看破伪装——立住：冷静\n作者自己补的这一整行'
  const entry = { facts: [], sections: [{ key: '名场面', label: '改过名的栏目', text: raw }] }
  assert.deepEqual(momentLines(entry), [
    { chapter: 12, what: '反手救人', shows: '果断', raw: '第 12 章：反手救人——立住了果断' },
    { chapter: 41, what: '看破伪装', shows: '冷静', raw: '第 41 章：看破伪装——立住：冷静' },
    { raw: '作者自己补的这一整行' },
  ])
  assert.equal(entry.sections[0].text, raw)
})

test('简介、总览和角色卡照样张的标签、class、小标题与折叠额度', () => {
  for (const className of ['intro-top', 'hero', 'cover', 'lbl', 'stamp', 'statline', 'side-box', 'plist one', 'merits3', 'merit', 'tiles', 'tile', 'hd', 'kv', 'ptree', 'sub', 'facts', 'now', 't', 'moments', 'ch', 'shows', 'fields', 'f', 'rail', 'rb', 'rhythm-cap']) {
    assert.ok(prototype.includes(`class="${className}"`), `样张有 ${className}`)
    assert.ok(source.includes(`className="${className}"`), `React 有 ${className}`)
  }
  for (const text of ['主要人物', '出场多的在前', '金手指和等级', '这本书好在哪', '主编照程序算好的数字写', '你改过的条目以后接着拆也不会被盖掉', '拆书的角色卡多这一栏', '和别人的关系', '已拆的各章', '记录里没有', '立住了：']) {
    assert.ok(prototype.includes(text))
    assert.ok(source.includes(text))
  }
  assert.match(source, /Clamp as="p" lines=\{7\}/)
  assert.match(source, /DeskEdit as="p"[^\n]+lines=\{4\}/)
  assert.match(source, /entries: VEntry\[\]; nav: DeskNav; cap\?: number/)
  assert.match(source, /cap = 8/)
  assert.match(source, /More items={secrets} cap=\{3\}/)
  assert.doesNotMatch(source, /className="[^"]*(?:bg-card|text-ink|grid-cols-|flex-wrap|border-line)/)
})

test('作者编辑和草稿保护仍走真实actions，不为样张删掉置顶、锁删、关系、栏目、阶梯和候选功能', () => {
  for (const action of ['saveBook', 'saveWorld', 'saveEntry', 'deleteEntry', 'pinEntry', 'saveRelation', 'addRelation', 'deleteRelation', 'createCategory']) assert.ok(source.includes(`actions.${action}`))
  assert.match(source, /CardTemplateEditor category={category} template={templateOf\(book, category\)}/)
  assert.match(source, /AskPanel book={book} category={category}/)
  assert.match(source, /onNewEntry\(category\.name\)/)
  assert.match(source, /key={cardKey\(entry\.id\)}/)
  assert.match(source, /entry\.readonly \? undefined/)
  assert.match(source, /levels: levels\.map\(\(item, at\) => at === index \? { \.\.\.item, text } : item\)/)
  assert.match(source, /levels: levels\.filter/)
  assert.match(editing, /contentEditable: onSave \? 'plaintext-only'/)
  assert.match(editing, /'data-spot': spot/)
  assert.match(editing, /onBlur:/)
  assert.match(editing, /event\.key === 'Escape'/)
  assert.match(editing, /document\.activeElement !== element/)
  assert.match(editing, /text\.replace\(\/\[&<>"\]\/g/)
})

test('新建作者类别仍保留三种样式与自定字段，拆书样张不增加按钮；暗色能精确覆盖空出场格', () => {
  assert.match(source, /!teardown && <div className="settings-actions"><button className="btn seal-line"[^\n]+新建类别/)
  for (const style of ['card', 'paragraph', 'ladder']) assert.ok(source.includes(`<option value="${style}">`))
  assert.match(source, /book\.categories\.some\(category => category\.name === title\)/)
  assert.match(source, /actions\.createCategory\(title, style, columns, about\)/)
  assert.match(source, /data-empty={!seen\.includes\(index \+ 1\) \? 'true' : undefined}/)
  assert.match(source, /background: '#efe6d6', borderColor: '#efe6d6'/)
})
