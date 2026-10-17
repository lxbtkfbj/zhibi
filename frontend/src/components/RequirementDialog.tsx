import { useState } from 'react'
import { Button, ErrorText, inputClass, Modal } from './ui'
import { REQUIREMENT_SCOPES, type RequirementScope } from '../lib/chat'

export function ScopeSelect({ value, onChange }: { value: RequirementScope; onChange: (value: RequirementScope) => void }) {
  return <label className="block space-y-2 text-sm"><span>有效范围</span><select aria-label="有效范围" className={`${inputClass} w-full`} value={value} onChange={event => onChange(event.target.value as RequirementScope)}>{REQUIREMENT_SCOPES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
}

export function RequirementDialog({ initial, scope = 'always', onClose, onSave }: { initial: string; scope?: RequirementScope; onClose: () => void; onSave: (text: string, scope: RequirementScope) => Promise<unknown> }) {
  const [text, setText] = useState(initial)
  const [value, setValue] = useState(scope)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const save = async () => { if (busy || !text.trim()) return; setBusy(true); setError(null); try { await onSave(text.trim(), value); onClose() } catch (cause) { setError(cause) } finally { setBusy(false) } }
  return <Modal open title="要记下的要求" onClose={() => !busy && onClose()} footer={<><Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button><Button loading={busy} disabled={!text.trim()} onClick={() => void save()}>记下</Button></>}><div className="space-y-4"><textarea autoFocus aria-label="要记下的要求" className={`${inputClass} min-h-28 w-full`} value={text} onChange={event => setText(event.target.value)} /><ScopeSelect value={value} onChange={setValue} /><ErrorText error={error} /></div></Modal>
}
