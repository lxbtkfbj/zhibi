import { CheckCircle2, Eye, EyeOff, Pencil, Plug, Plus, Trash2, XCircle } from 'lucide-react'
import { type ReactNode, useId, useState } from 'react'
import { useProfileMutations, useProfiles, useRoles } from '../api/hooks'
import type { LlmProfile, LlmProfileInput, RoleKey } from '../api/types'
import { Badge, Button, Card, EmptyState, ErrorText, inputClass, Label, Modal, Spinner } from '../components/ui'
import { Diamond } from '../components/decor'
import { ModelSelector } from '../components/ModelSelector'
import { ROLE_KEY_LABEL, ROLE_KEYS } from '../lib/roles'

const PRESETS: { name: string; base_url: string; model: string }[] = [
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
  { name: '智谱 GLM', base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus' },
  { name: '通义千问', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { name: 'Kimi', base_url: 'https://api.moonshot.cn/v1', model: 'kimi-latest' },
  { name: '本地 Ollama', base_url: 'http://127.0.0.1:11434/v1', model: 'qwen3.5:4b' },
]

const EMPTY: LlmProfileInput = {
  name: '',
  provider: 'openai_compatible',
  base_url: '',
  api_key: '',
  model: '',
  temperature: 0.8,
  max_tokens: null,
  structured_method: 'function_calling',
  timeout_s: 300,
  reasoning_effort: '',
}

const advancedInputClass = `${inputClass} h-11`

function AdvancedField({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block min-w-0">
      <Label>{title}</Label>
      {children}
      {hint && <span className="mt-1.5 block text-xs leading-5 text-ink-3">{hint}</span>}
    </label>
  )
}

function ProfileDialog({ profile, onClose }: { profile: LlmProfile | null; onClose: () => void }) {
  const { create, update } = useProfileMutations()
  const apiKeyId = useId()
  const [showApiKey, setShowApiKey] = useState(false)
  const [form, setForm] = useState<LlmProfileInput>(
    profile ? { ...EMPTY, ...profile, api_key: '', reasoning_effort: profile.reasoning_effort ?? '' } : EMPTY,
  )
  const set = <K extends keyof LlmProfileInput>(key: K, value: LlmProfileInput[K]) => setForm((f) => ({ ...f, [key]: value }))
  const mutation = profile ? update : create
  const isDemo = form.provider === 'demo'

  const submit = async () => {
    if (profile) await update.mutateAsync({ id: profile.id, ...form })
    else await create.mutateAsync(form)
    onClose()
  }

  return (
    <Modal
      open
      stableHeight={!isDemo}
      onClose={onClose}
      title={profile ? `修改「${profile.name}」` : '添加模型配置'}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} loading={mutation.isPending} disabled={!form.name.trim()}>
            保存
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!profile && (
          <div>
            <Label>快速填写</Label>
            <div className="flex flex-wrap gap-2">
              {PRESETS.map((p) => (
                <button
                  key={p.name}
                  onClick={() =>
                    setForm((f) => ({
                      ...f,
                      provider: 'openai_compatible',
                      name: f.name || p.name,
                      base_url: p.base_url,
                      model: p.model,
                      reasoning_effort: p.name.includes('Ollama') ? 'none' : f.reasoning_effort,
                    }))
                  }
                  className="rounded-full border border-line-2 bg-card px-3 py-1 text-xs hover:border-seal/40 hover:text-seal"
                >
                  {p.name}
                </button>
              ))}
              <button
                onClick={() => setForm({ ...EMPTY, name: '演示模式', provider: 'demo' })}
                className="rounded-full border border-dashed border-line-2 px-3 py-1 text-xs text-ink-3 hover:text-ink"
              >
                演示模式（不联网）
              </button>
            </div>
          </div>
        )}
        <label className="block">
          <Label>名称</Label>
          <input value={form.name} onChange={(e) => set('name', e.target.value)} className={inputClass} placeholder="例如：DeepSeek" />
        </label>
        {!isDemo && (
          <>
            <label className="block">
              <Label hint="OpenAI 兼容接口，一般以 /v1 结尾">接口地址</Label>
              <input value={form.base_url} onChange={(e) => set('base_url', e.target.value)} className={inputClass} placeholder="https://…/v1" />
            </label>
            <div>
              <label htmlFor={apiKeyId}>
                <Label hint={profile?.has_key ? '已保存不回显；留空表示不修改' : '加密保存在本机'}>API Key</Label>
              </label>
              <div className="relative">
                <input
                  id={apiKeyId}
                  type={showApiKey ? 'text' : 'password'}
                  value={form.api_key}
                  onChange={(e) => set('api_key', e.target.value)}
                  className={`${inputClass} h-11 pr-11`}
                  placeholder={profile?.has_key ? '••••••••' : 'sk-…'}
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                />
                <button
                  type="button"
                  aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                  aria-pressed={showApiKey}
                  aria-controls={apiKeyId}
                  title={profile?.has_key && !form.api_key ? '已保存的密钥不会回显；只能显示本次输入的密钥' : showApiKey ? '隐藏 API Key' : '显示 API Key'}
                  disabled={!form.api_key}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => setShowApiKey((visible) => !visible)}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-xl text-ink-3 hover:text-ink focus-visible:outline-2 focus-visible:outline-seal disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {showApiKey ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>
            <ModelSelector
              value={form.model}
              onChange={(value) => set('model', value)}
              baseUrl={form.base_url}
              apiKey={form.api_key}
              profileId={profile?.id}
            />
            <details className="rounded-lg border border-line px-3 py-2">
              <summary className="cursor-pointer text-sm text-ink-2">高级参数</summary>
              <div className="mt-4 grid gap-x-4 gap-y-4 sm:grid-cols-2">
                <AdvancedField title="温度" hint="越高越有创意">
                  <input type="number" step={0.1} min={0} max={2} value={form.temperature} onChange={(e) => set('temperature', Number(e.target.value))} className={advancedInputClass} />
                </AdvancedField>
                <AdvancedField title="最大输出 token" hint="留空使用模型默认值">
                  <input
                    type="number"
                    value={form.max_tokens ?? ''}
                    onChange={(e) => set('max_tokens', e.target.value ? Number(e.target.value) : null)}
                    className={advancedInputClass}
                  />
                </AdvancedField>
                <AdvancedField title="结构化输出方式" hint="不支持时会自动降级">
                  <select value={form.structured_method} onChange={(e) => set('structured_method', e.target.value as LlmProfileInput['structured_method'])} className={advancedInputClass}>
                    <option value="function_calling">工具调用（推荐）</option>
                    <option value="json_mode">JSON 模式</option>
                    <option value="json_schema">JSON Schema</option>
                  </select>
                </AdvancedField>
                <AdvancedField title="推理强度" hint="思考型模型可调；Ollama 设为 none 关闭思考">
                  <select value={form.reasoning_effort} onChange={(e) => set('reasoning_effort', e.target.value)} className={advancedInputClass}>
                    <option value="">不设置（模型默认）</option>
                    <option value="none">none（不思考，最快）</option>
                    <option value="low">low</option>
                    <option value="medium">medium</option>
                    <option value="high">high</option>
                  </select>
                </AdvancedField>
                <AdvancedField title="超时（秒）">
                  <input type="number" value={form.timeout_s} onChange={(e) => set('timeout_s', Number(e.target.value))} className={advancedInputClass} />
                </AdvancedField>
              </div>
            </details>
          </>
        )}
        <ErrorText error={mutation.error} />
      </div>
    </Modal>
  )
}

