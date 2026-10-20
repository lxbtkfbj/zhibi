import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { teardownRefreshGate } from '../src/lib/teardownRefresh.ts'

test('拆书：每次进度与聊天不拉书，保存只拉两份轻量数据，结束每个job只整本刷新一次', () => {
  const next = teardownRefreshGate()
  for (const status of ['queued', 'running', 'running']) assert.equal(next('job', { id: 'one', status }), 'none')
  assert.equal(next('message'), 'none')
  assert.equal(next('saved'), 'parts')
  assert.equal(next('saved'), 'parts')
  assert.equal(next('job', { id: 'one', status: 'succeeded' }), 'book')
  assert.equal(next('job', { id: 'one', status: 'succeeded' }), 'none')
  assert.equal(next('job', { id: 'two', status: 'cancelled' }), 'book')
  assert.equal(next('job', { id: 'two', status: 'cancelled' }), 'none')
  assert.equal(next('job', { id: 'three', status: 'failed' }), 'book')
})

test('实际SSE接线具有拆书专用边界，作者书保留原来刷新路径', () => {
  const source = readFileSync(new URL('../src/lib/useMeeting.ts', import.meta.url), 'utf8')
  assert.match(source, /source\.addEventListener\('teardown_saved'/)
  assert.match(source, /get<ApiParts\['outline'\]>\(`\/books\/\$\{bookId\}\/outline-tree`\)/)
  assert.match(source, /get<ApiParts\['chapters'\]>\(`\/books\/\$\{bookId\}\/chapters\?with_outline=true`\)/)
  assert.match(source, /generation === partsGeneration/)
  assert.match(source, /if \(isTeardown\(\)\) \{ refresh\(\[\['chat-convs', bookId\]\]\); return \}/)
  assert.match(source, /teardownGate\('job', job\) === 'book'/)
  assert.match(source, /if \(SETTLED\.has\(job\.status\)\)/)
})
