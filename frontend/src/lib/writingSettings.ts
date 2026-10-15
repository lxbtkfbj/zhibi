/** Mirrors agents/playbook.py: only genre and tags participate in automatic matching. */
export function automaticPlaybookName(concept: { genre?: unknown; tags?: unknown } | null | undefined): string {
  const tags = Array.isArray(concept?.tags) ? concept.tags : []
  const words = [String(concept?.genre ?? ''), ...tags.map(String)].join(' ')
  const fantasy = ['玄幻', '修仙', '仙侠', '修真', '高武', '异世']
  const payoff = ['后宫', '多女主', '修罗场', '种马', '爽文', '无敌', '打脸']
  return fantasy.some(word => words.includes(word)) && payoff.some(word => words.includes(word)) ? '后宫玄幻爽文' : '通用'
}

export function requirementSource(source: string): string {
  const names: Record<string, string> = { answer: '动笔前的回答', note: '插话', trial: '试读意见', manual: '手动添加', legacy: '旧记录' }
  if (source.startsWith('volume:')) return `第 ${source.slice(7)} 卷卷纲意见`
  if (source.startsWith('private:')) {
    const roles: Record<string, string> = { chief: '主编', lorekeeper: '设定师', writer: '写手', reviewer: '审稿' }
    return `私聊${roles[source.slice(8)] ?? source.slice(8)}`
  }
  return names[source] ?? source
}
