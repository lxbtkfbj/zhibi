import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { handbookApi } from '../src/api/handbooks.ts'
import { clearHandbookDraftIfUnchanged, handbookDraftChanged, readHandbookDraft, writeHandbookDraft } from '../src/lib/handbookDrafts.ts'
import { changeHandbookEnabled, compareHandbookParagraphs, visibleHandbooks } from '../src/lib/handbookEditor.ts'
import { handbooksHref } from '../src/lib/handbookNavigation.ts'
import { promptsHref, readPromptReturnContext } from '../src/lib/promptNavigation.ts'
import { presetsHref } from '../src/lib/presetNavigation.ts'

const books = [{ key: 'opening', name: '开书', when: '要定主角的时候', enabled: true }, { key: 'standards', name: '写书的标准', when: '写好了以后核对 ABC', enabled: false }]
const browserStorage = () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage'), values = new Map()
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) } })
  return { values, restore: () => { if (original) Object.defineProperty(globalThis, 'sessionStorage', original); else delete globalThis.sessionStorage } }
}

test('手册列表搜索名称或什么时候翻，忽略前后空格和英文大小写，不改原顺序', () => {
  assert.deepEqual(visibleHandbooks(books, '').map(book => book.key), ['opening', 'standards'])
  assert.deepEqual(visibleHandbooks(books, ' 开书 '), [books[0]])
  assert.deepEqual(visibleHandbooks(books, '主角'), [books[0]])
  assert.deepEqual(visibleHandbooks(books, 'aBc'), [books[1]])
  assert.deepEqual(visibleHandbooks(books, '不存在'), [])
  assert.equal(books[1].enabled, false)
})

test('打开被422拦下时回到已提交的开关状态，显示后台原话，不吞掉非422网络错误', async () => {
  const item = books[1]
  const text = '名称、什么时候翻、正文都写上，才能打开。'
  const result = await changeHandbookEnabled(item, async enabled => { assert.equal(enabled, true); throw Object.assign(new Error(text), { status: 422 }) })
  assert.equal(result.item, item)
  assert.equal(result.item.enabled, false)
  assert.equal(result.error, text)
  const success = await changeHandbookEnabled(item, async enabled => ({ ...item, enabled }))
  assert.equal(success.item.enabled, true)
  assert.equal(success.error, '')
  assert.equal(item.enabled, false)
  assert.equal((await changeHandbookEnabled(item, async () => { throw new Error('网络断开') })).error, '网络断开')
})

test('三字段草稿切换后仍在，空正文不回落；放弃只清这一本，存储不可用也保留', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage')
  const storage = new Map()
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) } })
  try {
    const draft = { name: '我的开书', when: '作者自己写的时机', body: '' }
    writeHandbookDraft('unit-first', draft)
    writeHandbookDraft('unit-second', { name: '另一本', when: '', body: '  原文\n末尾  ' })
    draft.name = '不应跟着改'
    assert.deepEqual(readHandbookDraft('unit-first'), { name: '我的开书', when: '作者自己写的时机', body: '' })
    assert.deepEqual(JSON.parse(storage.get('zhibi:handbook-draft:unit-first')), readHandbookDraft('unit-first'))
    assert.equal(readHandbookDraft('unit-second').body, '  原文\n末尾  ')
    writeHandbookDraft('unit-first', null)
    assert.equal(readHandbookDraft('unit-first'), null)
    assert.equal(storage.has('zhibi:handbook-draft:unit-first'), false)
    assert.equal(readHandbookDraft('unit-second').name, '另一本')
    storage.set('zhibi:handbook-draft:from-storage', JSON.stringify({ name: '刷新后', when: '', body: '' }))
    assert.deepEqual(readHandbookDraft('from-storage'), { name: '刷新后', when: '', body: '' })
    storage.set('zhibi:handbook-draft:invalid', JSON.stringify({ name: '不完整', body: '' }))
    assert.equal(readHandbookDraft('invalid'), null)
    Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, get: () => { throw new Error('blocked') } })
    assert.doesNotThrow(() => writeHandbookDraft('blocked-handbook', { name: '草稿', when: '', body: '' }))
    assert.equal(readHandbookDraft('blocked-handbook').name, '草稿')
  } finally {
    if (original) Object.defineProperty(globalThis, 'sessionStorage', original)
    else delete globalThis.sessionStorage
  }
})

test('草稿按三个字段逐字判断，不去正文前后空格', () => {
  const book = { name: '开书', when: '开书时', body: '正文\n' }
  assert.equal(handbookDraftChanged(book, { ...book }), false)
  for (const key of ['name', 'when', 'body']) assert.equal(handbookDraftChanged(book, { ...book, [key]: book[key] + ' ' }), true)
})

