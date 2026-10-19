/** 目录来自后台；退役或失效的选择只能回退到当前目录，不能请求写死的旧模板。 */
export function resolvePromptSelection(items: readonly { name: string }[] | undefined, requested: string | null): string | null {
  if (!items?.length) return null
  return items.some(item => item.name === requested) ? requested : items[0].name
}
