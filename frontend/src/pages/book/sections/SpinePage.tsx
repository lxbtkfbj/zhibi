import clsx from 'clsx'
import { ArrowDown, ArrowUp, Check, ChevronDown, MessageSquare, Pin, PinOff, Plus, Shuffle, Trash2 } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { useBible, useChapters, useJobActions, useNodeMutations, useNodes, useUpdateBook } from '../../../api/hooks'
import type { Spine, StoryNode, Volume } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { TechniqueChip } from '../../../components/TechniqueChip'
import { StoryMapStrip } from '../../../components/StoryMapStrip'
import { Button, Card, ErrorText, inputClass, Modal, Reveal, Skeleton } from '../../../components/ui'
import { isWritingComplete, nodeCounts, NODE_STATUS, plannedVolumeChapters, segments, writingPosition, type WritingPosition } from '../../../lib/storyMap'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
import { FieldBlock, Locked, PageHeader } from './common'

type Candidate = Pick<StoryNode, 'title' | 'event' | 'prerequisite' | 'consequence' | 'volume'> & Partial<Pick<StoryNode, 'editor_note' | 'techniques'>>

function NodeMarker({ node, passed }: { node: StoryNode; passed: boolean }) {
  return <span aria-label={`${NODE_STATUS[node.status]}${passed ? ' · 已写到' : ''}`} className={clsx(
    'flex size-8 items-center justify-center rounded-full font-serif text-sm',
    node.status === 'pinned' ? 'bg-seal text-paper-2 shadow-[var(--shadow-paper)]' :
      node.status === 'pencil' ? 'border-2 border-dashed border-chief bg-paper text-chief' : 'border-2 border-dotted border-ink-3 bg-paper text-ink-2',
  )}>{passed ? <Check className="size-4" /> : node.status === 'pinned' ? <Pin className="size-4" /> : node.index}</span>
}

function NodeAction({ label, children, onClick, disabled }: { label: string; children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} disabled={disabled} className="inline-flex size-8 items-center justify-center rounded-lg text-ink-2 hover:bg-paper-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-seal disabled:cursor-not-allowed disabled:opacity-40">{children}</button>
}

function CandidateCard({ candidate, onChoose, busy }: { candidate: Candidate; onChoose: () => void; busy: boolean }) {
  return <div className="rounded-xl border border-line-2 bg-card p-4 text-sm leading-relaxed">
    <div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-serif text-lg font-bold text-ink">{candidate.title}</h3>{candidate.volume != null && <span className="text-xs text-ink-2">约第 {candidate.volume} 卷</span>}</div>
    <p className="mt-2 whitespace-pre-wrap">{candidate.event}</p>
    <p className="mt-2"><span className="mr-2 text-xs text-ink-2">之前得先有</span>{candidate.prerequisite || '（未定）'}</p>
    <p className="mt-1"><span className="mr-2 text-xs text-ink-2">之后变成</span>{candidate.consequence || '（未定）'}</p>
    {candidate.editor_note && <p className="mt-3 border-t border-line pt-2 text-xs text-ink-2"><span className="mr-2">批注</span>{candidate.editor_note}</p>}
    {!!candidate.techniques?.length && <div className="mt-2 flex flex-wrap gap-1.5">{candidate.techniques.map(name => <TechniqueChip key={name} name={name} />)}</div>}
    <Button type="button" size="sm" variant="soft" className="mt-3" onClick={onChoose} disabled={busy}><Check className="size-3.5" />用这个</Button>
  </div>
}

