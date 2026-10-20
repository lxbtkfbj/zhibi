import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { chapterSearchDisplay, teardownEta, teardownProgressView } from '../src/lib/teardownProgress.ts'
import { teardownRecordSections } from '../src/lib/teardownRecords.ts'

function fixture(stage = 'running') {
  return {
    source: 'teardown', teardown: { stage, chapters: 40, upto: 20, stop_note: '拆到第 20 章了（你定的）。' },
    outline: { id: 'book', kind: '全书', children: [
      { id: 'v1', kind: '卷', children: [{ id: 'u1', kind: '单元', children: [
        { id: 'c1', kind: '章', ref: { id: '1' }, teardown: { read: true, failed: false } },
        { id: 'c2', kind: '章', ref: { id: '2' }, teardown: { read: false, failed: true } },
      ] }] },
      { id: 'v2', kind: '卷', open: true, children: [{ id: 'virtual', kind: '单元', virtual: true, children: [] }] },
    ] },
  }
}
function job(doing, extra = {}) {
  return { kind: 'teardown', status: doing === 'queued' ? 'queued' : 'running', pending: { teardown: {
    doing, reading: [9, 12], range: [1, 20], read: 8, target: 20, total: 40, eta_seconds: 120, failed: [], ...extra,
  } } }
}

test('还要大约：不到一分钟、分钟、小时与整点不补零分钟', () => {
  for (const [seconds, text] of [[0, '不到 1 分钟'], [59, '不到 1 分钟'], [60, '1 分钟'], [61, '2 分钟'], [3599, '60 分钟'], [3600, '1 小时'], [3660, '1 小时 1 分钟'], [7200, '2 小时']]) assert.equal(teardownEta(seconds), text)
})

test('任务第3节逐项文字：排队、读、归单元、归卷、收尾与部分目标', () => {
  const book = fixture()
  assert.equal(teardownProgressView(book, job('queued')).text, '排队中：前面还有书在拆')
  assert.equal(teardownProgressView(book, job('read')).text, '设定师在读第 9–12 章 · 已拆 8／20 章（拆到第 20 章） · 还要大约 2 分钟')
  assert.equal(teardownProgressView(book, job('units')).text, '主编在归单元：第 1–20 章 · 已拆 8／20 章（拆到第 20 章） · 还要大约 2 分钟')
  assert.equal(teardownProgressView(book, job('volumes')).text, '主编在归卷 · 已拆 8／20 章（拆到第 20 章）')
  assert.equal(teardownProgressView(book, job('closing')).text, '在收尾：把最后几章归进单元和卷')
  assert.equal(teardownProgressView(book, job('read', { target: 40, eta_seconds: null })).text, '设定师在读第 9–12 章 · 已拆 8／40 章')
  assert.equal(teardownProgressView(book, job('read', { reading: null, eta_seconds: 40 })).text, '设定师在读原文 · 已拆 8／20 章（拆到第 20 章） · 还要大约 不到 1 分钟')
  assert.match(teardownProgressView(book, job('read', { eta_seconds: 3660 })).text, /还要大约 1 小时 1 分钟$/)
})

test('运行中只用事件进度，停下/完成从目录重建，旧终态job不能盖过书状态', () => {
  const progress = teardownProgressView(fixture(), job('read', { failed: [7, 5, 7] }))
  assert.equal(progress.read, 8)
  assert.deepEqual(progress.failed, [5, 7])
  assert.equal(progress.percent, 40)
  const stopped = teardownProgressView(fixture('stopped'), { ...job('read'), status: 'cancelled' })
  assert.equal(stopped.text, '拆到第 20 章了（你定的）。')
  assert.equal(stopped.read, 1)
  assert.deepEqual(stopped.failed, [2])
  assert.equal(stopped.active, false)
  assert.equal(teardownProgressView(fixture('done'), null).text, '拆完了 · 40 章，1 个单元，1 卷')
  assert.equal(teardownProgressView({ ...fixture(), source: 'new' }, job('read')).visible, false)
  assert.equal(teardownProgressView(fixture('confirming'), null).visible, false)
})

