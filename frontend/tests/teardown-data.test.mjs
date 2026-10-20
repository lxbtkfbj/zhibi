import assert from 'node:assert/strict'
import test from 'node:test'
import { bookFromApi } from '../src/pages/workspace/fromApi.ts'

const summary = {
  stage: 'imported', author: '原作者', intro: '原书简介', chars: 1720000, chapters: 2, volumes: 1,
  number_issue_total: 2, excluded_count: 1, open_volume_id: 'volume', imported_at: '2026-10-20T02:00:00Z',
}
const chapter = (index, extra = {}) => ({
  id: `chapter-${index}`, index, title: `章名${index}`, volume_id: 'volume', unit_id: null,
  status: 'final', word_count: 3120, summary: '', attempts: 0, outline: null, ...extra,
})
function parts(source = 'teardown') {
  return {
    book: { id: 'book-id', title: '手改书名', genre: '', source, teardown: summary, concept: { title: '旧概念书名' } },
    library: { characters: [], entries: [], categories: [], suggestions_pending: 0 },
    relationships: [],
    chapters: [chapter(1)],
    outline: {
      segmented: false, ending: null,
      arcs: [{
        node_id: null, title: '', text: '', status: 'done', locked: false, planned: true, end: null,
        volumes: [{
          id: 'volume', index: 1, title: '还没分卷', summary: '', chapter_count: 2, status: 'done', locked: false, open: true,
          units: [{
            id: 'unassigned:volume', index: null, title: '还没归单元', summary: '', chapter_count: 2, status: 'done', locked: false, virtual: true,
            chapters: [{ index: 1, title: '章名1', status: 'final', word_count: 3120 }, { index: 2, title: '', status: 'final', word_count: 2145 }],
          }],
        }],
      }],
    },
  }
}

test('拆书来源和摘要原样带到工作台，书名以手改后的真实书名为准', () => {
  const book = bookFromApi(parts())
  assert.equal(book.source, 'teardown')
  assert.equal(book.title, '手改书名')
  assert.deepEqual(book.teardown, summary)
  assert.equal(book.teardown.imported_at, '2026-10-20T02:00:00Z')
})

test('虚单元只做显示容器，没有可写的真实 unit 引用；卷保留还没收尾标记', () => {
  const volume = bookFromApi(parts()).outline.children[0]
  assert.equal(volume.open, true)
  assert.deepEqual(volume.ref, { type: 'volume', id: 'volume' })
  const unit = volume.children[0]
  assert.equal(unit.title, '还没归单元')
  assert.equal(unit.virtual, true)
  assert.equal(unit.ref, undefined)
  assert.deepEqual(unit.range, [1, 2])
})

test('拆书空章纲保持三栏可手改，不伪造摘要；正文只保留字数、不预加载原文', () => {
  const chapters = bookFromApi(parts()).outline.children[0].children[0].children
  assert.deepEqual(chapters[0].sections.map(({ label, text }) => ({ label, text })), [
    { label: '发生什么', text: '' }, { label: '看点', text: '' }, { label: '结尾钩子', text: '' },
  ])
  assert.deepEqual(chapters[0].ref, { type: 'chapter', id: '1' })
  assert.equal(chapters[0].body.words, 3120)
  assert.equal(chapters[0].body.text, undefined)
  assert.equal(chapters[1].body.words, 2145, '列表缺章时仍保留大纲树里的字数')
  assert.equal(chapters[1].title, '第2章　')
})

test('作者自己的书与没有来源的旧快照仍沿用原来的书名和章纲显示', () => {
  for (const source of ['new', 'imported', undefined]) {
    const input = parts(source)
    if (source === undefined) delete input.book.source
    input.book.teardown = null
    input.chapters[0].summary = '这一章写了什么'
    const unit = input.outline.arcs[0].volumes[0].units[0]
    delete unit.virtual
    unit.id = 'real-unit'
    unit.index = 1
    const book = bookFromApi(input)
    assert.equal(book.title, '旧概念书名')
    const mapped = book.outline.children[0].children[0]
    assert.deepEqual(mapped.ref, { type: 'unit', id: 'real-unit' })
    assert.match(mapped.title, /^单元一　/)
    assert.deepEqual(mapped.children[0].sections, [{ label: '这一章写了什么', text: '这一章写了什么' }])
  }
})

test('拆书目录状态随章节点传递；自己的书没有拆书字段，目录不冒充单章全文记录', () => {
  const input = parts()
  input.chapters[0].teardown = { read: true, failed: false }
  const mapped = bookFromApi(input).outline.children[0].children[0].children[0]
  assert.deepEqual(mapped.teardown, { read: true, failed: false })
  assert.equal(mapped.body.teardown, undefined)
  input.book.source = 'new'
  const own = bookFromApi(input).outline.children[0].children[0].children[0]
  assert.equal(Object.hasOwn(own, 'teardown'), false)
})
