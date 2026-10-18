/** 编辑部帮拆：单元出章纲、卷拆成单元。先出一版草稿给作者看，作者改、删、收下才放进大纲；能再出一版，收下了也能撤销。 */

import clsx from 'clsx'
import { RotateCcw, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import type { VNode } from './model'
import { smallButton } from './styles'
import type { Draft, Split } from './useSplit'
import { Editable } from './widgets'

const CHAPTER_FIELDS = ['发生什么', '看点', '结尾钩子'] as const
/** 章名写成「第3章「药铺」」，还没起名的就写「第3章」 */
const chapterName = (title: string) => {
  const [number, name] = title.split('　')
  return name?.trim() ? `${number}「${name.trim()}」` : number
}
const primaryButton = 'h-9 rounded-lg bg-ink px-5 text-sm text-paper-2 transition-colors hover:bg-ink-2 disabled:opacity-40'


/** 一条草稿：章是名字加章纲三栏，单元是名字、一段话、章数。都能直接改。 */
function DraftCard({ draft, label, chapter, onEdit }: { draft: Draft; label: string; chapter: boolean; onEdit: (change: Partial<Draft>) => void }) {
  if (draft.dropped) {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed border-line-2 px-5 py-3 text-[14px] text-ink-3">
        <span className="line-through">{label}　{draft.name}</span>
        <span>不要了</span>
        <button type="button" onClick={() => onEdit({ dropped: false })} className="ml-auto text-chief hover:underline">放回来</button>
      </div>
    )
  }
  return (
    <div className="group/draft relative rounded-xl border border-line bg-card px-5 py-4 shadow-[0_1px_2px_rgb(60_40_20/0.06)]">
      <button type="button" onClick={() => onEdit({ dropped: true })} title={`不要这${chapter ? '一章' : '个单元'}`}
        className="absolute top-3 right-3 flex items-center gap-1 rounded-md px-2 py-1 text-[13px] text-ink-3 opacity-0 transition-opacity group-hover/draft:opacity-100 hover:bg-subtle hover:text-seal focus-visible:opacity-100">
        <X className="size-3.5" />不要这{chapter ? '一章' : '个单元'}
      </button>
      <div className="flex items-baseline gap-3 pr-28">
        <span className="shrink-0 font-serif text-[17px] font-bold text-ink">{label}</span>
        <Editable value={draft.name} placeholder="起个名字" className="font-serif text-[17px] font-bold text-ink"
          onSave={(name) => onEdit({ name: name.trim() || draft.name })} />
        {!chapter && <span className="ml-auto shrink-0 text-[13px] text-ink-3">{draft.chapters ? `${draft.chapters} 章` : '章数没定'}</span>}
      </div>
      {chapter ? (
        <dl className="mt-2.5 grid grid-cols-[4.5em_1fr] gap-x-3 gap-y-1.5 text-[14px] leading-relaxed">
          {CHAPTER_FIELDS.map((field) => (
            <div key={field} className="contents">
              <dt className="pt-px text-[13px] text-ink-3">{field}</dt>
              <dd><Editable multiline value={draft.sections?.[field] ?? ''} placeholder="还没写" className="text-ink-2"
                onSave={(text) => onEdit({ sections: { ...draft.sections, [field]: text } })} /></dd>
            </div>
          ))}
        </dl>
      ) : (
        <Editable multiline value={draft.text ?? ''} placeholder="这个单元讲什么" className="mt-2 text-[14px] leading-relaxed text-ink-2"
          onSave={(text) => onEdit({ text })} />
      )}
    </div>
  )
}

