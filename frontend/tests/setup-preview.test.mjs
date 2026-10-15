import assert from 'node:assert/strict'
import test from 'node:test'
import { setupPreviewForPath } from '../src/pages/book/setupPreview.ts'

const job = { id: 'current', kind: 'book_setup', status: 'running', pending: null }
const message = (type, data = {}, overrides = {}) => ({
  id: 1, book_id: 'book', job_id: job.id, kind: 'artifact', payload: { type, data }, ...overrides,
})

for (const [type, suffix, data] of [
  ['concept', '/concept', { title: '书名' }],
  ['lore', '/characters', { characters: [] }],
  ['spine', '/spine', { opening: '开篇' }],
  ['threads', '/threads', { threads: [] }],
  ['outline', '', { volumes: [] }],
  ['volume_plan', '/volume/1', { volume: 1, units: [] }],
]) {
  test(`running setup previews ${type} on its manuscript route`, () => {
    const artifact = message(type, data)
    assert.equal(setupPreviewForPath('book', job, [artifact], `/books/book${suffix}`), artifact)
  })
}

test('preview uses the latest matching artifact, not the latest unrelated output', () => {
  const old = message('concept', { title: '旧稿' })
  const current = message('concept', { title: '本轮修订' }, { id: 2 })
  const lore = message('lore', { characters: [] }, { id: 3 })
  assert.equal(setupPreviewForPath('book', job, [old, current, lore], '/books/book/concept/'), current)
})

test('author questions, review, settled jobs, and writing never replace actual pages', () => {
  const artifact = message('outline', { volumes: [] })
  for (const status of ['waiting_author', 'succeeded', 'failed', 'cancelled']) {
    assert.equal(setupPreviewForPath('book', { ...job, status }, [artifact], '/books/book'), null)
  }
  assert.equal(setupPreviewForPath('book', { ...job, kind: 'write_book' }, [artifact], '/books/book'), null)
  assert.equal(setupPreviewForPath('book', null, [artifact], '/books/book'), null)
})

test('other books, other jobs, empty data, and unrelated routes cannot leak into a preview', () => {
  const messages = [
    message('concept', {}, { book_id: 'other-book' }),
    message('concept', {}, { job_id: 'old-job' }),
    message('concept', null),
    message('concept', {}, { kind: 'speech' }),
  ]
  assert.equal(setupPreviewForPath('book', job, messages, '/books/book/concept'), null)
  assert.equal(setupPreviewForPath('book', job, [message('concept')], '/books/book/spine'), null)
})

test('queued setup can still show its checkpoint output without changing payload objects', () => {
  const artifact = Object.freeze(message('outline', Object.freeze({ volumes: [] })))
  assert.equal(setupPreviewForPath('book', { ...job, status: 'queued' }, [artifact], '/books/book'), artifact)
})
