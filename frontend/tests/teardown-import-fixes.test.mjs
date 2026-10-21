import assert from 'node:assert/strict'
import test from 'node:test'
import { initialWorkspaceDirectoryOpen, resolveWorkspaceReadingPosition } from '../src/lib/workspaceReadingPosition.ts'

const node = (id, kind, children = []) => ({ id, kind, children })
const book = {
  id: 'arc-book', source: 'teardown', categories: [{ name: '角色列表', entries: [{ id: 'hero' }] }],
  outline: node('book', '全书', [node('arc-one', '篇', [node('volume', '卷', [node('unit', '单元', [node('c1', '章')])])]), node('arc-two', '篇')]),
}
const position = { tab: '大纲', entry: 'overview', node: 'volume', chapter: 'home', open: ['book', 'volume'] }

test('篇默认全部展开，迁移旧目录不丢原来的卷、单元和类别状态', () => {
  for (const source of ['new', 'teardown']) for (const directoryVersion of [undefined, 1]) {
    assert.deepEqual(initialWorkspaceDirectoryOpen({ ...book, source }, { ...position, directoryVersion }), ['book', 'volume', 'arc-one', 'arc-two'])
  }
  assert.deepEqual(initialWorkspaceDirectoryOpen(book, { ...position, entry: 'hero' }), ['book', 'volume', 'arc-one', 'arc-two', 'cat:角色列表'])
  assert.deepEqual(initialWorkspaceDirectoryOpen(book, { ...position, directoryVersion: 1, open: ['cat:角色列表'] }), ['cat:角色列表', 'arc-one', 'arc-two'])
})

test('新版本明确收起的篇刷新不再自动展开，无篇的书保留原状态', () => {
  for (const open of [[], ['book', 'arc-two'], ['book', 'arc-one', 'volume', 'unit']]) {
    const saved = resolveWorkspaceReadingPosition(book, { ...position, directoryVersion: 2, open }, position, true)
    assert.equal(saved.directoryVersion, 2)
    assert.deepEqual(initialWorkspaceDirectoryOpen(book, saved), open)
  }
  const direct = { ...book, outline: node('book', '全书', [node('volume', '卷')]) }
  assert.deepEqual(initialWorkspaceDirectoryOpen(direct, { ...position, directoryVersion: 1 }), position.open)
})
