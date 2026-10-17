import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, existsSync } from 'node:fs'
import { buildOutlineTree, flattenOutline, outlineStatusText } from '../src/lib/outlineTree.ts'
import { writingOutline, nextOutlineUnit, outlineReviewMatches, selectOutlineItem, segmentReviewKey } from '../src/lib/outlineWriting.ts'
import { pendingTarget, composerRoute, progressText } from '../src/lib/workspace.ts'
import { nextSegmentFields } from '../src/lib/setupPresentation.ts'
import { legacyBookRoute } from '../src/lib/bookRoutes.ts'
import { decisionCopy } from '../src/lib/decision.ts'

const unit = (id, index, chapters = []) => ({ id, index, title: id, summary: '作者的一段话', chapter_count: 3, locked: true, status: 'planned', chapters })
const volume = (index, units) => ({ id: `v${index}`, index, title: `卷${index}`, summary: '作者的卷纲', chapter_count: 6, locked: true, status: 'planned', units })
const arc = (node_id, planned, volumes = []) => ({ node_id, title: node_id, text: '作者的篇', planned, volumes, locked: false, status: planned ? 'planned' : 'later', end: { title: '终点', event: '破局', kind: node_id === 'end' ? 'ending' : 'milestone' } })
const tree = { arcs: [arc('a', true, [volume(1, [unit('u1', 1, [{ index: 1, status: 'planned' }]), unit('u2', 2)])]), arc('b', false), arc('end', false)], ending: { node_id: 'end', title: '结局', event: '归来' }, segmented: true }
const nodes = [{ id: 'a', index: 2 }, { id: 'b', index: 3 }, { id: 'end', index: 4 }]
const pending = { kind: 'segment_review', flow: 3, number: 2, round: 1, plan: { title: '天风国篇', text: '只在待确认里。', end: { ref: 3, title: '青云宗大比', event: '胜出', adopted: true }, fill_entries: [], new_entries: [], new_characters: [] }, split: { volumes: [] }, warnings: [], decisions: [] }

test('待确认篇替换已有终点那篇且不修改原树或数据库形状', () => {
  const root = buildOutlineTree(tree)
  const before = JSON.stringify(root)
  const projected = writingOutline(root, pending, nodes)
  assert.deepEqual(projected.children.map(item => item.key), ['segment-a', 'pending', 'segment-end', 'ending'])
  assert.equal(projected.children[1].pending, pending)
  assert.equal(projected.children[1].name, '第 2 篇 · 天风国篇')
  assert.equal(outlineStatusText(projected.children[1].status), '待你确认')
  assert.equal(JSON.stringify(root), before)
})

test('新起终点插在最后已规划篇后面，未来篇和结局一字不动', () => {
  const root = buildOutlineTree(tree)
  const projected = writingOutline(root, { ...pending, plan: { ...pending.plan, end: { ...pending.plan.end, ref: 0, adopted: false } } }, nodes)
  assert.deepEqual(projected.children.map(item => item.key), ['segment-a', 'pending', 'segment-b', 'segment-end', 'ending'])
  assert.equal(projected.children[2].name, '第 3 篇 · b')
  assert.equal(projected.children[2].arc, root.children[1].arc)
  assert.equal(root.children[1].name, '第 2 篇 · b')
  assert.equal(projected.children.at(-1), root.children.at(-1))
})

test('旧flow2只有redo入口，群聊不能绕过旧确认；共享锁住选项随轮次任务更新', () => {
  const old = { ...pending, flow: 2 }
  assert.equal(writingOutline(buildOutlineTree(tree), old, nodes).children[1].pending.flow, 2)
  assert.equal(composerRoute({ kind: 'write_book', status: 'waiting_author', pending: old }, '直接改', null).kind, 'blocked')
  assert.equal(decisionCopy(old, 'book').approve, '按新写法重出')
  assert.equal(composerRoute({ kind: 'write_book', status: 'waiting_author', pending }, '直接改', null).kind, 'segment')
  assert.notEqual(segmentReviewKey('job', pending), segmentReviewKey('job', { ...pending, round: 2 }))
  assert.notEqual(segmentReviewKey('job', pending), segmentReviewKey('other', pending))
  assert.notEqual(segmentReviewKey('job', pending), segmentReviewKey('job', old))
  assert.equal(segmentReviewKey('job', null), '')
})

