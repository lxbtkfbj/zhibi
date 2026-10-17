import clsx from 'clsx'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useBible, useNodes, useSecretMutations, useSecrets } from '../../../api/hooks'
import type { Character, Secret, StoryNode } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Badge, Button, Card, ErrorText, inputClass, Skeleton } from '../../../components/ui'
import { useBookContext } from '../context'
import { FieldBlock, Locked, PageHeader } from './common'

type Knower = Secret['knowers'][number]

function KnowerForm({ value, names, busy, onSave, onCancel }: { value: Knower; names: string[]; busy: boolean; onSave: (knower: Knower) => void; onCancel: () => void }) {
  const [name, setName] = useState(value.name || names[0] || '')
  const [chapter, setChapter] = useState(value.since_chapter?.toString() ?? '')
  const [how, setHow] = useState(value.how)
  return <form className="mt-3 space-y-3 rounded-xl border border-line bg-paper p-3" onSubmit={event => {
    event.preventDefault()
    if (!name || busy) return
    onSave({ name, since_chapter: chapter ? Number(chapter) : null, how })
  }}>
    <div className="flex flex-wrap gap-3">
      <label className="min-w-28 flex-1 text-xs text-ink-2">谁知道<select aria-label="知情人" value={name} disabled={busy} onChange={event => setName(event.target.value)} className={clsx(inputClass, 'mt-1 w-full')} required>{names.map(person => <option key={person}>{person}</option>)}</select></label>
      <label className="min-w-28 flex-1 text-xs text-ink-2">从第几章知道<input aria-label="知情章节" type="number" min="1" step="1" value={chapter} disabled={busy} onChange={event => setChapter(event.target.value)} placeholder="留空表示开书时" className={clsx(inputClass, 'mt-1 w-full')} /></label>
    </div>
    <label className="block text-xs text-ink-2">怎么知道的<textarea aria-label="知情方式" value={how} disabled={busy} onChange={event => setHow(event.target.value)} rows={2} className={clsx(inputClass, 'mt-1 w-full resize-y')} /></label>
    <div className="flex gap-2"><Button type="submit" variant="primary" size="sm" disabled={!name || busy} loading={busy}>保存知情人</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={onCancel}>取消</Button></div>
  </form>
}

export function SecretCard({ secret, characters, nodes }: { secret: Secret; characters: Character[]; nodes: StoryNode[] }) {
  const { bookId, working } = useBookContext()
  const { update, remove } = useSecretMutations(bookId)
  // -1 means a new knower; null closes the small editor.
  const [editingKnower, setEditingKnower] = useState<number | null>(null)
  const busy = working || update.isPending || remove.isPending
  const save = (patch: Partial<Secret>) => update.mutateAsync({ id: secret.id, ...patch })
  const currentKnower = editingKnower !== null && editingKnower >= 0 ? secret.knowers[editingKnower] : undefined
  const availableNames = characters.filter(character => !secret.knowers.some((knower, index) => knower.name === character.name && index !== editingKnower)).map(character => character.name)
  const hasUnknownCharacter = characters.some(character => !secret.knowers.some(knower => knower.name === character.name))
  const revealNode = nodes.find(node => node.id === secret.node_id)

  return <Card className="space-y-5 p-5 @lg/manuscript:p-6">
    <div className="flex flex-wrap items-start gap-3">
      <span className="pt-1 font-serif text-xl font-bold text-ink-2">{secret.code}</span>
      <EditableText value={secret.title} onSave={title => save({ title })} locked={busy} placeholder="给这个秘密起个短名" className="min-w-24 flex-1 font-serif text-lg font-bold" />
      {working ? <Badge tone={secret.status === 'hidden' ? 'idle' : 'ok'}>{secret.status === 'hidden' ? '隐藏' : '公开'}</Badge> : <select aria-label={`${secret.code} 状态`} value={secret.status} disabled={busy} onChange={event => update.mutate({ id: secret.id, status: event.target.value as Secret['status'] })} className="rounded-lg border border-line-2 bg-card px-2 py-1 text-xs"><option value="hidden">隐藏</option><option value="public">公开</option></select>}
      {!working && <button title="删除秘密" aria-label={`删除 ${secret.code}`} disabled={busy} onClick={() => { if (confirm(`删除秘密 ${secret.code}「${secret.title}」？`)) remove.mutate(secret.id) }} className="rounded-md p-1.5 text-ink-2 hover:bg-seal-soft hover:text-seal disabled:opacity-50"><Trash2 className="size-4" /></button>}
    </div>
    <FieldBlock label="读者知不知道">
      {working ? <span>{secret.reader_knows ?? '未标注'}</span> : <select aria-label={`${secret.code} 读者知不知道`} value={secret.reader_knows ?? ''} disabled={busy} onChange={event => update.mutate({ id: secret.id, reader_knows: (event.target.value || null) as Secret['reader_knows'] })} className={clsx(inputClass, 'w-full')}><option value="">未标注</option><option>知道</option><option>不知道</option><option>部分</option></select>}
    </FieldBlock>
    <FieldBlock label="真相"><EditableText value={secret.truth} onSave={truth => save({ truth })} locked={busy} multiline placeholder="这件事的真相是什么" /></FieldBlock>
    <section>
      <h3 className="mb-2 text-xs tracking-[0.15em] text-ink-2">知道的人</h3>
      <div className="flex flex-wrap gap-2">
        {secret.knowers.map((knower, index) => <div key={`${knower.name}-${index}`} className="inline-flex items-center rounded-full border border-line-2 bg-paper text-xs text-ink-2">
          <button type="button" title={knower.how || '尚未说明怎么知道的'} aria-label={`${knower.name}，${knower.since_chapter === null ? '开书时' : `第 ${knower.since_chapter} 章`}知道，${knower.how || '尚未说明怎么知道的'}`} disabled={busy} onClick={() => setEditingKnower(index)} className="rounded-full px-3 py-1.5 text-left hover:text-chief disabled:cursor-default">{knower.name} · {knower.since_chapter === null ? '开书时' : `第 ${knower.since_chapter} 章`}</button>
          {!working && <button type="button" title={`移除知情人${knower.name}`} aria-label={`移除知情人${knower.name}`} disabled={busy} onClick={() => { if (confirm(`将${knower.name}从知情人中移除？`)) update.mutate({ id: secret.id, knowers: secret.knowers.filter((_, i) => i !== index) }, { onSuccess: () => setEditingKnower(null) }) }} className="mr-1 rounded-full p-1 hover:text-seal disabled:opacity-50"><Trash2 className="size-3" /></button>}
        </div>)}
        {!secret.knowers.length && <p className="text-sm text-ink-3">还没有记录知情人</p>}
        {!working && <Button type="button" size="sm" variant="ghost" disabled={busy || !hasUnknownCharacter} onClick={() => setEditingKnower(-1)}><Plus className="size-3.5" />添加知情人</Button>}
      </div>
      {!characters.length && !working && <p className="mt-2 text-xs text-ink-2">先在人物页添加人物，再记录谁知道这个秘密。</p>}
      {editingKnower !== null && !working && <KnowerForm key={`${secret.id}:${editingKnower}`} value={currentKnower ?? { name: '', since_chapter: null, how: '' }} names={availableNames} busy={busy} onCancel={() => setEditingKnower(null)} onSave={knower => update.mutate({ id: secret.id, knowers: editingKnower === -1 ? [...secret.knowers, knower] : secret.knowers.map((existing, index) => index === editingKnower ? knower : existing) }, { onSuccess: () => setEditingKnower(null) })} />}
    </section>
    <FieldBlock label="计划怎么揭"><EditableText value={secret.reveal_plan} onSave={reveal_plan => save({ reveal_plan })} locked={busy} multiline placeholder="打算在什么情境下揭开" /></FieldBlock>
    <FieldBlock label="揭开节点">
      {working ? <span>{revealNode ? `节点 ${revealNode.index}「${revealNode.title}」` : '未指定'}</span> : <select aria-label={`${secret.code} 揭开节点`} value={secret.node_id ?? ''} disabled={busy} onChange={event => update.mutate({ id: secret.id, node_id: event.target.value || null })} className={clsx(inputClass, 'w-full')}><option value="">未指定</option>{nodes.map(node => <option key={node.id} value={node.id}>节点 {node.index}「{node.title || '留空'}」</option>)}</select>}
    </FieldBlock>
    <ErrorText error={update.error ?? remove.error} />
  </Card>
}

