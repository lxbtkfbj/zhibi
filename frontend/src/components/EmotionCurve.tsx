import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import type { ChapterBrief } from '../api/types'
import { emotionPoint, emotionText, repeatedMoodChapters } from '../lib/writingUi'
import { WritingHint } from './WritingLabels'

export function EmotionCurve({ chapters }: { chapters: ChapterBrief[] }) {
  const container = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(320)
  useEffect(() => {
    if (!container.current) return
    const observer = new ResizeObserver(entries => { const next = entries[0]?.contentRect.width; if (next && next > 0) setWidth(next) })
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])
  const sorted = [...chapters].sort((a, b) => a.index - b.index)
  const points = sorted.map((chapter, index) => emotionPoint(chapter.outline?.emotion, index, sorted.length, width))
  const warnings = repeatedMoodChapters(sorted)
  const hasEmotions = points.some(Boolean)
  return <section aria-label="本单元情绪曲线" className="my-4 border-t border-line pt-3">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-1 text-xs text-ink-2"><span>情绪曲线 · 按章纲</span>{hasEmotions && <span>压抑 −2 ↔ 爽快 +2</span>}</div>
    <div ref={container}>
      {hasEmotions ? <>
        <div className="relative h-8" data-testid="emotion-curve">
          <svg aria-hidden="true" width="100%" height="32" viewBox={`0 0 ${width} 32`} className="overflow-visible">
            <line x1="0" x2={width} y1="16" y2="16" className="stroke-line-2" strokeDasharray="3 4" />
            {points.map((point, index) => point && <g key={sorted[index].id}>
              {index > 0 && points[index - 1] && sorted[index].index === sorted[index - 1].index + 1 && <line x1={points[index - 1]!.x} y1={points[index - 1]!.y} x2={point.x} y2={point.y} className="stroke-seal" strokeWidth="1.5" />}
              <circle cx={point.x} cy={point.y} r="3" className="fill-seal stroke-card" strokeWidth="1" />
            </g>)}
          </svg>
          {points.map((point, index) => point && <WritingHint key={sorted[index].id} hint={`第 ${sorted[index].index} 章 · ${emotionText(sorted[index].outline?.emotion)}${sorted[index].outline?.mood ? ` · ${sorted[index].outline.mood}` : ''}`} className="absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${point.x / width * 100}%`, top: point.y }}><span className="sr-only">第 {sorted[index].index} 章情绪</span></WritingHint>)}
        </div>
        <ol aria-label="各章主情绪" className="mt-2 flex justify-between gap-1 text-xs">{sorted.map(chapter => <li key={chapter.id} className={clsx('text-center', warnings.has(chapter.id) ? 'font-medium text-seal-dark' : 'text-ink-2')} aria-label={`第 ${chapter.index} 章：${chapter.outline?.mood || '暂无主情绪'}${warnings.has(chapter.id) ? '，连续至少 4 章主情绪相同' : ''}`}>{chapter.outline?.mood || '—'}</li>)}</ol>
        {!!warnings.size && <p className="mt-1.5 text-xs text-seal-dark">连续至少 4 章主情绪相同，建议留意节奏。</p>}
      </> : <p className="text-xs text-ink-2">出章纲后显示情绪曲线</p>}
    </div>
  </section>
}
