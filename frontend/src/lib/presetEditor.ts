import type { PresetBlock } from '../api/presets'

export type BlockFilter = 'all' | 'on' | 'off'
export const presetBlockFields = (blocks: PresetBlock[]) => blocks.map(({ id, title, role, enabled, required, when, content }) => ({ id, title, role, enabled, required, when, content }))
export const presetDraftChanged = (original: { name: string; blocks: PresetBlock[] }, draft: { name: string; blocks: PresetBlock[] }) => original.name !== draft.name || JSON.stringify(presetBlockFields(original.blocks)) !== JSON.stringify(presetBlockFields(draft.blocks))
export const blockCharacters = (content: string) => [...content].length

export function visiblePresetBlocks(blocks: PresetBlock[], search: string, filter: BlockFilter) {
  const needle = search.trim().toLocaleLowerCase()
  return blocks.map((block, index) => ({ block, index })).filter(({ block }) => (filter === 'all' || (filter === 'on' ? block.enabled : !block.enabled)) && `${block.title}\n${block.content}`.toLocaleLowerCase().includes(needle))
}

export function changePresetBlock(blocks: PresetBlock[], id: string, change: Partial<PresetBlock>) {
  return blocks.map(block => block.id === id ? { ...block, ...change, id: block.id, required: block.required } : block)
}

/** Dropping on a row inserts immediately before that row; source/target use full-list IDs, never filtered indices. */
export function movePresetBlock(blocks: PresetBlock[], source: string, target: string) {
  if (source === target || !blocks.some(block => block.id === source) || !blocks.some(block => block.id === target)) return blocks
  const moving = blocks.find(block => block.id === source)!
  const remaining = blocks.filter(block => block.id !== source)
  const destination = remaining.findIndex(block => block.id === target)
  return [...remaining.slice(0, destination), moving, ...remaining.slice(destination)]
}

export function addPresetBlock(blocks: PresetBlock[], selected: string | null, id: string) {
  const block: PresetBlock = { id, title: '新的块', role: 'system', enabled: true, required: false, when: 'always', content: '' }
  const index = blocks.findIndex(item => item.id === selected)
  const at = index < 0 ? blocks.length : index + 1
  return [...blocks.slice(0, at), block, ...blocks.slice(at)]
}

export function deletePresetBlock(blocks: PresetBlock[], selected: string) {
  const index = blocks.findIndex(block => block.id === selected)
  const next = blocks.filter(block => block.id !== selected)
  return { blocks: next, selected: next[Math.min(Math.max(index, 0), next.length - 1)]?.id ?? null }
}

export function insertPresetPlaceholder(content: string, name: string, from: number, to = from) {
  const start = Math.min(Math.max(0, from), content.length)
  const end = Math.min(Math.max(start, to), content.length)
  const insertion = `{{${name}}}`
  return { content: content.slice(0, start) + insertion + content.slice(end), cursor: start + insertion.length }
}

export function selectedAfterPresetSave(before: PresetBlock[], after: PresetBlock[], selected: string | null) {
  if (after.some(block => block.id === selected)) return selected
  const index = before.findIndex(block => block.id === selected)
  return after[Math.min(Math.max(index, 0), after.length - 1)]?.id ?? null
}

export function comparePresetBlocks(left: PresetBlock[], right: PresetBlock[]) {
  const leftOnly = left.filter(block => !right.some(item => item.id === block.id))
  const rightOnly = right.filter(block => !left.some(item => item.id === block.id))
  const common = left.flatMap(block => {
    const other = right.find(item => item.id === block.id)
    return other ? [{ left: block, right: other }] : []
  })
  return { leftOnly, rightOnly, changed: common.filter(pair => pair.left.content !== pair.right.content), same: common.filter(pair => pair.left.content === pair.right.content).length }
}

/** Metadata follows the system's history; text comparison stays pinned to the copied edition. */
export function presetBlockReference(id: string, system: PresetBlock[], copied: PresetBlock[], requiresCopiedEdition = false) {
  const metadata = system.find(block => block.id === id) ?? copied.find(block => block.id === id)
  return { metadata, copied: copied.find(block => block.id === id) ?? (requiresCopiedEdition ? undefined : metadata) }
}
