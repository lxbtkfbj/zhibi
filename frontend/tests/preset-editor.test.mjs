import assert from 'node:assert/strict'
import test from 'node:test'
import { addPresetBlock, blockCharacters, changePresetBlock, comparePresetBlocks, deletePresetBlock, insertPresetPlaceholder, movePresetBlock, presetBlockReference, presetDraftChanged, selectedAfterPresetSave, visiblePresetBlocks } from '../src/lib/presetEditor.ts'

const blocks = [
  { id: 'role', title: '角色', role: 'system', content: '你是主编', enabled: true, required: true, when: 'always' },
  { id: 'voice', title: '口吻', role: 'system', content: '简短白话', enabled: false, required: false, when: 'always' },
  { id: 'note', title: '作者这次说的', role: 'user', content: '{{作者这次说的}}', enabled: true, required: true, when: 'always' },
]

test('块开关不改原件或必须属性；筛选保留整份中的序号', () => {
  const changed = changePresetBlock(blocks, 'role', { enabled: false, required: false })
  assert.equal(blocks[0].enabled, true)
  assert.equal(changed[0].enabled, false)
  assert.equal(changed[0].required, true)
  assert.deepEqual(visiblePresetBlocks(blocks, '', 'off').map(row => row.index), [1])
  assert.deepEqual(visiblePresetBlocks(blocks, '', 'on').map(row => row.index), [0, 2])
})

test('标题与正文均可搜索，搜索与开关筛选合用', () => {
  assert.equal(visiblePresetBlocks(blocks, '白话', 'all')[0].block.id, 'voice')
  assert.equal(visiblePresetBlocks(blocks, '作者这次', 'on')[0].index, 2)
  assert.equal(visiblePresetBlocks(blocks, '白话', 'on').length, 0)
})

test('拖动按真实ID排序，筛选状态不改变定位', () => {
  assert.deepEqual(movePresetBlock(blocks, 'note', 'voice').map(block => block.id), ['role', 'note', 'voice'])
  assert.deepEqual(movePresetBlock(blocks, 'role', 'note').map(block => block.id), ['voice', 'role', 'note'])
  assert.equal(movePresetBlock(blocks, 'bad', 'note'), blocks)
})

test('加块显式提供页面默认值，选中块后插入，没选中时加末尾', () => {
  const next = addPresetBlock(blocks, 'role', 'temporary')
  assert.deepEqual(next[1], { id: 'temporary', title: '新的块', role: 'system', enabled: true, required: false, when: 'always', content: '' })
  assert.equal(addPresetBlock(blocks, null, 'last').at(-1).id, 'last')
})

test('删块选中相邻块，最后一块删除后为空', () => {
  assert.equal(deletePresetBlock(blocks, 'voice').selected, 'note')
  assert.equal(deletePresetBlock(blocks, 'note').selected, 'voice')
  assert.equal(deletePresetBlock([blocks[0]], 'role').selected, null)
})

test('内容、名称、开关、先后变动都应提醒未保存；系统附加来历不算修改', () => {
  const original = { name: '我的预设', blocks }
  assert.equal(presetDraftChanged(original, { ...original, blocks: structuredClone(blocks) }), false)
  assert.equal(presetDraftChanged(original, { ...original, blocks: blocks.map(block => ({ ...block, origin: '来历' })) }), false)
  for (const draft of [ { ...original, name: '改名' }, { ...original, blocks: changePresetBlock(blocks, 'voice', { content: '新字' }) }, { ...original, blocks: changePresetBlock(blocks, 'role', { enabled: false }) }, { ...original, blocks: movePresetBlock(blocks, 'note', 'voice') } ]) assert.equal(presetDraftChanged(original, draft), true)
})

test('占位符插在光标或替换选择范围；插入后的光标在占位符后', () => {
  assert.deepEqual(insertPresetPlaceholder('前后', '设定库', 1), { content: '前{{设定库}}后', cursor: 8 })
  assert.deepEqual(insertPresetPlaceholder('前删去后', '记忆', 1, 3), { content: '前{{记忆}}后', cursor: 7 })
})

test('保存采用返回块，临时ID变更时仍按原位置保留选中；计数不把代理对算两字', () => {
  const draft = addPresetBlock(blocks, 'role', 'temporary')
  const saved = draft.map(block => block.id === 'temporary' ? { ...block, id: 'custom_server' } : block)
  assert.equal(selectedAfterPresetSave(draft, saved, 'temporary'), 'custom_server')
  assert.equal(selectedAfterPresetSave(draft, saved, 'note'), 'note')
  assert.equal(blockCharacters('字😀{{记忆}}'), 8)
})

test('比较按块区分新增、作者独有、正文改变及相同块', () => {
  const left = [...blocks, { ...blocks[0], id: 'new' }]
  const right = [...changePresetBlock(blocks, 'voice', { content: '改过' }), { ...blocks[0], id: 'custom' }]
  const comparison = comparePresetBlocks(left, right)
  assert.deepEqual(comparison.leftOnly.map(block => block.id), ['new'])
  assert.deepEqual(comparison.rightOnly.map(block => block.id), ['custom'])
  assert.deepEqual(comparison.changed.map(pair => pair.left.id), ['voice'])
  assert.equal(comparison.same, 2)
})

test('作者副本按ID取系统最新来历，但正文比较仍使用复制基版，不改作者正文', () => {
  const copied = [{ ...blocks[0], without: '旧说明', history: [{ version: 1, date: '2026-10-27', change: '第一版' }] }]
  const latest = [{ ...copied[0], content: '新版正文', without: '新说明', history: [...copied[0].history, { version: 2, date: '2026-10-28', change: '第二版' }] }]
  const reference = presetBlockReference('role', latest, copied)
  assert.equal(reference.metadata.without, '新说明')
  assert.equal(reference.metadata.history.length, 2)
  assert.equal(reference.copied.content, '你是主编')
  assert.equal(copied[0].content, '你是主编')
  assert.deepEqual(presetBlockReference('custom_new', latest, copied), { metadata: undefined, copied: undefined })
})

test('已知复制基版但尚未读到时不拿新版冒充；导入无基版时才按当前系统比', () => {
  const latest = [{ ...blocks[0], content: '第二版', origin: '最新来历' }]
  const loading = presetBlockReference('role', latest, [], true)
  assert.equal(loading.metadata.origin, '最新来历')
  assert.equal(loading.copied, undefined)
  assert.equal(presetBlockReference('role', latest, [], false).copied.content, '第二版')
  const loaded = presetBlockReference('role', latest, blocks, true)
  assert.equal(loaded.copied.content, '你是主编')
})
