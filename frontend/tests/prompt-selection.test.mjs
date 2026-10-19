import assert from 'node:assert/strict'
import test from 'node:test'
import { resolvePromptSelection } from '../src/lib/promptSelection.ts'

test('提示词首次打开及退役选择均取当前目录首项，不写死模板名称', () => {
  const items = [{ name: 'future_first' }, { name: 'playbooks.generic' }]
  assert.equal(resolvePromptSelection(items, null), 'future_first')
  assert.equal(resolvePromptSelection(items, 'setup_interview'), 'future_first')
  assert.equal(resolvePromptSelection(items, 'playbooks.generic'), 'playbooks.generic')
})

test('目录尚未读到或为空时没有选中项，不应发送详情请求', () => {
  assert.equal(resolvePromptSelection(undefined, 'setup_interview'), null)
  assert.equal(resolvePromptSelection([], 'setup_interview'), null)
})
