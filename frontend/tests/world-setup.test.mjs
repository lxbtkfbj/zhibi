import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { characterNameParts, joinWorldPower, patchFarMap, patchWorldMap, protagonistTension, splitWorldPower, worldPeople } from '../src/lib/worldSetup.ts'

test('世界力量规则与后来追加的层级分开显示，改规则保留后来内容', () => {
  assert.deepEqual(splitWorldPower(undefined), { before: '', later: '' })
  assert.deepEqual(splitWorldPower('炼气三层'), { before: '炼气三层', later: '' })
  const source = '炼气三层\n（第 2 段）筑基\n（第 3 段）金丹'
  assert.deepEqual(splitWorldPower(source), { before: '炼气三层', later: '（第 2 段）筑基\n（第 3 段）金丹' })
  const split = splitWorldPower(source)
  assert.equal(joinWorldPower(split.before, split.later), source)
  assert.equal(joinWorldPower('作者改过的规则', split.later), '作者改过的规则\n（第 2 段）筑基\n（第 3 段）金丹')
  assert.deepEqual(splitWorldPower('第一段提到（第 2 段）只是正文，不是追加标记'), { before: '第一段提到（第 2 段）只是正文，不是追加标记', later: '' })
  assert.deepEqual(splitWorldPower('初级\r\n（第2段）中级'), { before: '初级', later: '（第2段）中级' })
})

test('改第一张地图与远图一项时整份列表保存，其他字段和其他地图保持原值', () => {
  const first = Object.freeze({ name: '镇子', rules: '作者的规矩', ceiling: '镇守', powers: '商会' })
  const second = Object.freeze({ name: '京城', rules: '宵禁' })
  const maps = Object.freeze([first, second])
  assert.deepEqual(patchWorldMap(maps, 0, { name: '新镇名' }), [{ ...first, name: '新镇名' }, second])
  assert.equal(maps[0], first)
  assert.deepEqual(patchWorldMap(undefined, 0, { name: '第一张图' }), [{ name: '第一张图' }])
  const far = Object.freeze([{ name: '远处', line: '作者的一句话' }, { name: '更远处', line: '保留' }])
  assert.deepEqual(patchFarMap(far, 0, { name: '远图新名' }), [{ name: '远图新名', line: '作者的一句话' }, far[1]])
})

test('人物姓名优先最长匹配，可重复、含标点；原文无损，不匹配空名字', () => {
  const people = [{ id: 'short', name: '苏晚' }, { id: 'long', name: '苏晚晴' }, { id: 'symbol', name: '小[白]' }, { id: 'blank', name: '' }]
  const value = '苏晚晴找苏晚，小[白]挡住苏晚晴。'
  const parts = characterNameParts(value, people)
  assert.equal(parts.map(part => part.text).join(''), value)
  assert.deepEqual(parts.filter(part => part.characterId).map(part => part.characterId), ['long', 'short', 'symbol', 'long'])
  assert.deepEqual(characterNameParts('', people), [])
  assert.deepEqual(characterNameParts('未出场姓名', people), [{ text: '未出场姓名' }])
})

test('主角按卡片姓名优先排第一，不改原人物数组；关系张力兼容两种方向', () => {
  const people = Object.freeze([{ id: 'r', name: '对手', role_type: '反派' }, { id: 'p', name: '陆远', role_type: '主角' }, { id: 'f', name: '妹妹', role_type: '配角' }])
  assert.deepEqual(worldPeople(people, '陆远').map(person => person.id), ['p', 'r', 'f'])
  assert.equal(people[0].id, 'r')
  const relations = [{ source_id: 'r', target_id: 'p', description: '想控制主角', kind: '对手' }, { source_id: 'p', target_id: 'r', description: '主角想揭穿他', kind: '敌人' }, { source_id: 'f', target_id: 'r', description: '无关关系', kind: '相识' }]
  assert.equal(protagonistTension('r', 'p', relations), '想控制主角；主角想揭穿他')
  assert.equal(protagonistTension('p', 'p', relations), '')
  assert.equal(protagonistTension('r', undefined, relations), '')
})

test('世界页六题来自共用题表，旧书不上世界卡；后续空项无编辑入口且人物可精确定位', () => {
  const page = readFileSync(new URL('../src/pages/book/sections/BiblePages.tsx', import.meta.url), 'utf8')
  const setup = readFileSync(new URL('../src/pages/book/sections/WorldSetup.tsx', import.meta.url), 'utf8')
  assert.deepEqual([...setup.matchAll(/questionKey="([^"]+)"/g)].map(match => match[1]), ['surface', 'power', 'first_map', 'opponents', 'people', 'shadows'])
  assert.ok(page.includes('{hasWorld && <WorldSetup bible={data} />}'))
  assert.ok(page.includes('id={`character-${c.id}`}'))
  assert.ok(page.includes("target.focus({ preventScroll: true })"))
  assert.ok(setup.includes('此刻想要：'))
  assert.ok(setup.includes('<LaterValue value={world.mystery_answer}>'))
  assert.ok(setup.includes('<LaterValue value={world.shadow}>'))
  assert.ok(setup.includes('patchWorldMap(maps, 0,'))
  assert.ok(setup.includes('patchFarMap(farMaps, index,'))
})
