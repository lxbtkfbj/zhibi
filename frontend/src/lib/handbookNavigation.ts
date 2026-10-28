import { readPromptReturnContext, safePromptReturnContext, type PromptSourceLocation } from './promptNavigation.ts'

/** 管理页互跳不嵌套返回地址，始终沿用最初的书页。 */
export function handbooksHref(location: PromptSourceLocation, key?: string): string {
  const context = ['/prompts', '/presets', '/handbooks'].includes(location.pathname)
    ? readPromptReturnContext(location.search ?? '')
    : safePromptReturnContext(`${location.pathname}${location.search ?? ''}${location.hash ?? ''}`)
  const params = new URLSearchParams()
  if (context.bookId) params.set('returnTo', context.returnTo)
  if (key) params.set('key', key)
  return `/handbooks${params.size ? `?${params}` : ''}`
}
