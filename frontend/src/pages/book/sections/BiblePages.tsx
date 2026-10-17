import type { Tone } from '../../../lib/status'
import { useReducedMotion } from '../../../lib/appearance'
import clsx from 'clsx'
import { Plus, Trash2 } from 'lucide-react'
import { motion } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { useBible, useBibleMutations } from '../../../api/hooks'
import type { Foreshadowing, ForeshadowingStatus } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Badge, Button, Card, EmptyState, ErrorText, inputClass, Skeleton } from '../../../components/ui'
import { useBookContext } from '../context'
import { Locked, PageHeader } from './common'

function Stagger({ i, children, className }: { i: number; children: ReactNode; className?: string }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: Math.min(i, 10) * 0.04, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  )
}

function useBibleData() {
  const { bookId, working } = useBookContext()
  const query = useBible(bookId)
  return { bookId, locked: working, ...query }
}

export function RelationsPage() {
  const { bookId, locked, data, isLoading } = useBibleData()
  const { create, update, remove } = useBibleMutations(bookId, 'relationships')
  const characters = data?.characters ?? []
  const relations = data?.relationships ?? []
  const names = Object.fromEntries(characters.map((c) => [c.id, c.name]))
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [kind, setKind] = useState('')

  return (
    <div>
      <PageHeader eyebrow="设定库" title="人物关系" subtitle="谁和谁是什么关系、之间有什么张力。" />
      <Locked locked={locked} />
      {isLoading && <Skeleton className="h-48" />}
      {!isLoading && relations.length === 0 && <EmptyState title="还没有人物关系" />}
      <div className="space-y-3">
        {relations.map((r, i) => (
          <Stagger key={r.id} i={i}>
            <Card hover className="group p-5">
              <div className="flex items-center gap-3">
                <span className="font-serif text-lg font-bold">{names[r.source_id]}</span>
                <span className="h-px flex-1 bg-gradient-to-r from-line-2 to-transparent" />
                <EditableText value={r.kind} onSave={(v) => update.mutateAsync({ id: r.id, kind: v })} locked={locked} className="rounded-full bg-lore-soft px-3 py-0.5 text-sm text-lore" />
                <span className="h-px flex-1 bg-gradient-to-l from-line-2 to-transparent" />
                <span className="font-serif text-lg font-bold">{names[r.target_id]}</span>
                {!locked && (
                  <button onClick={() => remove.mutate(r.id)} className="rounded p-1 text-ink-2 opacity-0 transition-opacity group-hover:opacity-100 hover:text-seal" aria-label="删除">
                    <Trash2 className="size-4" />
                  </button>
                )}
              </div>
              <EditableText
                value={r.description}
                onSave={(v) => update.mutateAsync({ id: r.id, description: v })}
                locked={locked}
                multiline
                placeholder="（补充说明）"
                className="mt-2.5 text-center text-[14px] text-ink-2"
              />
            </Card>
          </Stagger>
        ))}
      </div>
      {!locked && characters.length >= 2 && (
        <section className="mt-6 flex flex-wrap items-center gap-2 border-t border-line pt-6">
          <select value={source} onChange={(e) => setSource(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            <option value="">人物 A</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="关系，如 师徒" className={clsx(inputClass, 'w-36')} />
          <select value={target} onChange={(e) => setTarget(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            <option value="">人物 B</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <Button
            variant="primary"
            disabled={!source || !target || source === target || !kind.trim()}
            loading={create.isPending}
            onClick={async () => {
              await create.mutateAsync({ source_id: source, target_id: target, kind: kind.trim(), description: '' })
              setKind('')
            }}
          >
            <Plus className="size-4" />
            添加
          </Button>
          <ErrorText error={create.error} />
        </section>
      )}
    </div>
  )
}

// ---------- 伏笔与期待 ----------

const F_STATUS: Record<ForeshadowingStatus, { label: string; tone: Tone }> = {
  planned: { label: '计划中', tone: 'idle' },
  planted: { label: '已埋下', tone: 'busy' },
  resolved: { label: '已回收', tone: 'ok' },
  abandoned: { label: '已放弃', tone: 'wait' },
}
const E_STATUS: Record<ForeshadowingStatus, { label: string; tone: Tone }> = {
  planned: { label: '未立', tone: 'idle' },
  planted: { label: '已立', tone: 'busy' },
  resolved: { label: '已兑现', tone: 'ok' },
  abandoned: { label: '放弃', tone: 'wait' },
}

export function ForeshadowingPage({ embedded = false }: { embedded?: boolean }) {
  const { bookId, locked, data, isLoading, error } = useBibleData()
  const { create, update, remove } = useBibleMutations(bookId, 'foreshadowings')
  const [filter, setFilter] = useState<'全部' | Foreshadowing['kind']>('全部')
  const [adding, setAdding] = useState(false)
  const [newKind, setNewKind] = useState<Foreshadowing['kind']>('伏笔')
  const [description, setDescription] = useState('')
  const items = (data?.foreshadowings ?? []).filter(item => filter === '全部' || item.kind === filter)
  const busy = locked || create.isPending || update.isPending || remove.isPending
  return (
    <div>
      {embedded
        ? <h2 className="mb-1.5 flex flex-wrap items-center gap-2.5 text-[17px] font-semibold">伏笔与期待<span className="text-[13px] font-normal text-ink-3">写作时编辑部每章都会查这本账，防止埋了忘收、立了不兑现</span>{!locked && <Button className="ml-auto" size="sm" variant="outline" disabled={busy} onClick={() => { setNewKind(filter === '全部' ? '伏笔' : filter); setAdding(true) }}><Plus className="size-3.5" />添加</Button>}</h2>
        : <PageHeader eyebrow="大纲" title="伏笔与期待" subtitle="伏笔是暗中埋下的线，期待是读者明知并等着兑现的承诺。编辑部按台账安排立下、提醒与兑现。" action={!locked && <Button size="sm" variant="outline" disabled={busy} onClick={() => { setNewKind(filter === '全部' ? '伏笔' : filter); setAdding(true) }}><Plus className="size-4" />添加条目</Button>} />}
      <Locked locked={locked} />
      <div role="group" aria-label="按台账类型筛选" className="mb-5 inline-flex gap-0.5 rounded-lg bg-line/70 p-0.5">
        {(['全部', '伏笔', '期待'] as const).map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)} className={clsx('rounded-md px-3 py-1 text-[13px] transition-colors', filter === value ? 'bg-card font-medium text-ink shadow-[0_1px_2px_rgb(0_0_0/0.06)]' : 'text-ink-2 hover:text-ink')}>{value}</button>)}
      </div>
      {adding && !locked && <form className="mb-5 space-y-3 rounded-xl border border-line bg-card p-4" onSubmit={event => {
        event.preventDefault()
        if (!description.trim() || busy) return
        create.mutate({ kind: newKind, description: description.trim() }, { onSuccess: () => { setAdding(false); setDescription(''); setFilter(newKind) } })
      }}>
        <div role="group" aria-label="新增条目类型" className="flex gap-2">{(['伏笔', '期待'] as const).map(kind => <Button key={kind} type="button" size="sm" disabled={busy} variant={newKind === kind ? 'primary' : 'outline'} aria-pressed={newKind === kind} onClick={() => setNewKind(kind)}>{kind}</Button>)}</div>
        <textarea aria-label="新增台账内容" value={description} disabled={busy} onChange={event => setDescription(event.target.value)} placeholder={newKind === '期待' ? '读者知道并等着兑现的承诺' : '准备暗中埋下的线索'} className={clsx(inputClass, 'w-full resize-y')} rows={2} />
        <div className="flex gap-2"><Button type="submit" variant="primary" size="sm" disabled={!description.trim() || busy} loading={create.isPending}>添加{newKind}</Button><Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setAdding(false)}>取消</Button></div>
      </form>}
      <ErrorText error={error ?? create.error ?? update.error ?? remove.error} />
      {isLoading && <Skeleton className="h-48" />}
      {!isLoading && !items.length && <p className="rounded-xl border border-dashed border-line-2 p-6 text-sm text-ink-2">{filter === '全部' ? '还没有伏笔或期待，可以先添上一条。' : `还没有${filter}。`}</p>}
      <div className="space-y-4">
        {items.map((f, i) => {
          const expectation = f.kind === '期待'
          const statuses = expectation ? E_STATUS : F_STATUS
          const plant = expectation ? '立下' : '埋下'
          const payoff = expectation ? '兑现' : '回收'
          return <Stagger key={f.id} i={i}>
            <Card hover className="group p-5 @lg/manuscript:p-6">
              <div className="mb-4 flex flex-wrap items-start gap-3">
                <span className="mt-1 shrink-0 font-serif text-xl leading-none font-bold text-ink-2">{f.code}</span>
                <EditableText value={f.description} onSave={v => update.mutateAsync({ id: f.id, description: v })} locked={busy} multiline className="min-w-24 flex-1 font-serif text-[17px] font-bold" />
                {locked ? <Badge tone={statuses[f.status].tone}>{statuses[f.status].label}</Badge> : <select aria-label={`${f.code} 状态`} value={f.status} disabled={busy} onChange={event => update.mutate({ id: f.id, status: event.target.value as ForeshadowingStatus })} className="rounded-lg border border-line-2 bg-card px-2 py-1 text-xs">
                  {Object.entries(statuses).map(([value, { label }]) => <option key={value} value={value}>{label}</option>)}
                </select>}
                {!locked && <button title={`删除${f.kind}`} onClick={() => { if (confirm(`删除这条${f.kind}？`)) remove.mutate(f.id) }} disabled={busy} className="rounded p-1 text-ink-2 hover:text-seal disabled:opacity-50" aria-label={`删除 ${f.code}`}><Trash2 className="size-4" /></button>}
              </div>
              <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
                <Badge tone={expectation ? 'busy' : 'idle'}>{f.kind}</Badge>
                <span className="rounded-full bg-line/70 px-2.5 py-0.5 text-ink-2">{f.span}线</span>
                {f.plant_volume && <span className="rounded-full bg-lore-soft px-2.5 py-0.5 text-lore">计划第 {f.plant_volume} 卷{plant}</span>}
                {f.payoff_volume && <span className="rounded-full bg-seal-soft px-2.5 py-0.5 text-seal">计划第 {f.payoff_volume} 卷{payoff}</span>}
                {f.planted_chapter && <span className="rounded-full bg-card px-2.5 py-0.5 text-ink-2 ring-1 ring-line">第 {f.planted_chapter} 章已{plant}</span>}
                {f.hint_chapters.length > 0 && <span className="rounded-full bg-card px-2.5 py-0.5 text-ink-2 ring-1 ring-line">提醒于第 {f.hint_chapters.join('、')} 章</span>}
                {f.resolved_chapter && <span className="rounded-full bg-card px-2.5 py-0.5 text-ink-2 ring-1 ring-line">第 {f.resolved_chapter} 章已{payoff}</span>}
              </div>
              <p className="mb-3 text-xs text-ink-2">台账动作：{plant} / 提醒 / {payoff}</p>
              <div className="grid gap-3 @lg/manuscript:grid-cols-2">
                <div className="border-t border-line pt-3">
                  <p className="mb-1 text-xs text-ink-2">怎么{plant}</p>
                  <EditableText value={f.plant_plan} onSave={v => update.mutateAsync({ id: f.id, plant_plan: v })} locked={busy} multiline className="text-[14px]" />
                </div>
                <div className="border-t border-line pt-3">
                  <p className="mb-1 text-xs text-ink-2">怎么{payoff}</p>
                  <EditableText value={f.payoff_plan} onSave={v => update.mutateAsync({ id: f.id, payoff_plan: v })} locked={busy} multiline className="text-[14px]" />
                </div>
              </div>
            </Card>
          </Stagger>
        })}
      </div>
    </div>
  )
}
