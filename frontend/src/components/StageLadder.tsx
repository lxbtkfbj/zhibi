import { type CSSProperties, useState } from 'react'
import { splitStageLadder } from '../lib/stageLadder'
import { EditableText } from './Editable'
import { Button, ErrorText, inputClass } from './ui'
import './setupQuestions.css'

export function StageLadder({ value, onSave, locked }: { value: string; onSave: (value: string) => Promise<unknown>; locked?: boolean }) {
  const [draft, setDraft] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const stages = splitStageLadder(value)
  if (draft !== null) return <form onSubmit={async event => {
    event.preventDefault()
    if (locked || saving) return
    setSaving(true); setError(null)
    try { await onSave(draft); setDraft(null) } catch (cause) { setError(cause) } finally { setSaving(false) }
  }}>
    <label className="mb-2 block text-xs text-ink-2" htmlFor="stage-ladder-draft">舞台阶梯原文（用 → 分隔）</label>
    <textarea id="stage-ladder-draft" className={inputClass} value={draft} rows={3} disabled={locked || saving} onChange={event => setDraft(event.target.value)} />
    <div className="mt-2 flex gap-2"><Button type="submit" size="sm" loading={saving} disabled={locked}>保存舞台阶梯</Button><Button type="button" size="sm" variant="ghost" disabled={saving} onClick={() => setDraft(null)}>取消</Button></div>
    <ErrorText error={error} />
  </form>
  if (stages.length < 2) return <EditableText value={value} onSave={onSave} locked={locked} multiline />
  return <div>
    <ol className="stage-ladder" aria-label="舞台阶梯">{stages.map((stage, index) => <li key={`${index}-${stage}`} className="stage-ladder-step" style={{ '--stage-index': index } as CSSProperties}>
      <p className="mb-2 text-xs text-ink-2">{index === 0 ? '第一张地图' : '写到再定'}</p><p className="font-serif text-base">{stage}</p>
    </li>)}</ol>
    {!locked && <Button size="sm" variant="ghost" onClick={() => { setError(null); setDraft(value) }} aria-label="改舞台阶梯">改</Button>}
  </div>
}
