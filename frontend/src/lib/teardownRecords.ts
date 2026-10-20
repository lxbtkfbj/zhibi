import type { TeardownChapterData } from '../api/types'

export interface TeardownRecordLine { text: string; name?: string; aliases?: string }
export interface TeardownRecordSection { title: string; lines: TeardownRecordLine[] }

/** 只呈现章上的原始记录；读者感觉、看点、钩子不在正文末尾重复。 */
export function teardownRecordSections(data: TeardownChapterData | null | undefined): TeardownRecordSection[] {
  if (data?.read_version == null || !data.read) return []
  const read = data.read
  return [
    { title: '出场的人', lines: (read.people ?? []).map(person => ({ name: person.name, aliases: person.also_called?.join('、'), text: `：${person.shown}${person.change ? `（${person.change}）` : ''}` })) },
    { title: '新冒出来的', lines: (read.things ?? []).map(thing => ({ text: `${thing.kind}${thing.kind === '秘密' && thing.secret ? `（${thing.secret}）` : ''}「${thing.name}」：${thing.note}${thing.belongs ? ` 属于 ${thing.belongs}` : ''}` })) },
    { title: '名场面', lines: (read.moments ?? []).map(moment => ({ text: `${moment.who}：${moment.what}——立住了${moment.shows}` })) },
    { title: '读者在等的', lines: (read.waits ?? []).map(wait => ({ text: `${wait.action}：${wait.what}` })) },
    { title: '用了的桥段', lines: read.tropes?.length ? [{ text: read.tropes.join('、') }] : [] },
  ].filter(section => section.lines.length > 0)
}