test('停下马上禁用且照原文显示，失败列表可展开、重试只走提供的控制入口', () => {
  const source = readFileSync(new URL('../src/pages/workspace/TeardownProgress.tsx', import.meta.url), 'utf8')
  assert.match(source, /const busy = !!control\?\.starting \|\| stopping/)
  assert.match(source, /disabled={!control \|\| busy}[^\n]*perform\(control\?\.stop\)[^\n]*正在停：读完手上这几章就停/)
  assert.match(source, /aria-expanded={expanded}/)
  assert.match(source, /view.failed.map\(index => `第 \$\{index} 章`\)/)
  assert.match(source, /perform\(control\?\.retry\)/)
  assert.match(source, /onClick={control\?\.openStart}>接着拆/)
  assert.match(source, /role="progressbar"[^\n]*aria-valuenow={view.read}/)
})

const records = {
  read_version: 1, read: {
    people: [{ name: '云澈', shown: '不肯服输', also_called: ['萧澈', '小澈'], change: '离开萧门' }],
    things: [{ kind: '地方', name: '萧门', note: '萧氏所居', belongs: '流云城' }, { kind: '秘密', name: '旧事', note: '线索', secret: '埋下' }, { kind: '秘密', name: '身世', note: '真相', secret: '揭开' }],
    moments: [{ who: '云澈', what: '直面长老', shows: '不屈' }],
    waits: [{ action: '立下', what: '离开之后如何变强' }], tropes: ['退婚', '逆袭'], feel: '大爽', cool_point: '不应出现', hook: '不应出现',
  },
}
test('这一章记下的各段依原始记录格式显示，别名独立小字，感觉与看点钩子不重复', () => {
  assert.deepEqual(teardownRecordSections(records), [
    { title: '出场的人', lines: [{ name: '云澈', aliases: '萧澈、小澈', text: '：不肯服输（离开萧门）' }] },
    { title: '新冒出来的', lines: [{ text: '地方「萧门」：萧氏所居 属于 流云城' }, { text: '秘密（埋下）「旧事」：线索' }, { text: '秘密（揭开）「身世」：真相' }] },
    { title: '名场面', lines: [{ text: '云澈：直面长老——立住了不屈' }] },
    { title: '读者在等的', lines: [{ text: '立下：离开之后如何变强' }] },
    { title: '用了的桥段', lines: [{ text: '退婚、逆袭' }] },
  ])
  const source = readFileSync(new URL('../src/pages/workspace/desk-v2/OutlinePages.tsx', import.meta.url), 'utf8')
  assert.match(source, /<aside className="rail">/)
  assert.match(source, /这一章出场的人/)
  assert.match(source, /<More items=\{read\.people\} cap=\{3\} unit="人">/)
  assert.match(source, /<small className="aka">也叫 \{person\.also_called\.join\('、'\)\}/)
  assert.match(source, /<div className="mm"[^\n]+<div className="sh">立住了：\{moment\.shows\}/)
  assert.match(source, /新冒出来的 · 读者在等的/)
})

test('没读过不显示记录，空段隐藏；每个独立段非空才出现', () => {
  for (const data of [undefined, null, {}, { read: records.read }, { read_version: 1 }, { read_version: 1, read: {} }]) assert.deepEqual(teardownRecordSections(data), [])
  for (const [key, title] of [['people', '出场的人'], ['things', '新冒出来的'], ['moments', '名场面'], ['waits', '读者在等的'], ['tropes', '用了的桥段']]) {
    assert.deepEqual(teardownRecordSections({ read_version: 1, read: { [key]: records.read[key] } }).map(section => section.title), [title])
  }
  assert.deepEqual(teardownRecordSections({ read_version: 1, read: { people: [{ name: '张三', shown: '路过' }] } })[0].lines, [{ name: '张三', aliases: undefined, text: '：路过' }])
})

test('目录搜索：标题命中照列、仅原文命中不写没找到、两边都无只写一次没找到', () => {
  assert.deepEqual(chapterSearchDisplay(1, 0, true), { empty: false, body: false })
  assert.deepEqual(chapterSearchDisplay(0, 118, true), { empty: false, body: true })
  assert.deepEqual(chapterSearchDisplay(0, 0, true), { empty: true, body: false })
  assert.deepEqual(chapterSearchDisplay(2, 3, true), { empty: false, body: true })
  assert.deepEqual(chapterSearchDisplay(0, undefined, true), { empty: false, body: true }, '等待网络或请求出错都不能宣告无结果')
  assert.deepEqual(chapterSearchDisplay(0, undefined, false), { empty: true, body: false }, '原型离线按标题查找')
})
