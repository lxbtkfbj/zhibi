import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { needsTeardownShelfRead, teardownShelfRead, teardownShelfStatus } from '../src/lib/teardownShelf.ts'

const info = { chapters: 498, read: 97, upto: 100, stop_note: '拆到第 100 章了（你定的）。' }

test('小修1书架逐字显示分章、排队、正在拆、拆完和导入状态', () => {
  for (const [stage, text] of [
    ['confirming', '还没确认分章'],
    ['queued', '排队中'],
    ['running', '正在拆 · 已拆 97 / 498 章'],
    ['done', '拆完了 · 498 章'],
    ['imported', '已导入 498 章 · 还没开拆'],
  ]) assert.deepEqual(teardownShelfStatus({ ...info, stage }), { text })
  assert.deepEqual(teardownShelfStatus(), { text: '已导入 0 章 · 还没开拆' })
})

test('小修1手动或范围停下只显示真实已读章数，不显示旧句子或目标章号', () => {
  for (const stop_reason of ['upto', 'author']) {
    const status = teardownShelfStatus({ ...info, stage: 'stopped', stop_reason })
    assert.deepEqual(status, { text: '已拆 97 / 498 章' })
    assert.equal(status.title, undefined)
  }
  assert.deepEqual(teardownShelfStatus({ ...info, read: 0, stage: 'stopped', stop_reason: null }), { text: '已拆 0 / 498 章' })
})

test('小修1模型或运行错误状态带出错停了，鼠标提示逐字保留stop_note全文', () => {
  const stop_note = '模型没回复原文\n第二行和标点都保留。'
  for (const stop_reason of ['model', 'error']) {
    assert.deepEqual(teardownShelfStatus({ ...info, stage: 'stopped', stop_reason, stop_note }), {
      text: '已拆 97 / 498 章 · 出错停了', title: stop_note,
    })
  }
})

test('小修1书架使用状态助手和原有样式，错误全文接到title而不改作者书状态', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  assert.match(home, /const teardownStatus = teardownShelfStatus\(book\.teardown, fallbackRead\)/)
  assert.match(home, /<p className="mt-1\.5 text-xs text-ink-2" title=\{teardownStatus\.title\}>\{teardownStatus\.text\}<\/p>/)
  assert.match(home, /<Badge tone=\{status\.tone\}>/)
  assert.doesNotMatch(home, /book\.teardown\.stop_note/)
})

test('新后台有read（包括0）时不请求目录，旧后台只在需要显示计数时补取', () => {
  for (const stage of ['confirming', 'queued', 'running', 'stopped', 'done', 'imported']) {
    assert.equal(needsTeardownShelfRead({ ...info, stage }), false)
    assert.equal(needsTeardownShelfRead({ ...info, stage, read: 0 }), false)
    assert.equal(needsTeardownShelfRead({ ...info, stage, read: undefined }), ['running', 'stopped'].includes(stage))
  }
  assert.equal(needsTeardownShelfRead(), false)
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  assert.match(home, /enabled: teardown && needsTeardownShelfRead\(book\.teardown\)/)
  assert.match(home, /get<ChapterBrief\[\]>\(`\/books\/\$\{book\.id\}\/chapters`\)/)
  assert.doesNotMatch(home, /get<Chapter>\(/)
})

test('旧后台按目录read标记计数，读失败和未读不计入，不把最后章号当已读数量', () => {
  const chapters = [
    { teardown: { read: true, failed: false } },
    { teardown: { read: false, failed: true } },
    { teardown: { read: false, failed: false } },
    { teardown: { read: true, failed: false } },
  ]
  const read = teardownShelfRead(chapters, 4)
  assert.equal(read, 2)
  assert.deepEqual(teardownShelfStatus({ ...info, chapters: 4, stage: 'stopped', read: undefined, upto: 4 }, read), { text: '已拆 2 / 4 章' })
  assert.deepEqual(teardownShelfStatus({ ...info, stage: 'stopped', read: 0 }, read), { text: '已拆 0 / 498 章' })
  assert.equal(teardownShelfRead([{ teardown: { read: false, failed: false } }], 1), 0)
  assert.equal(teardownShelfRead([], 0), 0)
})

test('旧后台计数未取到、请求失败或目录缺标记时不伪造0', () => {
  assert.equal(teardownShelfRead([], 498), undefined)
  assert.equal(teardownShelfRead([{ teardown: null }], 1), undefined)
  assert.deepEqual(teardownShelfStatus({ ...info, stage: 'stopped', read: undefined }), { text: '已拆 — / 498 章' })
  assert.deepEqual(teardownShelfStatus({ ...info, stage: 'running', read: undefined }), { text: '正在拆 · 已拆 — / 498 章' })
})
