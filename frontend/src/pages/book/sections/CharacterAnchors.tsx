import clsx from 'clsx'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useAnchorMutations, useNodes } from '../../../api/hooks'
import type { NodeAnchor } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Button, ErrorText, inputClass } from '../../../components/ui'
import { useBookContext } from '../context'

const KINDS: NodeAnchor['kind'][] = ['登场', '确认关系', '翻脸', '高光', '退场', '其他']

function AnchorKinds({ value, onChange, disabled }: { value: NodeAnchor['kind']; onChange: (kind: NodeAnchor['kind']) => void; disabled: boolean }) {
  return <div role="group" aria-label="锚点类型" className="flex flex-wrap gap-1 rounded-lg bg-paper p-1">
    {KINDS.map(kind => <button key={kind} type="button" aria-pressed={value === kind} disabled={disabled} onClick={() => onChange(kind)} className={clsx('rounded-md px-2.5 py-1.5 text-xs disabled:cursor-not-allowed', value === kind ? 'bg-card text-chief shadow-sm ring-1 ring-line' : 'text-ink-2 hover:bg-card/60')}>{kind}</button>)}
  </div>
}

/** 锚点从节点接口读取，人物卡与全书地图共享同一份事实。 */
export function CharacterAnchors({ characterId }: { characterId: string }) {
  const { bookId, working } = useBookContext()
  const nodes = useNodes(bookId)
  const { create, update, remove } = useAnchorMutations(bookId)
  const [adding, setAdding] = useState(false)
  const [nodeId, setNodeId] = useState('')
  const [kind, setKind] = useState<NodeAnchor['kind']>('登场')
  const [note, setNote] = useState('')
  const anchors = (nodes.data ?? []).flatMap(node => node.anchors.filter(anchor => anchor.character_id === characterId).map(anchor => ({ ...anchor, node })))
  const busy = working || create.isPending || update.isPending || remove.isPending
  const options = (nodes.data ?? []).map(node => <option key={node.id} value={node.id}>节点 {node.index}「{node.title || '留空'}」</option>)

  return <section className="space-y-3 border-t border-line pt-5">
    <div className="flex items-center justify-between gap-2">
      <h3 className="font-serif text-lg font-bold">人物上轴</h3>
      {!working && <Button size="sm" variant="soft" disabled={busy || !nodes.data?.length} onClick={() => { setNodeId(nodes.data?.[0]?.id ?? ''); setAdding(true) }}><Plus className="size-3.5" />添加锚点</Button>}
    </div>
    {!nodes.isLoading && !anchors.length && <p className="text-sm text-ink-2">还没有锚点。把人物的重要变化放到全书地图上。</p>}
    {anchors.map(anchor => <div key={anchor.id} className="space-y-3 rounded-xl border border-line bg-paper/60 p-3">
      <div className="flex items-center gap-2">
        <select aria-label={`${anchor.character_name}的锚点节点`} className={clsx(inputClass, 'min-w-0 flex-1')} value={anchor.node_id} disabled={busy} onChange={event => update.mutate({ id: anchor.id, node_id: event.target.value })}>{options}</select>
        {!working && <button type="button" title="删除锚点" aria-label={`删除节点 ${anchor.node.index} 的${anchor.kind}锚点`} disabled={busy} className="rounded-md p-2 text-ink-2 hover:bg-seal-soft hover:text-seal disabled:opacity-50" onClick={() => { if (confirm(`删除节点 ${anchor.node.index}「${anchor.node.title}」上的${anchor.kind}锚点？`)) remove.mutate(anchor.id) }}><Trash2 className="size-4" /></button>}
      </div>
      <AnchorKinds value={anchor.kind} disabled={busy} onChange={kind => update.mutate({ id: anchor.id, kind })} />
      <EditableText value={anchor.note} onSave={note => update.mutateAsync({ id: anchor.id, note })} locked={busy} multiline className="text-sm" placeholder="补充这个节点上发生的变化" />
    </div>)}
    {adding && !working && <form className="space-y-3 rounded-xl border border-chief/30 bg-chief-soft/40 p-3" onSubmit={event => {
      event.preventDefault()
      if (!nodeId || busy) return
      create.mutate({ character_id: characterId, node_id: nodeId, kind, note }, { onSuccess: () => { setAdding(false); setNote('') } })
    }}>
      <label className="block text-xs text-ink-2">放在哪个节点<select aria-label="新锚点节点" className={clsx(inputClass, 'mt-1 w-full')} value={nodeId} disabled={busy} onChange={event => setNodeId(event.target.value)}>{options}</select></label>
      <AnchorKinds value={kind} onChange={setKind} disabled={busy} />
      <textarea aria-label="新锚点说明" value={note} onChange={event => setNote(event.target.value)} disabled={busy} placeholder="说明这个节点上的变化" rows={2} className={clsx(inputClass, 'w-full resize-y')} />
      <div className="flex gap-2"><Button type="submit" size="sm" variant="primary" disabled={!nodeId || busy} loading={create.isPending}>添加</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setAdding(false)}>取消</Button></div>
    </form>}
    <ErrorText error={nodes.error ?? create.error ?? update.error ?? remove.error} />
  </section>
}