test('篇/卷/章纲确认跟随同一大纲树，新旧next-segment路由一致', () => {
  assert.equal(legacyBookRoute('next-segment'), 'outline?node=pending')
  assert.equal(pendingTarget(pending, 'book').path, '/books/book/outline?node=pending')
  assert.equal(pendingTarget({ kind: 'volume_review', volume: 2 }, 'book').path, '/books/book/outline?node=volume-2')
  const chapters = { kind: 'chapters_review', volume: 1, unit_id: 'u2', unit_title: '破局', first: 4, last: 6 }
  assert.equal(pendingTarget(chapters, 'book').path, '/books/book/outline?node=unit-u2')
  assert.equal(decisionCopy(chapters, 'book').approve, '批准开写')
  assert.equal(composerRoute({ kind: 'write_book', status: 'waiting_author', pending: chapters }, '多一点冲突', null).kind, 'decision')
  const projected = writingOutline(buildOutlineTree(tree), pending, nodes)
  assert.equal(selectOutlineItem(projected, null, pending).key, 'pending')
  assert.equal(selectOutlineItem(projected, 'volume-1', pending).key, 'volume-1')
  assert.equal(selectOutlineItem(projected, 'first-arc', pending).key, 'segment-a')
  assert.equal(selectOutlineItem(buildOutlineTree(tree), null, chapters).key, 'unit-u2')
})

test('卷确认标明卷和单元，章纲确认标明单元和它的章；下一个单元按全书顺序找', () => {
  const root = buildOutlineTree(tree)
  const reviewed = writingOutline(root, { kind: 'volume_review', volume: 1 }, nodes)
  assert.equal(flattenOutline(reviewed).find(item => item.key === 'volume-1').status, 'pending')
  assert.equal(flattenOutline(reviewed).find(item => item.key === 'unit-u2').status, 'pending')
  const current = { kind: 'chapters_review', volume: 1, unit_id: 'u1', unit_title: 'u1', first: 1, last: 1 }
  const marked = flattenOutline(writingOutline(root, current, nodes))
  assert.equal(marked.find(item => item.key === 'chapter-1').status, 'pending')
  assert.equal(outlineReviewMatches(marked.find(item => item.key === 'unit-u1'), current), true)
  assert.equal(outlineReviewMatches(marked.find(item => item.key === 'unit-u2'), current), false)
  assert.equal(nextOutlineUnit(tree), 'u2')
  assert.equal(nextOutlineUnit({ arcs: [{ volumes: [volume(2, [unit('later', 3)]), volume(1, [unit('next', 1)])] }] }), 'next')
})

test('会议卡新篇显示标题正文终点，旧消息继续显示旧事实', () => {
  assert.deepEqual(nextSegmentFields(pending.plan), [{ label: '篇名', value: '天风国篇' }, { label: '一段话', value: '只在待确认里。' }, { label: '终点', value: '青云宗大比：胜出' }])
  assert.deepEqual(nextSegmentFields({ map: '旧地图', goal: '旧目标' }), [{ label: '地图', value: '旧地图' }, { label: '目标', value: '旧目标' }])
  assert.deepEqual(nextSegmentFields({ title: '尚待补齐的新篇', text: '', end: {} }), [{ label: '篇名', value: '尚待补齐的新篇' }])
})

test('展开任务有中文进度，单元章纲开关共用本书和新书默认组件', () => {
  assert.equal(progressText({ active_job: { kind: 'outline_expand', status: 'running', id: 'j' }, chapters_final: 0 }, [], null, null), '展开大纲 · 主编正在展开这一个')
  const shared = readFileSync(new URL('../src/components/settings/WritingSettings.tsx', import.meta.url), 'utf8')
  assert.ok(shared.indexOf('每卷卷纲都要我拍板') < shared.indexOf('每个单元的章纲都给我看'))
  assert.ok(shared.indexOf('每个单元的章纲都给我看') < shared.indexOf('每一篇开写前先给我确认'))
  assert.match(shared, /checked=\{value.chapters_approval \?\? false\}/)
})

test('确认视图不提供改一句，旧页面与专用问卷组件已退役，通用写作组件仍保留', () => {
  const pendingPage = readFileSync(new URL('../src/pages/book/sections/PendingArcReview.tsx', import.meta.url), 'utf8')
  assert.ok(!pendingPage.includes('RewriteField'))
  assert.ok(pendingPage.includes('segmentReview.submit'))
  assert.ok(pendingPage.includes('segmentPinEnd'))
  const layout = readFileSync(new URL('../src/pages/book/BookLayout.tsx', import.meta.url), 'utf8')
  assert.ok(layout.includes('segmentLock.current'))
  for (const path of ['pages/book/sections/NextSegmentPage.tsx', 'lib/nextSegmentQuestions.ts', 'components/QuestionSection.tsx', 'lib/questionTypes.ts']) assert.equal(existsSync(new URL(`../src/${path}`, import.meta.url)), false)
  for (const path of ['components/FactTable.tsx', 'components/EmotionCurve.tsx', 'components/WritingLabels.tsx', 'components/ForeshadowChips.tsx']) assert.equal(existsSync(new URL(`../src/${path}`, import.meta.url)), true)
})
