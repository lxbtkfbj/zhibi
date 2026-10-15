import { ArrowLeft, CheckCircle2, Eye, EyeOff, X, XCircle } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { get } from '../api/client'
import { useProfileMutations, useProfiles, useRoles } from '../api/hooks'
import { useNewBookDefaults, useSettingsEditor, type SettingsResponse } from '../api/settings'
import type { LlmProfile, LlmProfileInput, RoleKey } from '../api/types'
import { ErrorText, Spinner } from '../components/ui'
import { ModelSelector } from '../components/ModelSelector'
import { Segmented, SettingsButton, SettingsGroup, SettingsRow, Stepper, Toggle } from '../components/settings/SettingsList'
import { RulesPreview, WritingSettings } from '../components/settings/WritingSettings'
import { ROLE_KEY_LABEL, ROLE_KEYS } from '../lib/roles'
import { useAppearance } from '../lib/appearance'

const PRESETS = [
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus' },
  { name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: 'Kimi', base_url: 'https://api.moonshot.cn/v1', model: 'kimi-latest' },
  { name: '本地 Ollama', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen3.5:4b' },
]
const EMPTY: LlmProfileInput = { name: '', provider: 'openai_compatible', base_url: '', api_key: '', model: '', temperature: 0.8, max_tokens: null, structured_method: 'function_calling', timeout_s: 300, reasoning_effort: '' }

/** A page within the settings window, never another dialog. */
function ProfileForm({ profile, onBack }: { profile: LlmProfile | null; onBack: () => void }) {
  const { create, update } = useProfileMutations()
  const apiKeyId = useId()
  const [showKey, setShowKey] = useState(false)
  const [form, setForm] = useState<LlmProfileInput>(profile ? { ...EMPTY, ...profile, api_key: '', reasoning_effort: profile.reasoning_effort ?? '' } : EMPTY)
  const set = <K extends keyof LlmProfileInput>(key: K, value: LlmProfileInput[K]) => setForm(previous => ({ ...previous, [key]: value }))
  const mutation = profile ? update : create
  const submit = async () => {
    try {
      if (profile) await update.mutateAsync({ id: profile.id, ...form })
      else await create.mutateAsync(form)
      onBack()
    } catch { /* Render the mutation error without discarding the form. */ }
  }
  return <div className="settings-profile-form">
    <div className="mb-5 flex items-center gap-3"><SettingsButton onClick={onBack} disabled={mutation.isPending}><ArrowLeft className="size-3.5" />返回</SettingsButton><h3 className="text-sm text-ink">{profile ? `修改「${profile.name}」` : '添加模型配置'}</h3></div>
    <SettingsGroup title="模型连接">
      {!profile && <SettingsRow label="快速填写"><select className="settings-select" aria-label="快速填写" defaultValue="" onChange={event => { if (event.target.value === 'demo') setForm({ ...EMPTY, name: '演示模式', provider: 'demo' }); else { const preset = PRESETS.find(item => item.name === event.target.value); if (preset) setForm(previous => ({ ...previous, ...preset, provider: 'openai_compatible', reasoning_effort: preset.name.includes('Ollama') ? 'none' : previous.reasoning_effort })) } }}><option value="" disabled>选择服务商</option>{PRESETS.map(preset => <option key={preset.name}>{preset.name}</option>)}<option value="demo">演示模式（不联网）</option></select></SettingsRow>}
      <SettingsRow label="名称"><input aria-label="模型配置名称" value={form.name} onChange={event => set('name', event.target.value)} className="settings-input" placeholder="例如：DeepSeek" /></SettingsRow>
      {form.provider !== 'demo' && <>
        <SettingsRow label="接口地址" hint="OpenAI 兼容接口，一般以 /v1 结尾" extra={<input aria-label="接口地址" value={form.base_url} onChange={event => set('base_url', event.target.value)} className="settings-input" placeholder="https://…/v1" />} />
        <SettingsRow label={<label htmlFor={apiKeyId}>API Key</label>} hint={profile?.has_key ? '已保存不回显；留空表示不修改' : '加密保存在本机'} extra={<div className="relative"><input id={apiKeyId} type={showKey ? 'text' : 'password'} value={form.api_key} onChange={event => set('api_key', event.target.value)} className="settings-input !pr-9" placeholder={profile?.has_key ? '••••••••' : 'sk-…'} autoComplete="off" autoCapitalize="none" spellCheck={false} /><button type="button" aria-label={showKey ? '隐藏 API Key' : '显示 API Key'} aria-pressed={showKey} aria-controls={apiKeyId} disabled={!form.api_key} onClick={() => setShowKey(!showKey)} className="absolute inset-y-0 right-0 flex w-8 items-center justify-center text-ink-2 disabled:opacity-40">{showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}</button></div>} />
        <div className="settings-row"><ModelSelector compact value={form.model} onChange={model => set('model', model)} baseUrl={form.base_url} apiKey={form.api_key} profileId={profile?.id} /></div>
      </>}
    </SettingsGroup>
    {form.provider !== 'demo' && <SettingsGroup title="高级参数">
      <SettingsRow label="温度" hint="越高越有创意"><input aria-label="温度" type="number" step={0.1} min={0} max={2} value={form.temperature} onChange={event => set('temperature', Number(event.target.value))} className="settings-input" /></SettingsRow>
      <SettingsRow label="最大输出 token" hint="留空使用模型默认值"><input aria-label="最大输出 token" type="number" min={1} value={form.max_tokens ?? ''} onChange={event => set('max_tokens', event.target.value ? Number(event.target.value) : null)} className="settings-input" /></SettingsRow>
      <SettingsRow label="结构化输出方式" hint="不支持时会自动降级"><select aria-label="结构化输出方式" value={form.structured_method} onChange={event => set('structured_method', event.target.value as LlmProfileInput['structured_method'])} className="settings-select"><option value="function_calling">工具调用（推荐）</option><option value="json_mode">JSON 模式</option><option value="json_schema">JSON Schema</option></select></SettingsRow>
      <SettingsRow label="推理强度" hint="思考型模型可调；Ollama 设为 none 关闭思考"><select aria-label="推理强度" value={form.reasoning_effort} onChange={event => set('reasoning_effort', event.target.value)} className="settings-select"><option value="">不设置（模型默认）</option><option value="none">none（不思考，最快）</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select></SettingsRow>
      <SettingsRow label="超时（秒）"><input aria-label="超时（秒）" type="number" min={1} value={form.timeout_s} onChange={event => set('timeout_s', Number(event.target.value))} className="settings-input" /></SettingsRow>
    </SettingsGroup>}
    <ErrorText error={mutation.error} />
    <div className="mt-5 flex justify-end gap-2"><SettingsButton disabled={mutation.isPending} onClick={onBack}>取消</SettingsButton><SettingsButton primary disabled={mutation.isPending || !form.name.trim() || (form.provider !== 'demo' && (!form.base_url.trim() || !form.model.trim()))} onClick={() => void submit()}>{mutation.isPending ? '保存中…' : '保存'}</SettingsButton></div>
  </div>
}

function ProfileRow({ profile, onEdit }: { profile: LlmProfile; onEdit: () => void }) {
  const { remove, test } = useProfileMutations()
  return <SettingsRow label={profile.name} hint={profile.provider === 'demo' ? '演示模式 · 内置示例内容，不联网' : `${profile.model} · ${profile.has_key ? '已保存密钥' : '未填 Key'}`} extra={<>
    {test.data && <p className={`flex items-center gap-1 text-xs ${test.data.ok ? 'text-lore' : 'text-seal'}`}>{test.data.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}{test.data.message}</p>}
    <ErrorText error={remove.error || test.error} />
  </>}><SettingsButton disabled={test.isPending} onClick={() => test.mutate(profile.id)}>{test.isPending ? '测试中…' : '测试'}</SettingsButton><SettingsButton onClick={onEdit}>修改</SettingsButton><SettingsButton danger disabled={remove.isPending} onClick={() => { if (confirm(`删除「${profile.name}」？`)) remove.mutate(profile.id) }}>删除</SettingsButton></SettingsRow>
}

function ModelsPanel() {
  const profiles = useProfiles()
  const roles = useRoles()
  const { setRoles } = useProfileMutations()
  const [editing, setEditing] = useState<LlmProfile | 'new' | null>(null)
  if (editing) return <ProfileForm key={editing === 'new' ? 'new' : editing.id} profile={editing === 'new' ? null : editing} onBack={() => setEditing(null)} />
  return <>
    <SettingsGroup title="模型列表" action={<SettingsButton onClick={() => setEditing('new')}>＋ 添加</SettingsButton>}>
      {profiles.isLoading && <SettingsRow label={<Spinner />} />}
      {profiles.error && <SettingsRow label={<ErrorText error={profiles.error} />} />}
      {profiles.data?.length === 0 && <SettingsRow label="还没有模型配置" hint="没有配置时，编辑部使用演示模式生成示例内容。" />}
      {profiles.data?.map(profile => <ProfileRow key={profile.id} profile={profile} onEdit={() => setEditing(profile)} />)}
    </SettingsGroup>
    <SettingsGroup title="编辑部分工">
      {roles.error && <SettingsRow label={<ErrorText error={roles.error} />} />}
      {ROLE_KEYS.map(role => <SettingsRow key={role} label={role === 'default' ? '默认' : ROLE_KEY_LABEL[role]} hint={role === 'default' ? '未单独指定的角色都用它' : undefined}><select aria-label={`${role === 'default' ? '默认' : ROLE_KEY_LABEL[role]}使用的模型`} value={roles.data?.[role] ?? ''} disabled={!roles.data || setRoles.isPending} onChange={event => setRoles.mutate({ [role]: event.target.value || null } as Partial<Record<RoleKey, string | null>>)} className="settings-select max-w-60"><option value="">{role === 'default' ? '未设置，使用第一个配置' : '跟随默认'}</option>{profiles.data?.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></SettingsRow>)}
    </SettingsGroup>
    <ErrorText error={setRoles.error} />
  </>
}

function AppearancePanel() {
  const { appearance, setAppearance } = useAppearance()
  return <>
    <SettingsGroup title="阅读">
      <SettingsRow label="主题"><Segmented label="主题" value={appearance.theme} options={[{ value: 'paper', label: '宣纸·亮' }, { value: 'ink', label: '墨色·暗' }, { value: 'system', label: '跟随系统' }]} onChange={theme => setAppearance({ theme })} /></SettingsRow>
      <SettingsRow label="正文字体"><Segmented label="正文字体" value={appearance.font} options={[{ value: 'song', label: '宋体' }, { value: 'kai', label: '楷体' }, { value: 'hei', label: '黑体' }]} onChange={font => setAppearance({ font })} /></SettingsRow>
      <SettingsRow label="正文字号"><Stepper label="正文字号" value={appearance.readingSize} min={15} max={20} onChange={readingSize => setAppearance({ readingSize })} /></SettingsRow>
      <SettingsRow label="行距"><Segmented label="行距" value={appearance.readingLeading} options={[{ value: 'compact', label: '紧凑' }, { value: 'standard', label: '标准' }, { value: 'relaxed', label: '宽松' }]} onChange={readingLeading => setAppearance({ readingLeading })} /></SettingsRow>
    </SettingsGroup>
    <SettingsGroup title="界面">
      <SettingsRow label="界面文字"><Segmented label="界面文字" value={appearance.uiScale} options={[{ value: 'standard', label: '标准' }, { value: 'large', label: '大一号' }]} onChange={uiScale => setAppearance({ uiScale })} /></SettingsRow>
      <SettingsRow label="减少动效" hint="关掉打字机、滑入这些动画"><Toggle label="减少动效" checked={appearance.reducedMotion} onChange={reducedMotion => setAppearance({ reducedMotion })} /></SettingsRow>
    </SettingsGroup>
  </>
}

function DefaultsEditor({ initial }: { initial: SettingsResponse }) {
  const editor = useSettingsEditor(initial, '/settings/new-book-defaults', 'PUT')
  return <><p className="mb-5 text-xs leading-5 text-ink-3">自动保存。只影响之后新开的书；已有书保留自己的设置。</p>{!!editor.error && <div className="mb-4"><ErrorText error={editor.error} /><SettingsButton onClick={editor.retry}>重试保存</SettingsButton></div>}<WritingSettings value={editor.value} onChange={editor.update} statuses={editor.statuses} /><RulesPreview text={editor.rulesText} /></>
}
function DefaultsPanel() {
  const query = useNewBookDefaults()
  if (query.isLoading) return <Spinner />
  if (!query.data) return <><ErrorText error={query.error} /><SettingsButton onClick={() => void query.refetch()}>重试</SettingsButton></>
  return <DefaultsEditor initial={query.data} />
}

interface UsageTotals { calls: number; prompt_tokens: number | null; completion_tokens: number | null }
interface UsageSummary { items: (UsageTotals & { book_id: string | null; book_title: string; role: string })[]; total: UsageTotals }
function UsagePanel() {
  const query = useQuery({ queryKey: ['global-usage'], queryFn: () => get<UsageSummary>('/usage') })
  const number = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString('zh-CN')
  return <SettingsGroup title="用量">
    {query.isLoading && <SettingsRow label={<Spinner />} />}
    {query.error && <SettingsRow label={<ErrorText error={query.error} />} />}
    {query.data && <div className="overflow-x-auto"><table className="settings-table"><thead><tr><th>书名</th><th>角色</th><th className="numeric">调用</th><th className="numeric">输入 token</th><th className="numeric">输出 token</th></tr></thead><tbody>{query.data.items.map(item => <tr key={`${item.book_id ?? 'global'}:${item.role}`}><td>{item.book_title || '未归属书籍'}</td><td>{ROLE_KEY_LABEL[item.role as RoleKey] ?? item.role}</td><td className="numeric">{number(item.calls)}</td><td className="numeric">{number(item.prompt_tokens)}</td><td className="numeric">{number(item.completion_tokens)}</td></tr>)}{!query.data.items.length && <tr><td colSpan={5}>还没有调用记录</td></tr>}</tbody><tfoot><tr><td colSpan={2}>合计</td><td className="numeric">{number(query.data.total.calls)}</td><td className="numeric">{number(query.data.total.prompt_tokens)}</td><td className="numeric">{number(query.data.total.completion_tokens)}</td></tr></tfoot></table></div>}
  </SettingsGroup>
}

const TABS = [{ key: 'models', label: '模型' }, { key: 'appearance', label: '外观' }, { key: 'defaults', label: '新书默认' }, { key: 'usage', label: '用量' }] as const
function SettingsWindow({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<(typeof TABS)[number]['key']>('models')
  const dialog = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => { closeRef.current = onClose }, [onClose])
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.current?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); closeRef.current() }
      if (event.key !== 'Tab') return
      const elements = Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]') ?? []).filter(element => element.getClientRects().length > 0)
      const first = elements[0]
      const last = elements.at(-1)
      if (!first) { event.preventDefault(); return }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.current)) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); document.body.style.overflow = previousOverflow; previousFocus?.focus() }
  }, [])
  return <div className="settings-modal-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}><div ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="settings-title" className="settings-modal">
    <header className="settings-modal-heading"><h2 id="settings-title">设置</h2><SettingsButton aria-label="关闭设置" onClick={onClose}><X className="size-4" /></SettingsButton></header>
    <div className="settings-modal-body"><nav className="settings-modal-nav" aria-label="设置分页"><div role="tablist" aria-orientation="vertical" className="flex flex-col gap-1">{TABS.map(item => <button key={item.key} id={`settings-tab-${item.key}`} role="tab" aria-selected={tab === item.key} aria-controls="settings-panel" onClick={() => setTab(item.key)}>{item.label}</button>)}</div><Link to="/prompts" onClick={onClose}>提示词与调用记录 →</Link></nav>
      <div id="settings-panel" role="tabpanel" aria-labelledby={`settings-tab-${tab}`} className="settings-modal-content scroll-thin">{tab === 'models' && <ModelsPanel />}{tab === 'appearance' && <AppearancePanel />}{tab === 'defaults' && <DefaultsPanel />}{tab === 'usage' && <UsagePanel />}</div>
    </div>
  </div></div>
}

export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return open ? createPortal(<SettingsWindow onClose={onClose} />, document.body) : null
}
