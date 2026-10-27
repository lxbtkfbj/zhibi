import { readPromptReturnContext, safePromptReturnContext, type PromptSourceLocation } from './promptNavigation.ts'

export interface PresetNavigationSelection { source: 'system' | 'mine'; id?: string; version?: number; block?: string }

/** 预设与提示词共享同一份受限书页上下文，不把编辑页面本身嵌套成返回地址。 */
export function presetsHref(location: PromptSourceLocation, selection?: PresetNavigationSelection): string {
  const context = location.pathname === '/prompts' || location.pathname === '/presets'
    ? readPromptReturnContext(location.search ?? '')
    : safePromptReturnContext(`${location.pathname}${location.search ?? ''}${location.hash ?? ''}`)
  const params = new URLSearchParams()
  if (context.bookId) params.set('returnTo', context.returnTo)
  if (selection) {
    params.set('source', selection.source)
    if (selection.source === 'mine' && selection.id) params.set('id', selection.id)
    if (selection.source === 'system' && selection.version && Number.isSafeInteger(selection.version) && selection.version > 0) params.set('version', String(selection.version))
    if (selection.block) params.set('block', selection.block)
  }
  return `/presets${params.size ? `?${params}` : ''}`
}
