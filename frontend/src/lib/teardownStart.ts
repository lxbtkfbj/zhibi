/** 留空或填得超过全本都按全本；非法章号与全本的 null 明确分开。 */
export function parseTeardownUpto(value: string, total: number): number | null | undefined {
  if (!value.trim()) return null
  const upto = Number(value)
  if (!Number.isSafeInteger(upto) || upto < 1) return undefined
  return upto > total ? null : upto
}

/** 旧目标仍在前面才预填；已经拆到的目标不妨碍继续拆全本。 */
export function initialTeardownUpto(upto: number | null | undefined, last: number): string {
  return upto != null && upto > last ? String(upto) : ''
}

export function teardownStartLabel(stage: string, needsClosing: boolean): string | null {
  if (stage === 'imported') return '开始拆'
  if (stage === 'done') return needsClosing ? '补上整理' : null
  return '接着拆'
}

/** 与后台分工一致：拆书专用 → 默认 → 第一项；完全没有配置才是演示模式。 */
export function teardownModelName(profiles: readonly { id: string; name: string }[], roles: { teardown?: string | null; default?: string | null }): string {
  return (profiles.find(profile => profile.id === roles.teardown)
    ?? profiles.find(profile => profile.id === roles.default)
    ?? profiles[0])?.name ?? '演示模式'
}
