import assert from 'node:assert/strict'
import test from 'node:test'
import { setupPreviewForPath } from '../src/pages/book/setupPreview.ts'

const job = { id: 'current', kind: 'book_setup', status: 'running', pending: null }
const message = (type, data = {}, overrides = {}) => ({
  id: 1, book_id: 'book', job_id: job.id, kind: 'artifact', payload: { type, data }, ...overrides,
})

for (const [type, suffix, data] of [
  ['protagonist', '/library?view=focus', { name: '陆远' }],
  ['world', '/library?cat=世界与地图', { surface: '公开修仙' }],
  ['segment', '/outline?node=first-arc', { nodes: [] }],
  ['segment_volumes', '/outline?node=first-arc', { volumes: [] }],
  ['concept', '/concept', { title: '书名' }],
  ['directions', '', { directions: [{ name: '方向一' }] }],
  ['lore', '/library?cat=角色卡片', { characters: [] }],
  ['spine', '/outline?view=map', { opening: '开篇' }],
  ['threads', '/outline?view=threads', { threads: [] }],
  ['outline', '/outline?node=first-arc', { volumes: [] }],
  ['volume_plan', '/outline?node=volume-1', { volume: 1, units: [] }],
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
    assert.equal(setupPreviewForPath('book', { ...job, status }, [artifact], '/books/book/outline?node=first-arc'), null)
  }
  assert.equal(setupPreviewForPath('book', { ...job, kind: 'write_book' }, [artifact], '/books/book/outline?node=first-arc'), null)
  assert.equal(setupPreviewForPath('book', null, [artifact], '/books/book/outline?node=first-arc'), null)
})

test('other books, other jobs, empty data, and unrelated routes cannot leak into a preview', () => {
  const messages = [
    message('concept', {}, { book_id: 'other-book' }),
    message('concept', {}, { job_id: 'old-job' }),
    message('concept', null),
    message('concept', {}, { kind: 'speech' }),
  ]
  assert.equal(setupPreviewForPath('book', job, messages, '/books/book/concept'), null)
  assert.equal(setupPreviewForPath('book', job, [message('concept')], '/books/book/outline?node=first-arc'), null)
})

test('queued setup can still show its checkpoint output without changing payload objects', () => {
  const artifact = Object.freeze(message('outline', Object.freeze({ volumes: [] })))
  assert.equal(setupPreviewForPath('book', { ...job, status: 'queued' }, [artifact], '/books/book/outline?node=first-arc'), artifact)
})

test('map and outline previews stay on their own query-param view without replacing one another', () => {
  const spine = message('spine', { nodes: [{ title: '旧节点' }] })
  const outline = message('outline', { volumes: [{ title: '新分卷' }] }, { id: 2 })
  assert.equal(setupPreviewForPath('book', job, [spine, outline], '/books/book/outline?node=first-arc'), outline)
  assert.equal(setupPreviewForPath('book', job, [spine, outline], '/books/book/outline?view=map'), spine)
  assert.equal(setupPreviewForPath('book', { ...job, status: 'waiting_author', pending: { kind: 'setup_piece', piece: 'segment' } }, [spine, outline], '/books/book/outline?node=first-arc'), null)
})

test('choosing or redoing directions leaves overview loading visible instead of replaying old cards', () => {
  const directions = message('directions', { directions: [{ name: '旧方向' }] })
  const decision = message('',{}, {id:2,kind:'decision',speaker:'author',content:'选方向「旧方向」。'})
  for (const status of ['queued','running']) {
    assert.equal(setupPreviewForPath('book',{...job,status},[directions,decision],'/books/book'),null)
  }
})

test('only outputs after the latest author decision can cover a persisted manuscript', () => {
  const old = message('concept',{title:'旧稿'})
  const decision = message('',{}, {id:2,kind:'decision',speaker:'author',content:'确认定调'})
  assert.equal(setupPreviewForPath('book',job,[old,decision],'/books/book/concept'),null)
  const fresh = message('concept',{title:'新稿'},{id:3})
  const note = message('',{}, {id:4,kind:'note',speaker:'author',content:'补一句意见'})
  assert.equal(setupPreviewForPath('book',job,[old,decision,fresh,note],'/books/book/concept'),fresh)
  const otherJob = {...decision,id:5,job_id:'other-job'}
  const otherBook = {...decision,id:6,book_id:'other-book'}
  const teamDecision = {...decision,id:7,speaker:'chief'}
  assert.equal(setupPreviewForPath('book',job,[fresh,note,otherJob,otherBook,teamDecision],'/books/book/concept'),fresh)
})
