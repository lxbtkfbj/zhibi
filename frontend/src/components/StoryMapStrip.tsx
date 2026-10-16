import { Check } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChapterBrief, Concept, StoryNode, Volume } from '../api/types'
import { isWritingComplete, NODE_STATUS, storyMapNodeChapters, storyMapWritingIndex, visibleStoryMapNodes, writingPosition, writingPositionText } from '../lib/storyMap'
import './StoryMapStrip.css'

interface StoryMapStripProps {
  nodes: StoryNode[]
  volumes: Volume[]
  chapters: ChapterBrief[]
  concept?: Concept
  onNodeSelect: (node: StoryNode) => void
}

/** 横向地图按稿件栏宽度折叠，不通过横向滚动挤压三栏工作台。 */
export function StoryMapStrip({ nodes, volumes, chapters, concept, onNodeSelect }: StoryMapStripProps) {
  const ref = useRef<HTMLElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current?.closest('#manuscript-pane') ?? ref.current
    if (!element) return
    // 560px 指稿件栏本身；不能把页内留白扣掉后误判成地图容器的断点。
    const observer = new ResizeObserver(() => setWidth(element.getBoundingClientRect().width))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const position = writingPosition(nodes, volumes, chapters, concept)
  const summary = writingPositionText(position, volumes, chapters, nodes)
  const sorted = [...nodes].sort((a, b) => a.index - b.index)
  const hasTargets = volumes.some(volume => nodes.some(node => node.id === volume.target_node_id))
  const done = chapters.filter(chapter => chapter.status === 'final').length
  const plannedThrough = sorted.some(node => node.segment)
    ? Math.max(0, sorted.findLastIndex(node => volumes.some(volume => volume.target_node_id === node.id)))
    : sorted.length - 1
  const writingIndex = storyMapWritingIndex(storyMapNodeChapters(sorted, volumes, concept), done, plannedThrough, isWritingComplete(volumes, chapters, nodes))
  const visible = visibleStoryMapNodes(sorted, writingIndex, width)
  const leftIndex = Math.floor(writingIndex)
  const leftSlot = visible.findIndex(node => node?.id === sorted[leftIndex]?.id)
  const rightSlot = visible.findIndex(node => node?.id === sorted[Math.min(leftIndex + 1, sorted.length - 1)]?.id)
  const marker = hasTargets && sorted.length > 1
    ? (leftSlot + (rightSlot - leftSlot) * (writingIndex - leftIndex)) / Math.max(1, visible.length - 1)
    : position.ratio

  // 保持观测容器挂载，第一章定稿后无须切页即可显示地图。
  return <section ref={ref} className="story-map-strip" aria-label={summary || undefined} data-testid={position.volume == null ? undefined : 'story-map-strip'}>
    {position.volume != null && <>
      <div className="story-map-track" data-testid="story-map-track">
        <span className="story-map-line" aria-hidden="true" />
        <span className="story-map-progress" aria-hidden="true" style={{ width: `${Math.max(0, Math.min(1, marker)) * 100}%` }} />
        <span className="story-map-cursor" data-testid="story-map-cursor" style={{ left: `${Math.max(0, Math.min(1, marker)) * 100}%` }}>
          <span style={{ transform: marker < 0.1 ? 'translateX(0)' : marker > 0.9 ? 'translateX(-100%)' : undefined }}>写到这里</span>
        </span>
        {hasTargets ? visible.map((node, index) => node ? <button
          key={node.id}
          type="button"
          className="story-map-node"
          style={{ left: `${index / Math.max(1, visible.length - 1) * 100}%`, width: `min(80px, ${100 / Math.max(1, visible.length)}%)` }}
          data-status={node.status}
          data-passed={position.passed.includes(node.id)}
          data-tooltip-align={index < 2 ? 'start' : index >= visible.length - 2 ? 'end' : 'center'}
          aria-label={`节点 ${node.index}「${node.title}」 · ${NODE_STATUS[node.status]}${position.passed.includes(node.id) ? ' · 已写到' : ''}`}
          onClick={() => onNodeSelect(node)}
        >
          <span className="story-map-dot">{position.passed.includes(node.id) && <Check size={12} strokeWidth={3} />}</span>
          <span className="story-map-name">{Array.from(node.title || '未命名节点').slice(0, 6).join('')}{Array.from(node.title).length > 6 ? '…' : ''}</span>
          <span role="tooltip" className="story-map-tooltip">{node.title || '未命名节点'}</span>
        </button> : <span key={`gap-${index}`} className="story-map-ellipsis" aria-label="省略的节点" style={{ left: `${index / Math.max(1, visible.length - 1) * 100}%` }}>…</span>) : <div className="story-map-legacy-labels"><span>开写</span><span>计划终点</span></div>}
      </div>
      <p className="story-map-summary" data-testid="story-map-summary">{summary}</p>
    </>}
  </section>
}
