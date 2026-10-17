import type { Pending } from '../api/types'
import { cleanVolumeTitle } from './status.ts'

export interface DecisionCopy {
  eyebrow: string
  title: string
  hint: string
  approve: string
  placeholder: string
  links: [string, string][]
  issues?: string[]
}

/** 等作者拍板的几种情况：开书方案、某一卷的卷纲、前几章试读、重写两次仍未通过的章节。 */
export function decisionCopy(pending: Pending | null | undefined, bookId: string): DecisionCopy {
  const base = `/books/${bookId}`
  switch (pending?.kind) {
    case 'segment_review':
      if (pending.flow === 2) return { eyebrow: '下一步 · 定下一篇', title: `待你确认：第 ${pending.number} 篇`, hint: '这一篇是按旧写法规划的，要按新写法重出一次', approve: '按新写法重出', placeholder: '先在大纲里按新写法重出这一篇', links: [[`第 ${pending.number} 篇`, `${base}/outline?node=pending`]] }
      return {
        eyebrow: '下一步 · 定下一篇',
        title: `待你确认：第 ${pending.number} 篇`,
        hint: '主编已经定好下一篇的走向与分卷。想调整的地方在对话框里说；确认后照常拆卷纲。',
        approve: '确认这一篇',
        placeholder: '说说下一篇想怎么改…',
        links: [[`第 ${pending.number} 篇`, `${base}/outline?node=pending`]],
        issues: pending.warnings ?? [],
      }
    case 'volume_review': {
      const issues = [...(pending.issues ?? [])]
      if (pending.node_update && !issues.some(issue => issue.startsWith('节点调整：'))) {
        const proposal = pending.node_update
        issues.push(`节点调整：没锁的节点 ${proposal.index}「${proposal.current.title}」拟改为「${proposal.proposed.title}」；${proposal.reason}（批准卷纲后应用）`)
      }
      return {
        eyebrow: '下一步 · 卷纲拍板',
        title: `第${pending.volume}卷《${cleanVolumeTitle(pending.title)}》的卷纲拆好了`,
        hint: issues.length
          ? '主编把这一卷拆成了剧情单元；下面是待你确认的提醒与节点提议。哪里不对就告诉主编怎么改；满意就盖章开写，没锁的节点提议会随批准应用。'
          : '主编把这一卷拆成了剧情单元，比稿选出这一版，审稿又专门查过反派、节奏、伏笔、套路重复和期待感。哪里不对就告诉主编怎么改；满意就盖章开写。',
        approve: '批准开写',
        placeholder: '例如：第三单元太拖，压缩一下；女主在这一卷多一些戏份',
        links: [[`第${pending.volume}卷卷纲`, `${base}/outline?node=volume-${pending.volume}`], ['线索', `${base}/threads`]],
        issues,
      }
    }
    case 'chapters_review':
      return { eyebrow: '下一步 · 章纲拍板', title: `「${pending.unit_title}」的章纲写好了`, hint: `第 ${pending.first}–${pending.last} 章。先看看剧情、爽点和钩子；确认后再写正文。`, approve: '批准开写', placeholder: '说说这个单元的章纲想怎么改…', links: [['查看章纲', `${base}/outline?node=unit-${pending.unit_id}`]] }
    case 'trial_read':
      return {
        eyebrow: '下一步 · 试读',
        title: `前 ${pending.chapters} 章写好了，请你试读`,
        hint: '读一读开头几章：文风、节奏、人物哪里不对就直接说，之后每一章都照你说的写；满意就让编辑部继续。',
        approve: '继续写',
        placeholder: '例如：对话太多，节奏再快一点；主角说话再狠一些',
        links: [['读第 1 章', `${base}/chapter/1`], ['目录', `${base}/chapters`]],
      }
    case 'chapter_stuck':
      return {
        eyebrow: '需要你定夺',
        title: `第${pending.chapter}章《${pending.title}》重写两次仍未通过`,
        hint: '审稿还有意见没解决。先读一读：觉得能用就直接定稿；想让写手再改，就告诉他怎么改。',
        approve: '定稿',
        placeholder: '例如：打斗那段删掉，直接写结果',
        links: [['读这一章', `${base}/chapter/${pending.chapter}`]],
        issues: pending.issues,
      }
    default:
      return {
        eyebrow: '下一步 · 拍板',
        title: '开书方案已就绪，等你过目',
        hint: '先看看概念、线索、总纲和第一卷卷纲，觉得哪里不对可以直接改。满意就盖章批准；想让编辑部改，就写下你的意见。',
        approve: '盖章批准',
        placeholder: '例如：女主出场太晚了，第一单元就让她登场；反派的动机再狠一点。',
        links: [
          ['书的概念', `${base}/concept`],
          ['线索', `${base}/threads`],
          ['第一卷卷纲', `${base}/volume/1`],
          ['人物', `${base}/characters`],
        ],
      }
  }
}
