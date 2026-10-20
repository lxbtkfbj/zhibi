import type { TeardownSummary } from '../api/types'
import type { TeardownAppendPreview, TeardownNumberIssue } from './teardownPreview'
import { teardownPreviewTotals } from './teardownPreview.ts'

/** 勾回只改变展示计划；后台确认时仍会对着当时的书重新分章计算。 */
export function teardownAppendSelection(preview: TeardownAppendPreview, include: readonly number[]): TeardownAppendPreview {
  if (!preview.selection) return preview
  const included = new Set(include)
  const selected = preview.selection.filter(chapter => !chapter.excluded || included.has(chapter.order))
  const counts = new Map<number, number>()
  for (const chapter of selected) counts.set(chapter.volume, (counts.get(chapter.volume) ?? 0) + 1)
  const context = preview.reopen_context
  let volumes = preview.volumes.map(volume => ({ ...volume, chapters: counts.get(volume.index) ?? 0 }))
  let reopen = preview.reopen
  if (context) {
    const lastVolume = context.last_volume
    if (context.original_volumes) {
      volumes = volumes.filter(volume => !volume.continued || volume.chapters > 0)
      if (counts.has(lastVolume.index) && !volumes.some(volume => volume.index === lastVolume.index)) volumes.unshift({ index: lastVolume.index, title: lastVolume.title, chapters: counts.get(lastVolume.index)!, continued: true })
    }
    reopen = preview.reopen.filter(item => item.kind === 'ending')
    if (context.tail_unit && (!context.original_volumes || counts.has(lastVolume.index))) reopen.push({ kind: 'unit', ...context.tail_unit })
    if (context.original_volumes && lastVolume.summary) reopen.push({ kind: 'summary', title: lastVolume.title })
    if (!context.original_volumes && !context.open_volume_id) reopen.push({ kind: 'volume', title: lastVolume.title })
  }
  const numbered = selected.map((chapter, index) => ({ ...chapter, index: preview.previous.chapters + index + 1 })).filter(chapter => chapter.number !== null && !chapter.flags.includes('番外'))
  const anchor = preview.last_numbered
  let junction = preview.junction
  if (anchor !== undefined) {
    const first = numbered[0]
    junction = { kind: null, a: anchor?.number ?? null, b: first?.number ?? null, missing: 0 }
    if (anchor && first) {
      const a = anchor.number, b = first.number!
      junction = { kind: b === a + 1 || (first.volume !== anchor.volume && b === 1) ? null : b > a + 1 ? '跳了' : '倒回去了', a, b, missing: Math.max(0, b - a - 1) }
    }
  }
  // 与 split.number_issues 同一规矩：番外不比较，新卷从1开始不算倒退，孤立笔误不连报。
  const numberIssues: TeardownNumberIssue[] = []
  let issueTotal = 0
  let previous = anchor?.number ?? null
  let previousVolume = anchor?.volume ?? null
  for (const [position, chapter] of numbered.entries()) {
    let number = chapter.number!
    const newVolume = chapter.volume !== previousVolume
    if (previous !== null && number !== previous + 1 && !(newVolume && number === 1)) {
      const following = numbered[position + 1]
      const expected = previous + 1
      const typo = !!following && !newVolume && following.volume === chapter.volume && following.number === previous + 2 && following.number !== number + 1
      const kind = typo ? '打错了' : number > expected ? '跳了' : number === previous ? '重了' : '倒回去了'
      issueTotal += 1
      if (numberIssues.length < 50) numberIssues.push({ index: chapter.index, title: chapter.raw_title ?? chapter.title, number, expected, kind })
      if (typo) number = expected
    }
    previous = number
    previousVolume = chapter.volume
  }
  return { ...preview, volumes, reopen, junction,
    first: selected[0] ? { index: preview.previous.chapters + 1, title: selected[0].title } : null,
    last: selected.length ? { index: preview.previous.chapters + selected.length, title: selected.at(-1)!.title } : null,
    number_issues: anchor === undefined ? preview.number_issues : numberIssues,
    number_issue_total: anchor === undefined ? preview.number_issue_total : issueTotal,
  }
}

export function teardownAppendJunctionText(preview: TeardownAppendPreview): string | null {
  const { kind, a, b, missing } = preview.junction
  if (kind === '跳了') return `原书第 ${a} 章后面接的是原书第 ${b} 章，中间缺 ${missing} 章`
  if (kind === '倒回去了') return `新文件从原书第 ${b} 章开始，书里已经到原书第 ${a} 章了：是不是传错了文件？`
  return null
}

export function teardownAppendSplitText(preview: TeardownAppendPreview, include: readonly number[] = []): string {
  const { chapters } = teardownPreviewTotals(preview, include)
  return `新文件分出 ${chapters} 章，接在第 ${preview.previous.chapters} 章「${preview.previous.last.title}」后面，补上以后一共 ${preview.previous.chapters + chapters} 章。`
}

/** 接缝倒退在页首单独提醒；这里严格按任务列出其余接缝说明。 */
export function teardownAppendNotes(preview: TeardownAppendPreview): string[] {
  const notes: string[] = []
  if (preview.junction.kind === '跳了') notes.push(teardownAppendJunctionText(preview)!)
  const leading = preview.duplicates.leading
  if (leading.length) {
    const listed = leading.slice(0, 10).map(chapter => `第 ${chapter.number} 章 ${chapter.title}`)
    if (leading.length > 10) listed.push(`还有 ${leading.length - 10} 章`)
    notes.push(`开头 ${leading.length} 章书里已经有了，不再补：${listed.join('、')}。`)
  }
  if (preview.duplicates.content) notes.push(`另有 ${preview.duplicates.content} 章和书里的正文一模一样，不再补。`)
  for (const kind of ['unit', 'summary', 'volume'] as const) {
    for (const item of preview.reopen) {
      if (item.kind !== kind) continue
      if (kind === 'unit') notes.push(`最后一个单元「${item.title}」（第 ${item.first}–${item.last} 章）会和新补的章一起重新归`)
      if (kind === 'summary') notes.push(`最后一卷「${item.title}」那段话会重写`)
      if (kind === 'volume') notes.push(`最后一卷「${item.title}」会和新补的章一起重新归，名字和那段话会重写`)
    }
  }
  if (preview.reopen.some(item => item.kind === 'ending')) notes.push('全书结局会删掉：补上以后拆到最后一章，再看原书完没完')
  if (!preview.previous.original_volumes && preview.ignored_volumes) notes.push(`新文件里写了 ${preview.ignored_volumes} 个卷名，这本书的卷是主编归的，不按文件分卷`)
  return notes
}

export function teardownAppendVolumeText(volume: TeardownAppendPreview['volumes'][number]): string {
  return `${volume.continued ? '接着' : ''}第 ${volume.index} 卷 ${volume.title} · ${volume.chapters} 章`
}

export function teardownAddedText(data?: Pick<TeardownSummary, 'added'> | null): string {
  const added = data?.added ?? []
  const last = added.at(-1)
  return last ? ` · 补过 ${added.length} 次，最近 ${last.at.slice(0, 10)} 补了第 ${last.first}–${last.last} 章` : ''
}

export function teardownAppendEntryText(data?: Pick<TeardownSummary, 'adding'> | null): string {
  return data?.adding ? '补章节还没确认' : '补后面的章节'
}
