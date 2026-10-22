import assert from 'node:assert/strict'
import test from 'node:test'
import { clearSentChatDraft, copyChatText, loadChatDraft, saveChatDraft, subscribeChatDraft } from '../src/pages/workspace/chatBrowser.ts'

function replaceGlobal(t, name, value) {
  const original = Object.getOwnPropertyDescriptor(globalThis, name)
  Object.defineProperty(globalThis, name, { configurable: true, writable: true, value })
  t.after(() => {
    if (original) Object.defineProperty(globalThis, name, original)
    else delete globalThis[name]
  })
}

function storage(t) {
  const values = new Map()
  replaceGlobal(t, 'localStorage', {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  })
  return values
}

test('聊天草稿按书隔离，只保存字和点名；清空文字删掉本书的 key', t => {
  const values = storage(t)
  saveChatDraft('a', { text: '还没说完\n下一行', to: '设定师', quote: { text: '不存引用' } })
  saveChatDraft('b', { text: '另一本书', to: '审稿' })
  assert.deepEqual(JSON.parse(values.get('zhibi.chat-draft.a')), { text: '还没说完\n下一行', to: '设定师' })
  assert.deepEqual(loadChatDraft('a'), { text: '还没说完\n下一行', to: '设定师' })
  assert.deepEqual(loadChatDraft('b'), { text: '另一本书', to: '审稿' })
  saveChatDraft('a', { text: '', to: '设定师' })
  assert.equal(values.has('zhibi.chat-draft.a'), false)
  assert.deepEqual(loadChatDraft('b'), { text: '另一本书', to: '审稿' })
  saveChatDraft(undefined, { text: '原型不存' })
  assert.equal(values.size, 1)
})

test('无效、损坏或被浏览器禁止的草稿不报错', t => {
  const values = storage(t)
  for (const raw of ['{', 'null', '[]', '{"text":17}', '{"text":""}']) {
    values.set('zhibi.chat-draft.a', raw)
    assert.deepEqual(loadChatDraft('a'), { text: '' })
  }
  values.set('zhibi.chat-draft.a', '{"text":"能用的字","to":"不存在的人"}')
  assert.deepEqual(loadChatDraft('a'), { text: '能用的字' })
  Object.assign(globalThis.localStorage, { getItem() { throw Error('blocked') }, setItem() { throw Error('blocked') }, removeItem() { throw Error('blocked') } })
  assert.deepEqual(loadChatDraft('a'), { text: '' })
  assert.doesNotThrow(() => saveChatDraft('a', { text: '继续打字' }))
  assert.doesNotThrow(() => saveChatDraft('a', { text: '' }))
  assert.equal(clearSentChatDraft('a', { text: '发出后清空' }), true)
})

test('发送成功只清当次草稿，不能覆盖换浮窗后新打的字或新点名', t => {
  const values = storage(t)
  const sent = { text: '当次发送', to: '主编' }
  saveChatDraft('a', sent)
  assert.equal(clearSentChatDraft('a', sent), true)
  assert.equal(values.has('zhibi.chat-draft.a'), false)
  for (const next of [{ text: '新的一句', to: '主编' }, { text: '当次发送', to: '设定师' }]) {
    saveChatDraft('a', next)
    assert.equal(clearSentChatDraft('a', sent), false)
    assert.deepEqual(loadChatDraft('a'), next)
  }
})

test('发送在途换浮窗，成功后同步清掉新实例的旧草稿；新草稿不被清掉', t => {
  storage(t)
  replaceGlobal(t, 'window', new EventTarget())
  const sent = { text: '正在发出的字', to: '主编' }
  saveChatDraft('a', sent)
  // 原实例已卸载，新实例先读取到请求在途的草稿。
  let remounted = loadChatDraft('a')
  let otherBook = { text: '另一本' }
  const unsubscribe = subscribeChatDraft('a', draft => { remounted = draft })
  const unsubscribeOther = subscribeChatDraft('b', draft => { otherBook = draft })
  assert.deepEqual(remounted, sent)
  assert.equal(clearSentChatDraft('a', sent), true)
  assert.deepEqual(remounted, { text: '' })
  assert.deepEqual(otherBook, { text: '另一本' })
  const next = { text: '切换后新打的字', to: '设定师' }
  saveChatDraft('a', next)
  assert.equal(clearSentChatDraft('a', sent), false)
  assert.deepEqual(remounted, next)
  unsubscribe()
  unsubscribeOther()
  saveChatDraft('a', { text: '卸载后不再更新旧实例' })
  assert.deepEqual(remounted, next)
})

function clipboard(t, writeText, copied = true) {
  let value, appended = false, removed = false, focused = false
  class Element { focus() { focused = true } }
  class Field extends Element {
    style = {}
    selectionStart = 1
    selectionEnd = 3
    selectionDirection = 'forward'
    select() { value = this.value }
    remove() { removed = true }
    setSelectionRange(start, end, direction) { this.selectionStart = start; this.selectionEnd = end; this.selectionDirection = direction }
  }
  const active = new Field()
  replaceGlobal(t, 'HTMLElement', Element)
  replaceGlobal(t, 'HTMLTextAreaElement', Field)
  replaceGlobal(t, 'HTMLInputElement', class extends Element {})
  replaceGlobal(t, 'navigator', { clipboard: { writeText } })
  replaceGlobal(t, 'document', {
    activeElement: active,
    createElement: tag => { assert.equal(tag, 'textarea'); return new Field() },
    body: { appendChild() { appended = true } },
    execCommand: command => { assert.equal(command, 'copy'); return copied },
  })
  return () => ({ value, appended, removed, focused, selection: [active.selectionStart, active.selectionEnd, active.selectionDirection] })
}

test('复制优先用 Clipboard API，原样复制纯文字', async t => {
  let copied
  const state = clipboard(t, async text => { copied = text })
  assert.equal(await copyChatText('正文\n第二行'), true)
  assert.equal(copied, '正文\n第二行')
  assert.equal(state().appended, false)
})

test('Clipboard API 失败退回 textarea，并恢复焦点选区、移除临时节点', async t => {
  const state = clipboard(t, async () => { throw Error('denied') })
  assert.equal(await copyChatText('不含名牌的纯文字'), true)
  assert.deepEqual(state(), { value: '不含名牌的纯文字', appended: true, removed: true, focused: true, selection: [1, 3, 'forward'] })
})

test('两种复制都失败时返回 false，仍清理临时节点', async t => {
  const state = clipboard(t, async () => { throw Error('denied') }, false)
  assert.equal(await copyChatText('手动复制'), false)
  assert.equal(state().removed, true)
})
