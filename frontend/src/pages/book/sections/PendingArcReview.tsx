import { Button, ErrorText } from '../../../components/ui'
import { segmentReviewKey, type PendingArc } from '../../../lib/outlineWriting'
import { useBookContext } from '../context'
import { Decisions } from '../PieceDecisions'

/** 这里只读 pending 快照；任何改动都经 revise，确认前不发库/大纲 PATCH。 */
export function PendingArcReview({ pending }: { pending: PendingArc }) {
  const { job, segmentPinEnd, setSegmentPinEnd, segmentReview, requestFeedback } = useBookContext()
  const act = async (action: 'confirm' | 'delegate' | 'revise' | 'redo', flips?: { topic: string; choice: string }[]) => {
    try { await segmentReview.submit({ action, ...(flips ? { flips } : {}) }) } catch { /* 共享错误区保留作者选择。 */ }
  }
  if (pending.flow === 2) return <section data-testid="legacy-arc-review" className="space-y-4"><p className="text-sm leading-7">这一篇是按旧写法规划的，要按新写法重出一次</p><Button variant="seal" loading={segmentReview.submitting} disabled={segmentReview.submitting} onClick={() => void act('redo')}>按新写法重出</Button><ErrorText error={segmentReview.error} /></section>
  const { plan, split } = pending
  return <article data-testid="pending-arc-review" className="space-y-6">
    <header><p className="mb-2 text-xs text-chief">第 {pending.number} 篇 · 待你确认</p><h2 className="font-serif text-xl font-bold">{plan.title}</h2><p className="mt-4 whitespace-pre-wrap text-[15px] leading-8">{plan.text}</p><p className="mt-3 text-xs text-ink-2">确认后才会保存到大纲。现在想改，先提意见；保存后就能改这一句。</p></header>
    <section aria-label="这一篇的终点" className="space-y-3 rounded-xl border border-line bg-paper/60 p-4"><h3 className="font-serif font-bold">终点 · {plan.end.title}</h3><p className="text-xs text-ink-2">{plan.end.adopted || plan.end.ref > 0 ? '用大纲里已有的节点' : '新起一个'}</p><p className="whitespace-pre-wrap text-sm leading-7">{plan.end.event}</p>{plan.end.status === 'pinned' ? <p className="text-xs text-seal">已锁</p> : <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={segmentPinEnd} disabled={segmentReview.submitting} onChange={event => setSegmentPinEnd(event.target.checked)} />确认时把它锁住</label>}</section>
    <section className="space-y-3"><h3 className="font-serif font-bold">分卷</h3>{split.volumes.map(volume => <div key={volume.index} className="rounded-lg border border-line p-4"><p className="font-medium">第 {volume.index} 卷 · {volume.title}<span className="ml-2 text-xs font-normal text-ink-2">约 {volume.chapter_count} 章</span></p><p className="mt-2 whitespace-pre-wrap text-sm leading-7">{volume.summary || '（还没写一段话）'}</p></div>)}{split.wait?.description && <p className="text-sm leading-7"><span className="text-chief">读者在等：</span>{split.wait.description}</p>}</section>
    {([['这一篇要写全的设定', plan.fill_entries?.map(item => ({ name: item.name, text: item.content }))], ['这一篇新建的设定', plan.new_entries?.map(item => ({ name: item.name, text: item.one_line || item.content || '' }))], ['这一篇新登场的人物', plan.new_characters?.map(item => ({ name: item.name, text: [item.role_type, item.one_line].filter(Boolean).join(' · ') }))]] as const).map(([label, items]) => !!items?.length && <section key={label}><h3 className="mb-3 font-serif font-bold">{label}</h3><ul className="space-y-3 text-sm leading-7">{items.map((item, index) => <li key={`${item.name}-${index}`}><strong>{item.name}</strong><p className="whitespace-pre-wrap text-ink-2">{item.text}</p></li>)}</ul></section>)}
    {plan.secret && <section><h3 className="mb-2 font-serif font-bold">主编推的底牌</h3><p className="whitespace-pre-wrap text-sm leading-7">{plan.secret}</p></section>}
    {plan.ending_change && <section><h3 className="mb-2 font-serif font-bold">结局调整</h3><p className="whitespace-pre-wrap text-sm leading-7">{plan.ending_change}</p></section>}
    {!!pending.warnings.length && <section className="rounded-lg bg-chief-soft/40 p-4"><h3 className="mb-2 text-sm font-medium">程序提醒</h3><ul className="list-disc space-y-2 pl-4 text-sm leading-7">{pending.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></section>}
    {!!pending.decisions.length && <Decisions key={segmentReviewKey(job?.id, pending)} decisions={pending.decisions} name="pending-arc" disabled={segmentReview.submitting} loading={segmentReview.submitting && segmentReview.action === 'revise'} error={segmentReview.error} onRevise={flips => void act('revise', flips)} />}
    <footer className="space-y-3 border-t border-line pt-5"><div className="flex flex-wrap gap-2"><Button variant="seal" disabled={segmentReview.submitting} loading={segmentReview.submitting && segmentReview.action === 'confirm'} onClick={() => void act('confirm')}>确认这一篇</Button><Button variant="ghost" disabled={segmentReview.submitting} onClick={() => void act('delegate')}>交给编辑部定</Button><Button variant="ghost" disabled={segmentReview.submitting} onClick={requestFeedback}>提意见</Button></div><ErrorText error={segmentReview.error} /></footer>
  </article>
}
