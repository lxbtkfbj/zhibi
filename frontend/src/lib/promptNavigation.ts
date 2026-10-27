/** 提示词页独立于书页，但返回入口只接受本应用的书页路径。上下文放在 URL 中，刷新后仍然有效。 */
export interface PromptReturnContext { returnTo: string; bookId: string | null }
export interface PromptSourceLocation { pathname: string; search?: string; hash?: string }

const fallback = (): PromptReturnContext => ({ returnTo: '/', bookId: null })
const hasControlCharacter = (value: string) => [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)

export function safePromptReturnContext(value: unknown): PromptReturnContext {
  if (typeof value !== 'string' || !value.startsWith('/') || value.includes('\\') || hasControlCharacter(value)) return fallback()
  const pathname = value.split(/[?#]/, 1)[0]
  const match = /^\/(desk|books)\/([^/]+)(\/.*)?$/.exec(pathname)
  if (!match || (match[1] === 'desk' && match[3] && match[3] !== '/')) return fallback()
  try {
    // 不接受编码后的路径分隔符、点段或控制字符，避免浏览器/路由二次解码改变目的地。
    const segments = pathname.replace(/\/$/, '').slice(1).split('/').map(segment => decodeURIComponent(segment))
    if (segments.some(segment => !segment || segment === '.' || segment === '..' || /[\\/?#%\s]/.test(segment) || hasControlCharacter(segment))) return fallback()
    return { returnTo: value, bookId: segments[1] }
  } catch { return fallback() }
}

/** 在提示词页读取返回路径和当前书 ID；bookId 始终从安全路径推导，不采信另一个可冲突的参数。 */
export function readPromptReturnContext(search: string | URLSearchParams): PromptReturnContext {
  const params = typeof search === 'string' ? new URLSearchParams(search) : search
  return safePromptReturnContext(params.get('returnTo'))
}

/** 系统设置打开在书页时带上完整地址；在提示词页再次打开设置时沿用原来的书。 */
export function promptsHref(location: PromptSourceLocation): string {
  const context = location.pathname === '/prompts' || location.pathname === '/presets'
    ? readPromptReturnContext(location.search ?? '')
    : safePromptReturnContext(`${location.pathname}${location.search ?? ''}${location.hash ?? ''}`)
  if (!context.bookId) return '/prompts'
  return `/prompts?${new URLSearchParams({ returnTo: context.returnTo }).toString()}`
}