function SegmentBand({ volumes, chapters, unassignedVolumes, position, complete }: { volumes: Volume[]; chapters: number; unassignedVolumes?: Volume[]; position: WritingPosition; complete: boolean }) {
  const { bookId, manualNavigate } = useBookContext()
  if (!volumes.length) return null
  const first = volumes[0].index
  const last = volumes.at(-1)!.index
  const active = !complete && volumes.some(volume => volume.index === position.volume)
  return <details className={clsx('group mt-4 rounded-lg border text-sm', active ? 'border-seal/45 bg-seal-soft/45' : 'border-line bg-paper/80')} data-testid="node-segment" data-active={active}>
    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2.5 text-chief focus-visible:outline-2 focus-visible:outline-seal"><ChevronDown className="size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" /><span>第 {first === last ? first : `${first}-${last}`} 卷 · 约 {chapters} 章</span>{active && <span className="basis-full pl-6 text-xs font-medium text-seal">正在写：第 {position.volume} 卷 {position.doneInVolume}/{position.volumeChapters} 章</span>}{!!unassignedVolumes?.length && <span className="text-xs text-ink-2">含 {unassignedVolumes.length} 卷未指定目标节点</span>}</summary>
    <div className="space-y-2 border-t border-line p-3">{volumes.map(volume => <button type="button" key={volume.id} onClick={() => manualNavigate(`/books/${bookId}/volume/${volume.index}`)} className="block w-full rounded-lg border border-line bg-card p-3 text-left hover:border-chief/50">
      <span className="flex flex-wrap justify-between gap-2"><span className="font-serif font-bold text-ink">第 {volume.index} 卷 · {volume.title}</span><span className="text-xs text-ink-2">约 {plannedVolumeChapters(volume)} 章 →</span></span>
      <span className="mt-1 block text-ink-2">卷末目标：{volume.goal || volume.climax || '待确定'}</span>
      {!volume.target_node_id && <span className="mt-1 block text-xs text-seal">尚未指定目标节点，暂归在最后一段</span>}
    </button>)}</div>
  </details>
}

function EmptyNodeForm({ disabled, onFill, onCandidates }: { disabled: boolean; onFill: (feedback?: string) => Promise<void>; onCandidates: () => void }) {
  const [sentence, setSentence] = useState('')
  const [error, setError] = useState('')
  return <div className="mt-4 space-y-3 border-t border-dotted border-line-2 pt-4">
    <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="soft" disabled={disabled} onClick={onCandidates}>给我 3 个候选</Button><Button type="button" size="sm" variant="soft" disabled={disabled} onClick={() => void onFill()}>补上这个空位</Button></div>
    <form onSubmit={async event => { event.preventDefault(); if (!sentence.trim()) { setError('先写一句你想要的节点'); return }; setError(''); await onFill(sentence.trim()) }}>
      <label className="mb-1.5 block text-xs text-ink-2">我自己写一句</label>
      <div className="flex flex-wrap gap-2"><input aria-label="我自己写一句" value={sentence} onChange={event => { setSentence(event.target.value); setError('') }} disabled={disabled} placeholder="例如：主角在这里找到失踪的母亲" className={clsx(inputClass, 'min-w-0 flex-1 basis-48')} /><Button type="submit" disabled={disabled}>按这句补全</Button></div>
      {error && <p role="alert" className="mt-1 text-sm text-seal">{error}</p>}
    </form>
  </div>
}