export function SecretsPage() {
  const { bookId, working } = useBookContext()
  const query = useSecrets(bookId)
  const bible = useBible(bookId)
  const nodes = useNodes(bookId)
  const { create } = useSecretMutations(bookId)
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')
  const [truth, setTruth] = useState('')
  return <div>
    <PageHeader eyebrow="设定库" title="设定库" subtitle="信息差：同一件事，谁已经知道、读者知道多少、准备什么时候揭开。" action={!working && <Button size="sm" variant="soft" disabled={create.isPending} onClick={() => setAdding(true)}><Plus className="size-4" />添加秘密</Button>} />
    <Locked locked={working} />
    {adding && !working && <form className="mb-5 space-y-3 rounded-xl border border-line bg-card p-4" onSubmit={event => {
      event.preventDefault()
      if (!title.trim() || create.isPending) return
      create.mutate({ title: title.trim(), truth }, { onSuccess: () => { setAdding(false); setTitle(''); setTruth('') } })
    }}>
      <input aria-label="新秘密短名" required maxLength={100} value={title} disabled={create.isPending} onChange={event => setTitle(event.target.value)} className={clsx(inputClass, 'w-full')} placeholder="秘密的短名" />
      <textarea aria-label="新秘密真相" value={truth} disabled={create.isPending} onChange={event => setTruth(event.target.value)} className={clsx(inputClass, 'w-full resize-y')} rows={3} placeholder="真相是什么" />
      <div className="flex gap-2"><Button type="submit" variant="primary" size="sm" disabled={!title.trim()} loading={create.isPending}>添加秘密</Button><Button type="button" variant="ghost" size="sm" disabled={create.isPending} onClick={() => setAdding(false)}>取消</Button></div>
    </form>}
    <ErrorText error={query.error ?? bible.error ?? nodes.error ?? create.error} />
    {query.isLoading && <Skeleton className="h-48" />}
    {!query.isLoading && !query.error && !query.data?.length && <p className="rounded-xl border border-dashed border-line-2 p-6 text-sm text-ink-2">还没有信息差记录。可以添加一个秘密，记下知道它的人。</p>}
    <div className="space-y-4">{query.data?.map(secret => <SecretCard key={secret.id} secret={secret} characters={bible.data?.characters ?? []} nodes={nodes.data ?? []} />)}</div>
  </div>
}
