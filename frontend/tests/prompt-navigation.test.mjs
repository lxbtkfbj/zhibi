import assert from 'node:assert/strict'
import test from 'node:test'
import { promptsHref, readPromptReturnContext, safePromptReturnContext } from '../src/lib/promptNavigation.ts'

test('从书页打开提示词，完整保留书 ID、查询与锚点，刷新后可仅用 URL 恢复', () => {
  const source = { pathname: '/desk/book-123', search: '?tab=outline&draft=1', hash: '#chapter-8' }
  const href = promptsHref(source)
  const refreshed = new URL(href, 'https://example.test')
  assert.equal(refreshed.pathname, '/prompts')
  assert.deepEqual(readPromptReturnContext(refreshed.search), { returnTo: '/desk/book-123?tab=outline&draft=1#chapter-8', bookId: 'book-123' })
  assert.equal(promptsHref({ pathname: '/prompts', search: refreshed.search }), href, '提示词页内重新打开设置不会丢失原书')
})

test('兼容旧书路径、尾斜线以及编码书 ID；不把其他查询参数误当成书', () => {
  assert.deepEqual(safePromptReturnContext('/books/old-book/chapters/chapter-2?mode=read#text'), { returnTo: '/books/old-book/chapters/chapter-2?mode=read#text', bookId: 'old-book' })
  assert.deepEqual(safePromptReturnContext('/desk/book-1/'), { returnTo: '/desk/book-1/', bookId: 'book-1' })
  assert.equal(safePromptReturnContext('/desk/%E4%B9%A6%E4%B8%80').bookId, '书一')
  assert.equal(readPromptReturnContext(new URLSearchParams({ returnTo: '/desk/book-1', book: 'another-book' })).bookId, 'book-1')
})

test('直接入口、书房和新书页不伪造当前书，返回书房', () => {
  for (const source of [{ pathname: '/' }, { pathname: '/new' }, { pathname: '/prompts' }, { pathname: '/settings' }]) assert.equal(promptsHref(source), '/prompts')
  for (const search of ['', '?book=book-1', '?returnTo=%2F', '?returnTo=%2Fsettings']) assert.deepEqual(readPromptReturnContext(search), { returnTo: '/', bookId: null })
})

test('返回路径拒绝外链、协议相对地址、非书路由与路径伪装', () => {
  const invalid = [null, undefined, 3, '', 'https://evil.test/desk/book-1', '//evil.test/desk/book-1', 'javascript:alert(1)', 'desk/book-1', '/prompts', '/desk/', '/desk/book-1/extra', '/books/', '/desk/..', '/books/book-1/../settings', '/books/book-1/%2e%2e/settings', '/desk/%2F%2Fevil.test', '/desk/%252F%252Fevil.test', '/books/book-1/%5cevil', '/desk/book-1\\evil', '/desk/book-1\n', '/desk/%0aevil', '/desk/%E0%A4%A', '/books/book-1//settings']
  for (const value of invalid) assert.deepEqual(safePromptReturnContext(value), { returnTo: '/', bookId: null }, String(value))
  const attack = new URLSearchParams({ returnTo: '//evil.test' })
  assert.deepEqual(readPromptReturnContext(attack), { returnTo: '/', bookId: null })
  assert.equal(promptsHref({ pathname: '/prompts', search: `?${attack}` }), '/prompts')
})
