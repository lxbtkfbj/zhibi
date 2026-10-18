/** 工作台原型的数据形状：示例书、空书、旧书快照、书架上的真书，都先转成这个样子再画。 */

export interface VField {
  label: string
  text: string
  placeholder?: string
}

export interface VEntry {
  id: string
  kind: 'character' | 'goldfinger' | 'paragraph' | 'ladder'
  /** 归在哪一类（显示名） */
  category: string
  name: string
  oneLine: string
  tags: string[]
  locked: boolean
  /** 角色的定位，用来在目录里分组 */
  role?: string
  /** 右边资料卡里的短字段：名称、内容、空着时的提示 */
  facts: [string, string, string?][]
  /** 正文里一段一段的长字段 */
  sections: VField[]
  /** 角色此刻的状态，设定师每章更新；全空就不显示 */
  now?: [string, string][]
  relations?: { to: string; kind: string; text: string }[]
  /** 身世里「另有秘密」指向的条目 */
  secret?: string
  /** 角色的金手指条目 / 金手指的主人 */
  goldfinger?: string
  holder?: string
  overview?: string
  levels?: { name: string; text: string }[]
  /** 地点属于哪里：父条目 id */
  parent?: string
  appears: { node: string; label: string }[]
}

export interface VCategory {
  name: string
  hints: string[]
  starters?: string[]
  entries: VEntry[]
  /** 作者自建的类别：样式和卡片的栏目 */
  custom?: { style: 'paragraph' | 'card' | 'ladder'; fields: string[] }
}

export interface VNode {
  id: string
  kind: '全书' | '篇' | '卷' | '单元' | '章'
  title: string
  text: string
  /** 章纲：发生什么、看点、结尾钩子 */
  sections?: VField[]
  chapters?: number
  later?: boolean
  locked?: boolean
  uses: string[]
  children?: VNode[]
}

export interface VBook {
  id: string
  title: string
  channel: string
  genre: string
  tags: string[]
  length?: number
  chapterWords: number
  blurb: string
  categories: VCategory[]
  outline: VNode
  pending: number
}

export const ALL_CATEGORIES = ['角色', '金手指', '等级体系', '世界与地图', '势力划分', '物品与功法', '往事与秘密', '特殊规则']

/**
 * 默认显示哪几类。原本按题材收起用不上的，但题材猜不准：《神秘复苏》是都市却有鬼的等级，
 * 《惊悚乐园》有专精等级和纸并强凶狂神。空类别只占目录一行，所以八类一律全显示。
 */
export function defaultCategories(_genre: string): string[] {
  return ALL_CATEGORIES
}

export const CATEGORY_HINTS: Record<string, string[]> = {
  角色: ['有名有姓、会再出场的人', '会说话的器灵、系统人格也算'],
  金手指: ['是什么、能做什么', '有什么规矩和限制、要付什么代价', '怎么一步步变强', '从哪来，最好落在底牌上'],
  等级体系: ['怎么往上升、越级多难、有什么代价', '各级写名称和一段介绍，按高低排', '高阶的可以先只列名字，以后再补'],
  世界与地图: ['这是什么地方，给人什么感觉', '属于哪里、谁说了算', '有什么规矩或危险', '主角在这里处境如何、能得到什么'],
  势力划分: ['什么组织、想要什么', '谁领头、实力多大', '和主角是敌是友', '内部有什么矛盾'],
  物品与功法: ['是什么东西或什么本事', '有什么用、有什么限制', '从哪来、谁想要它', '现在在谁手里'],
  往事与秘密: ['过去发生了什么，或藏着什么真相', '谁知道、谁不知道', '打算什么时候、怎么揭开', '和主角有什么关系'],
  特殊规则: ['管什么、怎么运作', '有什么限制和代价', '会给故事制造什么麻烦或机会'],
}

/** 角色卡的字段（照真实设定库），定位按这个顺序分组。 */
export const ROLE_ORDER = ['主角', '女主', '男主', '班底', '对手', '导师', '配角']
export const LEGACY_ROLES: Record<string, string> = { 反派: '对手', 龙套: '配角' }

export const CHARACTER_PLACEHOLDERS: Record<string, string> = {
  外貌: '一两处让人记住的地方就够了，比如疤、小动作',
  性格与说话方式: '怎么说话最能看出这个人：话多话少、爱用什么词',
  身世: '公开的来历；藏着的写进「往事与秘密」，这里标一句「另有秘密」',
  想要什么: '长远想要什么，眼下想要什么',
  能力: '会什么本事，有什么限制',
  和主角的关系: '对主角来说，他是谁',
  备注: '随手记：口头禅、忌讳、以后可能用上的点子',
}

export const GOLDFINGER_PLACEHOLDERS: Record<string, string> = {
  是什么: '系统、物品、体质、功法、重生记忆……',
  谁知道: '谁知道主角有它',
  能做什么: '读者最爽的那一下是什么',
  规矩和限制: '什么时候能用、什么时候不能用',
  代价: '用一次要付出什么；代价越痛，故事越好看',
  怎么变强: '它会怎么升级，每一级多出什么本事',
  来历: '从哪来；最好落在底牌上',
}

const DIGITS = '零一二三四五六七八九'
/** 1→一，12→十二，25→二十五 */
export function cn(n: number): string {
  if (n < 10) return DIGITS[n]
  if (n < 20) return `十${n % 10 ? DIGITS[n % 10] : ''}`
  if (n < 100) return `${DIGITS[Math.floor(n / 10)]}十${n % 10 ? DIGITS[n % 10] : ''}`
  return String(n)
}

export function findEntry(book: VBook, id: string): VEntry | undefined {
  for (const category of book.categories) {
    const entry = category.entries.find((e) => e.id === id)
    if (entry) return entry
  }
  return undefined
}

export function findNode(node: VNode, id: string, path: VNode[] = []): VNode[] | null {
  if (node.id === id) return [...path, node]
  for (const child of node.children ?? []) {
    const found = findNode(child, id, [...path, node])
    if (found) return found
  }
  return null
}

/** 把条目名字在大纲里出现的地方连起来：条目的「出现在」和大纲节点的「用到的设定」。 */
export function linkMentions(book: VBook): void {
  const entries = book.categories.flatMap((c) => c.entries)
  const visit = (node: VNode) => {
    const text = [node.text, ...(node.sections ?? []).map((s) => s.text)].join('\n')
    for (const entry of entries) {
      const names = [entry.name.replace(/（.*?）|\(.*?\)/g, '')].filter((n) => n.length >= 2)
      if (!node.uses.includes(entry.id) && names.some((n) => text.includes(n))) node.uses.push(entry.id)
      if (node.uses.includes(entry.id) && node.kind !== '全书' && entry.appears.length < 4 && !entry.appears.some((a) => a.node === node.id)) {
        entry.appears.push({ node: node.id, label: node.title })
      }
    }
    node.uses = node.uses.slice(0, 10)
    node.children?.forEach(visit)
  }
  visit(book.outline)
}
