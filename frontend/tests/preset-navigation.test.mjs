import assert from 'node:assert/strict'
import test from 'node:test'
import { presetsHref } from '../src/lib/presetNavigation.ts'
import { promptsHref, readPromptReturnContext } from '../src/lib/promptNavigation.ts'

test('预设管理的系统设置、提示词入口共享原书的安全返回地址', () => {
  const book = { pathname: '/desk/book-123', search: '?tab=outline', hash: '#unit-2' }
  const first = new URL(presetsHref(book), 'https://example.test')
  assert.equal(first.pathname, '/presets')
  assert.deepEqual(readPromptReturnContext(first.search), { returnTo: '/desk/book-123?tab=outline#unit-2', bookId: 'book-123' })
  const prompts = new URL(promptsHref(book), first)
  assert.equal(presetsHref({ pathname: prompts.pathname, search: prompts.search }), first.pathname + first.search)
  assert.equal(promptsHref({ pathname: first.pathname, search: first.search }), prompts.pathname + prompts.search, '在预设页再次打开设置也能回原书')
})

test('系统调用的链接带记录的版号和真正发送的块，不把作者保存次数当系统版号', () => {
  const location = { pathname: '/prompts', search: `?${new URLSearchParams({ tab: 'calls', returnTo: '/desk/book-1' })}` }
  const system = new URL(presetsHref(location, { source: 'system', version: 2, block: 'tool_skills' }), 'https://example.test')
  assert.equal(system.searchParams.get('source'), 'system')
  assert.equal(system.searchParams.get('version'), '2')
  assert.equal(system.searchParams.get('block'), 'tool_skills')
  assert.equal(system.searchParams.get('returnTo'), '/desk/book-1')
  const mine = new URL(presetsHref(location, { source: 'mine', id: 'mine-1', version: 9, block: 'voice' }), system)
  assert.equal(mine.searchParams.get('id'), 'mine-1')
  assert.equal(mine.searchParams.get('version'), null)
  assert.equal(mine.searchParams.get('block'), 'voice')
})

test('预设入口不接受外链或未受信的单独书ID，选中块参数不会串改返回路径', () => {
  for (const source of [{ pathname: '/' }, { pathname: '/new' }, { pathname: '/prompts', search: '?book=book-1&returnTo=//evil.test' }, { pathname: '/presets', search: '?returnTo=%2Fsettings' }]) assert.equal(presetsHref(source), '/presets')
  const result = new URL(presetsHref({ pathname: '/desk/book-1' }, { source: 'mine', id: 'a&returnTo=//evil.test', block: '标题&source=system' }), 'https://example.test')
  assert.equal(result.searchParams.get('id'), 'a&returnTo=//evil.test')
  assert.equal(result.searchParams.get('block'), '标题&source=system')
  assert.equal(result.searchParams.get('returnTo'), '/desk/book-1')
  assert.equal(result.searchParams.get('source'), 'mine')
  assert.equal(new URL(presetsHref({ pathname: '/' }, { source: 'system', version: -1 }), result).searchParams.has('version'), false)
})
