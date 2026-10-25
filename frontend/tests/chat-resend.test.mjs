import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import * as jsx from 'react/jsx-runtime'
import ts from 'typescript'
import clsx from 'clsx'
import * as icons from 'lucide-react'
import * as model from '../src/pages/workspace/chatModel.ts'
import { sendChatFirst } from '../src/lib/chat.ts'

const liveSource = readFileSync(new URL('../src/pages/workspace/LiveChat.tsx', import.meta.url), 'utf8')
const chatSource = readFileSync(new URL('../src/pages/workspace/Chat.tsx', import.meta.url), 'utf8')
const noop = () => {}
const originalQuote = { text: '原来引用的一句。', where: '第 3 章 · 原文' }
const nextQuote = { text: '下一问新选的一句。', where: '第 9 章 · 原文' }
const originalViewing = { target_type: 'chapter', target_id: '3', label: '第 3 章' }
const nextViewing = { target_type: 'chapter', target_id: '9', label: '第 9 章' }
const note = { id: 10, speaker: 'author', kind: 'note', content: '  原话\n完整保留。  ', payload: { conv: 'conv-original', ask: 'reviewer', quote: originalQuote, viewing: originalViewing } }
const reply = { id: 11, speaker: 'reviewer', kind: 'speech', content: '原来的回答。', payload: { conv: 'conv-original', reply_to: [10] } }
const warning = n => `这句话改过书（${n} 处）。重新回答是把这句原样再发一遍，编辑部可能再改一遍；聊天退回这里，书不跟着退：要退书，用那几处下面的「换回原来的」，或者去「存档」。`

function compile(source, imports) {
  const module = { exports: {} }
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } })
  new Function('require', 'module', 'exports', outputText)(name => {
    assert.ok(name in imports, `未模拟的依赖 ${name}`)
    return imports[name]
  }, module, module.exports)
  return module.exports
}

function hooks() {
  const values = []
  const changes = []
  let index = 0
  return {
    reset: () => { index = 0 },
    changes,
    react: {
      ...React,
      useMemo: fn => fn(),
      useLayoutEffect: noop,
      useState: initial => {
        const at = index++
        if (!(at in values)) values[at] = typeof initial === 'function' ? initial() : initial
        return [values[at], value => {
          values[at] = typeof value === 'function' ? value(values[at]) : value
          changes.push([at, values[at]])
        }]
      },
    },
  }
}

// 编译真正的 LiveChat，替换数据 hooks 和网络边界，直接检查交给真实聊天界面的 control。
function liveHarness(messages = [note, reply], respond = async () => ({})) {
  const state = hooks()
  const requests = []
  const feedbacks = []
  const quoteChanges = []
  let viewed = 0
  const context = {
    bookId: 'resend-book', book: { source: 'teardown' }, messages,
    chatQuotes: { chief: nextQuote }, setChatQuotes: fn => quoteChanges.push(fn(context.chatQuotes)),
    viewing: () => { viewed++; return nextViewing },
  }
  const exports = compile(`${liveSource}\nexport { toChat }`, {
    react: state.react, 'react/jsx-runtime': jsx, 'lucide-react': icons,
    '../book/MemoryNotice': { MemoryNotice: () => null },
    '../../lib/memory': { isMemoryNote: () => false },
    '../../api/client': { post: async (path, body) => { requests.push({ path, body }); return respond(path, body) } },
    '../../components/ui': { ErrorText: () => null },
    '../../lib/chat': { sendChatFirst }, '../../lib/workspace': { pendingTarget: () => null },
    '../book/context': { useBookContext: () => context },
    '../book/MeetingFeed': { PlanSubmitted: () => null, StepOutcomes: () => null },
    '../book/PlanCard': { PlanCard: () => null },
    '../book/useGroupFeedback': { useGroupFeedback: () => async content => { feedbacks.push(content) } },
    './Chat': { EditorialChat: () => null, RoleRow: () => null },
    './convs': { convOf: m => m.payload?.conv ?? 'conv-original', useCurrentConv: () => ({ conv: 'conv-original', latest: 'conv-original' }), dayLabel: () => '' },
    './chatModel': model, './writing': {},
  })
  return {
    ...exports, state, requests, feedbacks, quoteChanges, get viewed() { return viewed },
    control: () => { state.reset(); return exports.LiveChat({}).props.chat },
  }
}

