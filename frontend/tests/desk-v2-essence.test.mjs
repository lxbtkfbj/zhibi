import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import {
  ESSENCE_GROUPS, ESSENCE_LEADS, ESSENCE_NAMES, emptyEssenceText, essenceCount, essenceNumber, hasEssence, introOutline, introSteps,
} from '../src/pages/workspace/desk-v2/essenceData.ts'

const context = { window: {} }
vm.runInNewContext(readFileSync(new URL('../../docs/界面原型/精髓样张-数据.js', import.meta.url), 'utf8'), context)
const sample = JSON.parse(JSON.stringify(context.window.DATA))
const source = readFileSync(new URL('../src/pages/workspace/desk-v2/EssencePages.tsx', import.meta.url), 'utf8')

test('精髓节名、每节说明和五组顺序逐字采用精髓样张，不自行改写', () => {
  assert.deepEqual(ESSENCE_NAMES, sample.names)
  assert.deepEqual(ESSENCE_LEADS, sample.leads)
  assert.deepEqual(ESSENCE_GROUPS, sample.groups)
  assert.equal(ESSENCE_GROUPS.flatMap(([, keys]) => keys).length, 12)
  for (let i = 1; i <= 30; i++) assert.equal(essenceNumber(i), i <= 10 ? '一二三四五六七八九十'[i - 1] : i <= 19 ? '十' + '一二三四五六七八九十'[i - 11] : String(i))
})

test('目录数字为知识点加人物，搜索逐字段命中，空白恢复原数而不计missing', () => {
  const essence = sample.essence
  assert.equal(essenceCount(essence, 'overview'), essence.overview.points.length)
  assert.equal(essenceCount(essence, 'cast'), essence.sections.cast.points.length + essence.sections.cast.figures.length)
  assert.equal(essenceCount(essence, 'cast', '  '), essenceCount(essence, 'cast'))
  assert.equal(essenceCount(null, 'cast'), 0)
  assert.equal(essenceCount({ sections: {} }, 'source'), 0)
  const point = { title: '标题', steps: ['第一步', '第二步'], evidence: '本书证据', note: '注意事项' }
  const figure = { name: '名字', archetype: '人设', build: '怎么立', role: '作用', arc: '变化' }
  const fixture = { upto: 2, overview: { points: [point] }, sections: { cast: { points: [point], figures: [figure], missing: ['待补'] } } }
  for (const field of [point.title, ...point.steps, point.evidence, point.note]) assert.equal(essenceCount(fixture, 'overview', field), 1)
  for (const field of Object.values(figure)) assert.equal(essenceCount(fixture, 'cast', field), 1)
  assert.equal(essenceCount(fixture, 'cast', '不存在'), 0)
  assert.equal(essenceCount(fixture, 'cast', '待补'), 0)
})

test('null或upto尚无值视为无精髓，有值包括0仍展示本次返回的新旧混合节，不加缓存', () => {
  for (const value of [null, undefined, {}, { upto: null }, { upto: undefined }, { ...sample.essence, upto: null }]) assert.equal(hasEssence(value), false)
  const mixed = { ...sample.essence, upto: 100, sections: { source: { ...sample.essence.sections.source, points: [{ title: '本次新节', steps: [], evidence: '', note: '' }] }, hero: sample.essence.sections.hero } }
  assert.equal(hasEssence(mixed), true)
  assert.equal(essenceCount(mixed, 'source', '本次新节'), 1)
  assert.equal(essenceCount(mixed, 'hero'), sample.essence.sections.hero.points.length)
  assert.equal(essenceCount({ ...mixed, upto: null }, 'hero'), 0)
  assert.equal(hasEssence({ ...mixed, upto: 0 }), true)
  assert.equal(essenceCount({ ...mixed, upto: 0 }, 'source'), 1)
  assert.equal(mixed.sections.hero, sample.essence.sections.hero, '直接用返回的节，不另存完整快照')
  assert.equal(mixed.sections.source.points[0].title, '本次新节')
})

