import clsx from 'clsx'
import { createContext, useContext, useState } from 'react'
import type { Job } from '../../api/types'
import { teardownProgressView } from '../../lib/teardownProgress'
import type { VBook } from './model'

export interface TeardownControl {
  job: Job | null
  stopping: boolean
  starting: boolean
  start: (upto: number | null) => Promise<void>
  stop: () => Promise<void>
  retry: () => Promise<void>
  openStart: () => void
  error?: unknown
}

const TeardownControlContext = createContext<TeardownControl | null>(null)
export const TeardownControlProvider = TeardownControlContext.Provider

const button = 'h-7 rounded-md border border-line-2 bg-card px-3 text-[13px] text-ink-2 transition-colors hover:border-ink-3/50 hover:text-ink disabled:opacity-40'

/** 和写作条使用同一套底色、字号与按钮；进度只由现成的 job 事件更新。 */
export function TeardownProgress({ book, embedded = false }: { book: VBook; embedded?: boolean }) {
  const control = useContext(TeardownControlContext)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState<unknown>()
  const view = teardownProgressView(book, control?.job ?? null)
  if (!view.visible || (!embedded && view.stage === 'imported')) return null
  const stopping = !!control?.stopping
  const busy = !!control?.starting || stopping
  const perform = (action?: () => Promise<void>) => {
    setError(undefined)
    action?.().catch(setError)
  }
  const tone = view.active ? 'bg-chief-soft/70 text-chief' : 'bg-subtle text-ink-2'
  const issue = error ?? control?.error
  return (
    <div className={clsx('shrink-0', embedded && 'mt-3 overflow-hidden rounded-lg border border-line')} data-testid={embedded ? 'teardown-progress-card' : 'teardown-progress-strip'}>
      <div role="status" className={clsx('flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2 text-[13px]', !embedded && 'justify-center', tone)}>
        <span aria-hidden className={clsx('size-2 shrink-0 rounded-full', view.active ? 'bg-chief motion-safe:animate-pulse' : 'bg-ink-3/60')} />
        {view.text && <span className="min-w-0">{view.text}</span>}
        {view.stage === 'imported' && <button type="button" className={button} disabled={!control || busy} onClick={control?.openStart}>开始拆</button>}
        {view.active && <button type="button" className={button} disabled={!control || busy} onClick={() => perform(control?.stop)}>{stopping ? '正在停：读完手上这几章就停' : '停下'}</button>}
        {view.stage === 'stopped' && <button type="button" className={button} disabled={!control || busy} onClick={control?.openStart}>接着拆</button>}
        {view.failed.length > 0 && <>
          <button type="button" aria-expanded={expanded} className="font-medium underline-offset-2 hover:underline" onClick={() => setExpanded(!expanded)}>· {view.failed.length} 章没读成</button>
          <button type="button" className={button} disabled={!control || busy || view.active} onClick={() => perform(control?.retry)}>再试一次</button>
        </>}
      </div>
      {view.stage !== 'imported' && <div role="progressbar" aria-label="拆书进度" aria-valuemin={0} aria-valuemax={view.target} aria-valuenow={view.read} className="h-0.5 bg-line">
        <div className="h-full bg-chief transition-[width]" style={{ width: `${view.percent}%` }} />
      </div>}
      {expanded && view.failed.length > 0 && <p className="border-b border-line bg-subtle px-4 py-2 text-[13px] leading-relaxed text-ink-2">{view.failed.map(index => `第 ${index} 章`).join('、')}</p>}
      {!!issue && <p role="alert" className="border-b border-line bg-seal-soft/60 px-4 py-2 text-[13px] text-seal-dark">{issue instanceof Error ? issue.message : String(issue)}</p>}
    </div>
  )
}
