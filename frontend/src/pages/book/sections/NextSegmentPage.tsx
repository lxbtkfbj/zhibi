import type { ReactNode } from 'react'
import { useBible } from '../../../api/hooks'
import type { Foreshadowing } from '../../../api/types'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, QuestionSection } from '../../../components/QuestionSection'
import { WritingHint } from '../../../components/WritingLabels'
import { Button, ErrorText } from '../../../components/ui'
import { segmentReviewKey } from '../../../lib/nextSegmentQuestions'
import { useBookContext } from '../context'
import { Decisions } from '../PieceDecisions'
import { PageHeader } from './common'

const value = (text?: string) => <p className="whitespace-pre-wrap break-words">{text?.trim() || <span className="text-ink-3">（未填写）</span>}</p>

/** 编号属于现有台账；只给真正的 F / E 引用加标签，不替作者补造线头。 */
function CarriedThreads({ text, ledger }: { text: string; ledger: Foreshadowing[] }) {
  return <p className="whitespace-pre-wrap break-words">{text ? text.split(/\b([FE]\d+)\b/g).map((part, index) => {
    if (!/^[FE]\d+$/.test(part)) return part
    const item = ledger.find(entry => entry.code === part)
    const hint = item ? `${item.code} · ${item.description}\n${item.kind === '期待' ? '怎么立' : '埋下'}：${item.plant_plan || '未定'}\n${item.kind === '期待' ? '怎么兑现' : '回收'}：${item.payoff_plan || '未定'}` : `${part}：台账中暂未找到这条记录。`
    return <WritingHint key={`${index}-${part}`} label={`查看 ${part} 台账`} hint={hint} className="mx-1 inline-flex rounded border border-chief/25 bg-chief-soft px-1.5 py-0.5 align-baseline text-xs font-medium text-chief">{part}</WritingHint>
  }) : <span className="text-ink-3">（未填写）</span>}</p>
}

