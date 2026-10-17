import { useJobActions } from '../../api/hooks'
import { Button, ErrorText } from '../../components/ui'
import { useBookContext } from './context'

export function PrefillGate() {
  const { bookId, job, resumeFollow } = useBookContext()
  const actions = useJobActions(bookId)
  if (job?.status !== 'waiting_author' || job.pending?.kind !== 'setup_prefill') return null
  return <aside aria-label="先写设定" className="space-y-3 rounded-xl border border-chief/20 bg-chief-soft p-4 text-sm leading-relaxed"><p>先把你想好的设定写下来：人物、金手指、境界、地方……都行，也可以让 AI 帮你补。写好了点「出三个故事方向」。</p><Button loading={actions.pitches.isPending} onClick={() => { resumeFollow(); actions.pitches.mutate({ jobId: job.id, action: 'start' }) }}>出三个故事方向</Button><ErrorText error={actions.pitches.error} /></aside>
}
