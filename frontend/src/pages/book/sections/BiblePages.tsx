import { useReducedMotion } from '../../../lib/appearance'
import clsx from 'clsx'
import { BookOpen, Castle, Gem, Landmark, MapPin, Mountain, Plus, ScrollText, Sparkles, Trash2, Zap } from 'lucide-react'
import { motion } from 'motion/react'
import { type ReactNode, useMemo, useState } from 'react'
import { useBible, useBibleMutations, useNodes } from '../../../api/hooks'
import type { Character, Foreshadowing, ForeshadowingStatus } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { Badge, Button, Card, EmptyState, ErrorText, inputClass, Sheet, Skeleton } from '../../../components/ui'
import type { Tone } from '../../../lib/status'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
import { CharacterAnchors } from './CharacterAnchors'
import { FieldBlock, Locked, PageHeader } from './common'

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

// ---------- 人物 ----------

const ROLE_STYLE: Record<string, { tone: Tone; ring: string; bg: string; text: string }> = {
  主角: { tone: 'wait', ring: 'ring-seal/40', bg: 'bg-seal-soft', text: 'text-seal' },
  女主: { tone: 'wait', ring: 'ring-seal/40', bg: 'bg-seal-soft', text: 'text-seal' },
  男主: { tone: 'wait', ring: 'ring-seal/40', bg: 'bg-seal-soft', text: 'text-seal' },
  反派: { tone: 'busy', ring: 'ring-chief/40', bg: 'bg-chief-soft', text: 'text-chief' },
}
const DEFAULT_ROLE = { tone: 'idle' as Tone, ring: 'ring-line-2', bg: 'bg-paper', text: 'text-ink-2' }

function CharacterSheet({ character, onClose }: { character: Character; onClose: () => void }) {
  const { bookId, locked } = useBibleData()
  const { update, remove } = useBibleMutations(bookId, 'characters')
  const save = (patch: Partial<Character>) => update.mutateAsync({ id: character.id, ...patch })
  const field = (label: string, key: keyof Character) => (
    <FieldBlock label={label}>
      <EditableText value={String(character[key] ?? '')} onSave={(v) => save({ [key]: v })} locked={locked} multiline />
    </FieldBlock>
  )
  return (
    <Sheet
      open
      onClose={onClose}
      title={<EditableText value={character.name} onSave={(name) => save({ name })} locked={locked} />}
      footer={
        !locked && (
          <Button
            variant="danger"
            size="sm"
            loading={remove.isPending}
            onClick={async () => {
              if (confirm(`删除人物「${character.name}」？与之相关的人物关系也会删除。`)) {
                try {
                  await remove.mutateAsync(character.id)
                  onClose()
                } catch { /* 保留抽屉与错误，供作者重试。 */ }
              }
            }}
          >
            <Trash2 className="size-4" />
            删除人物
          </Button>
        )
      }
    >
      <div className="space-y-5">
        <div className="grid grid-cols-3 gap-3">
          {field('定位', 'role_type')}
          {field('性别', 'gender')}
          {field('年龄', 'age')}
        </div>
        {field('外貌', 'appearance')}
        {field('性格', 'personality')}
        {field('背景', 'background')}
        {field('能力', 'abilities')}
        {field('想要什么', 'goal')}
        <div className="rounded-xl bg-paper px-4 py-3 ring-1 ring-line">
          <p className="mb-2 text-xs tracking-[0.15em] text-ink-2">当前状态（随剧情更新）</p>
          <div className="space-y-3">
            {field('位置', 'location')}
            {field('处境', 'condition')}
          </div>
        </div>
        {field('备注', 'notes')}
        <CharacterAnchors characterId={character.id} />
        <ErrorText error={update.error ?? remove.error} />
      </div>
    </Sheet>
  )
}

