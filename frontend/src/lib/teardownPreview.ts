export interface TeardownNumberIssue {
  index: number
  title: string
  number: number
  expected: number
  kind: '跳了' | '重了' | '倒回去了' | '打错了'
  count?: number
  end_index?: number
  end_number?: number
}

export interface TeardownIgnoredHeading {
  index: number
  title: string
  line: string
  order?: number
}

export interface TeardownFields {
  title: string
  author: string
}

export interface TeardownPreview extends TeardownFields {
  book_id: string
  intro: string
  file: { name: string; size: number }
  encoding: string
  encoding_auto: boolean
  traditional: boolean
  t2s: boolean
  t2s_seconds: number
  chars: number
  chapter_count: number
  volumes: { index: number; title: string; chapters: number }[]
  first: { index: number; title: string } | null
  last: { index: number; title: string } | null
  opening: string
  excluded: { order: number; title: string; chars: number; reason: string; head: string }[]
  number_issues: TeardownNumberIssue[]
  number_issue_total: number
  ignored_headings: TeardownIgnoredHeading[]
  ignored_heading_total: number
  ignored_heading_candidates?: { order: number; title: string; line: string }[]
  ads_removed: number
  duplicates_removed: number
  by_length: boolean
}

/** 补章节的章号、卷号已经由后台换成补后在书里的位置。 */
export interface TeardownAppendPreview extends TeardownPreview {
  mode: 'append'
  previous: { chapters: number; last: { index: number; title: string }; original_volumes: boolean }
  junction: { kind: '跳了' | '倒回去了' | null; a: number | null; b: number | null; missing: number }
  duplicates: { leading: { number: number; title: string }[]; content: number }
  reopen: ({ kind: 'unit' | 'summary' | 'volume'; title: string; first?: number; last?: number } | { kind: 'ending' })[]
  ignored_volumes: number
  volumes: { index: number; title: string; chapters: number; continued: boolean }[]
  selection?: { order: number; title: string; raw_title?: string; number: number | null; volume: number; excluded: boolean; flags: string[] }[]
  last_numbered?: { number: number; volume: number | null } | null
  reopen_context?: {
    tail_unit: { id: string; title: string; first: number; last: number } | null
    last_volume: { index: number; title: string; summary: boolean }
    open_volume_id: string | null
    original_volumes: boolean
  }
}

export function teardownWords(chars: number): string {
  return chars >= 10000 ? `${Math.round(chars / 10000)} 万字` : `${chars.toLocaleString('zh-CN')} 字`
}

/** 只把这份预览里勾回的条目加回来；编码变化后旧的 order 不会混进新预览。 */
export function teardownPreviewTotals(preview: TeardownPreview, include: readonly number[]) {
  const orders = new Set(include)
  const selected = preview.excluded.filter(chapter => orders.has(chapter.order))
  return {
    chars: preview.chars + selected.reduce((total, chapter) => total + chapter.chars, 0),
    chapters: preview.chapter_count + selected.length,
  }
}

export function teardownSplitText(preview: TeardownPreview, include: readonly number[] = []): string {
  const totals = teardownPreviewTotals(preview, include)
  if (preview.by_length) return `没认出章节标题，按三千字左右切成了 ${totals.chapters} 段`
  return `共 ${teardownWords(totals.chars)} · ${totals.chapters} 章，拆的时候主编按剧情分卷`
}

export function teardownNumberIssueText(issue: TeardownNumberIssue): string {
  const { index, number, expected, kind } = issue
  switch (kind) {
    case '跳了': return number - expected === 1
      ? `第 ${index} 章前：原书没有第 ${expected} 章`
      : `第 ${index} 章前：原书没有第 ${expected}–${number - 1} 章`
    case '重了': return `第 ${index} 章：原书第 ${number} 章出现了两次`
    case '倒回去了': return `第 ${index} 章：原书章号从第 ${expected - 1} 章倒回了第 ${number} 章`
    case '打错了': return issue.count && issue.count > 1
      ? `原书把第 ${expected}–${expected + issue.count - 1} 章写成了「第${number}章」到「第${issue.end_number}章」`
      : `第 ${index} 章：原书把第 ${expected} 章写成了「第${number}章」`
  }
}

export function teardownIgnoredHeadingText(heading: TeardownPreview['ignored_headings'][number]): string {
  return `第 ${heading.index} 章「${heading.title}」里的「${heading.line}」`
}

/** 确认页勾回的排除章会改变实际章号，候选也包括排除章自身的假标题。 */
export function teardownIgnoredHeadingSelection(preview: TeardownPreview, include: readonly number[], selected?: readonly { order: number }[], offset = 0) {
  const included = new Set(include)
  const excludedChapters = preview.excluded ?? []
  const excluded = new Set(excludedChapters.map(chapter => chapter.order))
  const positions = selected ? new Map(selected.map((chapter, index) => [chapter.order, offset + index + 1])) : null
  const indexOf = (order: number) => positions ? positions.get(order) : excluded.has(order) && !included.has(order) ? undefined
    : order + 1 - [...excluded].filter(value => value < order && !included.has(value)).length
  const candidates = preview.ignored_heading_candidates
  if (candidates) {
    const headings = candidates.flatMap(heading => {
      const index = indexOf(heading.order)
      return index === undefined ? [] : [{ ...heading, index }]
    })
    return { ignored_headings: headings.slice(0, 20), ignored_heading_total: headings.length }
  }
  return {
    ignored_headings: (preview.ignored_headings ?? []).map(heading => ({ ...heading,
      index: heading.order === undefined ? heading.index : positions?.get(heading.order) ?? heading.index + excludedChapters.filter(chapter => chapter.order < heading.order! && included.has(chapter.order)).length,
    })),
    ignored_heading_total: preview.ignored_heading_total,
  }
}

export function teardownCleaningText(preview: Pick<TeardownPreview, 'ads_removed' | 'duplicates_removed'>): string {
  return `去掉了 ${preview.ads_removed} 行广告和网址${preview.duplicates_removed ? `，重复的章 ${preview.duplicates_removed} 个` : ''}。`
}

/** 离焦保存逐次排队；换编码/导入先等待它，不能让旧 PATCH 晚于换编码覆盖手改。 */
export function createTeardownFieldSaver(initial: TeardownFields, persist: (patch: Partial<TeardownFields>) => Promise<unknown>) {
  let saved = { ...initial }
  let tail = Promise.resolve()
  return {
    save(fields: TeardownFields): Promise<void> {
      const snapshot = { ...fields }
      const next = tail.catch(() => {}).then(async () => {
        const changes: Partial<TeardownFields> = {}
        for (const key of ['title', 'author'] as const) if (snapshot[key] !== saved[key]) changes[key] = snapshot[key]
        if (!Object.keys(changes).length) return
        await persist(changes)
        saved = { ...saved, ...changes }
      })
      tail = next
      return next
    },
    settled: () => tail,
    accept: (fields: TeardownFields) => { saved = { ...fields } },
  }
}