test('单句群聊回答带原话重发标记；无改书不警告，答完和停下都可用', () => {
  const { toChat } = liveHarness()
  for (const state of [undefined, 'stopped']) {
    const answer = toChat([note, { ...reply, payload: { ...reply.payload, state } }]).at(-1)
    assert.equal(answer.replyTo, '10')
    assert.deepEqual(answer.resend, { warn: undefined })
  }
})

test('改书处数沿用 changedFrom，提醒逐字匹配，撤销、备选和空补齐不计数', () => {
  const changed = { ...note, payload: { ...note.payload, steps: [
    { kind: 'edit' }, { kind: 'fill', filled: ['性格'] }, { kind: 'created' }, { kind: 'outline' }, { kind: 'deleted' },
    { kind: 'edit', undone: true }, { kind: 'edit', mode: 'options' }, { kind: 'fill', filled: [] }, { kind: 'requirement' },
  ] } }
  const later = { ...note, id: 12, payload: { conv: 'conv-original', outcome: { kind: 'edit' } } }
  const plan = { id: 13, speaker: 'chief', kind: 'plan', content: '方案', payload: { results: [{ kind: 'outline' }, { kind: 'deleted', undone: true }] } }
  const { toChat } = liveHarness()
  assert.deepEqual(toChat([changed, reply])[1].resend, { warn: warning(5) })
  assert.deepEqual(toChat([changed, reply, later, plan])[1].resend, { warn: warning(7) })
  assert.equal(changed.payload.steps.length, 9, '显示适配不改源消息')
})

test('答多句、没有 conv、非 note、非作者或找不到原话都不带重发字段', () => {
  const { toChat } = liveHarness()
  const cases = [
    [note, { ...reply, payload: { ...reply.payload, reply_to: [10, 12] } }],
    [{ ...note, payload: {} }, reply],
    [{ ...note, kind: 'decision' }, reply],
    [{ ...note, speaker: 'chief' }, reply],
    [reply],
  ]
  for (const messages of cases) {
    const answer = toChat(messages).find(m => m.id === '11')
    assert.equal(answer.resend, undefined)
    assert.equal(answer.replyTo, '10', '保留旧 again 的关联')
  }
})

test('原话重发请求严格保留旧字段，不取现在页面和新引用，不改本地原消息', async () => {
  const messages = structuredClone([note, reply])
  const before = structuredClone(messages)
  const harness = liveHarness(messages)
  assert.equal(await harness.control().resend('11'), true)
  assert.deepEqual(harness.requests, [{ path: '/books/resend-book/notes', body: {
    content: note.content, ask: 'reviewer', quote: originalQuote, viewing: originalViewing, conv: 'conv-original', rewind_from: 10,
  } }])
  assert.equal(harness.viewed, 0, '不取现在正在看的页面')
  assert.deepEqual(harness.quoteChanges, [], '下一问的新引用保留')
  assert.deepEqual(harness.state.changes.filter(([at]) => at === 0), [[0, true], [0, false]], '共享 sending')
  assert.deepEqual(messages, before, '收起原消息交给后端，不乐观删除')
})

test('旧句无点名、引用和 viewing 时省略这些键，不把新引用默认点给主编', async () => {
  const harness = liveHarness([{ ...note, payload: { conv: 'conv-original' } }, reply])
  assert.equal(await harness.control().resend('11'), true)
  assert.deepEqual(harness.requests[0].body, { content: note.content, conv: 'conv-original', rewind_from: 10 })
  assert.equal(harness.viewed, 0)
  assert.deepEqual(harness.quoteChanges, [])
})

