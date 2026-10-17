import { useState, type ReactNode } from 'react'
import type { WritingSettings as Settings } from '../../api/settings'
import { Segmented, SettingsButton, SettingsGroup, SettingsRow, Stepper, Toggle } from './SettingsList'

const titleHints: Record<Settings['title_style'], string> = {
  short: '2-6 个字，像《逆天邪神》',
  tomato: '主题：一句话卖点，像《苟道邪尊：平时低调发育，战时越境秒杀》',
  chief: '让主编按这本书的内容起名',
  custom: '写下你希望的书名或起名规矩',
}
const intimacyHints: Record<Settings['intimacy'], string> = {
  heart: '只写心动、暧昧和拉扯，不写亲吻以上',
  fade: '可以写亲吻拥抱，再进一步就一笔带过',
  custom: '写下亲密戏的边界，编辑部会原样遵守',
}
const EFFORT_PRESETS = {
  quick: { max_rewrites: 1, pitches: 1, volume_audit: false, review_strictness: 'lenient' as const },
  balanced: { max_rewrites: 2, pitches: 2, volume_audit: true, review_strictness: 'standard' as const },
  premium: { max_rewrites: 3, pitches: 3, volume_audit: true, review_strictness: 'strict' as const },
}
const strictnessNames = { lenient: '宽松', standard: '标准', strict: '严格' }

