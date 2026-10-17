import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { THREE_PIECES, pieceStatuses } from '../src/lib/storyMap.ts'
import { artifactTarget, pendingTarget, progressText } from '../src/lib/workspace.ts'
import { initialWriteRequest, waitForSetupCompletion } from '../src/lib/setupThree.ts'

test('新三步只显示定调、设定库、大纲，实际确认状态不由内容臆测', () => {
  assert.deepEqual(THREE_PIECES.map(piece => [piece.key, piece.name, piece.path]), [['concept', '定调', '/concept'], ['settings', '设定库', '/library?view=focus'], ['outline', '大纲', '/outline?node=first-arc']])
  assert.deepEqual(pieceStatuses({ current: 'settings', pieces: { concept: 'confirmed', settings: 'waiting' } }, 3).pieces.map(piece => piece.status), ['confirmed', 'waiting', 'todo'])
  for (const piece of THREE_PIECES) assert.equal(pendingTarget({ kind: 'setup_piece', flow: 3, piece: piece.key }, 'book').path, `/books/book${piece.path}`)
  assert.equal(pendingTarget({ kind: 'setup_pitches', flow: 3 }, 'book').label, '三个短版')
})

test('重点和其余设定产出自动跟随设定库，三步状态使用新名称', () => {
  for (const type of ['settings_focus', 'settings_rest']) assert.deepEqual(artifactTarget({ payload: { type, data: {} } }, 'book'), { path: '/books/book/library?view=focus', label: '设定库' })
  assert.equal(progressText({ active_job: { setup_flow: 3, status: 'waiting_author', pending: { kind: 'setup_piece', flow: 3, piece: 'settings' } } }, [], null, null), '等你确认：设定库')
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

test('正式页面使用后端类别和候选接口，不复制类别配置，不保留新建提问选项', () => {
  const home = readFileSync(new URL('../src/pages/Home.tsx', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/pages/book/sections/LibraryPage.tsx', import.meta.url), 'utf8')
  const pitches = readFileSync(new URL('../src/pages/book/PitchSelection.tsx', import.meta.url), 'utf8')
  assert.ok(!home.includes('先问我几个问题'))
  assert.ok(home.includes('定调和设定库做完不停，停在大纲给你看'))
  assert.ok(page.includes('useLibraryConfig'))
  assert.ok(page.includes('SetupGate'))
  assert.ok(pitches.includes('index: index + 1'))
  assert.ok(pitches.includes('pending.recommended === index + 1'))
})


test('旧流程只有只读产出和重开入口，不再提供重新打开这一块', () => {
  const preview = readFileSync(new URL('../src/pages/book/SetupArtifactPreview.tsx', import.meta.url), 'utf8')
  const decisions = readFileSync(new URL('../src/pages/book/PieceDecisions.tsx', import.meta.url), 'utf8')
  assert.ok(preview.includes('needsSetupRestart(book, job)'))
  assert.ok(preview.includes('<fieldset disabled'))
  assert.ok(!decisions.includes("action: 'reopen'"))
  assert.ok(!decisions.includes('重新打开这一块'))
})
