import type { ReactNode } from 'react'
import type { Bible, Pending, SegmentPlan, Spine, StoryNode, Volume } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, LaterValue, QuestionField, QuestionSection } from '../../../components/QuestionSection'
import { firstSegment, OPENING_FIELDS } from '../../../lib/setupSegment'
import { NODE_STATUS, plannedVolumeChapters } from '../../../lib/storyMap'
import { useBookContext } from '../context'

type NodePatch = Partial<Pick<StoryNode, 'title' | 'event' | 'prerequisite' | 'consequence'>> & { segment?: Partial<SegmentPlan> }

export function FirstSegmentPanel({ nodes, volumes, bible, pending, locked, saveNode, saveSpine }: {
  nodes: StoryNode[]
  volumes: Volume[]
  bible: Bible | undefined
  pending: Pending | null
  locked: boolean
  saveNode: (id: string, patch: NodePatch) => Promise<unknown>
  saveSpine: (patch: Partial<Spine>) => Promise<unknown>
}) {
  const { bookId, book, manualNavigate } = useBookContext()
  const { endpoint, opening, ending, castNodes, distant, volumes: ownVolumes } = firstSegment(nodes, volumes)
  const segment = endpoint?.segment
  const spine = book.spine ?? {}
  const section = (questionKey: string, children: ReactNode) => <QuestionSection piece="segment" questionKey={questionKey} pending={pending}>{children}</QuestionSection>
  const text = (field: 'goal' | 'goal_link' | 'wait' | 'reveal') => <EditableText value={segment?.[field] ?? ''} locked={locked || !segment} multiline onSave={value => endpoint ? saveNode(endpoint.id, { segment: { [field]: value } }) : Promise.resolve()} />
  const nodeText = (node: StoryNode | null, field: 'title' | 'event' | 'prerequisite' | 'consequence') => <EditableText value={node?.[field] ?? ''} locked={locked || !node} multiline onSave={value => node ? saveNode(node.id, { [field]: value }) : Promise.resolve()} />
  const link = (path: string, children: ReactNode, className = '') => <button type="button" onClick={() => manualNavigate(`/books/${bookId}/${path}`)} className={`text-left text-chief underline decoration-chief/35 underline-offset-4 hover:decoration-chief focus-visible:outline-2 focus-visible:outline-chief ${className}`}>{children}</button>
  const expectations = (bible?.foreshadowings ?? []).filter(item => item.kind === '期待' && item.node_id === endpoint?.id)
  const segmentNodeIds = new Set(castNodes.map(node => node.id))
  const secrets = (bible?.secrets ?? []).filter(secret => secret.node_id ? segmentNodeIds.has(secret.node_id) : secret.created_chapter == null)
  const cast = castNodes.filter(node => node.anchors?.length)

  return <section aria-label="第一段怎么走" className="mb-9 border-b border-line pb-8" data-testid="first-segment-panel">
    <h2 className="mb-4 font-serif text-xl font-bold">第一段怎么走</h2>
    <FocusQuestions piece="segment" />
    {!segment && <p className="mb-6 text-sm text-ink-2">编辑部正在准备第一段，保存后的回答会显示在这里。</p>}
    {section('opening', <FactTable rows={OPENING_FIELDS.map(([field, label]) => ({ label, value: <EditableText value={segment?.opening?.[field] ?? ''} multiline locked={locked || !segment} onSave={value => endpoint ? saveNode(endpoint.id, { segment: { opening: { [field]: value } } }) : Promise.resolve()} /> }))} />)}
    {section('goal', <div className="space-y-4"><QuestionField label="目标">{text('goal')}</QuestionField><QuestionField label="为什么离长线追求更近">{text('goal_link')}</QuestionField></div>)}
    {section('wait', <div className="space-y-4">{text('wait')}{expectations.length > 0 && <ul className="space-y-2">{expectations.map(item => <li key={item.id} className="rounded-lg border border-line bg-paper/60 p-3 text-sm">{link('foreshadowing', <><span className="mr-2 font-medium">{item.code}</span>{item.description}</>, 'block w-full')}<p className="mt-1 text-xs text-ink-2">第 {item.plant_volume ?? '待定'} 卷立下 → 第 {item.payoff_volume ?? '待定'} 卷兑现</p></li>)}</ul>}</div>)}
    {section('reveal', <div className="space-y-4">{text('reveal')}{secrets.length > 0 && <div className="flex flex-wrap gap-2">{secrets.map(secret => <span key={secret.id} className="rounded-full border border-chief/20 bg-chief-soft px-2.5 py-1 text-xs">{link('secrets', `${secret.code}「${secret.title}」`)}</span>)}</div>}</div>)}
    {section('end', <div className="space-y-4">
      {endpoint && <div className="flex flex-wrap items-center gap-3 text-xs"><span className={endpoint.status === 'pinned' ? 'rounded-full border border-seal/40 bg-seal-soft px-2 py-0.5 text-seal' : 'rounded-full border border-dashed border-chief/50 px-2 py-0.5 text-chief'}>{NODE_STATUS[endpoint.status]}</span>{link(`spine#story-node-${endpoint.id}`, '在时间轴上看')}</div>}
      <FactTable rows={([['title', '名称'], ['event', '发生什么'], ['prerequisite', '之前得先有'], ['consequence', '之后变成']] as const).map(([field, label]) => ({ label, value: nodeText(endpoint, field) }))} />
    </div>)}
    {section('cast', cast.length ? <div className="space-y-4">{cast.map(node => <div key={node.id}><p className="mb-2 text-xs text-ink-2">节点 {node.index}「{node.title}」前后：</p><ul className="space-y-2 text-sm leading-relaxed">{node.anchors.map(anchor => <li key={anchor.id}>{link(`characters#character-${anchor.character_id}`, anchor.character_name)} <span className="text-lore">{anchor.kind}</span>{anchor.note && <>——{anchor.note}</>}</li>)}</ul></div>)}</div> : <p className="text-sm text-ink-2">还没有人物锚点，分卷后会把登场位置放到节点上。</p>)}
    {section('volumes', ownVolumes.length ? <div className="space-y-3">{ownVolumes.map(volume => <button key={volume.id} type="button" onClick={() => manualNavigate(`/books/${bookId}/volume/${volume.index}`)} className="block w-full rounded-lg border border-line bg-card p-4 text-left text-sm hover:border-chief/50 focus-visible:outline-2 focus-visible:outline-chief"><span className="flex flex-wrap items-baseline justify-between gap-2"><span className="font-serif font-bold">第 {volume.index} 卷 · {volume.title}</span><span className="text-xs text-ink-2">约 {plannedVolumeChapters(volume)} 章 →</span></span><span className="mt-2 block leading-relaxed text-ink-2">想做成：{volume.want || '（未定）'}</span></button>)}</div> : <p className="text-sm text-ink-2">第一段还没有分卷，主编会接着把它分成一到三卷。</p>)}
    {section('direction', <div className="space-y-4">
      <QuestionField label="结局方向" when="before">{nodeText(ending, 'event')}</QuestionField>
      <QuestionField label="主角最后变成什么样的人" when="before"><EditableText value={spine.protagonist_arc ?? ''} onSave={protagonist_arc => saveSpine({ protagonist_arc })} locked={locked} multiline /></QuestionField>
      <QuestionField label="核心矛盾" when="before"><EditableText value={spine.core_conflict ?? ''} onSave={core_conflict => saveSpine({ core_conflict })} locked={locked} multiline /></QuestionField>
      <QuestionField label="主题" when="before"><EditableText value={spine.theme ?? ''} onSave={theme => saveSpine({ theme })} locked={locked} multiline /></QuestionField>
      <QuestionField label="远景节点" when="later"><LaterValue value={distant}><ul className="space-y-2 text-sm">{distant.map(node => <li key={node.id} className="rounded-lg border border-dashed border-line-2 px-3 py-2">{link(`spine#story-node-${node.id}`, `节点 ${node.index}「${node.title}」`)}<span className="ml-2 text-xs text-ink-2">{NODE_STATUS[node.status]}</span>{node.event && <p className="mt-1 whitespace-pre-wrap leading-relaxed text-ink-2">{node.event}</p>}</li>)}</ul></LaterValue></QuestionField>
      <p className="text-xs leading-relaxed text-ink-2">远景节点只放你已经想到的；在下面的时间轴上点「在下面插入」，就能自己钉一个。</p>
    </div>)}
    {opening && <p className="mt-4 text-xs text-ink-2">从「{opening.title}」出发，先把这一段写扎实。</p>}
  </section>
}