/** 全页只展示当前任务的待确认快照，绝不从已保存节点拼凑下一篇。 */
export function NextSegmentPage() {
  const { bookId, job, working, manualNavigate, segmentPinEnd, setSegmentPinEnd, segmentReview } = useBookContext()
  const { data: bible } = useBible(bookId)
  const pending = job?.status === 'waiting_author' && job.pending?.kind === 'segment_review' ? job.pending : null
  if (!pending) return <div data-testid="next-segment-empty">
    <PageHeader eyebrow="定下一篇" title={working ? '编辑部正在准备下一步' : '当前没有待确认的下一篇'} subtitle={working ? '需要你确认时，下一篇的十四道题会显示在这里。已经确认的篇在全书地图里。' : '已经确认的篇在全书地图里；这里不保留可再次提交的旧稿。'} />
    <Button variant="soft" onClick={() => manualNavigate(`/books/${bookId}/spine`)}>去全书地图</Button>
  </div>

  const { plan, split } = pending
  const section = (questionKey: string, children: ReactNode) => <QuestionSection piece="next_segment" questionKey={questionKey} pending={pending}>{children}</QuestionSection>
  const anchors = [...new Set((split.anchors ?? []).map(anchor => anchor.node))].sort((a, b) => a - b)
  const act = async (action: 'confirm' | 'delegate' | 'revise', flips?: { topic: string; choice: string }[]) => {
    try { await segmentReview.submit({ action, ...(flips ? { flips } : {}) }) } catch { /* 留下原稿与选择，错误在共享操作区显示。 */ }
  }
  return <article data-testid="next-segment-review" data-segment-number={pending.number}>
    <PageHeader eyebrow="定下一篇" title={`第 ${pending.number} 篇：走到「${plan.end.title}」`} subtitle="这一篇还没写进书里，确认之后才会保存。想改就换掉下面替你做的决定，或者在群聊里说。" />
    {plan.finale && <p role="note" className="mb-6 rounded-lg border border-seal/25 bg-seal-soft px-4 py-3 text-sm leading-relaxed text-seal">这是收尾篇：开始收线，往结局走。</p>}
    {!!pending.decisions?.length && <Decisions key={segmentReviewKey(job?.id, pending)} decisions={pending.decisions} name="next-segment" disabled={segmentReview.submitting} loading={segmentReview.submitting && segmentReview.action === 'revise'} error={segmentReview.error} onRevise={flips => void act('revise', flips)} />}
    <FocusQuestions piece="next_segment" />
    {section('carried', <CarriedThreads text={plan.carried} ledger={bible?.foreshadowings ?? []} />)}
    {section('pursuit', value(plan.pursuit))}
    {section('finger_next', value(plan.finger_next))}
    {section('answers', plan.answers?.trim() ? value(plan.answers) : <p className="text-ink-3">还远，写到再定</p>)}
    {section('map', <>{value(plan.map)}{plan.new_map && <FactTable rows={([
      ['name', '地图名'], ['powers', '谁说了算'], ['ceiling', '天花板'], ['rules', '特有的规矩'], ['start', '主角从哪起步'], ['gains', '能拿到什么'],
    ] as const).map(([key, label]) => ({ label, value: value(plan.new_map?.[key]) }))} />}{plan.power && <FactTable rows={[{ label: '新的力量层级', value: value(plan.power) }]} />}</>)}
    {section('opponents', <FactTable rows={[{ label: '小麻烦', value: value(plan.trouble) }, { label: '大对手', value: value(plan.opponent) }]} />)}
    {section('people', plan.new_characters?.length ? <div className="space-y-3">{plan.new_characters.map((person, index) => <section key={`${index}-${person.name}`} className="rounded-lg border border-line bg-card p-4">
      <h3 className="mb-3 font-serif font-bold">{person.name}<span className="ml-2 font-sans text-xs font-normal text-ink-2">· {person.role_type}</span></h3>
      <FactTable rows={[{ label: '想要什么', value: value(person.goal) }, { label: '此刻想要', value: value(person.want) }]} />
    </section>)}</div> : <p className="text-ink-3">这一篇没有新增人物。</p>)}
    {section('goal', <FactTable rows={[{ label: '目标', value: value(plan.goal) }, { label: '为什么离长线追求更近', value: value(plan.goal_link) }]} />)}
    {section('wait', <><FactTable rows={[{ label: '期待的一句话', value: value(plan.wait?.description) }, { label: '怎么立', value: value(plan.wait?.plant_plan) }, { label: '怎么兑现', value: value(plan.wait?.payoff_plan) }]} /><p className="text-xs text-ink-2">第 {plan.wait?.plant_volume ?? '待定'} 卷立下 → 第 {plan.wait?.payoff_volume ?? '待定'} 卷兑现</p></>)}
    {section('reveal', <>{value(plan.reveal)}{!!plan.secrets?.length && <div className="space-y-3">{plan.secrets.map((secret, index) => <section key={`${index}-${secret.title}`} className="rounded-lg border border-lore/20 bg-lore-soft/30 p-4"><h3 className="mb-3 font-serif font-bold">{secret.title}</h3><FactTable rows={[{ label: '真相', value: value(secret.truth) }, { label: '知情人', value: secret.knowers?.join('、') || '暂时无人知道' }]} /></section>)}</div>}</>)}
    {section('end', <><div className="rounded-lg border border-chief/25 bg-card p-4">
      <p className="mb-3 text-xs text-chief">{plan.end.adopted ? `沿用远景节点（${plan.end.status === 'pinned' ? '铁钉' : '暂定'}）` : '新起'}</p>
      <FactTable rows={[...([
        ['title', '名称'], ['event', '发生什么'], ['prerequisite', '之前得先有'], ['consequence', '之后变成'],
      ] as const).map(([key, label]) => ({ label, value: value(plan.end[key]) })), { label: '约第几卷', value: <p>{plan.end.volume == null ? '待定' : `第 ${plan.end.volume} 卷`}</p> }]} />
    </div><label className="flex cursor-pointer items-center gap-2 rounded-lg border border-seal/20 bg-seal-soft/30 px-3 py-3 text-sm"><input type="checkbox" checked={segmentPinEnd} onChange={event => setSegmentPinEnd(event.target.checked)} disabled={segmentReview.submitting} className="size-4 shrink-0 accent-[var(--color-seal)]" />确认时把它钉死</label></>)}
    {section('cast', anchors.length ? <div className="space-y-4">{anchors.map(node => <div key={node}><h3 className="mb-2 text-sm font-medium">节点 {node}{plan.nodes_view?.find(item => item.index === node)?.title ? `「${plan.nodes_view.find(item => item.index === node)!.title}」` : ''}</h3><ul className="space-y-2 text-sm">{split.anchors?.filter(anchor => anchor.node === node).map((anchor, index) => <li key={`${index}-${anchor.character}`}><span className="font-medium">{anchor.character}</span><span className="mx-2 text-lore">{anchor.kind}</span>{anchor.note}</li>)}</ul></div>)}</div> : <p className="text-ink-3">还没有安排人物锚点。</p>)}
    {section('volumes', split.volumes?.length ? <div className="space-y-4">{split.volumes.map(volume => <section key={volume.index} className="rounded-lg border border-line bg-card p-4"><header className="mb-4 flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-serif font-bold">第 {volume.index} 卷 · {volume.title}</h3><span className="text-xs text-ink-2">约 {volume.chapter_count} 章</span></header><FactTable rows={[{ label: '想做成', value: value(volume.want) }, { label: '卷末结果', value: value(volume.goal) }, { label: '对手', value: value(volume.antagonist) }]} />
      <ul aria-label={`第 ${volume.index} 卷的线索节拍`} className="mt-4 space-y-2 border-t border-line pt-3 text-sm">{(split.threads ?? []).flatMap(thread => (thread.beats ?? []).filter(beat => beat.volume === volume.index).map((beat, index) => <li key={`${thread.name}-${index}`}><span className="mr-2 text-chief">{thread.name}</span>{beat.beat}</li>))}</ul>
    </section>)}</div> : <p className="text-ink-3">还没有分卷。</p>)}
    {section('direction', value(plan.ending?.trim() || '不调'))}
    <footer className="mt-8 border-t border-line pt-5" data-testid="next-segment-actions"><div className="flex flex-wrap gap-3">
      <Button variant="seal" disabled={segmentReview.submitting} loading={segmentReview.submitting && segmentReview.action === 'confirm'} onClick={() => void act('confirm')}>确认这一篇</Button>
      <Button variant="ghost" disabled={segmentReview.submitting} loading={segmentReview.submitting && segmentReview.action === 'delegate'} onClick={() => void act('delegate')}>交给编辑部定</Button>
    </div><ErrorText error={segmentReview.error} /></footer>
  </article>
}
