import assert from 'node:assert/strict'
import test from 'node:test'
import { clearTeardownEntry, readWorkspaceReadingPosition, resolveWorkspaceReadingPosition, teardownEntryTab, writeWorkspaceReadingPosition } from '../src/lib/workspaceReadingPosition.ts'

const node = (id, kind, children = []) => ({ id, kind, children })
const book = id => ({
  id,
  categories: [{ name: '角色列表', entries: [{ id: 'hero' }, { id: 'friend' }] }, { name: '地点', entries: [{ id: 'town' }] }],
  outline: node('book', '全书', [node('volume', '卷', [node('unit', '单元', [node('c1', '章'), node('c2', '章')])])]),
})
const fallback = { tab: '设定', entry: 'hero', node: 'unit', chapter: 'home', open: ['book', 'volume', 'unit'] }
const live = { live: true, manuscript: true }
const position = { tab: '正文', entry: 'town', node: 'c1', chapter: 'c2', open: ['book', 'volume'] }

test('书架拆书入口进简介，导入入口仍进正文，不改作者书与普通返回', () => {
  assert.equal(teardownEntryTab('teardown', { teardownIntro: true }), '简介')
  assert.equal(teardownEntryTab('teardown', { teardownHome: true }), '正文')
  assert.equal(teardownEntryTab('teardown', { teardownIntro: true, teardownHome: true }), '简介')
  for (const source of ['new', 'imported', undefined]) assert.equal(teardownEntryTab(source, { teardownIntro: true }), undefined)
  for (const state of [null, undefined, [], 'intro', {}, { teardownIntro: false }, { teardownIntro: 'true' }]) assert.equal(teardownEntryTab('teardown', state), undefined)
})

test('一次性入口消费只去掉两个入口标记，不改其他路由状态或原对象', () => {
  const state = { teardownIntro: true, teardownHome: true, other: { keep: '不动其他状态' } }
  assert.deepEqual(clearTeardownEntry(state), { other: state.other })
  assert.equal(state.teardownIntro, true)
  assert.equal(state.teardownHome, true)
  assert.equal(teardownEntryTab('teardown', clearTeardownEntry(state)), undefined)
  assert.equal(clearTeardownEntry({ teardownIntro: true }), null)
  assert.equal(clearTeardownEntry({ teardownHome: true }), null)
})

test('简介入口只覆盖本次进入，之后阅读、刷新和提示词返回仍保留当前章节', () => {
  const current = book('shelf-intro')
  writeWorkspaceReadingPosition(current, position, fallback, live)
  const state = { teardownIntro: true }
  const intro = { ...fallback, tab: teardownEntryTab('teardown', state) }
  assert.equal(readWorkspaceReadingPosition(current, intro, { ...live, explicitStart: true }).tab, '简介')
  // 进入后消费标记；切到正文并阅读第二章后，普通返回/刷新不再强制进简介。
  const consumed = clearTeardownEntry(state)
  writeWorkspaceReadingPosition(current, position, fallback, live)
  assert.deepEqual(readWorkspaceReadingPosition(current, fallback, { ...live, explicitStart: teardownEntryTab('teardown', consumed) !== undefined }), position)
})

test('reading positions return to the selected manuscript/entry/node and keep books separate', () => {
  writeWorkspaceReadingPosition(book('reading-one'), position, fallback, live)
  assert.deepEqual(readWorkspaceReadingPosition(book('reading-one'), fallback, live), position)
  assert.deepEqual(readWorkspaceReadingPosition(book('reading-two'), fallback, live), fallback)
  writeWorkspaceReadingPosition(book('reading-two'), { ...position, tab: '大纲', node: 'volume' }, fallback, live)
  assert.equal(readWorkspaceReadingPosition(book('reading-two'), fallback, live).node, 'volume')
  assert.equal(readWorkspaceReadingPosition(book('reading-one'), fallback, live).chapter, 'c2')
})

test('deleted IDs, unsaved draft IDs, nonchapter manuscript IDs, and invalid tabs safely fall back', () => {
  const invalid = { tab: '不存在', entry: 'draft-not-saved', node: 'deleted', chapter: 'volume', open: ['book', 'deleted', 2, 'book'] }
  assert.deepEqual(resolveWorkspaceReadingPosition(book('invalid'), invalid, fallback, true), { ...fallback, open: ['book'] })
  assert.equal(resolveWorkspaceReadingPosition(book('category'), { entry: 'cat:地点' }, fallback, true).entry, 'cat:地点')
  assert.equal(resolveWorkspaceReadingPosition(book('category'), { entry: 'cat:已删除' }, fallback, true).entry, 'hero')
  for (const entry of ['overview', 'world', 'friend']) assert.equal(resolveWorkspaceReadingPosition(book('special'), { entry }, fallback, true).entry, entry)
})

