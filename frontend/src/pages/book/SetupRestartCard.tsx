import { RotateCcw } from 'lucide-react'
import { useIsMutating } from '@tanstack/react-query'
import { useJobActions } from '../../api/hooks'
import { Button, ErrorText } from '../../components/ui'
import { LEGACY_SETUP_NOTICE, needsSetupRestart } from '../../lib/setupPresentation'
import { useBookContext } from './context'

/** 两处入口共享同一请求状态，失败不撤掉卡片，也不清掉作者的原文。 */
export function SetupRestartCard() {
  const { book, bookId, job, manualNavigate } = useBookContext()
  const { restartSetup } = useJobActions(bookId)
  const restarting = useIsMutating({ mutationKey: ['restart-setup', bookId] }) > 0
  if (!job || !needsSetupRestart(book, job)) return null
  const restart = async () => {
    try {
      await restartSetup.mutateAsync(job.id)
      manualNavigate(`/books/${bookId}`)
    } catch { /* 保留卡片，由 ErrorText 显示错误。 */ }
  }
  return <section aria-label="开书流程更新了" className="rounded-xl border border-seal/25 bg-card px-4 py-4">
    <h3 className="flex items-center gap-2 font-serif text-lg font-bold text-seal"><RotateCcw className="size-4 shrink-0" />开书流程更新了</h3>
    <p className="mt-2 text-sm leading-relaxed text-ink-2">{LEGACY_SETUP_NOTICE}</p>
    <Button className="mt-3" size="sm" variant="seal" loading={restarting} disabled={restarting} onClick={() => void restart()}>按新流程重开</Button>
    <ErrorText error={restartSetup.error} />
  </section>
}
