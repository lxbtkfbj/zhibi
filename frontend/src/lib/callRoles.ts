import { ROLE_KEYS, ROLE_KEY_LABEL, ROLE_META } from './roles.ts'

/** 默认配置不是调用角色；拆书和群聊分流则会以独立角色写入调用记录。 */
export const CALL_ROLE_KEYS = ROLE_KEYS.filter(role => role !== 'default')
export type CallRole = (typeof CALL_ROLE_KEYS)[number]

export function normalizeCallRole(value: unknown): CallRole | '' {
  return CALL_ROLE_KEYS.find(role => role === value) ?? ''
}

/** 提示词目录可能包含多个角色，调用列表和详情共用同一套中文名称。 */
export function roleName(role: string): string {
  if (role === 'all') return '全体成员'
  return role.split(',').map(value => {
    const key = value.trim()
    if (Object.hasOwn(ROLE_META, key)) return ROLE_META[key as keyof typeof ROLE_META].name
    return Object.hasOwn(ROLE_KEY_LABEL, key) ? ROLE_KEY_LABEL[key as keyof typeof ROLE_KEY_LABEL] : key
  }).join('、')
}