test('旧页面慢保存完成不能清掉离页后新页面继续写的持久草稿，三字段分别保护', async () => {
  const storage = browserStorage()
  try {
  for (const field of ['name', 'when', 'body']) {
    const key = `slow-save-${field}`
    const submitted = { name: '旧名称', when: '旧时机', body: '旧页提交的正文\n' }
    writeHandbookDraft(key, submitted)
    let complete
    const request = new Promise(resolve => { complete = resolve })
    // This is the former page's completion; its submitted snapshot must not change with a new editor.
    const oldPageSave = request.then(() => clearHandbookDraftIfUnchanged(key, submitted))
    const newer = { ...submitted, [field]: submitted[field] + '离页回来以后又写的新稿' }
    writeHandbookDraft(key, newer)
    complete()
    const cleared = await oldPageSave
    assert.deepEqual(JSON.parse(storage.values.get(`zhibi:handbook-draft:${key}`) ?? 'null'), newer, 'sessionStorage持久稿仍在，刷新不会丢')
    assert.deepEqual(readHandbookDraft(key), newer, `旧保存不能删新${field}，刷新还要读到它`)
    assert.equal(cleared, false)
  }
  } finally { storage.restore() }
})

test('慢换回/删除仅能清确认时那份草稿；没草稿的旧请求也不能清新页面刚写的', async () => {
  const storage = browserStorage()
  try {
  for (const expected of [null, { name: '确认丢弃的草稿', when: '原时机', body: '原正文' }]) {
    const key = expected ? 'slow-system-existing' : 'slow-system-empty'
    writeHandbookDraft(key, expected)
    let complete
    const pending = new Promise(resolve => { complete = resolve })
    const oldAction = pending.then(() => clearHandbookDraftIfUnchanged(key, expected))
    const newer = { name: '新页面的名字', when: '新页面的时机', body: '新页面的正文' }
    writeHandbookDraft(key, newer)
    complete()
    const cleared = await oldAction
    assert.deepEqual(JSON.parse(storage.values.get(`zhibi:handbook-draft:${key}`) ?? 'null'), newer, '慢换回/删除不得擦掉后来写入的sessionStorage')
    assert.deepEqual(readHandbookDraft(key), newer)
    assert.equal(cleared, false)
  }
  const key = 'same-submitted-snapshot'
  const submitted = { name: '已提交', when: '已提交时机', body: '末尾空格不能丢  \n' }
  writeHandbookDraft(key, { ...submitted })
  assert.equal(clearHandbookDraftIfUnchanged(key, submitted), true)
  assert.equal(readHandbookDraft(key), null, '仍是同一份提交快照才清掉')
  assert.equal(clearHandbookDraftIfUnchanged(key, null), true, '双方都没有草稿时幂等')
  } finally { storage.restore() }
})

test('段落比对末尾加一段准确计为加一，换行格式与文件末行不制造改动', () => {
  const original = '甲段\n第二行\n\n乙段\n'
  const compared = compareHandbookParagraphs(original, `${original}\n新增记号`)
  assert.deepEqual({ changed: compared.changed, added: compared.added, deleted: compared.deleted }, { changed: 0, added: 1, deleted: 0 })
  assert.deepEqual(compared.rows.map(row => row.kind), ['same', 'same', 'add'])
  assert.equal(compared.rows.at(-1).right, '新增记号')
  assert.equal(compareHandbookParagraphs('甲\r\n\r\n乙\r\n', '甲\n\n乙\n').changed, 0)
})

test('段落对齐相同锚点，变更配对、单边增删、连续空行和空正文', () => {
  const diff = compareHandbookParagraphs('起点\n\n原乙\n\n终点\n\n删去', '起点\n\n改乙\n\n加一\n\n终点')
  assert.deepEqual(diff.rows.map(row => row.kind), ['same', 'change', 'add', 'same', 'delete'])
  assert.deepEqual([diff.changed, diff.added, diff.deleted], [1, 1, 1])
  assert.equal(diff.rows[1].left, '原乙')
  assert.equal(diff.rows[1].right, '改乙')
  assert.deepEqual(compareHandbookParagraphs('', '').rows, [])
  assert.equal(compareHandbookParagraphs('', '甲\n\n\n乙').added, 2)
  assert.equal(compareHandbookParagraphs('甲\n\n乙', '').deleted, 2)
  assert.deepEqual(compareHandbookParagraphs('甲\n\n甲\n\n乙', '甲\n\n乙').rows.map(row => row.kind), ['same', 'delete', 'same'])
})

test('大正文比较使用有界内存的稳定锚点，相同段落仍然对齐', () => {
  const body = Array.from({ length: 1500 }, (_, n) => `第${n}段`).join('\n\n')
  const diff = compareHandbookParagraphs(body, body + '\n\n最后新增')
  assert.deepEqual([diff.changed, diff.added, diff.deleted], [0, 1, 0])
  assert.equal(diff.rows.filter(row => row.kind === 'same').length, 1500)
})