export function CharactersPage() {
  const { bookId, locked, data, isLoading, error } = useBibleData()
  const { job, manualNavigate } = useBookContext()
  const nodes = useNodes(bookId)
  const { create } = useBibleMutations(bookId, 'characters')
  const [openId, setOpenId] = useState<string | null>(null)
  const characters = data?.characters ?? []
  const opened = characters.find((c) => c.id === openId)

  const add = async () => {
    const name = prompt('新人物的名字')?.trim()
    if (!name) return
    try {
      const created = await create.mutateAsync({ name })
      setOpenId(created.id)
    } catch { /* 页面显示错误，不跳走或删除已有内容。 */ }
  }

  return (
    <div>
      <PieceDecisions piece="cast" />
      {job?.status === 'waiting_author' && job.pending?.kind === 'setup_piece' && job.pending.piece === 'cast' && <div className="mb-5 rounded-xl border border-chief/20 bg-chief-soft/50 px-4 py-3 text-sm text-chief">
        <p>这一块还包括世界观、人物关系和信息差</p>
        <div className="mt-2 flex flex-wrap gap-4">{[['世界观', 'world'], ['人物关系', 'relations'], ['信息差', 'secrets']].map(([name, path]) => <a key={path} href={`/books/${bookId}/${path}`} onClick={event => { event.preventDefault(); manualNavigate(`/books/${bookId}/${path}`) }} className="underline underline-offset-4">{name} →</a>)}</div>
      </div>}
      <PageHeader
        eyebrow="设定库"
        title="人物"
        subtitle="每个人想要什么、有什么经历、现在在哪。写章节时设定师会自动更新他们的状态。"
        action={
          !locked && (
            <Button size="sm" variant="soft" onClick={add} loading={create.isPending}>
              <Plus className="size-4" />
              添加人物
            </Button>
          )
        }
      />
      <Locked locked={locked} />
      {isLoading && <Skeleton className="h-48" />}
      <div className="grid gap-4 @lg/manuscript:grid-cols-2">
        {characters.map((c, i) => {
          const style = ROLE_STYLE[c.role_type] ?? DEFAULT_ROLE
          return (
            <Stagger key={c.id} i={i}>
              <button onClick={() => setOpenId(c.id)} className="block h-full w-full text-left">
                <Card hover className="flex h-full flex-col p-5">
                  <div className="flex items-center gap-3">
                    <span className={clsx('flex size-12 items-center justify-center rounded-full font-serif text-xl font-bold ring-2', style.bg, style.text, style.ring)}>
                      {c.name.slice(0, 1)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-serif text-lg font-bold">
                        {c.name}
                        {!c.is_alive && <span className="ml-1 text-xs font-normal text-ink-2">（已故）</span>}
                      </p>
                      <p className="text-xs text-ink-2">{[c.gender, c.age].filter(Boolean).join(' · ')}</p>
                    </div>
                    <Badge tone={style.tone}>{c.role_type}</Badge>
                  </div>
                  <p className="mt-3 line-clamp-2 text-[14px] leading-relaxed text-ink-2">{c.personality}</p>
                  {c.goal && <p className="mt-2 line-clamp-1 text-[14px] text-ink-2">想要：{c.goal}</p>}
                  <div className="mt-3 space-y-1.5 border-t border-line pt-3 text-sm text-ink-2">
                    {(nodes.data ?? []).flatMap(node => node.anchors.filter(anchor => anchor.character_id === c.id).map(anchor => <p key={anchor.id} title={anchor.note}>节点 {node.index}「{node.title || '留空'}」· {anchor.kind}{anchor.note && `——${anchor.note}`}</p>))}
                    {!(nodes.data ?? []).some(node => node.anchors.some(anchor => anchor.character_id === c.id)) && <p className="text-xs text-ink-3">还没有人物锚点</p>}
                  </div>
                  {(c.location || c.condition) && (
                    <p className="mt-auto flex items-start gap-1 pt-3 text-xs text-ink-2">
                      <MapPin className="mt-0.5 size-3 shrink-0" />
                      <span className="line-clamp-1">{[c.location, c.condition].filter(Boolean).join('，')}</span>
                    </p>
                  )}
                </Card>
              </button>
            </Stagger>
          )
        })}
      </div>
      <ErrorText error={error ?? nodes.error ?? create.error} />
      {opened && <CharacterSheet character={opened} onClose={() => setOpenId(null)} />}
    </div>
  )
}

// ---------- 世界观 ----------

const CATEGORIES: Record<string, ReactNode> = {
  力量体系: <Zap className="size-4" />,
  规则: <ScrollText className="size-4" />,
  势力: <Castle className="size-4" />,
  地理: <Mountain className="size-4" />,
  历史: <Landmark className="size-4" />,
  物品: <Gem className="size-4" />,
  其他: <Sparkles className="size-4" />,
}

export function WorldPage() {
  const { bookId, locked, data, isLoading } = useBibleData()
  const { create, update, remove } = useBibleMutations(bookId, 'world_entries')
  const [category, setCategory] = useState('其他')
  const [name, setName] = useState('')
  const entries = useMemo(() => data?.world_entries ?? [], [data])
  const groups = useMemo(() => {
    const order = [...Object.keys(CATEGORIES), ...new Set(entries.map((e) => e.category))]
    return [...new Set(order)].map((cat) => ({ cat, items: entries.filter((e) => e.category === cat) })).filter((g) => g.items.length)
  }, [entries])

  return (
    <div>
      <PageHeader eyebrow="设定库" title="世界观" subtitle="力量体系、势力、地理与规则。好的设定都有限制和代价。" />
      <Locked locked={locked} />
      {isLoading && <Skeleton className="h-48" />}
      <div className="space-y-9">
        {groups.map(({ cat, items }) => (
          <section key={cat}>
            <h3 className="mb-3 flex items-center gap-2 font-serif text-lg font-bold">
              <span className="text-seal">{CATEGORIES[cat] ?? <BookOpen className="size-4" />}</span>
              {cat}
            </h3>
            <div className="grid gap-3 @2xl/manuscript:grid-cols-2">
              {items.map((entry, i) => (
                <Stagger key={entry.id} i={i}>
                  <Card hover className="group h-full p-5">
                    <div className="mb-1.5 flex items-center justify-between gap-2">
                      <EditableText value={entry.name} onSave={(v) => update.mutateAsync({ id: entry.id, name: v })} locked={locked} className="font-serif text-[17px] font-bold" />
                      {!locked && (
                        <button
                          onClick={() => confirm(`删除「${entry.name}」？`) && remove.mutate(entry.id)}
                          className="rounded p-1 text-ink-2 opacity-0 transition-opacity group-hover:opacity-100 hover:text-seal"
                          aria-label="删除"
                        >
                          <Trash2 className="size-4" />
                        </button>
                      )}
                    </div>
                    <EditableText value={entry.content} onSave={(v) => update.mutateAsync({ id: entry.id, content: v })} locked={locked} multiline className="text-[14px] text-ink-2" />
                  </Card>
                </Stagger>
              ))}
            </div>
          </section>
        ))}
      </div>
      {!locked && (
        <section className="mt-8 flex flex-wrap items-center gap-2 border-t border-line pt-6">
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            {Object.keys(CATEGORIES).map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="新条目名称" className={clsx(inputClass, 'min-w-40 flex-1')} />
          <Button
            variant="primary"
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={async () => {
              await create.mutateAsync({ category, name: name.trim(), content: '' })
              setName('')
            }}
          >
            <Plus className="size-4" />
            添加
          </Button>
        </section>
      )}
    </div>
  )
}

// ---------- 人物关系 ----------

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

export function ForeshadowingPage() {
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
      <PageHeader
        eyebrow="设定库"
        title="伏笔与期待"
        subtitle="伏笔是暗中埋下的线，期待是读者明知并等着兑现的承诺。编辑部按台账安排立下、提醒与兑现。"
        action={!locked && <Button size="sm" variant="soft" disabled={busy} onClick={() => { setNewKind(filter === '全部' ? '伏笔' : filter); setAdding(true) }}><Plus className="size-4" />添加条目</Button>}
      />
      <Locked locked={locked} />
      <div role="group" aria-label="按台账类型筛选" className="mb-5 inline-flex gap-1 rounded-xl bg-paper p-1 ring-1 ring-line">
        {(['全部', '伏笔', '期待'] as const).map(value => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)} className={clsx('rounded-lg px-4 py-2 text-sm transition-colors', filter === value ? 'bg-card text-chief shadow-sm' : 'text-ink-2 hover:bg-card/60')}>{value}</button>)}
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
