import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { needsSetupRestart } from '../../lib/setupPresentation'
import { artifactTarget } from '../../lib/workspace'
import { useBookContext } from './context'
import { ArtifactBody } from './MeetingFeed'
import { Locked, PageHeader } from './sections/common'
import { setupPreviewForPath } from './setupPreview'

/** 产出只读预览不冒充数据库实体，且不卸载正式稿件，保留作者尚未提交的输入。 */
export function SetupArtifactPreview({ children }: { children: ReactNode }) {
  const { bookId, book, job, messages, outline } = useBookContext()
  const { pathname, search } = useLocation()
  const message = setupPreviewForPath(bookId, job, messages, pathname + search, outline)
  const target = message ? artifactTarget(message, bookId, outline) : null
  const data = message?.payload?.data as { title?: string } | undefined
  const title = message?.payload?.type === 'concept' && data?.title ? data.title : target?.label ?? '开书方案'

  if (needsSetupRestart(book, job)) return <section aria-label="旧开书产出（只读）"><p className="mb-4 text-sm leading-relaxed text-ink-2">这是旧流程的产出，只供查看。请在上方点「按新流程重开」。</p><fieldset disabled className="min-w-0 border-0 p-0">{children}</fieldset></section>

  // 正式三页始终读取最新数据库，旧会议快照不能盖住作者正在编辑的稿件。
  if (['/concept', '/library', '/outline'].includes(pathname.slice(`/books/${bookId}`.length))) return children

  return <>
    <div hidden={!!message}>{children}</div>
    {message && <section data-testid="live-setup-preview" data-artifact-type={message.payload?.type}>
      <PageHeader
        eyebrow="本轮产出 · 未定稿"
        title={title}
        subtitle="编辑部正在完善开书方案。这里展示本轮最新产出，暂时只读；方案保存后会切回正式书稿。"
      />
      <Locked locked />
      <p className="mb-6 border-l-2 border-seal pl-3 text-sm leading-relaxed text-ink-2">{message.content}</p>
      <div className="text-sm leading-[1.75] text-ink-2"><ArtifactBody message={message} /></div>
    </section>}
  </>
}
