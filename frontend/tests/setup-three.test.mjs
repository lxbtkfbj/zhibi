import assert from 'node:assert/strict'
import test from 'node:test'
import { existsSync, readFileSync } from 'node:fs'
import { THREE_PIECES, pieceStatuses } from '../src/lib/storyMap.ts'
import { artifactTarget, pendingTarget, progressText } from '../src/lib/workspace.ts'
import { initialWriteRequest, waitForSetupCompletion } from '../src/lib/setupThree.ts'

test('新三步只显示定调、设定库、大纲，实际确认状态不由内容臆测', () => {
  assert.deepEqual(THREE_PIECES.map(piece => [piece.key, piece.name, piece.path]), [['concept', '定调', '/concept'], ['settings', '设定库', '/library?view=focus'], ['outline', '大纲', '/outline?node=first-arc']])
  assert.deepEqual(pieceStatuses({ current: 'settings', pieces: { concept: 'confirmed', settings: 'waiting' } }, 3).pieces.map(piece => piece.status), ['confirmed', 'waiting', 'todo'])
  for (const piece of THREE_PIECES) assert.equal(pendingTarget({ kind: 'setup_piece', flow: 3, piece: piece.key }, 'book').path, `/books/book${piece.key === 'settings' ? '/concept' : piece.path}`)
  assert.equal(pendingTarget({ kind: 'setup_pitches', flow: 3 }, 'book').label, '三个故事方向')
})

test('重点和其余设定产出自动跟随设定库，三步状态使用新名称', () => {
  for (const type of ['settings_focus', 'settings_rest']) assert.deepEqual(artifactTarget({ payload: { type, data: {} } }, 'book'), { path: '/books/book/library?view=focus', label: '设定库' })
  assert.equal(progressText({ active_job: { setup_flow: 3, status: 'waiting_author', pending: { kind: 'setup_piece', flow: 3, piece: 'settings' } } }, [], null, null), '等你确认：定调和设定库')
})

test('确认开写等待同一任务成功，不在运行中、失败、取消或超时后开写', async () => {
  const statuses = ['queued', 'running', 'succeeded']
  let reads = 0, waits = 0
  await waitForSetupCompletion(async () => ({ status: statuses[reads++] }), async () => { waits += 1 })
  assert.equal(reads, 3)
  assert.equal(waits, 2)
  for (const status of ['failed', 'cancelled']) await assert.rejects(waitForSetupCompletion(async () => ({ status, error: '未完成' }), async () => {}), /未完成/)
  await assert.rejects(waitForSetupCompletion(async () => ({ status: 'running' }), async () => {}, 2), /暂未自动开写/)
  assert.deepEqual(initialWriteRequest({ chapters_final: 0, trial_read_done: false }), { until: 'count', count: 3 })
  assert.deepEqual(initialWriteRequest({ chapters_final: 3, trial_read_done: true }), { until: 'count', count: 10 })
})

test('首页不保留新建提问选项，只剩「开新书」进新建页', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  assert.ok(!home.includes('先问我几个问题'))
  // 首页只剩「开新书」，进新建页；开书方式那一排已经去掉
  assert.ok(home.includes("navigate('/new'"))
})

test('旧版书页退役：旧的开书流程页面（选方向、拍板条、只读产出）都拿掉了', () => {
  for (const path of ['pages/book/sections/LibraryPage.tsx', 'pages/book/PitchSelection.tsx', 'pages/book/ActionBar.tsx', 'pages/book/SetupArtifactPreview.tsx', 'pages/book/PieceDecisions.tsx']) assert.equal(existsSync(new URL(`../src/${path}`, import.meta.url)), false)
})