function ProfileRow({ profile, onEdit }: { profile: LlmProfile; onEdit: () => void }) {
  const { remove, test } = useProfileMutations()
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 font-medium">
          {profile.name}
          {profile.provider === 'demo' && <Badge>演示</Badge>}
          {profile.provider !== 'demo' && !profile.has_key && <Badge tone="wait">未填 Key</Badge>}
        </p>
        <p className="truncate text-xs text-ink-3">{profile.provider === 'demo' ? '内置示例内容，不联网' : `${profile.model} · ${profile.base_url}`}</p>
        {test.data && (
          <p className={`mt-1 flex items-center gap-1 text-xs ${test.data.ok ? 'text-lore' : 'text-seal'}`}>
            {test.data.ok ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
            {test.data.message}
          </p>
        )}
      </div>
      <div className="flex gap-1">
        <Button size="sm" variant="ghost" onClick={() => test.mutate(profile.id)} loading={test.isPending}>
          <Plug className="size-4" />
          测试
        </Button>
        <Button size="sm" variant="ghost" onClick={onEdit}>
          <Pencil className="size-4" />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => confirm(`删除「${profile.name}」？`) && remove.mutate(profile.id)}>
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  )
}

export function SettingsPage() {
  const { data: profiles, isLoading } = useProfiles()
  const { data: roles } = useRoles()
  const { setRoles } = useProfileMutations()
  const [editing, setEditing] = useState<LlmProfile | null | 'new'>(null)

  return (
    <div>
      <div className="mx-auto max-w-3xl space-y-10 px-5 pt-8 pb-20 sm:px-8">
        <section>
          <div className="mb-5 flex items-end justify-between gap-4">
            <div>
              <p className="mb-2 flex items-center gap-2 text-xs tracking-[0.25em] text-ink-3">
                <Diamond />
                设置
              </p>
              <h1 className="font-serif text-3xl font-bold">模型设置</h1>
              <p className="mt-2 text-[15px] text-ink-2">支持任何 OpenAI 兼容接口：DeepSeek、智谱、通义、Kimi、本地 Ollama 等。</p>
            </div>
            <Button variant="primary" onClick={() => setEditing('new')}>
              <Plus className="size-4" />
              添加
            </Button>
          </div>
          <Card>
            {isLoading && (
              <div className="flex justify-center py-10 text-ink-3">
                <Spinner />
              </div>
            )}
            {profiles?.length === 0 && (
              <EmptyState title="还没有模型配置">没有配置时，编辑部使用「演示模式」生成示例内容。</EmptyState>
            )}
            {profiles?.map((p) => <ProfileRow key={p.id} profile={p} onEdit={() => setEditing(p)} />)}
          </Card>
        </section>

        {profiles && profiles.length > 0 && roles && (
          <section>
            <h2 className="mb-1 font-serif text-xl font-bold">编辑部分工</h2>
            <p className="mb-3 text-sm text-ink-3">每个角色可以用不同的模型，比如写手用文笔好的，审稿用便宜快的。</p>
            <Card className="divide-y divide-line overflow-hidden">
              {ROLE_KEYS.map((role) => (
                <label key={role} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <span className="text-sm">{ROLE_KEY_LABEL[role]}</span>
                  <select
                    value={roles[role] ?? ''}
                    onChange={(e) => setRoles.mutate({ [role]: e.target.value || null } as Partial<Record<RoleKey, string | null>>)}
                    className="min-w-48 rounded-lg border border-line-2 bg-card px-3 py-1.5 text-sm"
                  >
                    <option value="">{role === 'default' ? '（未设置，使用第一个配置）' : '跟随默认'}</option>
                    {profiles.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </Card>
          </section>
        )}
      </div>
      {editing && <ProfileDialog profile={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
