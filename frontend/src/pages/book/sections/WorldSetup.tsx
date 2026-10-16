import { Pencil } from 'lucide-react'
import { useState } from 'react'
import { useUpdateBook } from '../../../api/hooks'
import type { Bible, Character, World } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, LaterValue, QuestionField, QuestionSection } from '../../../components/QuestionSection'
import { Button, ErrorText, inputClass } from '../../../components/ui'
import { characterNameParts, joinWorldPower, patchFarMap, patchWorldMap, protagonistTension, splitWorldPower, worldPeople } from '../../../lib/worldSetup'
import { useBookContext } from '../context'

const MAP_FIELDS = [
  ['地图名', 'name'], ['谁说了算', 'powers'], ['天花板', 'ceiling'],
  ['特有的规矩', 'rules'], ['主角从哪起步', 'start'], ['能拿到什么', 'gains'],
] as const

function CharacterLink({ id, name }: { id: string; name: string }) {
  const { bookId, manualNavigate } = useBookContext()
  const href = `/books/${bookId}/characters#character-${id}`
  return <a href={href} onClick={event => { event.preventDefault(); manualNavigate(href) }} className="inline rounded border border-lore/20 bg-lore-soft px-1.5 py-0.5 text-sm text-lore underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lore">{name}</a>
}

