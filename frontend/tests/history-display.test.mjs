import assert from 'node:assert/strict'
import test from 'node:test'
import { compareHistory, historyRows } from '../src/lib/historyDisplay.ts'

const config = {
  character_category: { fields: [{ name: '配置里的姓名', column: 'name' }, { name: '配置里的能力', column: 'abilities' }] },
  statuses: { must: '现在要定', later: '以后再说' }, styles: { ladder: '阶梯' }, sources: { author: '作者写的' }, legacy_role_types: { 反派: '对手' },
}

test('历史的角色字段顺序、字段名、状态和来源取后端配置，不抄前端类别表', () => {
  const rows = historyRows({ abilities: '御风', status: 'must', name: '陈安', role_type: '反派', source: 'author' }, 'character', config)
  assert.deepEqual(rows.slice(0, 2).map(row => [row.key, row.label, row.value]), [['name', '配置里的姓名', '陈安'], ['abilities', '配置里的能力', '御风']])
  assert.equal(rows.find(row => row.key === 'status').value, '现在要定')
  assert.equal(rows.find(row => row.key === 'role_type').value, '对手')
  assert.equal(rows.find(row => row.key === 'source').value, '作者写的')
})

test('历史完整保留卡片字段、等级、空值和换行文字，不输出大段JSON也不修改快照', () => {
  const snapshot = { fields: [{ name: '代价', value: '第一行。\n第二行🧭！' }], levels: [{ name: '初境', text: '' }, { name: '化灵', text: '可飞。' }], locked: true, tags: [], parent_id: null }
  const before = JSON.stringify(snapshot)
  const rows = historyRows(snapshot, 'entry', config)
  assert.equal(rows.find(row => row.key === 'fields.0.value').value, '第一行。\n第二行🧭！')
  assert.equal(rows.find(row => row.key === 'levels.1.text').label, '各级 · 第 2 级 · 一段话')
  assert.equal(rows.find(row => row.key === 'levels.0.text').value, '（空）')
  assert.equal(rows.find(row => row.key === 'locked').value, '是')
  assert.equal(rows.find(row => row.key === 'tags').value, '（空）')
  assert.equal(JSON.stringify(snapshot), before)
})

test('定调和大纲使用中文单位和规划状态，自建类别和关联条目可读且不丢引用编号', () => {
  const library = { categories: [{ key: 'custom:1', name: '厉鬼' }], entries: [{ id: 'entry-1', name: '青阳城' }] }
  const rows = historyRows({ category: 'custom:1', parent_id: 'entry-1', chapter_count: 6, target_length: 300, chapter_words: 4000, segment: { status: 'confirmed', text: '过城关。' } }, 'segment', config, library)
  assert.equal(rows.find(row => row.key === 'category').value, '厉鬼')
  assert.equal(rows.find(row => row.key === 'parent_id').value, '青阳城（关联编号：entry-1）')
  assert.equal(rows.find(row => row.key === 'chapter_count').value, '6 章')
  assert.equal(rows.find(row => row.key === 'target_length').value, '300 万字')
  assert.equal(rows.find(row => row.key === 'chapter_words').value, '4000 字')
  assert.equal(rows.find(row => row.key === 'segment.status').value, '已确认')
})

test('相邻版本分别标记修改、新增、删除和未变，保留改前及改后完整内容', () => {
  const previous = { title: '旧稿', summary: '原句。\n留下。', chapter_count: 3, tags: ['旧标签'] }
  const current = { title: '新稿', summary: '原句。\n留下。', chapter_count: 4, locked: true }
  const original = JSON.stringify([previous, current])
  const rows = compareHistory(current, previous, 'unit', config)
  assert.deepEqual(rows.map(row => [row.key, row.change]), [['title', 'changed'], ['summary', 'same'], ['chapter_count', 'changed'], ['locked', 'added'], ['tags', 'removed']])
  assert.equal(rows.find(row => row.key === 'title').before, '旧稿')
  assert.equal(rows.find(row => row.key === 'title').after, '新稿')
  assert.equal(rows.find(row => row.key === 'tags').after, null)
  assert.equal(JSON.stringify([previous, current]), original)
  assert.ok(compareHistory(current, null, 'unit', config).every(row => row.change === 'same'))
})

test('结构数组成员增删逐项显示，未知历史字段仍保留，不丢作者资料', () => {
  const rows = compareHistory({ levels: [{ name: '初境', text: '新版' }], '作者旧字段': '保留' }, { levels: [{ name: '初境', text: '旧版' }, { name: '终境', text: '飞升' }] }, 'entry', config)
  assert.equal(rows.find(row => row.key === 'levels.0.text').change, 'changed')
  assert.equal(rows.find(row => row.key === 'levels.1.name').change, 'removed')
  assert.equal(rows.find(row => row.key === 'levels.1.text').before, '飞升')
  assert.equal(rows.find(row => row.key === '作者旧字段').after, '保留')
})
