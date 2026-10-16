import type { Character, Relationship, World } from '../api/types'

/** 写作追加的层级沿用 world.power 的「（第 N 段）」段落，不另造储存字段。 */
export function splitWorldPower(value: string | undefined): { before: string; later: string } {
  const text = value ?? ''
  const marker = /(?:^|\r?\n)[ \t]*[（(]第\s*\d+\s*段[）)]/.exec(text)
  if (!marker) return { before: text, later: '' }
  return { before: text.slice(0, marker.index).trimEnd(), later: text.slice(marker.index).trimStart() }
}

export function joinWorldPower(before: string, later: string): string {
  return [before, later].filter(Boolean).join('\n')
}

/** 数组必须完整提交，单项编辑不能覆盖后来新增的地图。 */
export function patchWorldMap(maps: World['maps'], index: number, patch: NonNullable<World['maps']>[number]) {
  const result = [...(maps ?? [])]
  result[index] = { ...result[index], ...patch }
  return result
}

export function patchFarMap(maps: World['far_maps'], index: number, patch: NonNullable<World['far_maps']>[number]) {
  return (maps ?? []).map((map, i) => i === index ? { ...map, ...patch } : map)
}

export function worldPeople(characters: Character[], protagonistName?: string): Character[] {
  return [...characters].sort((a, b) => {
    const score = (person: Character) => person.name === protagonistName ? 2 : person.role_type === '主角' ? 1 : 0
    return score(b) - score(a)
  })
}

export function protagonistTension(characterId: string, protagonistId: string | undefined, relationships: Relationship[]): string {
  if (!protagonistId || characterId === protagonistId) return ''
  return relationships.filter(relation =>
    (relation.source_id === protagonistId && relation.target_id === characterId) ||
    (relation.target_id === protagonistId && relation.source_id === characterId),
  ).map(relation => relation.description || relation.kind).filter(Boolean).join('；')
}

/** 优先识别较长姓名，避免「苏晚」截断「苏晚晴」；不把作者原文当正则执行。 */
export function characterNameParts(value: string, characters: Pick<Character, 'id' | 'name'>[]): { text: string; characterId?: string }[] {
  const names = characters.filter(person => person.name.trim()).slice().sort((a, b) => b.name.length - a.name.length)
  const result: { text: string; characterId?: string }[] = []
  let cursor = 0
  while (cursor < value.length) {
    let next: { index: number; person: Pick<Character, 'id' | 'name'> } | undefined
    for (const person of names) {
      const index = value.indexOf(person.name, cursor)
      if (index >= 0 && (!next || index < next.index)) next = { index, person }
    }
    if (!next) {
      result.push({ text: value.slice(cursor) })
      break
    }
    if (next.index > cursor) result.push({ text: value.slice(cursor, next.index) })
    result.push({ text: next.person.name, characterId: next.person.id })
    cursor = next.index + next.person.name.length
  }
  return result
}
