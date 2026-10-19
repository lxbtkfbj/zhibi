import type { ButtonHTMLAttributes, ReactNode } from 'react'
import './settings.css'

export function SettingsGroup({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return <section className="settings-group"><div className="settings-group-heading"><h3>{title}</h3>{action}</div><div className="settings-list">{children}</div></section>
}

export function SettingsRow({ label, hint, children, extra, status, className = '' }: { className?: string; label: ReactNode; hint?: ReactNode; children?: ReactNode; extra?: ReactNode; status?: string }) {
  return <div className={`settings-row ${className}`}><div className="settings-row-main"><div className="settings-row-copy"><div className="settings-row-label">{label}{status && <span className="settings-save-status" role="status">{status}</span>}</div>{hint && <div className="settings-row-hint">{hint}</div>}</div>{children && <div className="settings-row-control">{children}</div>}</div>{extra && <div className="settings-row-extra">{extra}</div>}</div>
}

export function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: readonly { value: T; label: string }[]; onChange: (value: T) => void }) {
  return <div className="settings-segmented" role="group" aria-label={label}>{options.map(option => <button key={option.value} type="button" aria-pressed={value === option.value} className={value === option.value ? 'is-selected' : undefined} onClick={() => onChange(option.value)}>{option.label}</button>)}</div>
}

export function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <button type="button" className={`settings-toggle ${checked ? 'is-on' : ''}`} role="switch" aria-label={label} aria-checked={checked} onClick={() => onChange(!checked)}><span /></button>
}

export function Stepper({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <div className="settings-stepper"><button type="button" aria-label={`${label}减少`} disabled={value <= min} onClick={() => onChange(value - 1)}>－</button><output aria-label={label}>{value}</output><button type="button" aria-label={`${label}增加`} disabled={value >= max} onClick={() => onChange(value + 1)}>＋</button></div>
}

export function SettingsButton({ primary, danger, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; danger?: boolean }) {
  return <button type="button" {...props} className={`settings-button ${primary ? 'is-primary' : ''} ${danger ? 'is-danger' : ''} ${className}`} />
}