test('changed book shape cannot restore a chapter or entry that no longer exists', () => {
  const old = book('deleted-after-leaving')
  writeWorkspaceReadingPosition(old, position, fallback, live)
  const changed = { ...old, categories: [old.categories[0]], outline: node('book', '全书', [node('unit', '单元')]) }
  assert.deepEqual(readWorkspaceReadingPosition(changed, fallback, live), { ...fallback, tab: '正文', open: ['book'] })
})

test('missing manuscript support falls back to settings; empty expanded-tree state is retained', () => {
  const actual = resolveWorkspaceReadingPosition(book('without-writing'), { ...position, open: [] }, fallback, false)
  assert.equal(actual.tab, '设定')
  assert.deepEqual(actual.open, [])
})

test('prototype never reads or overwrites live positions, and explicit starts take priority', () => {
  const same = book('prototype-safe')
  writeWorkspaceReadingPosition(same, position, fallback, live)
  assert.deepEqual(readWorkspaceReadingPosition(same, fallback, { ...live, live: false }), fallback)
  writeWorkspaceReadingPosition(same, fallback, fallback, { ...live, live: false })
  assert.deepEqual(readWorkspaceReadingPosition(same, fallback, live), position)
  const explicit = { ...fallback, tab: '大纲', node: 'volume' }
  assert.deepEqual(readWorkspaceReadingPosition(same, explicit, { ...live, explicitStart: true }), explicit)
})

test('session storage only receives whitelisted UI fields, and damaged records do not throw', () => {
  const values = new Map()
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) } })
  try {
    const current = book('serialized')
    writeWorkspaceReadingPosition(current, { ...position, content: '不要保存书稿', draft: '不要保存编辑草稿' }, fallback, live)
    const stored = values.get('zhibi:workspace-reading:serialized')
    assert.deepEqual(JSON.parse(stored), position)
    assert.deepEqual(readWorkspaceReadingPosition(current, fallback, live), position)
    values.set('zhibi:workspace-reading:bad-json', '{broken')
    assert.deepEqual(readWorkspaceReadingPosition(book('bad-json'), fallback, live), fallback)
    for (const raw of ['null', '[]', '42', '{"open":"book","entry":null,"tab":17}']) {
      values.set('zhibi:workspace-reading:bad-shape', raw)
      assert.deepEqual(readWorkspaceReadingPosition(book('bad-shape'), fallback, live), fallback)
    }
  } finally {
    if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
    else delete globalThis.sessionStorage
  }
})

test('拆书精髓记住节，作者书忽略精髓标签，损坏节键回到核心要点', () => {
  const teardown = { ...book('essence-reading'), source: 'teardown' }
  const core = { ...fallback, essence: 'overview' }
  for (const essence of ['overview', 'source', 'cast', 'opening']) {
    const selected = { ...position, tab: '精髓', essence }
    writeWorkspaceReadingPosition(teardown, selected, core, live)
    assert.deepEqual(readWorkspaceReadingPosition(teardown, core, live), selected)
  }
  assert.equal(resolveWorkspaceReadingPosition(teardown, { tab: '精髓', essence: '坏键' }, core, true).essence, 'overview')
  assert.equal(resolveWorkspaceReadingPosition(book('author-no-essence'), { tab: '精髓', essence: 'cast' }, fallback, true).tab, '设定')
})

test('目录保存明确收起状态和分类展开，不把条目 id 当可展开节点', () => {
  const current = book('category-fold')
  const folded = { ...position, tab: '设定', directoryVersion: 1, open: [] }
  writeWorkspaceReadingPosition(current, folded, fallback, live)
  assert.deepEqual(readWorkspaceReadingPosition(current, fallback, live), folded)
  assert.deepEqual(resolveWorkspaceReadingPosition(current, { ...folded, open: ['cat:角色列表', 'world', 'cat:已删', 'friend'] }, fallback, true).open, ['cat:角色列表', 'world'])
})
