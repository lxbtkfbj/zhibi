import { Fragment } from 'react'
import type { PromptReference, UsedPrompts as UsedPromptsInfo } from '../api/prompts'

function PromptNames({ prompts, separator, current, onSelect }: { prompts: PromptReference[]; separator: string; current?: string; onSelect: (name: string) => void }) {
  return <>{prompts.map((prompt, index) => <Fragment key={prompt.name}>
    {index > 0 && separator}
    {prompt.name === current ? <strong>{prompt.title}</strong> : <button type="button" className="prompt-text-link" onClick={() => onSelect(prompt.name)}>{prompt.title}</button>}
  </Fragment>)}</>
}

/** Both prompt details and call details use the same recorded source ordering. */
export function UsedPrompts({ used, current, onSelect, legacyLabel }: { used: UsedPromptsInfo; current?: string; onSelect: (name: string) => void; legacyLabel?: string }) {
  if (used.parts === null) return <div className="used-prompts used-prompts-legacy">
    {legacyLabel && <span className="used-prompts-label">{legacyLabel}</span>}
    <div><PromptNames prompts={used.names} separator="、" current={current} onSelect={onSelect} />（旧记录，分不出系统提示和用户提示）</div>
  </div>
  return <div className="used-prompts">{(['system', 'user'] as const).map(part => used.parts![part].length > 0 && <div className="used-prompts-row" key={part}>
    <span className="used-prompts-label">{part === 'system' ? '系统提示' : '用户提示'}</span>
    <div><PromptNames prompts={used.parts![part]} separator=" → " current={current} onSelect={onSelect} /></div>
  </div>)}</div>
}
