import clsx from 'clsx'
import { MapPin, Plus, Trash2, UserRound } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useBible, useBibleMutations } from '../../api/hooks'
import type { Character, Foreshadowing, ForeshadowingStatus, Relationship, WorldEntry } from '../../api/types'
import { EditableList, EditableText } from '../../components/Editable'
import { Badge, Button, Card, EmptyState, ErrorText, inputClass, Modal, Spinner } from '../../components/ui'

type Tab = 'characters' | 'world' | 'relations' | 'foreshadowing'

const ROLE_TONE: Record<string, 'wait' | 'busy' | 'ok' | 'idle'> = { 主角: 'wait', 女主: 'wait', 男主: 'wait', 反派: 'busy' }

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-line/70 py-2.5 last:border-0 sm:grid-cols-[5rem_1fr] sm:gap-3">
      <span className="pt-0.5 text-xs text-ink-3">{label}</span>
      <div className="min-w-0 text-sm">{children}</div>
    </div>
  )
}

// ---------- 人物 ----------

function CharacterDialog({
  bookId,
  character,
  locked,
  onClose,
}: {
  bookId: string
  character: Character
  locked: boolean
  onClose: () => void
}) {
  const { update, remove } = useBibleMutations(bookId, 'characters')
  const save = (patch: Partial<Character>) => update.mutateAsync({ id: character.id, ...patch })
  const text = (label: string, key: keyof Character) => (
    <Row label={label}>
      <EditableText value={String(character[key] ?? '')} onSave={(v) => save({ [key]: v })} locked={locked} multiline />
    </Row>
  )
  return (
    <Modal
      open
      onClose={onClose}
      title={character.name}
      wide
      footer={
        !locked && (
          <Button
            variant="danger"
            size="sm"
            loading={remove.isPending}
            onClick={async () => {
              if (confirm(`删除人物「${character.name}」？与之相关的人物关系也会删除。`)) {
                await remove.mutateAsync(character.id)
                onClose()
              }
            }}
          >
            <Trash2 className="size-4" />
            删除人物
          </Button>
        )
      }
    >
      <Row label="姓名">
        <EditableText value={character.name} onSave={(name) => save({ name })} locked={locked} className="font-serif font-semibold" />
      </Row>
      {text('定位', 'role_type')}
      {text('性别', 'gender')}
      {text('年龄', 'age')}
      {text('外貌', 'appearance')}
      {text('性格', 'personality')}
      {text('背景', 'background')}
      {text('能力', 'abilities')}
      {text('目标', 'goal')}
      {text('当前位置', 'location')}
      {text('当前状态', 'condition')}
      <Row label="秘密">
        <EditableList items={character.secrets} onSave={(secrets) => save({ secrets })} locked={locked} />
      </Row>
      {text('备注', 'notes')}
      <ErrorText error={update.error ?? remove.error} />
    </Modal>
  )
}