export function WritingSettings({ value, onChange, statuses = {}, currentPlaybook, afterPreferences }: {
  value: Settings
  onChange: (changes: Partial<Settings>, debounce?: boolean) => void
  statuses?: Partial<Record<keyof Settings, string>>
  currentPlaybook?: string
  afterPreferences?: ReactNode
}) {
  const [editingRules, setEditingRules] = useState(false)
  const effortHint = `重写最多 ${value.max_rewrites} 次 · 卷纲出 ${value.pitches} 个方案${value.pitches > 1 ? '比稿' : ''} · ${value.volume_audit ? '做' : '不做'}专项审稿 · ${strictnessNames[value.review_strictness]}审稿`
  return <>
    <SettingsGroup title="写作偏好">
      <SettingsRow label="书名风格" hint={titleHints[value.title_style]} status={statuses.title_style || statuses.title_custom}
        extra={value.title_style === 'custom' && <input className="settings-input w-full" aria-label="自己写的书名规矩" placeholder="写下你希望的书名或起名规矩" value={value.title_custom} onChange={event => onChange({ title_custom: event.target.value }, true)} />}>
        <Segmented label="书名风格" value={value.title_style} options={[{ value: 'short', label: '经典短书名' }, { value: 'tomato', label: '番茄长书名' }, { value: 'chief', label: '交给主编' }, { value: 'custom', label: '自己写', custom: true }]} onChange={title_style => onChange({ title_style })} />
      </SettingsRow>
      <SettingsRow label="人称" status={statuses.person}><Segmented label="人称" value={value.person} options={[{ value: 'first', label: '第一人称' }, { value: 'second', label: '第二人称' }, { value: 'third', label: '第三人称' }]} onChange={person => onChange({ person })} /></SettingsRow>
      <SettingsRow label="亲密戏写到哪一步" hint={intimacyHints[value.intimacy]} status={statuses.intimacy || statuses.intimacy_custom}
        extra={value.intimacy === 'custom' && <input className="settings-input w-full" aria-label="自己写的亲密戏规矩" placeholder="写下亲密戏的边界" value={value.intimacy_custom} onChange={event => onChange({ intimacy_custom: event.target.value }, true)} />}>
        <Segmented label="亲密戏写到哪一步" value={value.intimacy} options={[{ value: 'heart', label: '只写心动' }, { value: 'fade', label: '点到为止' }, { value: 'custom', label: '自己写', custom: true }]} onChange={intimacy => onChange({ intimacy })} />
      </SettingsRow>
      <SettingsRow label="每章字数" hint="留空表示交给主编" status={statuses.chapter_words}><input className="settings-input w-28" aria-label="每章字数" type="number" min={1} max={100000} step={100} placeholder="交给主编" value={value.chapter_words ?? ''} onChange={event => { const next = event.target.value; if (!next || (Number(next) >= 1 && Number(next) <= 100000)) onChange({ chapter_words: next ? Number(next) : null }, true) }} /></SettingsRow>
      <SettingsRow label="其他规矩" hint={value.other_rules.trim() ? `已写 ${value.other_rules.split('\n').filter(line => line.trim()).length} 条，每行一条` : '每行一条，原样交给编辑部'} status={statuses.other_rules}
        extra={editingRules && <textarea className="settings-textarea" aria-label="其他规矩" rows={4} value={value.other_rules} placeholder="每行一条" onChange={event => onChange({ other_rules: event.target.value }, true)} />}><SettingsButton aria-expanded={editingRules} onClick={() => setEditingRules(!editingRules)}>{editingRules ? '收起' : '编辑'}</SettingsButton></SettingsRow>
      <SettingsRow label="题材打法" status={statuses.playbook}><select aria-label="题材打法" className="settings-select" value={value.playbook} onChange={event => onChange({ playbook: event.target.value as Settings['playbook'] })}><option value="auto">{currentPlaybook ? `自动匹配（当前：${currentPlaybook}）` : '自动匹配（开书后按题材匹配）'}</option><option value="harem_xuanhuan">后宫玄幻爽文</option><option value="general">通用</option></select></SettingsRow>
    </SettingsGroup>
    {afterPreferences}
    <SettingsGroup title="编辑部力度">
      <SettingsRow label="力度" hint={effortHint} status={statuses.effort_preset} extra={value.effort_preset === 'custom' && <div className="settings-subrows">
        <SettingsRow label="不合格最多重写几次" status={statuses.max_rewrites}><Stepper label="不合格最多重写几次" value={value.max_rewrites} min={0} max={5} onChange={max_rewrites => onChange({ max_rewrites })} /></SettingsRow>
        <SettingsRow label="卷纲出几个方案比稿" status={statuses.pitches}><Stepper label="卷纲出几个方案比稿" value={value.pitches} min={1} max={4} onChange={pitches => onChange({ pitches })} /></SettingsRow>
        <SettingsRow label="审稿松紧" status={statuses.review_strictness}><Segmented label="审稿松紧" value={value.review_strictness} options={[{ value: 'lenient', label: '宽松' }, { value: 'standard', label: '标准' }, { value: 'strict', label: '严格' }]} onChange={review_strictness => onChange({ review_strictness })} /></SettingsRow>
        <SettingsRow label="卷纲专项审稿" status={statuses.volume_audit}><Toggle label="卷纲专项审稿" checked={value.volume_audit} onChange={volume_audit => onChange({ volume_audit })} /></SettingsRow>
      </div>}>
        <Segmented label="力度" value={value.effort_preset} options={[{ value: 'quick', label: '省时' }, { value: 'balanced', label: '均衡' }, { value: 'premium', label: '精品' }, { value: 'custom', label: '自定义', custom: true }]} onChange={effort_preset => onChange({ effort_preset, ...(effort_preset === 'custom' ? {} : EFFORT_PRESETS[effort_preset]) })} />
      </SettingsRow>
      <SettingsRow label="每卷卷纲都要我拍板" status={statuses.volume_approval}><Toggle label="每卷卷纲都要我拍板" checked={value.volume_approval} onChange={volume_approval => onChange({ volume_approval })} /></SettingsRow>
      <SettingsRow label="每一篇开写前先给我确认" hint="关掉后，主编定好下一篇就直接往下写，群聊里会告诉你；大纲地图上会标出新规划的篇，节点是暂定的，之后仍然可以改。" status={statuses.segment_approval}><Toggle label="每一篇开写前先给我确认" checked={value.segment_approval ?? true} onChange={segment_approval => onChange({ segment_approval })} /></SettingsRow>
      <SettingsRow label="新书前 3 章先给我试读" status={statuses.trial_read}><Toggle label="新书前 3 章先给我试读" checked={value.trial_read} onChange={trial_read => onChange({ trial_read })} /></SettingsRow>
    </SettingsGroup>
  </>
}

export function RulesPreview({ text }: { text: string }) {
  return <section className="settings-preview"><h3>实际发给编辑部的话</h3><p>开书各步、卷纲、章纲、正文、审稿都会带上</p><pre>{text || '（未填写写作规矩）'}</pre><p>（后面接着是作者要求清单里的每一条）</p></section>
}