/** 节点是全书地图的唯一事实来源；作者编辑永不写入会议快照。 */
export function SpinePage() {
  const { book, bookId, job, outline, working, requestNodeFeedback, manualNavigate } = useBookContext()
  const location = useLocation()
  const update = useUpdateBook(bookId)
  const query = useNodes(bookId)
  const { data: chapters = [] } = useChapters(bookId)
  const bible = useBible(bookId)
  const mutations = useNodeMutations(bookId)
  const { pieceAction } = useJobActions(bookId)
  const [error, setError] = useState<unknown>(null)
  const [deleting, setDeleting] = useState<StoryNode | null>(null)
  const [inserting, setInserting] = useState<StoryNode | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [dismissedCandidates, setDismissedCandidates] = useState('')
  const spine: Spine = book.spine ?? {}
  const nodes = query.data ?? []
  const position = writingPosition(nodes, outline?.volumes ?? [], chapters)
  const complete = isWritingComplete(outline?.volumes ?? [], chapters, nodes)
  const writing = chapters.some(chapter => chapter.status === 'final')
  const setup = book.status === 'setting_up' || (job?.kind === 'book_setup' && ['queued', 'running', 'waiting_author'].includes(job.status))
  const pending = job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece' ? job.pending : null
  const canRequestNodes = !writing && setup && pending?.piece === 'segment'
  const busy = working || pieceAction.isPending || mutations.create.isPending || mutations.update.isPending || mutations.remove.isPending || mutations.reorder.isPending
  const counts = nodeCounts(nodes)
  const bands = segments(nodes, outline?.volumes ?? [])
  const candidateKey = JSON.stringify(pending?.candidates ?? null)
  const candidates = canRequestNodes && candidateKey !== dismissedCandidates ? pending?.candidates : null
  const longThreads = (bible.data?.foreshadowings ?? []).filter(item => item.span === '长').sort((a, b) => Number(b.kind === '期待') - Number(a.kind === '期待') || a.seq - b.seq)
  const save = (patch: Partial<Spine>) => update.mutateAsync({ spine: patch })
  const run = async (action: () => Promise<unknown>) => {
    if (busy) return
    setError(null)
    try { await action() } catch (cause) { setError(cause) }
  }
  const requestNode = async (node: StoryNode, action: 'fill' | 'candidates', feedback?: string) => {
    if (!job || !canRequestNodes) return
    await run(async () => { await pieceAction.mutateAsync({ jobId: job.id, action, piece: 'segment', node_id: node.id, feedback }); if (action === 'candidates') setDismissedCandidates('') })
  }
  const insertAfter = (node: StoryNode) => {
    if (canRequestNodes) void run(() => mutations.create.mutateAsync({ title: '留一个空位', status: 'empty', after_node_id: node.id, volume: node.volume }))
    else { setNewTitle(''); setInserting(node) }
  }
  const moveNode = (node: StoryNode, direction: -1 | 1) => {
    const at = nodes.findIndex(item => item.id === node.id)
    const next = at + direction
    if (node.kind !== 'milestone' || !nodes[next] || nodes[next].kind !== 'milestone') return
    const ids = nodes.map(item => item.id)
    ;[ids[at], ids[next]] = [ids[next], ids[at]]
    void run(() => mutations.reorder.mutateAsync(ids))
  }

  useEffect(() => {
    if (!location.hash.startsWith('#story-node-')) return
    const frame = requestAnimationFrame(() => {
      const target = document.getElementById(location.hash.slice(1))
      target?.scrollIntoView({ block: 'center', behavior: 'instant' })
      target?.focus({ preventScroll: true })
    })
    return () => cancelAnimationFrame(frame)
  }, [location.hash, location.key, query.data])

  if (query.isLoading) return <Skeleton className="h-64" />
  if (query.isError) return <div><ErrorText error={query.error} /><Button variant="soft" onClick={() => void query.refetch()}>重新加载节点</Button></div>

  return <div data-testid="story-puzzle-board">
    <PieceDecisions piece="segment" />
    <PageHeader eyebrow="全书地图" title={setup && book.setup_progress?.pieces?.segment !== 'confirmed' ? '第一段' : '从开篇到结局'} subtitle={<><span className="block" data-testid="node-counts">{counts.total} 个节点 · {counts.pinned} 铁钉 · {counts.pencil} 暂定 · {counts.empty} 留空</span><span className="mt-1 block text-sm">先钉住故事的重要转折，再把人物与每一卷放到合适的位置。</span></>} />
    {writing && <div className="mb-8 border-b border-line pb-6"><StoryMapStrip nodes={nodes} volumes={outline?.volumes ?? []} chapters={chapters} onNodeSelect={node => manualNavigate(`/books/${bookId}/spine#story-node-${node.id}`)} /></div>}
    <Locked locked={working} />
    <ErrorText error={error} />
    {!nodes.length ? <p className="py-8 text-sm leading-relaxed text-ink-2">{setup ? '主编还在准备关键节点。新产出会先以只读稿展示，保存后就能在这里钉节点、改文字。' : '这本书尚未建立关键节点，原有书稿和续写不受影响。'}</p> : <>
      <Reveal><section className="mb-8 grid gap-6 border-b border-line pb-8 @2xl/manuscript:grid-cols-3">
        <FieldBlock label="核心矛盾"><EditableText value={spine.core_conflict ?? ''} onSave={core_conflict => save({ core_conflict })} locked={busy} multiline /></FieldBlock>
        <FieldBlock label="主角成长弧"><EditableText value={spine.protagonist_arc ?? ''} onSave={protagonist_arc => save({ protagonist_arc })} locked={busy} multiline /></FieldBlock>
        <FieldBlock label="主题"><EditableText value={spine.theme ?? ''} onSave={theme => save({ theme })} locked={busy} multiline className="font-serif" /></FieldBlock>
      </section></Reveal>
      {bands.filter(band => !band.from).map((band, i) => <div className="mb-4 pl-10" key={`before-${i}`}><SegmentBand {...band} position={position} complete={complete} /></div>)}
      {nodes.map((node, i) => <Reveal key={node.id} delay={Math.min(i * 0.025, 0.2)} className={clsx('relative pl-10', i < nodes.length - 1 && 'pb-6')}>
        {i < nodes.length - 1 && <span aria-hidden className="absolute top-6 bottom-0 left-[15px] w-px bg-line-2" />}
        <span className="absolute top-4 left-0"><NodeMarker node={node} passed={position.passed.includes(node.id)} /></span>
        <div id={`story-node-${node.id}`} tabIndex={-1} className="scroll-mt-6 rounded-xl focus-visible:outline-2 focus-visible:outline-seal" data-testid={`story-node-${node.id}`} data-node-status={node.status} data-passed={position.passed.includes(node.id)}>
          <Card className={clsx('p-4 @lg/manuscript:p-5', node.status === 'empty' && '!border-2 !border-dotted !border-line-2 !bg-paper/50 !shadow-none', node.status === 'pinned' && '!border-seal/30')}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 text-xs text-ink-2"><span>节点 {node.index}{node.kind === 'opening' ? ' · 开篇' : node.kind === 'ending' ? ' · 结局' : ''}</span>{position.passed.includes(node.id) && <span className="inline-flex items-center gap-1 text-seal"><Check className="size-3.5" />已写到</span>}<span className={node.status === 'pinned' ? 'text-seal' : node.status === 'pencil' ? 'text-chief' : 'text-ink-2'}>{NODE_STATUS[node.status]}</span></div>
            {node.updated_by_volume != null && <p className="mb-3 text-xs text-ink-2">第 {node.updated_by_volume} 卷拆卷纲时调整过</p>}
            <div className="mb-3"><EditableText value={node.title} onSave={title => mutations.update.mutateAsync({ id: node.id, title })} locked={busy} placeholder="（未命名节点）" className="font-serif text-lg font-bold" /></div>
            <div className="mb-4 flex items-center gap-1.5 text-xs text-ink-2"><span>约第</span><EditableText value={node.volume == null ? '' : String(node.volume)} placeholder="待定" locked={busy} onSave={value => { const volume = value.trim() ? Number(value) : null; if (volume != null && (!Number.isInteger(volume) || volume < 1)) return Promise.reject(new Error('卷数请填大于 0 的整数')); return mutations.update.mutateAsync({ id: node.id, volume }) }} /><span>卷</span></div>
            <FieldBlock label="发生什么"><EditableText value={node.event} onSave={event => mutations.update.mutateAsync({ id: node.id, event })} locked={busy} multiline placeholder={node.status === 'empty' ? '把这段故事先留给想象' : '（未定）'} /></FieldBlock>
            <div className="mt-4 grid gap-3 border-t border-line pt-3">
              <FieldBlock label="之前得先有"><EditableText value={node.prerequisite} onSave={prerequisite => mutations.update.mutateAsync({ id: node.id, prerequisite })} locked={busy} multiline className="text-ink-2" /></FieldBlock>
              <FieldBlock label="之后变成"><EditableText value={node.consequence} onSave={consequence => mutations.update.mutateAsync({ id: node.id, consequence })} locked={busy} multiline className="text-ink-2" /></FieldBlock>
            </div>
            {!!node.anchors?.length && <div className="mt-4 flex flex-wrap gap-2">{node.anchors.map(anchor => <span key={anchor.id} tabIndex={0} className="group/anchor relative rounded-full bg-lore-soft px-2.5 py-1 text-xs text-lore focus-visible:outline-2 focus-visible:outline-lore" title={anchor.note}>{anchor.character_name} · {anchor.kind}{anchor.note && <span role="tooltip" className="pointer-events-none absolute bottom-full left-0 z-10 mb-2 hidden w-56 rounded-lg border border-line-2 bg-card p-3 text-xs leading-relaxed text-ink shadow-[var(--shadow-paper)] group-hover/anchor:block group-focus/anchor:block">{anchor.note}</span>}</span>)}</div>}
            <div className="mt-4 border-t border-line pt-3 text-xs text-ink-2"><p className="mb-1">批注</p><EditableText value={node.editor_note} onSave={editor_note => mutations.update.mutateAsync({ id: node.id, editor_note })} locked={busy} multiline placeholder="（暂无批注）" className="text-xs" />{!!node.techniques?.length && <div className="mt-2 flex flex-wrap gap-1.5">{node.techniques.map(name => <TechniqueChip key={name} name={name} />)}</div>}</div>
            {!writing && canRequestNodes && node.status === 'empty' && <><EmptyNodeForm disabled={busy} onFill={feedback => requestNode(node, 'fill', feedback)} onCandidates={() => void requestNode(node, 'candidates')} /></>}
            <div className="mt-4 flex flex-wrap items-center gap-1 border-t border-line pt-2">
              {node.status !== 'empty' && <NodeAction label={`${node.status === 'pinned' ? '改暂定' : '钉死'}节点 ${node.index}`} disabled={busy} onClick={() => void run(() => mutations.update.mutateAsync({ id: node.id, status: node.status === 'pinned' ? 'pencil' : 'pinned' }))}>{node.status === 'pinned' ? <PinOff className="size-4" /> : <Pin className="size-4" />}</NodeAction>}
              <NodeAction label={`改节点 ${node.index}「${node.title}」`} disabled={busy} onClick={() => requestNodeFeedback(node)}><MessageSquare className="size-4" /></NodeAction>
              {canRequestNodes && node.status !== 'empty' && <NodeAction label={`换候选：节点 ${node.index}`} disabled={busy} onClick={() => void requestNode(node, 'candidates')}><Shuffle className="size-4" /></NodeAction>}
              {node.kind !== 'ending' && <NodeAction label={`在节点 ${node.index} 下面插入`} disabled={busy} onClick={() => insertAfter(node)}><Plus className="size-4" /></NodeAction>}
              {node.kind === 'milestone' && <>
                <NodeAction label={`上移节点 ${node.index}`} disabled={busy || nodes[i - 1]?.kind !== 'milestone'} onClick={() => moveNode(node, -1)}><ArrowUp className="size-4" /></NodeAction>
                <NodeAction label={`下移节点 ${node.index}`} disabled={busy || nodes[i + 1]?.kind !== 'milestone'} onClick={() => moveNode(node, 1)}><ArrowDown className="size-4" /></NodeAction>
                <NodeAction label={`删除节点 ${node.index}`} disabled={busy} onClick={() => setDeleting(node)}><Trash2 className="size-4" /></NodeAction>
              </>}
            </div>
          </Card>
          {candidates?.node_id === node.id && <section className="mt-3 space-y-3 rounded-xl border border-chief/25 bg-chief-soft/25 p-3" aria-label={`节点 ${node.index} 的候选`}>
            <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-medium text-chief">换一个走向</h3><Button type="button" size="sm" variant="ghost" onClick={() => setDismissedCandidates(candidateKey)}>都不要</Button></div>
            {candidates.nodes.map((candidate, candidateIndex) => <CandidateCard key={candidateIndex} candidate={candidate} busy={busy} onChoose={() => void run(async () => { await mutations.update.mutateAsync({ id: node.id, title: candidate.title, event: candidate.event, prerequisite: candidate.prerequisite, consequence: candidate.consequence, volume: candidate.volume, status: node.status === 'empty' ? 'pencil' : node.status }); setDismissedCandidates(candidateKey) })} />)}
          </section>}
        </div>
        {bands.filter(band => band.from?.id === node.id).map((band, bandIndex) => <SegmentBand key={bandIndex} {...band} position={position} complete={complete} />)}
      </Reveal>)}
    </>}
    {!!outline?.volumes.length && <details className="group mt-8 border-t border-line pt-5" data-testid="long-story-threads"><summary className="flex cursor-pointer list-none items-center gap-2 font-serif text-lg font-bold"><ChevronDown className="size-4 transition-transform group-open:rotate-180 motion-reduce:transition-none" />长线伏笔与期待<span className="font-sans text-xs font-normal text-ink-2">{longThreads.length} 条</span></summary><div className="mt-4 space-y-3">{longThreads.map(item => <div key={item.id} className="rounded-lg border border-line bg-card p-3 text-sm leading-relaxed"><p><span className={clsx('mr-2 font-medium', item.kind === '期待' ? 'text-chief' : 'text-lore')}>{item.code}</span>{item.description}</p><p className="mt-1 text-xs text-ink-2">{item.kind === '期待' ? '立下' : '埋下'}：{item.plant_volume ? `第 ${item.plant_volume} 卷` : '待定'} → {item.kind === '期待' ? '兑现' : '回收'}：{item.payoff_volume ? `第 ${item.payoff_volume} 卷` : '待定'}</p></div>)}{!longThreads.length && <p className="text-sm text-ink-2">暂时没有长线伏笔与期待。</p>}<ErrorText error={bible.error} /></div></details>}
    <Modal open={!!deleting} onClose={() => !busy && setDeleting(null)} title="删除这个节点？" footer={<><Button onClick={() => setDeleting(null)} disabled={busy}>保留</Button><Button variant="danger" loading={mutations.remove.isPending} disabled={busy} onClick={() => deleting && void run(async () => { await mutations.remove.mutateAsync(deleting.id); setDeleting(null) })}>确认删除</Button></>}><p className="text-sm leading-relaxed text-ink-2">将删除「{deleting?.title}」及它的人物锚点，相关卷和信息差会解除对这个节点的关联。此操作无法撤销。</p><ErrorText error={error} /></Modal>
    <Modal open={!!inserting} onClose={() => !busy && setInserting(null)} title="插入一个铁钉节点" footer={<><Button onClick={() => setInserting(null)} disabled={busy}>取消</Button><Button variant="seal" disabled={busy || !newTitle.trim()} loading={mutations.create.isPending} onClick={() => inserting && void run(async () => { await mutations.create.mutateAsync({ title: newTitle.trim(), status: 'pinned', after_node_id: inserting.id, volume: inserting.volume }); setInserting(null) })}>添加节点</Button></>}><label className="mb-2 block text-sm text-ink-2" htmlFor="new-node-title">{book.status === 'awaiting_approval' ? '一口气方案已生成；此时亲手新增的节点是铁钉，不再留空。' : '你亲手加的节点默认是铁钉。'}</label><input id="new-node-title" autoFocus maxLength={100} value={newTitle} onChange={event => setNewTitle(event.target.value)} className={inputClass} placeholder="给节点起个名字" /><ErrorText error={error} /></Modal>
  </div>
}
