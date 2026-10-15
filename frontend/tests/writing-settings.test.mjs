import assert from 'node:assert/strict'
import test from 'node:test'
import { automaticPlaybookName, requirementSource } from '../src/lib/writingSettings.ts'

test('automatic playbook requires both fantasy and payoff tags', () => {
  assert.equal(automaticPlaybookName({ genre: '玄幻', tags: ['热血'] }), '通用')
  assert.equal(automaticPlaybookName({ genre: '都市', tags: ['后宫'] }), '通用')
  assert.equal(automaticPlaybookName({ genre: '仙侠', tags: ['多女主'] }), '后宫玄幻爽文')
  assert.equal(automaticPlaybookName({ genre: '高武爽文', tags: [] }), '后宫玄幻爽文')
  assert.equal(automaticPlaybookName({ genre: '都市', title: '后宫玄幻爽文' }), '通用')
  assert.equal(automaticPlaybookName(null), '通用')
})

test('author requirement source labels preserve all supported origins', () => {
  for (const [source, label] of [['answer', '动笔前的回答'], ['note', '插话'], ['trial', '试读意见'], ['manual', '手动添加'], ['legacy', '旧记录'], ['volume:12', '第 12 卷卷纲意见'], ['private:lorekeeper', '私聊设定师'], ['private:chief', '私聊主编'], ['private:writer', '私聊写手'], ['private:reviewer', '私聊审稿']]) {
    assert.equal(requirementSource(source), label)
  }
})
