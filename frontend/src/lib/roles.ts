import type { Speaker } from '../api/types'

export interface RoleMeta {
  name: string
  short: string
  text: string
  bg: string
  ring: string
  dot: string
  duty: string
}

export const ROLE_META: Record<Speaker, RoleMeta> = {
  chief: {
    name: '主编',
    short: '编',
    text: 'text-chief',
    bg: 'bg-chief-soft',
    ring: 'ring-chief/30',
    dot: 'bg-chief',
    duty: '方向、大纲、章纲',
  },
  lorekeeper: {
    name: '设定师',
    short: '设',
    text: 'text-lore',
    bg: 'bg-lore-soft',
    ring: 'ring-lore/30',
    dot: 'bg-lore',
    duty: '人物、世界观、伏笔台账',
  },
  writer: {
    name: '写手',
    short: '写',
    text: 'text-writer',
    bg: 'bg-writer-soft',
    ring: 'ring-writer/30',
    dot: 'bg-writer',
    duty: '正文',
  },
  reviewer: {
    name: '审稿',
    short: '审',
    text: 'text-reviewer',
    bg: 'bg-reviewer-soft',
    ring: 'ring-reviewer/30',
    dot: 'bg-reviewer',
    duty: '审稿意见',
  },
  author: { name: '作者', short: '我', text: 'text-paper-2', bg: 'bg-ink', ring: 'ring-ink/30', dot: 'bg-ink', duty: '拍板' },
  system: { name: '系统', short: '·', text: 'text-ink-3', bg: 'bg-line', ring: 'ring-line-2', dot: 'bg-ink-3', duty: '' },
}

export const BOOK_STATUS: Record<string, { label: string; tone: 'busy' | 'wait' | 'ok' | 'idle' }> = {
  setting_up: { label: '编辑部开书中', tone: 'busy' },
  awaiting_approval: { label: '等你拍板', tone: 'wait' },
  ready: { label: '方案已定稿', tone: 'ok' },
  writing: { label: '写作中', tone: 'busy' },
}

export const JOB_STATUS: Record<string, string> = {
  queued: '排队中',
  running: '编辑部工作中',
  waiting_author: '等你拍板',
  succeeded: '已完成',
  failed: '出错了',
  cancelled: '已停止',
}

export const ROLE_KEYS = ['default', 'chief', 'lorekeeper', 'writer', 'reviewer', 'router'] as const
export const ROLE_KEY_LABEL: Record<(typeof ROLE_KEYS)[number], string> = {
  router: '群聊分流',
  default: '默认（未单独指定的角色都用它）',
  chief: '主编',
  lorekeeper: '设定师',
  writer: '写手',
  reviewer: '审稿',
}
