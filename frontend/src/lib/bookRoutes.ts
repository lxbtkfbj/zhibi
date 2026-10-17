/** 旧链接只迁移位置，不丢掉作者指定的卷号。 */
export function legacyBookRoute(path: string): string | null {
  const routes: Record<string, string> = {
    'next-segment': 'outline?node=pending', protagonist: 'library?view=focus', characters: 'library?cat=角色卡片',
    world: 'library?cat=世界与地图', spine: 'outline?view=map', threads: 'outline?view=threads',
  }
  const volume = path.match(/^volume\/(\d+)$/)
  return volume ? `outline?node=volume-${volume[1]}` : routes[path] ?? null
}

/** 从书房进入才默认跟随；刷新/打开具体稿件链接视为作者指定位置。 */
export function followOnBookOpen(pathname: string, bookId: string) {
  return pathname.replace(/\/$/, '') === `/books/${bookId}`
}