function CharactersTab({ bookId, characters, locked }: { bookId: string; characters: Character[]; locked: boolean }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const { create } = useBibleMutations(bookId, 'characters')
  const opened = characters.find((c) => c.id === openId)

  const add = async () => {
    const name = prompt('新人物的名字')?.trim()
    if (!name) return
    const created = await create.mutateAsync({ name })
    setOpenId(created.id)
  }

  return (
    <div>
      <div className="mb-3 flex justify-end">
        {!locked && (
          <Button size="sm" onClick={add} loading={create.isPending}>
            <Plus className="size-4" />
            添加人物
          </Button>
        )}
      </div>
      <ErrorText error={create.error} />
      <div className="grid gap-3 sm:grid-cols-2">
        {characters.map((c) => (
          <button key={c.id} onClick={() => setOpenId(c.id)} className="text-left">
            <Card className="h-full p-4 transition-shadow hover:shadow-md">
              <div className="mb-2 flex items-center gap-2">
                <span className="flex size-9 items-center justify-center rounded-full bg-paper font-serif text-lg font-bold text-ink-2">
                  {c.name.slice(0, 1)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-serif font-semibold">
                    {c.name}
                    {!c.is_alive && <span className="ml-1 text-xs text-ink-3">（已故）</span>}
                  </p>
                  <p className="text-xs text-ink-3">{[c.gender, c.age].filter(Boolean).join(' · ')}</p>
                </div>
                <Badge tone={ROLE_TONE[c.role_type] ?? 'idle'}>{c.role_type}</Badge>
              </div>
              <p className="line-clamp-2 text-sm text-ink-2">{c.personality}</p>
              {(c.location || c.condition) && (
                <p className="mt-2 flex items-start gap-1 text-xs text-ink-3">
                  <MapPin className="mt-0.5 size-3 shrink-0" />
                  <span className="line-clamp-1">{[c.location, c.condition].filter(Boolean).join('，')}</span>
                </p>
              )}
            </Card>
          </button>
        ))}
      </div>
      {opened && <CharacterDialog bookId={bookId} character={opened} locked={locked} onClose={() => setOpenId(null)} />}
    </div>
  )
}

// ---------- 世界观 ----------

const CATEGORIES = ['力量体系', '规则', '势力', '地理', '历史', '物品', '其他']

function WorldTab({ bookId, entries, locked }: { bookId: string; entries: WorldEntry[]; locked: boolean }) {
  const { create, update, remove } = useBibleMutations(bookId, 'world_entries')
  const [category, setCategory] = useState('其他')
  const [name, setName] = useState('')
  const groups = useMemo(() => {
    const order = [...CATEGORIES, ...new Set(entries.map((e) => e.category))]
    return [...new Set(order)]
      .map((cat) => ({ cat, items: entries.filter((e) => e.category === cat) }))
      .filter((g) => g.items.length)
  }, [entries])

  return (
    <div className="space-y-5">
      {groups.map(({ cat, items }) => (
        <section key={cat}>
          <p className="mb-2 text-xs font-medium tracking-wider text-ink-3">{cat}</p>
          <div className="space-y-2">
            {items.map((entry) => (
              <Card key={entry.id} className="group p-4">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <EditableText
                    value={entry.name}
                    onSave={(v) => update.mutateAsync({ id: entry.id, name: v })}
                    locked={locked}
                    className="font-serif font-semibold"
                  />
                  {!locked && (
                    <button
                      onClick={() => confirm(`删除「${entry.name}」？`) && remove.mutate(entry.id)}
                      className="rounded p-1 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-seal"
                      aria-label="删除"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  )}
                </div>
                <EditableText
                  value={entry.content}
                  onSave={(v) => update.mutateAsync({ id: entry.id, content: v })}
                  locked={locked}
                  multiline
                  className="text-sm text-ink-2"
                />
              </Card>
            ))}
          </div>
        </section>
      ))}
      {!locked && (
        <Card className="flex flex-wrap items-center gap-2 p-3">
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            {CATEGORIES.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="新条目名称" className={clsx(inputClass, 'min-w-40 flex-1')} />
          <Button
            size="sm"
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
        </Card>
      )}
    </div>
  )
}

// ---------- 人物关系 ----------

function RelationsTab({
  bookId,
  relations,
  characters,
  locked,
}: {
  bookId: string
  relations: Relationship[]
  characters: Character[]
  locked: boolean
}) {
  const { create, update, remove } = useBibleMutations(bookId, 'relationships')
  const names = Object.fromEntries(characters.map((c) => [c.id, c.name]))
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [kind, setKind] = useState('')

  return (
    <div className="space-y-2">
      {relations.length === 0 && <EmptyState icon={<UserRound className="size-8" />} title="还没有人物关系" />}
      {relations.map((r) => (
        <Card key={r.id} className="group p-4">
          <div className="flex items-center gap-2">
            <span className="font-serif font-semibold">{names[r.source_id]}</span>
            <span className="h-px flex-1 bg-line-2" />
            <EditableText
              value={r.kind}
              onSave={(v) => update.mutateAsync({ id: r.id, kind: v })}
              locked={locked}
              className="rounded-full bg-lore-soft px-2.5 text-xs text-lore"
            />
            <span className="h-px flex-1 bg-line-2" />
            <span className="font-serif font-semibold">{names[r.target_id]}</span>
            {!locked && (
              <button
                onClick={() => remove.mutate(r.id)}
                className="ml-1 rounded p-1 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-seal"
                aria-label="删除"
              >
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
            className="mt-2 text-sm text-ink-2"
          />
        </Card>
      ))}
      {!locked && characters.length >= 2 && (
        <Card className="flex flex-wrap items-center gap-2 p-3">
          <select value={source} onChange={(e) => setSource(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            <option value="">人物 A</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="关系，如 师徒" className={clsx(inputClass, 'w-32')} />
          <select value={target} onChange={(e) => setTarget(e.target.value)} className={clsx(inputClass, 'w-auto')}>
            <option value="">人物 B</option>
            {characters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <Button
            size="sm"
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
        </Card>
      )}
    </div>
  )
}

// ---------- 伏笔 ----------

const F_STATUS: Record<ForeshadowingStatus, { label: string; tone: 'idle' | 'busy' | 'ok' | 'wait' }> = {
  planned: { label: '计划中', tone: 'idle' },
  planted: { label: '已埋下', tone: 'busy' },
  resolved: { label: '已回收', tone: 'ok' },
  abandoned: { label: '已放弃', tone: 'wait' },
}

function ForeshadowingTab({ bookId, items, locked }: { bookId: string; items: Foreshadowing[]; locked: boolean }) {
  const { create, update, remove } = useBibleMutations(bookId, 'foreshadowings')
  return (
    <div className="space-y-2">
      {items.map((f) => (
        <Card key={f.id} className="group p-4">
          <div className="mb-2 flex items-start gap-2">
            <EditableText
              value={f.description}
              onSave={(v) => update.mutateAsync({ id: f.id, description: v })}
              locked={locked}
              multiline
              className="flex-1 font-medium"
            />
            {locked ? (
              <Badge tone={F_STATUS[f.status].tone}>{F_STATUS[f.status].label}</Badge>
            ) : (
              <select
                value={f.status}
                onChange={(e) => update.mutate({ id: f.id, status: e.target.value as ForeshadowingStatus })}
                className="rounded-md border border-line-2 bg-card px-2 py-1 text-xs"
              >
                {Object.entries(F_STATUS).map(([value, { label }]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            )}
            {!locked && (
              <button
                onClick={() => confirm('删除这条伏笔？') && remove.mutate(f.id)}
                className="rounded p-1 text-ink-3 opacity-0 group-hover:opacity-100 hover:text-seal"
                aria-label="删除"
              >
                <Trash2 className="size-4" />
              </button>
            )}
          </div>
          <div className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <p className="text-xs text-ink-3">怎么埋</p>
              <EditableText value={f.plant_plan} onSave={(v) => update.mutateAsync({ id: f.id, plant_plan: v })} locked={locked} multiline className="text-ink-2" />
            </div>
            <div>
              <p className="text-xs text-ink-3">怎么收</p>
              <EditableText value={f.payoff_plan} onSave={(v) => update.mutateAsync({ id: f.id, payoff_plan: v })} locked={locked} multiline className="text-ink-2" />
            </div>
          </div>
        </Card>
      ))}
      {!locked && (
        <Button
          size="sm"
          loading={create.isPending}
          onClick={() => {
            const description = prompt('伏笔内容')?.trim()
            if (description) create.mutate({ description })
          }}
        >
          <Plus className="size-4" />
          添加伏笔
        </Button>
      )}
    </div>
  )
}

export function BiblePanel({ bookId, locked }: { bookId: string; locked: boolean }) {
  const { data, isLoading } = useBible(bookId)
  const [tab, setTab] = useState<Tab>('characters')
  if (isLoading) {
    return (
      <div className="flex justify-center py-16 text-ink-3">
        <Spinner />
      </div>
    )
  }
  if (!data || (data.characters.length === 0 && data.world_entries.length === 0)) {
    return <EmptyState title="设定库还是空的">设定师建好世界观和人物后会出现在这里。</EmptyState>
  }
  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'characters', label: '人物', count: data.characters.length },
    { key: 'world', label: '世界观', count: data.world_entries.length },
    { key: 'relations', label: '关系', count: data.relationships.length },
    { key: 'foreshadowing', label: '伏笔', count: data.foreshadowings.length },
  ]
  return (
    <div>
      <div className="mb-4 flex gap-1 rounded-lg bg-line/50 p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={clsx(
              'flex-1 rounded-md px-3 py-1.5 text-sm transition-colors',
              tab === t.key ? 'bg-card font-medium text-ink shadow-sm' : 'text-ink-2 hover:text-ink',
            )}
          >
            {t.label}
            <span className="ml-1 text-xs text-ink-3">{t.count}</span>
          </button>
        ))}
      </div>
      {tab === 'characters' && <CharactersTab bookId={bookId} characters={data.characters} locked={locked} />}
      {tab === 'world' && <WorldTab bookId={bookId} entries={data.world_entries} locked={locked} />}
      {tab === 'relations' && (
        <RelationsTab bookId={bookId} relations={data.relationships} characters={data.characters} locked={locked} />
      )}
      {tab === 'foreshadowing' && <ForeshadowingTab bookId={bookId} items={data.foreshadowings} locked={locked} />}
    </div>
  )
}