/** 帮拆的整块：说想要什么 → 主编在出 → 一版草稿（还没放进大纲），改、删、收下、再出一版、都不要。 */
export function SplitPanel({ node, split }: { node: VNode; split: Split }) {
  const [again, setAgain] = useState<string | null>(null)
  const { state } = split
  const chapter = node.kind === '单元'
  const unit = chapter ? '章' : '个单元'
  if (state.step === 'idle') return null

  if (state.step === 'ask') {
    return (
      <div className="mt-5 rounded-2xl border border-line bg-subtle p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-full bg-chief font-serif text-xs text-on-role">主</span>
          <p className="text-[15px] text-ink">{chapter ? '想让这个单元怎么展开成一章章？' : '想让这一卷分成哪几个小故事？'}</p>
          <button type="button" onClick={split.close} className="ml-auto text-[13px] text-ink-3 hover:text-ink">收起</button>
        </div>
        <textarea autoFocus value={state.request} onChange={(e) => split.setRequest(e.target.value)} rows={2}
          placeholder={chapter ? '比如：考核那场戏多给两章；第一章就要死人。不写也行，主编照这个单元那段话和前后的大纲来。' : '比如：先认识内门，再查讲经堂，最后停在老祖出关前。不写也行，主编照这一卷那段话来。'}
          className="w-full resize-none rounded-xl border border-line-2 bg-card px-4 py-3 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
        <div className="mt-3 flex items-center justify-between gap-4">
          <p className="text-xs text-ink-3">
            {chapter ? (node.count ? `照这个单元定的 ${node.count} 章出。` : '章数没定：主编按剧情定。') : '章数没定的，主编按剧情定。'}
            先出一版给你看，你收下了才放进大纲。
          </p>
          <button type="button" onClick={split.start} className={clsx(primaryButton, 'shrink-0')}>{chapter ? '出章纲' : '拆'}</button>
        </div>
        {state.error && <p className="mt-2 text-[13px] text-seal">{state.error}</p>}
      </div>
    )
  }

  if (state.step === 'working') {
    return (
      <div className="mt-5 rounded-2xl border-2 border-dashed border-chief/25 bg-chief-soft/30 p-5">
        <p className="flex items-center gap-1.5 text-[14px] text-chief"><Sparkles className="size-4" />主编在{chapter ? '出章纲' : '拆单元'}，一般要两三分钟，拆一整卷要四五分钟，出好了在这里给你看…</p>
        <div className="mt-4 space-y-3">
          {[0, 1, 2].map((i) => <div key={i} className="h-20 rounded-xl bg-card/70 motion-safe:animate-pulse" />)}
        </div>
      </div>
    )
  }

  const result = state.result!
  const kept = state.drafts.filter((d) => !d.dropped)
  const labelOf = (i: number) => (chapter ? `第${(result.first ?? 1) + i}章` : `单元${'一二三四五六七八九十'[i] ?? i + 1}`)
  // 不要的那几条不占章号：章号按留下的往下排
  const labels = state.drafts.map((d, i) => labelOf(d.dropped ? i : state.drafts.slice(0, i).filter((x) => !x.dropped).length))
  return (
    <div className="mt-5 rounded-2xl border-2 border-dashed border-chief/30 bg-chief-soft/25 p-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="flex size-7 items-center justify-center rounded-full bg-chief font-serif text-[13px] text-on-role">主</span>
        <p className="font-serif text-[18px] font-bold text-ink">主编出的{chapter ? '章纲' : '单元'} · {state.drafts.length} {unit}</p>
        {state.round > 1 && <span className="text-[13px] text-ink-3">第 {state.round} 版</span>}
        <span className="ml-auto rounded-full border border-chief/30 bg-card px-2.5 py-0.5 text-xs text-chief">草稿 · 还没放进大纲</span>
      </div>
      {result.note && <p className="mt-3 text-[14px] leading-relaxed text-ink-2">主编：{result.note}</p>}
      <p className="mt-2 text-[14px] leading-relaxed text-ink-2">
        哪一{chapter ? '章' : '个'}不对，直接在下面改，或者点它右上角的「不要这{chapter ? '一章' : '个单元'}」；满意就收下。
      </p>
      {(result.keeps.length > 0 || result.replaces.length > 0) && (
        <p className="mt-2 rounded-lg bg-card/80 px-3.5 py-2 text-[13px] leading-relaxed text-seal-dark">
          收下以后：{result.replaces.length ? `${result.replaces.map(chapterName).join('、')}的章纲换成下面的` : '下面的接在后面'}
          {result.keeps.length > 0 && `；${result.keeps.map((t) => t.split('　')[0]).join('、')}已经写好了，不动`}。
        </p>
      )}
      <div className="mt-5 space-y-3">
        {state.drafts.map((draft, i) => <DraftCard key={i} draft={draft} chapter={chapter} label={labels[i]} onEdit={(change) => split.edit(i, change)} />)}
      </div>
      {state.error && <p className="mt-3 text-[13px] text-seal">{state.error}</p>}
      {again !== null ? (
        <div className="mt-5 rounded-xl border border-line bg-card p-4">
          <p className="mb-2 text-[14px] text-ink">这一版哪里不对？（可以不写，主编换个排法）</p>
          <textarea autoFocus value={again} onChange={(e) => setAgain(e.target.value)} rows={2} placeholder="比如：考场那场戏太短，拆成两章；第 8 章太顺"
            className="w-full resize-none rounded-lg border border-line-2 bg-card px-3.5 py-2.5 text-[15px] leading-relaxed text-ink [field-sizing:content] placeholder:text-ink-3 focus:border-ink-3 focus:outline-none" />
          <div className="mt-2.5 flex justify-end gap-2">
            <button type="button" onClick={() => setAgain(null)} className="h-9 rounded-lg px-3 text-sm text-ink-2 hover:bg-subtle">取消</button>
            <button type="button" onClick={() => { split.again(again); setAgain(null) }} className={primaryButton}>再出一版</button>
          </div>
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-chief/20 pt-5">
          <button type="button" onClick={split.accept} disabled={!kept.length} className={primaryButton}>收下这 {kept.length} {unit}</button>
          <button type="button" onClick={() => setAgain('')} className={clsx(smallButton, 'flex h-9 items-center gap-1.5 px-4 text-sm')}><RotateCcw className="size-3.5" />再出一版</button>
          <button type="button" onClick={split.close} className="h-9 rounded-lg px-3 text-sm text-ink-3 hover:bg-card/70 hover:text-ink">都不要</button>
          <span className="ml-auto text-xs text-ink-3">收下了才放进大纲；收下以后也能撤销。</span>
        </div>
      )}
    </div>
  )
}