test('重发被 409 use_feedback 挡回，沿用 sendChatFirst 转为原话修改意见', async () => {
  const conflict = { status: 409, code: 'use_feedback' }
  const harness = liveHarness([note, reply], async () => { throw conflict })
  assert.equal(await harness.control().resend('11'), true)
  assert.deepEqual(harness.feedbacks, [note.content])
  assert.equal(harness.requests.length, 1)
  assert.deepEqual(harness.quoteChanges, [])
  assert.equal(harness.control().sending, false)
  assert.equal(harness.control().sendError.props.error, null)
})

test('重发的其他失败走输入框错误出口，不改聊天、不转修改意见且解除 sending', async () => {
  const conflict = { status: 409, detail: '编辑部还在照这几句话办，办完再重来' }
  const messages = structuredClone([note, reply])
  const before = structuredClone(messages)
  const harness = liveHarness(messages, async () => { throw conflict })
  assert.equal(await harness.control().resend('11'), false)
  assert.equal(harness.control().sendError.props.error, conflict)
  assert.equal(harness.control().sending, false)
  assert.deepEqual(harness.feedbacks, [])
  assert.deepEqual(harness.quoteChanges, [])
  assert.deepEqual(messages, before)
})

test('正常发送仍带新引用和当前页面，原地修改仍不带或清除新引用', async () => {
  const harness = liveHarness()
  assert.equal(await harness.control().send('下一问', '写手'), true)
  assert.deepEqual(harness.requests[0].body, { content: '下一问', ask: 'writer', quote: nextQuote, viewing: nextViewing, conv: 'conv-original' })
  assert.deepEqual(harness.quoteChanges, [{ chief: null }])
  const inline = liveHarness()
  assert.equal(await inline.control().send(note.content, '审稿', '10'), true)
  assert.deepEqual(inline.requests[0].body, { content: note.content, ask: 'reviewer', viewing: nextViewing, conv: 'conv-original', rewind_from: 10 })
  assert.deepEqual(inline.quoteChanges, [])
})

test('failed 不开放重发；重试还是请求原回答的 again', async () => {
  const failed = { ...reply, payload: { ...reply.payload, state: 'failed', error: '中途出错' } }
  const harness = liveHarness([note, failed])
  const control = harness.control()
  assert.equal(control.messages.at(-1).resend, undefined)
  assert.equal(await control.resend('11'), false, '防御性阻止失败回答误重发')
  assert.deepEqual(harness.requests, [])
  control.again('11')
  assert.deepEqual(harness.requests, [{ path: '/books/resend-book/chat/replies/11/again', body: undefined }])
})

function elements(node) {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!React.isValidElement(node)) return []
  return [node, ...elements(node.props.children)]
}
function textOf(node) {
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (React.isValidElement(node)) return textOf(node.props.children)
  return typeof node === 'string' ? node : ''
}
const button = (tree, text) => elements(tree).find(node => node.type === 'button' && textOf(node) === text)

function replyHarness(props) {
  const state = hooks()
  const exports = compile(`${chatSource}\nexport { Reply, AuthorBubble, InlineEdit }`, {
    react: state.react, 'react/jsx-runtime': jsx, 'lucide-react': icons, clsx,
    './chatModel': model, './chatBrowser': {}, '../../components/ui': {},
  })
  return { ...exports, render: () => { state.reset(); return exports.Reply(props) } }
}

const uiAnswer = { id: '11', who: '审稿', text: reply.content, state: 'done', replyTo: '10', resend: {} }

