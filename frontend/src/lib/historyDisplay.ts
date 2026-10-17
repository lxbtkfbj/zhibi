import type { LibraryConfig, LibrarySnapshot, TargetType } from '../api/library'

/** 这里只翻译定调、大纲和通用元数据；角色字段和设定类别始终取后端配置。 */
const LABELS: Record<string, string> = {
  title: '名称', name: '名称', aliases: '别名', category: '类别', style: '样式', status: '状态', source: '来源', tags: '标签', locked: '锁住', position: '列表位置', one_line: '一句话', content: '内容', fields: '卡片字段', levels: '各级', parent_id: '属于哪里', secret_id: '关联的信息差',
  story: '定调的一段话', genre: '类型', tone: '基调与文风', target_reader: '目标读者', target_length: '篇幅', chapter_words: '每章字数', target_volumes: '预计卷数', alt_titles: '书名候选', pitches: '三个短版', text: '一段话', secret_entry_id: '底牌', logline: '一句话故事', selling_points: '核心卖点', core_loop: '核心循环', protagonist_hook: '主角看点', benchmark: '对标作品', stage_ladder: '故事舞台',
  event: '发生什么', segment: '这一篇的规划', number: '篇号', planned_at: '规划时已写章数', summary: '一段话', chapter_count: '章数', stage: '舞台', goal: '目标', want: '想要什么', pressure: '压力', climax: '高潮', antagonist: '对手', power_range: '实力范围', thread_beats: '线索推进', new_characters: '新登场人物', target_node_id: '终点', reaches_node: '在卷末到达终点', editor_note: '编辑批注', techniques: '写法', conflict: '冲突', outcome: '结果', loop: '核心循环', key_events: '关键事件', foreshadow_actions: '伏笔与期待', tropes: '情节套路', resolution: '破局方法', reveals: '揭开的信息',
  map: '地图', trouble: '麻烦', opponent: '对手', goal_link: '与主线的联系', wait: '读者在等什么', reveal: '揭开什么', opening: '开篇安排', carried: '上一篇的线头', pursuit: '主角的追求', finger_next: '金手指的下一步', answers: '定下的谜底', finale: '是否收尾篇', scene: '场景', first_win: '第一次取胜', finger: '金手指', hook: '钩子',
  thread: '线索', beat: '推进', ref: '编号', action: '动作', detail: '说明', to: '告诉谁', how: '怎么揭开', value: '内容', label: '名称', why: '理由', recommended: '是否推荐', titles: '书名候选', volume: '卷号', decisions: '替你做的决定', topic: '问题', choice: '选择', reason: '理由', options: '选项',
}
const OUTLINE_STATUS: Record<string, string> = { pinned: '锁住', pencil: '暂定', empty: '留空', planned: '已规划', outlined: '已有章纲', done: '已写完', writing: '正在写', confirmed: '已确认', auto: '自动通过', approved: '已批准', detailed: '等你确认' }

export interface HistoryRow { key: string; label: string; value: string; raw: string }
export interface HistoryDifference { key: string; label: string; before: string | null; after: string | null; change: 'same' | 'changed' | 'added' | 'removed' }

export function historyRows(snapshot: Record<string, unknown>, target: TargetType, config?: LibraryConfig, library?: Pick<LibrarySnapshot, 'categories' | 'entries'>): HistoryRow[] {
  const rows: HistoryRow[] = []
  const characterFields = target === 'character' ? config?.character_category.fields ?? [] : []
  const labels = { ...LABELS, ...Object.fromEntries(characterFields.map(field => [field.column, field.name])) }
  const fieldLabel = (key: string) => labels[key] ?? key
  const format = (value: unknown, field: string): string => {
    if (value == null || value === '') return '（空）'
    if (typeof value === 'boolean') return value ? '是' : '否'
    if (field === 'status' && typeof value === 'string') return target === 'entry' || target === 'character' ? config?.statuses[value] ?? value : OUTLINE_STATUS[value] ?? value
    if (field === 'style' && typeof value === 'string') return config?.styles[value as keyof LibraryConfig['styles']] ?? value
    if (field === 'source' && typeof value === 'string') return config?.sources[value] ?? value
    if (field === 'role_type' && typeof value === 'string') return config?.legacy_role_types[value] ?? value
    if (field === 'category') return library?.categories.find(category => category.key === value)?.name ?? String(value)
    if (['parent_id', 'secret_entry_id'].includes(field)) {
      const entry = library?.entries.find(entry => entry.id === value)
      return entry ? `${entry.name}（关联编号：${value}）` : `关联编号：${value}`
    }
    if (typeof value === 'number') return field === 'target_length' ? `${value} 万字` : field === 'chapter_words' ? `${value} 字` : field === 'chapter_count' ? `${value} 章` : String(value)
    return String(value)
  }
  const visit = (value: unknown, key: string, label: string, field: string) => {
    if (Array.isArray(value)) {
      if (!value.length || value.every(item => item == null || typeof item !== 'object')) rows.push({ key, label, value: value.length ? value.map(item => format(item, field)).join('、') : '（空）', raw: JSON.stringify(value) })
      else value.forEach((item, index) => visit(item, `${key}.${index}`, `${label} · 第 ${index + 1} ${field === 'levels' ? '级' : '项'}`, field))
    } else if (value && typeof value === 'object') {
      const entries = Object.entries(value)
      if (!entries.length) rows.push({ key, label, value: '（空）', raw: '{}' })
      else entries.forEach(([child, childValue]) => visit(childValue, `${key}.${child}`, `${label} · ${fieldLabel(child)}`, child))
    } else rows.push({ key, label, value: format(value, field), raw: JSON.stringify(value) ?? 'null' })
  }
  const ordered = [...characterFields.map(field => String(field.column)), ...Object.keys(snapshot)]
  for (const key of new Set(ordered)) if (Object.hasOwn(snapshot, key)) visit(snapshot[key], key, fieldLabel(key), key)
  return rows
}

/** 按实际字段路径对比相邻版本；删除的字段也显示，不修改或裁剪任何快照。 */
export function compareHistory(current: Record<string, unknown>, previous: Record<string, unknown> | null, target: TargetType, config?: LibraryConfig, library?: Pick<LibrarySnapshot, 'categories' | 'entries'>): HistoryDifference[] {
  const now = historyRows(current, target, config, library)
  const before = previous ? historyRows(previous, target, config, library) : []
  const previousRows = new Map(before.map(row => [row.key, row]))
  const result: HistoryDifference[] = now.map(row => {
    const old = previousRows.get(row.key)
    return { key: row.key, label: row.label, before: old?.value ?? null, after: row.value, change: !previous ? 'same' : !old ? 'added' : old.raw === row.raw ? 'same' : 'changed' }
  })
  const present = new Set(now.map(row => row.key))
  for (const row of before) if (!present.has(row.key)) result.push({ key: row.key, label: row.label, before: row.value, after: null, change: 'removed' })
  return result
}
