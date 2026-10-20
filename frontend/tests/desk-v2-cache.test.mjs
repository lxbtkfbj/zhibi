import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { QueryClient } from '@tanstack/react-query'
import ts from 'typescript'
import { teardownRefreshGate } from '../src/lib/teardownRefresh.ts'

const read = file => readFileSync(new URL(file, import.meta.url), 'utf8')
// 执行真正的 hook 回调，只替换 React 调度和 HTTP；缓存仍用真正的 QueryClient。
function load(file, imports, timers = {}) {
  const { outputText } = ts.transpileModule(read(file), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', 'setTimeout', 'clearTimeout', 'EventSource', outputText)(
    name => {
      assert.ok(name in imports, `未模拟的依赖 ${name}`)
      return imports[name]
    }, module, module.exports, timers.setTimeout ?? (() => 1), timers.clearTimeout ?? (() => {}), timers.EventSource,
  )
  return module.exports
}

const react = {
  useMemo: fn => fn(), useCallback: fn => fn, useEffect: fn => { fn() },
  useRef: current => ({ current }), useState: value => [typeof value === 'function' ? value() : value, () => {}],
}
const keyFactory = () => new Proxy({ books: ['books'] }, { get: (value, name) => value[name] ?? (id => [name, id]) })
const keys = keyFactory(), settingsKeys = keyFactory(), libraryKeys = keyFactory()
const chapterKey = (book = 'book-a', chapter = 'c1') => ['desk-v2-chapter', book, chapter, 4, false]
const node = { id: 'c1', kind: '章', ref: { type: 'chapter', id: '1' }, body: { words: 4, status: 'done' } }

function hooks(qc, api = {}) {
  const parts = { book: { source: 'new' }, library: { entries: [] } }
  const client = { get: async () => ({}), post: async () => ({}), patch: async () => ({}), put: async () => ({}), del: async () => ({}), ...api }
  const query = { useQueryClient: () => qc, useQuery: () => ({ data: parts }) }
  const actions = load('../src/pages/workspace/liveActions.ts', {
    '@tanstack/react-query': query, react, '../../api/client': client, '../../api/hooks': { keys },
    './fromApi': { bookFromApi: () => ({}), CHARACTER_COLUMNS: {}, ENTRY_CATEGORY: {}, WORLD_OVERVIEW: '世界概况' }, './model': {},
  })
  const writing = load('../src/pages/workspace/liveWriting.ts', {
    '@tanstack/react-query': query, react, '../../api/client': client, '../../api/hooks': { keys },
    '../../api/settings': { settingsKeys, useBookSettings: () => ({ data: { settings: {} } }) },
    './liveActions': actions, './model': {}, './writing': {},
  })
  return { actions, writing }
}

function cache(t) {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 5000, retry: false } } })
  t.after(() => qc.clear())
  qc.setQueryData(chapterKey(), { text: '旧稿四字' })
  qc.setQueryData(chapterKey('book-a', 'c2'), { text: '本书另一章' })
  qc.setQueryData(chapterKey('book-b'), { text: '别书不失效' })
  return qc
}

function assertBookInvalidated(qc) {
  assert.equal(qc.getQueryState(chapterKey()).isInvalidated, true)
  assert.equal(qc.getQueryState(chapterKey('book-a', 'c2')).isInvalidated, true)
  assert.equal(qc.getQueryState(chapterKey('book-b')).isInvalidated, false)
}

test('同字数手改后立即返回：正文、review和changes都重新读，不等五秒过期', async t => {
  const qc = cache(t)
  let chapter = { content: '旧稿四字', changes: ['旧变化'], review: { review: { highlights: ['旧看点'], issues: [] } } }
  const { writing } = hooks(qc, {
    get: async () => chapter,
    patch: async (_, body) => { chapter = { content: body.content, changes: ['新变化'], review: { review: { highlights: ['新看点'], issues: [{ problem: '新问题' }] } } } },
  })
  const control = writing.useLiveWriting({ bookId: 'book-a', detail: {}, messages: [], draft: null })
  // 相同的书、章、字数和read key已经是fresh；普通fetch不会拉第二次。
  const options = { queryKey: chapterKey(), queryFn: () => control.loadChapter(node) }
  await control.setText(node, '新稿四字')
  assertBookInvalidated(qc)
  assert.deepEqual(await qc.fetchQuery(options), { text: '新稿四字', changes: ['新变化'], teardown: undefined, review: { good: ['新看点'], issues: ['新问题'] } })
})