test('有改书提醒的重新回答：初点只提醒，算了不发，确认才重发，文字逐字匹配', () => {
  let resends = 0
  let agains = 0
  const harness = replyHarness({ message: { ...uiAnswer, resend: { warn: warning(2) } }, latest: true, answering: false, onAgain: () => { agains++ }, onResend: () => { resends++ } })
  const first = button(harness.render(), '重新回答')
  assert.equal(first.props.title, '把你那句话原样再发一遍，从头重新答（会重新查资料、翻手册）；你那句和这一条收起来')
  first.props.onClick()
  let dialog = elements(harness.render()).find(node => node.props.role === 'alertdialog')
  assert.ok(dialog)
  assert.equal(dialog.props.children[0].props.children, warning(2))
  assert.equal(resends, 0)
  button(harness.render(), '重新回答').props.onClick()
  assert.equal(resends, 0, '再次点原 footer 按钮不能绕过提醒框里的确认')
  button(dialog, '算了').props.onClick()
  assert.equal(elements(harness.render()).find(node => node.props.role === 'alertdialog'), undefined)
  assert.equal(resends, 0)
  button(harness.render(), '重新回答').props.onClick()
  dialog = elements(harness.render()).find(node => node.props.role === 'alertdialog')
  button(dialog, '重新回答').props.onClick()
  assert.equal(resends, 1)
  assert.equal(agains, 0)
})

test('无改书立即重发；兼容消息、原型和失败的重试仍调用 again', () => {
  let resends = 0
  let agains = 0
  const props = { message: uiAnswer, latest: true, answering: false, onAgain: () => { agains++ }, onResend: () => { resends++ } }
  button(replyHarness(props).render(), '重新回答').props.onClick()
  assert.equal(resends, 1)
  for (const change of [{ message: { ...uiAnswer, resend: undefined } }, { onResend: undefined }]) {
    const tree = replyHarness({ ...props, ...change }).render()
    assert.equal(button(tree, '重新回答').props.title, '把上面你那句话重新答一遍，这一条换成新的')
    button(tree, '重新回答').props.onClick()
  }
  const failed = replyHarness({ ...props, message: { ...uiAnswer, state: 'failed', error: '中途出错' } }).render()
  assert.equal(button(failed, '重新回答'), undefined)
  button(failed, '重试').props.onClick()
  assert.equal(resends, 1)
  assert.equal(agains, 3)
})

test('不是最新、仍在回答、发送或原地修改中都不显示重新回答', () => {
  const props = { message: uiAnswer, latest: true, answering: false, onAgain: noop, onResend: noop }
  for (const change of [{ latest: false }, { answering: true }, { busy: true }]) {
    assert.equal(button(replyHarness({ ...props, ...change }).render(), '重新回答'), undefined)
  }
})

test('原话重发调用网络前同步跟到底，保持原生 click 的立即回底行为', async () => {
  const state = hooks()
  const box = { scrollTop: 0, scrollHeight: 1200 }
  const events = []
  const exports = compile(chatSource, {
    react: { ...state.react, useRef: value => ({ current: value === null ? box : value }) },
    'react/jsx-runtime': jsx, 'lucide-react': icons, clsx, './chatModel': model,
    './chatBrowser': { loadChatDraft: () => ({ text: '' }) }, '../../components/ui': {},
  })
  state.reset()
  const tree = exports.EditorialChat({ chat: { messages: [], answering: false, send: noop, stop: noop, again: noop, resend: async id => { events.push({ id, scrollTop: box.scrollTop }); return true } } })
  const composer = elements(tree).find(node => node.type.name === 'Composer')
  assert.equal(await composer.props.chat.resend('11'), true)
  assert.deepEqual(events, [{ id: '11', scrollTop: 1200 }])
})

test('修改按钮提示与编辑框说明逐字使用任务指定文字', () => {
  const harness = replyHarness({ message: uiAnswer, latest: true, answering: false, onAgain: noop })
  const author = harness.AuthorBubble({ message: { id: '10', who: '作者', text: note.content, rewind: {} }, canRewind: true, onRewind: noop, editing: false, chat: {}, endRewind: noop })
  assert.equal(button(author, '修改').props.title, '改这句话再发，不改直接发也行：这句和后面的聊天收起来，从这句重新回答；书里改过的不跟着退')
  assert.ok(chatSource.includes('改好了点发送，不改直接发就是原话重来：这句和后面的聊天会收起来，从这句重新回答；书里改过的不跟着退'))
})
