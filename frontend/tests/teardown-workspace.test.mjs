import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { teardownImportedDate, teardownWorkspaceActions } from '../src/lib/teardownWorkspace.ts'

test('拆书仅关闭结构和 AI 能力，作者书原对象与行为均不变', async () => {
  const calls = []
  const save = async (...args) => { calls.push(args) }
  const actions = {
    live: true, saveBook: save, saveWorld: save, saveNode: save, saveEntry: save,
    createEntry: save, deleteEntry: save, saveRelation: save, saveTemplate: save,
    addNode: save, deleteNode: save, insertNode: save, moveNode: save,
    canAdd: () => true, canDelete: () => true, canArrange: () => true, canEdit: () => false,
    draft: save, rewrite: save, chooseOption: save, writeNode: save, canWrite: () => true,
    splitNode: save, acceptSplit: save,
  }
  for (const source of ['new', 'imported', undefined]) assert.equal(teardownWorkspaceActions(source, actions), actions)
  const locked = teardownWorkspaceActions('teardown', actions)
  for (const ability of ['canAdd', 'canDelete', 'canArrange', 'canWrite']) assert.equal(locked[ability]({}), false)
  for (const ability of ['draft', 'rewrite', 'chooseOption', 'writeNode', 'splitNode', 'acceptSplit']) assert.equal(locked[ability], undefined)
  for (const kind of ['全书', '卷', '单元', '章']) {
    const node = { kind, ref: { type: kind === '章' ? 'chapter' : 'volume', id: '1' } }
    assert.equal(locked.canEdit(node, 'name'), true)
    assert.equal(locked.canEdit(node, 'text'), true)
  }
  assert.equal(locked.canEdit({ virtual: true, ref: { type: 'unit', id: 'fake' } }, 'text'), false)
  assert.equal(locked.canEdit({ virtual: true }, 'name'), false)
  await locked.saveNode({ ref: { type: 'chapter', id: '1' } }, { sections: { 发生什么: '手改章纲' } })
  assert.equal(calls.length, 1)
  for (const ability of ['saveBook', 'saveWorld', 'saveEntry', 'createEntry', 'deleteEntry', 'saveTemplate']) assert.equal(locked[ability], actions[ability])
})

test('导入日期取真实已保存时间，缺失或坏值不捏造日期', () => {
  assert.match(teardownImportedDate('2026-10-20T12:00:00+08:00'), /^2026-10-20$/)
  for (const value of [null, undefined, '', 'bad']) assert.equal(teardownImportedDate(value), '')
})

test('工作台只读外壳明确隐藏写作、待处理、本书设置；保留存档、设置和问问主编', () => {
  const workspace = readFileSync(new URL('../src/pages/workspace/Workspace.tsx', import.meta.url), 'utf8')
  const desk = readFileSync(new URL('../src/pages/workspace/BookDesk.tsx', import.meta.url), 'utf8')
  assert.match(workspace, /!teardown && writing && <WritingStrip/)
  assert.match(workspace, /const editableCount = !teardown/)
  assert.match(workspace, /book\.source !== 'teardown' && <AskButton[^\n]+编辑部帮写/)
  assert.match(workspace, /!teardown && labels\.map/)
  assert.match(workspace, /teardown && bookContext && <button[\s\S]+?问问主编/)
  for (const text of ['还没拆出设定。', '还没拆出章纲', '这些章还没拆，拆的时候会归进单元。', '还没收尾', '原书简介', '文件里没有简介', '还没开拆。']) assert.ok(workspace.includes(text))
  assert.match(desk, /!teardown && <PendingButton/)
  assert.match(desk, /!teardown && <button[^>]+>[\s\S]*?本书设置/)
  assert.ok(desk.includes('chatBallNote={!teardown ? <PendingBallTag'))
  assert.match(desk, /<SavesRow/)
  assert.match(desk, /aria-label="系统设置"/)
  assert.match(desk, /<ChatConvs/)
  assert.match(workspace, /explicitStart: !!start \|\| openTeardownHome/)
})