test('简介摘要teardown.essence沿用同一upto规则，不把有points的半成品当已整理', () => {
  for (const [value, present] of [[null, false], [{ upto: null, points: 12 }, false], [{ points: 12 }, false], [{ upto: 100, points: 12 }, true], [{ upto: 0, points: 0 }, true]]) {
    const book = { teardown: { essence: value } }
    assert.equal(hasEssence(book.teardown.essence), present)
  }
  for (const name of ['EssenceDirectory', 'EssencePage', 'TeardownIntro']) {
    assert.match(source, new RegExp(`export function ${name}[^\\n]+\\n(?:[^\\n]*\\n)?  essence = hasEssence\\(essence\\) \\? essence : null`))
  }
})

test('无精髓四种现状逐字匹配任务，使用last_read而不是目标或成功章数', () => {
  const book = (last, stage = 'stopped') => ({ teardown: { last_read: last, stage, read: 7, upto: 100 } })
  assert.equal(emptyEssenceText(book(0), false), '还没开拆。拆过的章会整理成一条条知识点：情节怎么想、设定怎么设、爽点怎么造、人物怎么立。')
  assert.equal(emptyEssenceText(book(50), true), '拆书收尾时整理精髓，到时这里就有了。')
  assert.equal(emptyEssenceText(book(50, 'done'), false), '还没整理精髓：点右上角「补上整理」，不重读原文。')
  assert.equal(emptyEssenceText(book(50), false), '还没整理精髓：点右上角「接着拆」，选「只整理前 50 章」，不重读原文。')
  assert.equal(emptyEssenceText(book(50, 'done'), true), '拆书收尾时整理精髓，到时这里就有了。')
})

test('无精髓简介取大纲单元，尾部只列已读未归章，不假装未读章都拆过', () => {
  const chapter = (n, read = true) => ({ kind: '章', range: [n, n], teardown: { read } })
  const book = { outline: { kind: '全书', children: [{ kind: '卷', children: [
    { kind: '单元', title: '单元一　第一件事', range: [1, 3], children: [chapter(1), chapter(2), chapter(3)] },
    { kind: '单元', title: '单元二 · 第二件事', range: [4, 5], children: [chapter(4), chapter(5)] },
    { kind: '单元', virtual: true, range: [6, 498], children: [chapter(6), chapter(7), chapter(8, false), chapter(498, false)] },
  ] }] } }
  assert.deepEqual(introOutline(book), { units: [{ n: 1, title: '第一件事', first: 1, last: 3 }, { n: 2, title: '第二件事', first: 4, last: 5 }], tail: [6, 7] })
  assert.deepEqual(introOutline({ outline: { kind: '全书' } }), { units: [], tail: null })
})

test('简介步骤仅去样张指定的末尾标点再用箭头相连，不改原数组', () => {
  const point = { steps: ['先做。', '再做；;', '最后做，，', '保留！'] }
  assert.equal(introSteps(point), '先做 → 再做 → 最后做 → 保留！')
  assert.deepEqual(point.steps, ['先做。', '再做；;', '最后做，，', '保留！'])
})

test('精髓和新简介是实际React节点，章号、人物、单元与精髓入口接回调', () => {
  assert.doesNotMatch(source, /dangerouslySetInnerHTML|innerHTML\s*=/)
  for (const className of ['kp', 'steps', 'ev', 'nt', 'figs', 'fig', 'genre', 'engine', 'bars', 'feelstrip', 'legend', 'intro2', 'learn', 'cast2', 'waits2']) assert.match(source, new RegExp(`className="[^"]*\\b${className}\\b[^"]*"`))
  assert.match(source, /onChapter\(Number\(part\.match/)
  assert.match(source, /onPerson\(name\)/)
  assert.match(source, /onUnit\(unit\.n\)/)
  assert.match(source, /onClick=\{onEssence\}/)
  assert.match(source, /rail\.open\.length > 0/)
  assert.match(source, /book\.teardown\?\.intro &&/)
  assert.match(source, /position \?\? 0/)
})