test('管理三页循环跳转和设置入口始终保留原书路径，不嵌套编辑页面', () => {
  const original = '/desk/book-handbook?tab=outline#unit-3'
  let location = { pathname: '/desk/book-handbook', search: '?tab=outline', hash: '#unit-3' }
  for (const build of [handbooksHref, promptsHref, presetsHref, handbooksHref, presetsHref, promptsHref]) {
    const url = new URL(build(location), 'https://example.test')
    assert.deepEqual(readPromptReturnContext(url.search), { returnTo: original, bookId: 'book-handbook' })
    location = { pathname: url.pathname, search: url.search }
  }
  const selected = new URL(handbooksHref(location, 'mine_a&returnTo=//evil.test'), 'https://example.test')
  assert.equal(selected.searchParams.get('key'), 'mine_a&returnTo=//evil.test')
  assert.equal(selected.searchParams.get('returnTo'), original)
  for (const entry of [{ pathname: '/' }, { pathname: '/new' }, { pathname: '/handbooks', search: '?returnTo=//evil.test' }]) assert.equal(handbooksHref(entry), '/handbooks')
})

test('手册API按三字段保存、即时开关、版本与系统操作精确接线；删除204不读JSON', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return options?.method === 'DELETE' ? new Response(null, { status: 204 }) : new Response('{}')
  }
  try {
    const draft = { name: '名称', when: '时机', body: '  正文\n' }
    await handbookApi.list(); await handbookApi.detail('mine/a'); await handbookApi.create()
    await handbookApi.save('opening', draft); await handbookApi.enabled('opening', false)
    await handbookApi.useSystem('opening'); await handbookApi.seenSystem('opening')
    await handbookApi.saves('opening'); await handbookApi.snapshot('opening', 1); await handbookApi.restore('opening', 1)
    await handbookApi.remove('mine_a')
    assert.deepEqual(calls.map(row => row.url), ['/api/handbooks', '/api/handbooks/mine%2Fa', '/api/handbooks', '/api/handbooks/opening', '/api/handbooks/opening/enabled', '/api/handbooks/opening/use-system', '/api/handbooks/opening/seen-system', '/api/handbooks/opening/saves', '/api/handbooks/opening/saves/1', '/api/handbooks/opening/saves/1/restore', '/api/handbooks/mine_a'])
    assert.equal(calls[2].options.method, 'POST')
    assert.equal(calls[3].options.method, 'PUT')
    assert.deepEqual(JSON.parse(calls[3].options.body), draft)
    assert.deepEqual(JSON.parse(calls[4].options.body), { enabled: false })
    assert.equal(calls[9].options.method, 'POST')
  } finally { globalThis.fetch = original }
})

test('手册页固定说明、编辑器与三处入口保留规定文本，不复用提示词覆盖接口', () => {
  const page = readFileSync(new URL('../src/pages/HandbooksPage.tsx', import.meta.url), 'utf8')
  const settings = readFileSync(new URL('../src/pages/SettingsPage.tsx', import.meta.url), 'utf8')
  const presets = readFileSync(new URL('../src/pages/PresetsPage.tsx', import.meta.url), 'utf8')
  const prompts = readFileSync(new URL('../src/pages/PromptsPage.tsx', import.meta.url), 'utf8')
  for (const text of ['有没保存的改动：切到别的手册、刷新页面都还在，点「保存」才给主编用。', '还没写完：名称、什么时候翻、正文都写上，才能打开给主编翻。', '改的还没保存，确定不要了吗？', '开着：主编能翻；关着：主编翻不到']) assert.ok(page.includes(text), text)
  assert.match(page, /<PromptEditor[^>]+editable=\{!busy\}/)
  assert.match(page, /handbookApi\.save\(book\.key, submitted\), submitted/)
  assert.match(page, /handbookApi\.useSystem\(book\.key\), discardSnapshot/)
  assert.match(page, /handbookApi\.remove\(book\.key\); clearDraft\(book\.key, discardSnapshot\)/)
  assert.doesNotMatch(page, /writeDraft\([^\n]*, null\)/, '页面清理不得绕过当前持久稿的快照检查')
  assert.doesNotMatch(page, /promptApi|skills\./)
  assert.ok(settings.indexOf('data-testid="settings-presets-link"') < settings.indexOf('data-testid="settings-handbooks-link"'))
  assert.ok(settings.indexOf('data-testid="settings-handbooks-link"') < settings.indexOf('data-testid="settings-prompts-link"'))
  assert.ok(settings.includes('编辑部在群聊里自己翻的写书手册'))
  for (const source of [prompts, presets]) assert.match(source, /to=\{handbooksHref\(location\)\}/)
  assert.match(presets, /block\.id === 'tool_skills'/)
})
