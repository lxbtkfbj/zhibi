import type { WritingSettings as Settings } from '../../api/settings'
import { CHAPTER_WORDS_HINT, EFFORT_OPTIONS, EFFORT_PRESETS, INTIMACY_HINTS, INTIMACY_OPTIONS, PERSON_OPTIONS, effortHint, unusedCustomNote } from '../../lib/writingSettings'
import { Segmented, SettingsGroup, SettingsRow } from './SettingsList'

const titleHints: Record<Settings['title_style'], string> = {
  short: '2-6 个字，像《逆天邪神》',
  tomato: '主题：一句话卖点，像《苟道邪尊：平时低调发育，战时越境秒杀》',
  chief: '让主编按这本书的内容起名',
  custom: '写下你希望的书名或起名规矩',
}

/** 全局设置「新书默认」：之后新开的书照这个来。书名风格只在这里（新建页让编辑部起草书名时用）；
 *  停在哪由你定在每本书的开写页，写作要求、文风参考在每本书的本书设置里。 */
export function WritingSettings({ value, onChange, statuses = {} }: {
  value: Settings
  onChange: (changes: Partial<Settings>, debounce?: boolean) => void
  statuses?: Partial<Record<keyof Settings, string>>
}) {
  const intimacyNote = unusedCustomNote(value.intimacy, value.intimacy_custom)
  const titleNote = unusedCustomNote(value.title_style, value.title_custom)
  return <>
    <SettingsGroup title="起书名">
      <SettingsRow label="书名风格" hint={titleNote ? `${titleHints[value.title_style]}。${titleNote}` : titleHints[value.title_style]} status={statuses.title_style || statuses.title_custom}
        extra={value.title_style === 'custom' && <input className="settings-input w-full" aria-label="自己写的书名规矩" placeholder="写下你希望的书名或起名规矩" value={value.title_custom} onChange={event => onChange({ title_custom: event.target.value }, true)} />}>
        <Segmented label="书名风格" value={value.title_style} options={[{ value: 'short', label: '经典短书名' }, { value: 'tomato', label: '番茄长书名' }, { value: 'chief', label: '交给主编' }, { value: 'custom', label: '自己写' }]} onChange={title_style => onChange({ title_style })} />
      </SettingsRow>
    </SettingsGroup>
    <SettingsGroup title="写正文">
      <SettingsRow label="人称" status={statuses.person}><Segmented label="人称" value={value.person} options={PERSON_OPTIONS} onChange={person => onChange({ person })} /></SettingsRow>
      <SettingsRow label="亲密戏写到哪一步" hint={intimacyNote ? `${INTIMACY_HINTS[value.intimacy]}。${intimacyNote}` : INTIMACY_HINTS[value.intimacy]} status={statuses.intimacy || statuses.intimacy_custom}
        extra={value.intimacy === 'custom' && <input className="settings-input w-full" aria-label="自己写的亲密戏规矩" placeholder="写下亲密戏写到哪一步" value={value.intimacy_custom} onChange={event => onChange({ intimacy_custom: event.target.value }, true)} />}>
        <Segmented label="亲密戏写到哪一步" value={value.intimacy} options={INTIMACY_OPTIONS} onChange={intimacy => onChange({ intimacy })} />
      </SettingsRow>
      <SettingsRow label="每章字数" hint={`空着按每章 2500 字；${CHAPTER_WORDS_HINT}`} status={statuses.chapter_words}><input className="settings-input w-28" aria-label="每章字数" type="number" min={500} max={20000} step={100} placeholder="2500" value={value.chapter_words ?? ''} onChange={event => { const next = event.target.value; if (!next || (Number(next) >= 1 && Number(next) <= 100000)) onChange({ chapter_words: next ? Number(next) : null }, true) }} /></SettingsRow>
    </SettingsGroup>
    <SettingsGroup title="编辑部写得多仔细">
      <SettingsRow label="仔细程度" hint={effortHint(value)} status={statuses.effort_preset}>
        <Segmented label="编辑部写得多仔细" value={value.effort_preset} options={EFFORT_OPTIONS} onChange={effort_preset => { if (effort_preset !== 'custom') onChange({ effort_preset, ...EFFORT_PRESETS[effort_preset] }) }} />
      </SettingsRow>
    </SettingsGroup>
  </>
}
