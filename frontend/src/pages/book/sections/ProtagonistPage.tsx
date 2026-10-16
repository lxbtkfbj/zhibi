import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useBible, useUpdateBook } from '../../../api/hooks'
import type { Protagonist } from '../../../api/types'
import { EditableText } from '../../../components/Editable'
import { FactTable } from '../../../components/FactTable'
import { FocusQuestions, LaterValue, QuestionField, QuestionSection } from '../../../components/QuestionSection'
import { Button, ErrorText, inputClass } from '../../../components/ui'
import { useBookContext } from '../context'
import { PieceDecisions } from '../PieceDecisions'
import { FieldBlock, Locked, PageHeader } from './common'

type CaredPeople = NonNullable<Protagonist['cared']>

/** 编辑期间维护整份草稿；增删改只在明确保存时原子提交，不逐项覆盖。 */
function CaredPeopleEditor({ people, onSave, locked }: { people: CaredPeople; onSave: (people: CaredPeople) => Promise<unknown>; locked: boolean }) {
  const [draft, setDraft] = useState<CaredPeople | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  if (draft !== null) return <form onSubmit={async event => {
    event.preventDefault()
    if (locked || saving) return
    if (draft.some(person => !person.name?.trim())) { setError(new Error('请填写每位在乎的人的姓名，或删除空白卡片')); return }
    setSaving(true); setError(null)
    try { await onSave(draft); setDraft(null) } catch (cause) { setError(cause) } finally { setSaving(false) }
  }} className="space-y-4">
    <fieldset disabled={locked || saving} className="space-y-3">{draft.map((person, index) => <div className="rounded-xl border border-line bg-card p-4" key={index}>
      <div className="mb-3 flex items-center justify-between gap-3"><p className="text-xs text-ink-2">第 {index + 1} 位在乎的人</p><Button type="button" size="sm" variant="ghost" aria-label={`删除第 ${index + 1} 位在乎的人`} onClick={() => setDraft(draft.filter((_, at) => at !== index))}><Trash2 className="size-3.5" />删除</Button></div>
      <div className="space-y-3">{(['name', 'relation', 'why'] as const).map(key => <label key={key} className="block"><span className="mb-1 block text-xs text-ink-2">{{ name: '姓名', relation: '关系', why: '为什么在乎' }[key]}</span>{key === 'why'
        ? <textarea className={inputClass} rows={2} value={person[key] ?? ''} onChange={event => setDraft(draft.map((item, at) => at === index ? { ...item, [key]: event.target.value } : item))} />
        : <input className={inputClass} value={person[key] ?? ''} onChange={event => setDraft(draft.map((item, at) => at === index ? { ...item, [key]: event.target.value } : item))} />}</label>)}</div>
    </div>)}<Button type="button" size="sm" onClick={() => setDraft([...draft, { name: '', relation: '', why: '' }])}><Plus className="size-4" />添加在乎的人</Button></fieldset>
    <div className="flex flex-wrap gap-2"><Button type="submit" size="sm" variant="primary" loading={saving} disabled={locked}>保存在乎的人</Button><Button type="button" size="sm" variant="ghost" disabled={saving} onClick={() => { setDraft(null); setError(null) }}>取消</Button></div>
    <p className="text-xs text-ink-2">增删改会随整份列表一起保存。</p><ErrorText error={error} />
  </form>
  return <div className="space-y-3">
    {people.map((person, index) => <article className="rounded-xl border border-line bg-card p-4 shadow-[var(--shadow-paper)]" key={index}><h3 className="mb-2 font-serif text-base">{person.name || '未命名'} · {person.relation || '关系未定'}</h3><p className="text-sm leading-relaxed whitespace-pre-wrap"><span className="text-ink-2">为什么在乎：</span>{person.why || '（未定）'}</p></article>)}
    {!people.length && <p className="text-sm text-ink-3">还没有记下在乎的人。</p>}
    {!locked && <div className="flex flex-wrap gap-2"><Button size="sm" variant="ghost" onClick={() => setDraft(people.map(person => ({ ...person })))}>修改在乎的人</Button><Button size="sm" variant="ghost" onClick={() => setDraft([...people.map(person => ({ ...person })), { name: '', relation: '', why: '' }])}><Plus className="size-4" />添加在乎的人</Button></div>}
  </div>
}

