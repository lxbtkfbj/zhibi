import clsx from 'clsx'
import { ChevronDown, ChevronRight, Lock, Plus, Unlock } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useChapters } from '../../../api/hooks'
import { useOutlineChanges, useOutlineTree } from '../../../api/outline'
import { RewriteField, TargetHistory } from '../../../components/RewriteField'
import { Button, Card, ErrorText, inputClass, Modal, Skeleton } from '../../../components/ui'
import { arcStarted, arcText, buildOutlineTree, defaultOutlineExpanded, flattenOutline, isLaterEnding, outlineAncestors, outlineRange, outlineStatusText, unitStarted, volumeStarted, type OutlineItem } from '../../../lib/outlineTree'
import { useBookContext } from '../context'
import { SetupGate } from '../SetupGate'
import { PageHeader } from './common'
import { SpinePage } from './SpinePage'
import { ThreadsPage } from './ThreadsPage'

type EditableNode = Extract<OutlineItem, { kind: 'segment' | 'volume' | 'unit' }>
type Form = { kind: 'edit' | 'add-unit' | 'add-volume' | 'ending'; title: string; text: string; count: string }

function TreeRow({ item, selected, expanded, toggle, select, depth = 0 }: { item: OutlineItem; selected: string; expanded: Set<string>; toggle: (key: string) => void; select: (key: string) => void; depth?: number }) {
  const open = expanded.has(item.key)
  return <li role="treeitem" aria-selected={selected === item.key} aria-expanded={item.children.length ? open : undefined}>
    <div className={clsx('flex min-w-0 items-start rounded-lg py-1', selected === item.key ? 'bg-seal-soft' : item.status === 'writing' || item.status === 'drafting' ? 'bg-chief-soft/50' : 'hover:bg-paper-2')} style={{ paddingLeft: `${depth * 12}px` }}>
      <button type="button" className="mt-1.5 flex size-6 shrink-0 items-center justify-center text-ink-2 disabled:invisible" disabled={!item.children.length} aria-label={`${open ? '收起' : '展开'}${item.name}`} onClick={() => toggle(item.key)}>{open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}</button>
      <button type="button" className="min-w-0 flex-1 py-1.5 pr-2 text-left" onClick={() => select(item.key)} data-testid={`outline-node-${item.key}`}>
        <span className={clsx('block break-words text-sm', selected === item.key && 'font-semibold text-seal')}>{item.name}{item.locked && <Lock className="ml-1 inline size-3" aria-label="已锁住" />}</span>
        {item.kind !== 'book' && <span className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-ink-2"><span>{outlineRange(item)}</span><span className={clsx(item.status === 'writing' || item.status === 'drafting' ? 'font-medium text-chief' : '')}>{outlineStatusText(item.status)}</span></span>}
      </button>
    </div>
    {open && item.children.length > 0 && <ul role="group">{item.children.map(child => <TreeRow key={child.key} item={child} selected={selected} expanded={expanded} toggle={toggle} select={select} depth={depth + 1} />)}</ul>}
  </li>
}

function ChapterDetail({ item }: { item: Extract<OutlineItem, { kind: 'chapter' }> }) {
  const { bookId, manualNavigate } = useBookContext()
  const chapters = useChapters(bookId, item.volume.index)
  const chapter = chapters.data?.find(chapter => chapter.index === item.chapter.index)
  const outline = chapter?.outline
  return <section className="space-y-5" data-testid="outline-chapter-detail">
    <h2 className="font-serif text-xl font-bold">{item.name}</h2>
    <p className="text-xs text-ink-2">章纲 · {outlineStatusText(item.status)}</p>
    {chapters.isLoading ? <Skeleton className="h-40" /> : <>{[['要完成的剧情', outline?.goal], ['场景', outline?.scenes?.join('\n')], ['爽点', outline?.cool_point], ['钩子', outline?.hook]].map(([label, value]) => <div key={label}><h3 className="mb-2 text-xs text-ink-2">{label}</h3><p className="whitespace-pre-wrap text-sm leading-7">{value || '（还没写）'}</p></div>)}</>}
    <ErrorText error={chapters.error} />
    {item.chapter.status === 'final' && <Button variant="soft" onClick={() => manualNavigate(`/books/${bookId}/chapter/${item.chapter.index}`)}>去看正文</Button>}
  </section>
}

function OutlineDetail({ item, select, afterVolumeId }: { item: OutlineItem; select: (key: string) => void; afterVolumeId: string | null }) {
  const { bookId, book, working } = useBookContext()
  const change = useOutlineChanges(bookId)
  const [form, setForm] = useState<Form | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [count, setCount] = useState<string | null>(null)
  const [error, setError] = useState<unknown>(null)
  const busy = working || change.isPending
  const run = async (action: () => Promise<unknown>) => { setError(null); try { await action() } catch (cause) { setError(cause) } }
  if (item.kind === 'chapter') return <ChapterDetail item={item} />
  if (item.kind === 'book') return <section><h2 className="font-serif text-2xl font-bold">{book.title}</h2><p className="mt-4 whitespace-pre-wrap text-[15px] leading-8">{book.concept.story || book.concept.logline || '从左边选一篇，看看故事从哪里走向哪里。'}</p><p className="mt-5 text-xs leading-6 text-ink-2">从篇到卷，再到单元和章纲。先看眼前要写的部分，后面的写到再定。</p></section>
  const node: EditableNode | null = item.kind === 'ending' ? null : item
  const started = node?.kind === 'segment' ? arcStarted(node.arc) : node?.kind === 'volume' ? volumeStarted(node.volume) : node?.kind === 'unit' ? unitStarted(node.unit) : false
  const id = node?.kind === 'segment' ? node.arc.node_id : node?.kind === 'volume' ? node.volume.id : node?.kind === 'unit' ? node.unit.id : null
  const value = node?.kind === 'segment' ? arcText(node.arc) : node?.kind === 'volume' ? node.volume.summary : node?.kind === 'unit' ? node.unit.summary : ''
  const title = node?.kind === 'segment' ? node.arc.title : node?.kind === 'volume' ? node.volume.title : node?.kind === 'unit' ? node.unit.title : ''
  const laterEnding = node?.kind === 'segment' && isLaterEnding(node.arc)
  const notPlanned = node?.kind === 'segment' && !node.arc.planned
  const editable = !!id && !started && !notPlanned
  const ownCount = node?.kind === 'volume' ? node.volume.chapter_count : node?.kind === 'unit' ? node.unit.chapter_count : null
  const patchNode = (body: Record<string, unknown>) => id && node ? change.mutateAsync({ action: 'patch', kind: node.kind, id, body }) : Promise.resolve()
  const addForm = (kind: 'add-unit' | 'add-volume') => setForm({ kind, title: '', text: '', count: kind === 'add-unit' ? '3' : '30' })
  const reorder = (direction: -1 | 1) => {
    if (node?.kind !== 'unit') return
    const ids = node.volume.units.map(unit => unit.id)
    const index = ids.indexOf(node.unit.id)
    const next = index + direction
    if (next < 0 || next >= ids.length) return
    ;[ids[index], ids[next]] = [ids[next], ids[index]]
    void run(() => change.mutateAsync({ action: 'order-units', volumeId: node.volume.id, ids }))
  }
  const saveForm = async () => {
    if (!form) return
    const chapterCount = Number(form.count)
    if (['add-unit', 'add-volume'].includes(form.kind) && (!Number.isInteger(chapterCount) || chapterCount < 1)) throw new Error('章数请填大于 0 的整数')
    if (form.kind === 'ending' && item.kind === 'ending') await change.mutateAsync({ action: 'patch', kind: 'ending', id: item.ending.node_id, body: { event: form.text } })
    else if (form.kind === 'edit' && node) await patchNode({ title: form.title, [node.kind === 'segment' ? 'text' : 'summary']: form.text })
    else if (form.kind === 'add-unit' && node && 'volume' in node) {
      const result = await change.mutateAsync({ action: 'add-unit', volumeId: node.volume.id, title: form.title, summary: form.text, chapter_count: chapterCount, after_unit_id: node.kind === 'unit' ? node.unit.id : node.volume.units.at(-1)?.id ?? null }) as { id: string }
      select(`unit-${result.id}`)
    } else if (form.kind === 'add-volume' && node?.kind === 'segment') {
      const result = await change.mutateAsync({ action: 'add-volume', title: form.title, summary: form.text, chapter_count: chapterCount, target_node_id: node.arc.node_id, after_volume_id: afterVolumeId }) as { index: number }
      select(`volume-${result.index}`)
    }
    setForm(null)
  }
  return <section className="space-y-5" data-testid="outline-detail">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-serif text-xl leading-relaxed font-bold">{item.name}</h2><p className="mt-2 text-xs text-ink-2">{outlineStatusText(item.status)}{outlineRange(item) && ` · ${outlineRange(item)}`}</p></div>
      <div className="flex flex-wrap gap-1.5">
        {editable && <><Button size="sm" variant="soft" disabled={busy} onClick={() => setForm({ kind: 'edit', title, text: value, count: '' })}>自己改</Button><Button size="sm" disabled={busy} onClick={() => void run(() => node?.kind === 'segment' ? change.mutateAsync({ action: 'patch', kind: 'ending', id: id!, body: { status: item.locked ? 'pencil' : 'pinned' } }) : patchNode({ locked: !item.locked }))}>{item.locked ? <Unlock className="size-3.5" /> : <Lock className="size-3.5" />}{item.locked ? '解锁' : '锁住'}</Button></>}
        {id && node && <TargetHistory bookId={bookId} targetType={node.kind} targetId={id} disabled={started || busy} />}
        {item.kind === 'ending' && <Button size="sm" disabled={busy} onClick={() => setForm({ kind: 'ending', title: '', text: item.ending.event, count: '' })}>自己改</Button>}
      </div>
    </div>
    <ErrorText error={error} />
    {item.kind === 'ending' ? <p className="whitespace-pre-wrap text-[15px] leading-8">{item.ending.event || '（还没写结局）'}</p> : <>
      {started && <p className="rounded-lg bg-paper-2 px-3 py-2 text-xs leading-6 text-ink-2">这里已经开写，只能查看；还没写的内容仍可在下方节点里修改。</p>}
      {notPlanned ? <><p className="text-sm leading-7 text-ink-2">写到再定 · 写到这里之前，主编会先来定下一篇</p>{!laterEnding && value && <p className="whitespace-pre-wrap text-sm leading-7">{value}</p>}</> : editable && id && node ? <RewriteField bookId={bookId} targetType={node.kind} targetId={id} path={node.kind === 'segment' ? 'text' : 'summary'} value={value} locked={item.locked} disabled={busy} label="一段话" optionsOnly /> : <p className="whitespace-pre-wrap text-[15px] leading-8">{value || '（还没写一段话）'}</p>}
      {editable && ownCount != null && <form className="flex flex-wrap items-end gap-3 border-t border-line pt-4" onSubmit={event => { event.preventDefault(); const amount = Number(count ?? ownCount); void run(async () => { if (!Number.isInteger(amount) || amount < 1) throw new Error('章数请填大于 0 的整数'); await patchNode({ chapter_count: amount }); setCount(null) }) }}><label className="space-y-1 text-xs text-ink-2"><span className="block">章数</span><input aria-label="章数" className={`${inputClass} !w-24`} type="number" min="1" value={count ?? ownCount} disabled={busy} onChange={event => setCount(event.target.value)} /></label><Button type="submit" size="sm" disabled={busy || count === null}>改章数</Button>{node?.kind === 'volume' && node.volume.units.length > 0 && <span className="pb-2 text-xs text-ink-2">已拆成单元，实际章数按各单元相加。</span>}</form>}
      {node?.kind === 'volume' && !node.volume.units.length && <p className="rounded-lg border border-dashed border-line-2 p-3 text-xs leading-6 text-ink-2">这一卷还没拆成单元。想要的情节写进这一卷的一段话，写到这一卷时主编会照着拆。</p>}
      {!!id && !started && <div className="flex flex-wrap gap-2 border-t border-line pt-4">
        {node?.kind === 'segment' && <Button size="sm" disabled={busy} onClick={() => addForm('add-volume')}><Plus className="size-3.5" />加一卷</Button>}
        {node?.kind === 'volume' && node.volume.units.length > 0 && <Button size="sm" disabled={busy} onClick={() => addForm('add-unit')}><Plus className="size-3.5" />加一个单元</Button>}
        {(node?.kind === 'unit' || node?.kind === 'volume') && <details className="relative"><summary className="cursor-pointer rounded-md border border-line px-3 py-1.5 text-xs">更多</summary><div className="absolute right-0 z-10 mt-2 flex min-w-40 flex-col gap-1 rounded-lg border border-line bg-card p-2 shadow-[var(--shadow-paper)]">{node.kind === 'unit' && <><Button size="sm" variant="ghost" disabled={busy} onClick={() => addForm('add-unit')}>在后面加一个单元</Button><Button size="sm" variant="ghost" disabled={busy || node.volume.units[0]?.id === node.unit.id || unitStarted(node.volume.units[node.volume.units.findIndex(unit => unit.id === node.unit.id) - 1])} onClick={() => reorder(-1)}>上移</Button><Button size="sm" variant="ghost" disabled={busy || node.volume.units.at(-1)?.id === node.unit.id} onClick={() => reorder(1)}>下移</Button></>}<Button size="sm" variant="ghost" disabled={busy} className="text-seal" onClick={() => setDeleting(true)}>{node.kind === 'unit' ? '删掉这个单元' : '删掉这一卷'}</Button></div></details>}
      </div>}
    </>}
    <Modal open={!!form} onClose={() => !busy && setForm(null)} title={form?.kind === 'add-unit' ? '加一个单元' : form?.kind === 'add-volume' ? '加一卷' : form?.kind === 'ending' ? '修改结局' : '自己改'} footer={<><Button disabled={busy} onClick={() => setForm(null)}>取消</Button><Button variant="seal" disabled={busy || (!!form && form.kind !== 'ending' && !form.title.trim())} loading={change.isPending} onClick={() => void run(saveForm)}>保存</Button></>}>
      {form && <div className="space-y-4">{form.kind !== 'ending' && <label className="block space-y-2 text-sm"><span>名称</span><input autoFocus value={form.title} className={inputClass} onChange={event => setForm({ ...form, title: event.target.value })} /></label>}<label className="block space-y-2 text-sm"><span>{form.kind === 'ending' ? '结局' : '一段话'}</span><textarea rows={6} value={form.text} className={inputClass} onChange={event => setForm({ ...form, text: event.target.value })} /></label>{['add-unit', 'add-volume'].includes(form.kind) && <label className="block space-y-2 text-sm"><span>章数</span><input type="number" min="1" value={form.count} className={inputClass} onChange={event => setForm({ ...form, count: event.target.value })} /></label>}<ErrorText error={error} /></div>}
    </Modal>
    <Modal open={deleting} onClose={() => !busy && setDeleting(false)} title={node?.kind === 'unit' ? '删掉这个单元？' : '删掉这一卷？'} footer={<><Button disabled={busy} onClick={() => setDeleting(false)}>保留</Button><Button variant="danger" disabled={busy} loading={change.isPending} onClick={() => void run(async () => { if (node?.kind === 'unit') { await change.mutateAsync({ action: 'remove-unit', id: node.unit.id }); select(`volume-${node.volume.index}`) } else if (node?.kind === 'volume') { await change.mutateAsync({ action: 'remove-volume', id: node.volume.id }); select(`segment-${node.arc.node_id ?? 1}`) } setDeleting(false) })}>确认删除</Button></>}><p className="text-sm leading-7">将删除「{item.name}」和下面尚未开写的章纲，后面的章号会顺延。已经开写的内容不能删除。</p><ErrorText error={error} /></Modal>
  </section>
}

export function OutlinePage() {
  const { bookId, book, manualNavigate } = useBookContext()
  const [params] = useSearchParams()
  const query = useOutlineTree(bookId)
  const [expanded, setExpanded] = useState<Set<string> | null>(null)
  const [mobileDetail, setMobileDetail] = useState(() => !!params.get('node') && params.get('node') !== 'first-arc')
  const view = params.get('view') ?? 'tree'
  const root = query.data ? buildOutlineTree(query.data, book.title) : null
  const items = root ? flattenOutline(root) : []
  const requested = params.get('node')
  const selected = (requested === 'first-arc' ? root?.children.find(item => item.kind === 'segment') : items.find(item => item.key === requested)) ?? root?.children.find(item => item.kind === 'segment' && item.status === 'writing') ?? root?.children[0] ?? root
  const arcIndex = selected?.kind === 'segment' ? query.data?.arcs.indexOf(selected.arc) ?? -1 : -1
  const afterVolumeId = query.data?.arcs.slice(0, arcIndex + 1).flatMap(arc => arc.volumes).at(-1)?.id ?? null
  const open = expanded ?? new Set(root ? [...defaultOutlineExpanded(root), ...(requested && selected ? outlineAncestors(root, selected.key) : [])] : [])
  const select = (key: string) => {
    if (root) setExpanded(new Set([...open, ...outlineAncestors(root, key)]))
    setMobileDetail(true)
    manualNavigate(`/books/${bookId}/outline?view=tree&node=${encodeURIComponent(key)}`)
  }
  return <div data-testid="outline-page">
    <PageHeader eyebrow="书稿" title="大纲" subtitle="先看眼前要写的，再慢慢走向结局。" />
    <div className="mb-6 flex gap-2 border-b border-line pb-4" aria-label="大纲看法">{([['tree', '树'], ['map', '地图'], ['threads', '线索']] as const).map(([key, label]) => <Button key={key} variant={view === key ? 'seal' : 'ghost'} size="sm" onClick={() => manualNavigate(`/books/${bookId}/outline?view=${key}${requested ? `&node=${encodeURIComponent(requested)}` : ''}`)}>{label}</Button>)}</div>
    {view === 'map' ? <SpinePage /> : view === 'threads' ? <ThreadsPage /> : query.isLoading ? <Skeleton className="h-64" /> : query.isError ? <><ErrorText error={query.error} /><Button onClick={() => void query.refetch()}>重新加载大纲</Button></> : root && selected ? <div className="grid min-w-0 gap-5 min-[769px]:grid-cols-[minmax(160px,0.85fr)_minmax(0,1.7fr)]">
      <Card className={clsx('min-w-0 self-start p-2', mobileDetail && 'max-[768px]:hidden')}><ul role="tree" aria-label="全书大纲树"><TreeRow item={root} selected={selected.key} expanded={open} toggle={key => setExpanded(() => { const next = new Set(open); if (next.has(key)) next.delete(key); else next.add(key); return next })} select={select} /></ul></Card>
      <Card className={clsx('min-w-0 p-4 @lg/manuscript:p-5', !mobileDetail && 'max-[768px]:hidden')}><Button size="sm" variant="ghost" className="mb-4 min-[769px]:hidden" onClick={() => setMobileDetail(false)}>返回树</Button><OutlineDetail key={selected.key} item={selected} select={select} afterVolumeId={afterVolumeId} /></Card>
    </div> : <p className="text-sm text-ink-2">主编还在准备大纲，完成后会出现在这里。</p>}
    <SetupGate piece="outline" />
  </div>
}