test('真实actions完成路径覆盖采纳候选、撤销版本和章纲手改，整书前缀不漏其他章', async t => {
  const qc = cache(t)
  const { actions } = hooks(qc)
  const control = actions.useLiveBook('book-a').actions
  for (const operation of [() => control.chooseOption('candidate', 0), () => control.revert('version'), () => control.saveNode(node, { name: '新章名' })]) {
    qc.setQueryData(chapterKey(), { text: '仍是fresh' })
    qc.setQueryData(chapterKey('book-a', 'c2'), { text: '仍是fresh' })
    await operation()
    assertBookInvalidated(qc)
  }
})

test('真实写作进度effect覆盖重写结束、正文定稿与审稿产物，字数不变也清正文详情', async t => {
  const qc = cache(t)
  const { writing } = hooks(qc)
  for (const [status, done, artifacts] of [['running', true, 1], ['waiting_author', true, 2], ['succeeded', true, 3]]) {
    qc.setQueryData(chapterKey(), { text: '仍是fresh' })
    qc.setQueryData(chapterKey('book-a', 'c2'), { text: '仍是fresh' })
    writing.useLiveWriting({
      bookId: 'book-a', detail: { active_job: { id: 'rewrite', kind: 'rewrite_chapter', status } },
      draft: { job_id: 'rewrite', chapter: 1, done }, messages: Array.from({ length: artifacts }, () => ({ job_id: 'rewrite', kind: 'artifact' })),
    })
    assertBookInvalidated(qc)
  }
})

test('真实SSE的book/library、聊天修改和任务终态都失效同书章节缓存', async t => {
  const qc = cache(t), timers = [], listeners = new Map()
  qc.setQueryData(keys.book('book-a'), { source: 'new' })
  const module = load('../src/lib/useMeeting.ts', {
    '@tanstack/react-query': { useQueryClient: () => qc }, react, '../api/hooks': { keys }, '../api/settings': { settingsKeys },
    '../api/library': { libraryKeys }, '../api/client': { get: async () => ({}) }, './teardownRefresh': { teardownRefreshGate },
  }, { setTimeout: fn => { timers.push(fn); return timers.length }, EventSource: class { addEventListener(name, fn) { listeners.set(name, fn) } close() {} } })
  module.useMeeting('book-a')
  for (const [name, data] of [
    ['book', {}], ['library', {}], ['message_update', { id: 1 }],
    ['message', { id: 2, kind: 'artifact', payload: { type: 'chapter_final' } }], ['job', { id: 'write', kind: 'write_book', status: 'succeeded' }],
  ]) {
    qc.setQueryData(chapterKey(), { text: '仍是fresh' })
    qc.setQueryData(chapterKey('book-a', 'c2'), { text: '仍是fresh' })
    listeners.get(name)({ data: JSON.stringify(data) })
    while (timers.length) timers.shift()()
    assertBookInvalidated(qc)
  }
})

test('恢复存档的即时失效包含章节前缀，useDeskChapter不以字数变动代替失效', () => {
  const saves = read('../src/pages/workspace/Saves.tsx')
  const restore = saves.slice(saves.indexOf('const restore = async'), saves.indexOf('const data = detail.data'))
  assert.match(restore, /\['desk-v2-chapter', bookId\]/)
  assert.match(read('../src/pages/workspace/desk-v2/OutlinePages.tsx'), /queryKey: \['desk-v2-chapter', book\.id, node\?\.id/)
})

test('编辑部HTTP采纳/撤销候选不必等SSE，公共设定刷新失效同书正文详情', async t => {
  const qc = cache(t)
  const module = load('../src/api/library.ts', {
    '@tanstack/react-query': { useQueryClient: () => qc }, './hooks': { keys }, './client': {},
  })
  await module.useInvalidateLibrary('book-a')()
  assertBookInvalidated(qc)
  const chat = read('../src/pages/book/ChatActions.tsx')
  const noteRefresh = chat.slice(chat.indexOf('const refresh = () =>'), chat.indexOf('const act = async'))
  assert.match(noteRefresh, /\['desk-v2-chapter', bookId\]/)
  const candidateRefresh = chat.slice(chat.lastIndexOf('const refresh = () =>'), chat.indexOf('const choose = async'))
  assert.match(candidateRefresh, /\['desk-v2-chapter', bookId\]/)
})