/** 阅读态中的姓名可独立点击，不与文字编辑的点击区域互相抢事件。 */
function OpponentText({ value, characters, locked, onSave }: { value: string; characters: Character[]; locked: boolean; onSave: (value: string) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const save = async () => {
    if (saving || locked) return
    setSaving(true)
    setError(null)
    try { await onSave(draft); setEditing(false) } catch (reason) { setError(reason) } finally { setSaving(false) }
  }
  if (editing && !locked) return <div className="space-y-2">
    <textarea autoFocus aria-label="修改对手说明" rows={4} className={inputClass} value={draft} disabled={saving} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Escape') setEditing(false); if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void save() } }} />
    <div className="flex items-center gap-2"><Button size="sm" onClick={() => void save()} loading={saving}>保存</Button><Button size="sm" variant="ghost" disabled={saving} onClick={() => setEditing(false)}>取消</Button><span className="text-xs text-ink-2">Ctrl+Enter 保存</span></div>
    <ErrorText error={error} />
  </div>
  return <div className="space-y-2">
    <p className="text-[15px] leading-8 whitespace-pre-wrap">{value ? characterNameParts(value, characters).map((part, index) => part.characterId ? <CharacterLink key={index} id={part.characterId} name={part.text} /> : part.text) : <span className="text-ink-3">（未定）</span>}</p>
    {!locked && <button type="button" className="inline-flex items-center gap-1 text-xs text-ink-2 hover:text-chief" onClick={() => { setDraft(value); setError(null); setEditing(true) }}><Pencil className="size-3" />改</button>}
  </div>
}

export function WorldSetup({ bible }: { bible: Bible | undefined }) {
  const { book, bookId, job, working, manualNavigate } = useBookContext()
  const update = useUpdateBook(bookId)
  const world = book.world
  const pending = job?.status === 'waiting_author' ? job.pending : null
  const save = (patch: Partial<World>) => update.mutateAsync({ world: patch })
  const field = (key: 'surface' | 'mystery' | 'mystery_answer' | 'shadow') => <EditableText value={world[key] ?? ''} onSave={value => save({ [key]: value })} locked={working} multiline className="text-[15px]" />
  const power = splitWorldPower(world.power)
  const maps = world.maps ?? []
  const farMaps = world.far_maps ?? []
  const characters = worldPeople(bible?.characters ?? [], book.protagonist?.name)
  const protagonist = characters.find(person => person.name === book.protagonist?.name) ?? characters.find(person => person.role_type === '主角')
  const mapTable = (map: NonNullable<World['maps']>[number], editable: boolean) => <FactTable rows={MAP_FIELDS.map(([label, key]) => ({ label, value: editable ? <EditableText value={map[key] ?? ''} onSave={value => save({ maps: patchWorldMap(maps, 0, { [key]: value }) })} locked={working} multiline /> : <span className="whitespace-pre-wrap">{map[key] || '（未定）'}</span> }))} />

  return <section aria-label="世界与地图的六道必答题" className="mb-9">
    <FocusQuestions piece="world" />
    <QuestionSection piece="world" questionKey="surface" pending={pending}>{field('surface')}</QuestionSection>
    <QuestionSection piece="world" questionKey="power" pending={pending}>
      <div className="space-y-5">
        <QuestionField label="力量规则" when="before"><EditableText value={power.before} onSave={value => save({ power: joinWorldPower(value, power.later) })} locked={working} multiline className="text-[15px]" /></QuestionField>
        <QuestionField label="往上的层级" when="later"><LaterValue value={power.later}><p className="text-[15px] leading-relaxed whitespace-pre-wrap">{power.later}</p></LaterValue></QuestionField>
      </div>
    </QuestionSection>
    <QuestionSection piece="world" questionKey="first_map" pending={pending}>
      {mapTable(maps[0] ?? {}, true)}
      {maps.length > 1 && <div className="mt-6 space-y-5 border-t border-line pt-5"><h4 className="text-sm font-medium text-ink-2">后来到过的地图</h4>{maps.slice(1).map((map, index) => <div key={index}>{mapTable(map, false)}</div>)}</div>}
    </QuestionSection>
    <QuestionSection piece="world" questionKey="opponents" pending={pending}>
      <div className="space-y-5">
        <QuestionField label="开篇的小麻烦"><OpponentText value={world.trouble ?? ''} characters={characters} locked={working} onSave={value => save({ trouble: value })} /></QuestionField>
        <QuestionField label="这一段的大对手"><OpponentText value={world.opponent ?? ''} characters={characters} locked={working} onSave={value => save({ opponent: value })} /></QuestionField>
      </div>
    </QuestionSection>
    <QuestionSection piece="world" questionKey="people" pending={pending}>
      <div className="divide-y divide-line">
        {characters.map(person => {
          const tension = protagonistTension(person.id, protagonist?.id, bible?.relationships ?? [])
          const href = `/books/${bookId}/characters#character-${person.id}`
          return <article key={person.id} className="space-y-2 py-4 first:pt-0 last:pb-0">
            <p className="text-[15px]"><CharacterLink id={person.id} name={person.name} /><span className="ml-2 text-ink-2">· {person.role_type || '定位未定'}</span></p>
            <dl className="space-y-1 text-sm leading-relaxed">
              <div><dt className="inline text-ink-2">想要什么：</dt><dd className="inline">{person.goal || '（未定）'}</dd></div>
              <div><dt className="inline text-ink-2">此刻想要：</dt><dd className="inline">{person.want || '（未定）'}</dd></div>
              {person.id !== protagonist?.id && <div><dt className="inline text-ink-2">和主角的张力：</dt><dd className="inline">{tension || '（尚未记录）'}</dd></div>}
            </dl>
            <a href={href} onClick={event => { event.preventDefault(); manualNavigate(href) }} className="inline-block text-xs text-chief underline underline-offset-4">去人物页编辑 →</a>
          </article>
        })}
        {!characters.length && <p className="text-sm text-ink-2">这一段的人物还没有写下。</p>}
      </div>
    </QuestionSection>
    <QuestionSection piece="world" questionKey="shadows" pending={pending}>
      <div className="space-y-5">
        <QuestionField label="核心谜团的谜面" when="before">{field('mystery')}</QuestionField>
        <QuestionField label="谜底" when="later"><LaterValue value={world.mystery_answer}>{field('mystery_answer')}</LaterValue></QuestionField>
        <QuestionField label="后面的地图" when="later"><LaterValue value={farMaps.flatMap(map => [map.name, map.line]).filter(value => value?.trim())}>
          <div className="space-y-4">{farMaps.map((map, index) => <FactTable key={index} rows={[
            { label: '地图名', value: <EditableText value={map.name ?? ''} onSave={name => save({ far_maps: patchFarMap(farMaps, index, { name }) })} locked={working} /> },
            { label: '一句话', value: <EditableText value={map.line ?? ''} onSave={line => save({ far_maps: patchFarMap(farMaps, index, { line }) })} locked={working} multiline placeholder="（还没想好）" /> },
          ]} />)}</div>
        </LaterValue></QuestionField>
        <QuestionField label="终极敌人的影子" when="later"><LaterValue value={world.shadow}>{field('shadow')}</LaterValue></QuestionField>
      </div>
    </QuestionSection>
    <ErrorText error={update.error} />
  </section>
}
