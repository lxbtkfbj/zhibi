import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { artifactTarget } from '../../lib/workspace'
import { useBookContext } from './context'
import { ArtifactBody } from './MeetingFeed'
import { PageHeader } from './sections/common'
import { setupPreviewForPath } from './setupPreview'

/** A read-only bridge until setup is persisted; all normal routes and author forms remain unchanged. */
export function SetupArtifactPreview({ children }: { children: ReactNode }) {
  const { bookId, job, messages, outline } = useBookContext()
  const { pathname } = useLocation()
  const message = setupPreviewForPath(bookId, job, messages, pathname, outline)
  if (!message) return children
  const target = artifactTarget(message, bookId, outline)
  const data = message.payload?.data as { title?: string }
  const title = message.payload?.type === 'concept' && data.title ? data.title : target?.label ?? '开书方案'

  return (
    <section data-testid="live-setup-preview" data-artifact-type={message.payload?.type}>
      <PageHeader
        eyebrow="本轮产出 · 未定稿"
        title={title}
        subtitle="编辑部正在完善开书方案。这里展示本轮最新产出，暂时只读；方案保存后会切回正式书稿。"
      />
      <p className="mb-6 border-l-2 border-seal pl-3 text-sm leading-relaxed text-ink-2">{message.content}</p>
      <div className="text-sm leading-[1.75] text-ink-2">
        <ArtifactBody message={message} />
      </div>
    </section>
  )
}