export function ProtagonistPage() {
  const { book, bookId, working, job, manualNavigate } = useBookContext()
  const update = useUpdateBook(bookId)
  const bible = useBible(bookId)
  const card = book.protagonist ?? {}
  const available = Object.keys(card).length > 0
  const pending = job?.status === 'waiting_author' ? job.pending : null
  const save = (patch: Partial<Protagonist>) => update.mutateAsync({ protagonist: patch })
  const text = (key: Exclude<keyof Protagonist, 'cared'>) => <EditableText value={card[key] ?? ''} onSave={value => save({ [key]: value })} locked={working} multiline />
  const legacyHero = bible.data?.characters.find(character => character.role_type === '主角')
  return <div>
    <PageHeader eyebrow="主角卡" title={available ? <EditableText value={card.name || '主角'} onSave={name => save({ name })} locked={working} /> : '主角'} subtitle="他是谁、想要什么、为什么、凭什么。" />
    {available ? <>
      <PieceDecisions piece="protagonist" /><FocusQuestions piece="protagonist" /><Locked locked={working} />
      <div data-testid="protagonist-card">
        <QuestionSection piece="protagonist" questionKey="start" pending={pending}>{text('start')}</QuestionSection>
        <QuestionSection piece="protagonist" questionKey="drive" pending={pending}>
          {legacyHero?.want?.trim() && <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border-l-2 border-chief bg-chief-soft/40 px-3 py-2 text-sm leading-relaxed" data-testid="protagonist-current-want"><p className="min-w-0 whitespace-pre-wrap"><span className="text-ink-2">此刻想要（写作中设定师每章更新）：</span>{legacyHero.want}</p><a href={`/books/${bookId}/characters#character-${legacyHero.id}`} onClick={event => { event.preventDefault(); manualNavigate(event.currentTarget.getAttribute('href')!) }} className="shrink-0 text-chief underline underline-offset-4">去人物页 →</a></div>}
          <QuestionField label="开局动机" when="before">{text('trigger')}</QuestionField><QuestionField label="长线追求" when="before">{text('pursuit')}</QuestionField><QuestionField label="情感根源" when="before">{text('root')}</QuestionField>
          <QuestionField label="怎么升级" when="later"><LaterValue value={card.escalation}>{text('escalation')}</LaterValue></QuestionField>
        </QuestionSection>
        <QuestionSection piece="protagonist" questionKey="person" pending={pending}><FactTable rows={[{ label: '性格', value: text('personality') }, { label: '做事风格', value: text('style') }, { label: '底线', value: text('bottom_line') }, { label: '说话方式', value: text('voice') }]} /></QuestionSection>
        <QuestionSection piece="protagonist" questionKey="finger" pending={pending}>
          <QuestionField label="金手指·现在" when="before">{text('finger')}</QuestionField><QuestionField label="金手指·以后" when="later"><LaterValue value={card.finger_later}>{text('finger_later')}</LaterValue></QuestionField>
        </QuestionSection>
        <QuestionSection piece="protagonist" questionKey="flaw_arc" pending={pending}><QuestionField label="软肋">{text('flaw')}</QuestionField><QuestionField label="成长的终点" when="before" direction>{text('arc_end')}</QuestionField></QuestionSection>
        <QuestionSection piece="protagonist" questionKey="cared" pending={pending}><CaredPeopleEditor people={card.cared ?? []} onSave={cared => save({ cared })} locked={working} /></QuestionSection>
        <QuestionSection piece="protagonist" questionKey="interlock" pending={pending}>{text('interlock')}<div className="space-y-2 border-l-2 border-line pl-3 text-xs leading-relaxed text-ink-2"><p>驱动力（长线追求）：{card.pursuit || '（未定）'}</p><p>金手指（金手指·现在）：{card.finger || '（未定）'}</p><p>核心循环（定调）：{book.concept.core_loop || '（未定）'}</p></div></QuestionSection>
      </div>
    </> : <div className="space-y-5 text-sm leading-relaxed text-ink-2">
      <p>这本书开书时还没有主角卡。</p>
      {job?.setup_flow === 2 && ['setting_up', 'awaiting_approval'].includes(book.status) && <p>主编还在准备主角卡，定下来后会出现在这里。</p>}
      {book.concept.protagonist_hook && <FieldBlock label="主角钩子（旧版概念）"><p className="whitespace-pre-wrap">{book.concept.protagonist_hook}</p></FieldBlock>}
      {legacyHero && <FieldBlock label={`设定库里的主角 · ${legacyHero.name}`}><FactTable rows={[{ label: '性格', value: legacyHero.personality || '（未定）' }, { label: '背景', value: legacyHero.background || '（未定）' }, { label: '能力', value: legacyHero.abilities || '（未定）' }, { label: '想要什么', value: legacyHero.goal || '（未定）' }]} /></FieldBlock>}
      <a href={`/books/${bookId}/characters${legacyHero ? `#character-${legacyHero.id}` : ''}`} onClick={event => { event.preventDefault(); manualNavigate(event.currentTarget.getAttribute('href')!) }} className="inline-block text-chief underline underline-offset-4">去人物页 →</a><ErrorText error={bible.error} />
    </div>}
  </div>
}
