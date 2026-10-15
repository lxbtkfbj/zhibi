import assert from 'node:assert/strict'
import test from 'node:test'
import { readPromptDraft, writePromptDraft } from '../src/lib/promptDrafts.ts'

test('prompt drafts survive switches when browser storage is unavailable', () => {
  writePromptDraft('blocked-storage-fixture', '作者尚未保存的原文')
  assert.equal(readPromptDraft('blocked-storage-fixture'), '作者尚未保存的原文')
  writePromptDraft('blocked-storage-fixture', '')
  assert.equal(readPromptDraft('blocked-storage-fixture'), '', 'Empty draft must not fall back to the saved template')
  writePromptDraft('blocked-storage-fixture', null)
  assert.equal(readPromptDraft('blocked-storage-fixture'), null)
})
