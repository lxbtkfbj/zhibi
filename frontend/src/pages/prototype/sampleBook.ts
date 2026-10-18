/** 工作台原型用的两本假书：理想样子的示例书，和刚开的空书。只为看样子，不连后台。 */

import {
  CATEGORY_HINTS, CHARACTER_PLACEHOLDERS, GOLDFINGER_PLACEHOLDERS, defaultCategories, linkMentions,
  type VBook, type VCategory, type VEntry, type VNode,
} from './model'

interface CharacterInput {
  id: string
  name: string
  oneLine: string
  tags?: string[]
  role: string
  alias?: string
  gender?: string
  age?: string
  long: Partial<Record<'外貌' | '性格与说话方式' | '身世' | '想要什么' | '能力' | '和主角的关系' | '备注', string>>
  now?: { 想要?: string; 在哪?: string; 处境?: string; 活着?: string }
  relations?: VEntry['relations']
  secret?: string
  goldfinger?: string
}

function character(c: CharacterInput): VEntry {
  const labels = ['外貌', '性格与说话方式', '身世', '想要什么', '能力', ...(c.role === '主角' ? [] : ['和主角的关系']), '备注'] as const
  return {
    id: c.id, kind: 'character', category: '角色', name: c.name, oneLine: c.oneLine, tags: c.tags ?? [], locked: false, role: c.role,
    facts: [['别名', c.alias ?? ''], ['定位', c.role], ['性别', c.gender ?? ''], ['年龄', c.age ?? '']],
    sections: labels.map((label) => ({ label, text: c.long[label] ?? '', placeholder: CHARACTER_PLACEHOLDERS[label] })),
    now: c.now ? [['想要', c.now.想要 ?? ''], ['在哪', c.now.在哪 ?? ''], ['处境', c.now.处境 ?? ''], ['活着', c.now.活着 ?? '']] : undefined,
    relations: c.relations, secret: c.secret, goldfinger: c.goldfinger, appears: [],
  }
}

function paragraph(category: string, e: { id: string; name: string; oneLine: string; body: string; tags?: string[]; locked?: boolean; parent?: string; knownBy?: string }): VEntry {
  return {
    id: e.id, kind: 'paragraph', category, name: e.name, oneLine: e.oneLine, tags: e.tags ?? [], locked: !!e.locked, parent: e.parent,
    facts: e.knownBy ? [['谁知道', e.knownBy]] : [],
    sections: [{ label: '详细', text: e.body, placeholder: `一段话写清：${CATEGORY_HINTS[category]?.join('；') ?? ''}。` }],
    appears: [],
  }
}

const categories: VCategory[] = [
  {
    name: '角色',
    hints: CATEGORY_HINTS.角色,
    entries: [
      character({
        id: 'chenmo', name: '陈默', oneLine: '外门杂役，一睁眼就能看见所有人头顶剩下的寿命。', tags: ['主角'], role: '主角', alias: '小默子', gender: '男', age: '十七岁',
        long: {
          外貌: '瘦，肤色偏黑，走路总低着头；右手少了半截小指。',
          性格与说话方式: '胆小是装的，记仇是真的。话少，开口先算账；被逼急了反而会笑。',
          身世: '山下猎户家的孩子，十二岁被卖进宗门做杂役。另有秘密。',
          想要什么: '长远：活下去，弄清是谁在收割整座宗门。\n眼下：熬过三天后的外门考核。',
          能力: '炼气一层，靠的是窥命之眼。',
        },
        now: { 想要: '躲过那枚筑基丹', 在哪: '外门杂役院', 处境: '被传功执事盯上', 活着: '活着' },
        relations: [
          { to: 'zhao', kind: '上司', text: '正盯着他，要他吃下丹药' },
          { to: 'laozu', kind: '宿敌', text: '还没见过面，命数却连在一起' },
          { to: 'sun', kind: '恩人', text: '杂役院做饭的婆婆，偷偷给他留过半个馒头' },
        ],
        secret: 'origin', goldfinger: 'eye',
      }),
      character({
        id: 'zhao', name: '赵长河', oneLine: '笑眯眯的传功执事，头顶只剩三天寿命，却还在给弟子发丹药。', tags: ['第一卷'], role: '对手', gender: '男', age: '看着五十，实际一百一十岁',
        long: {
          外貌: '圆脸，总是笑，袖口永远干干净净。',
          性格与说话方式: '说话慢，爱拍人肩膀，从不发火；越客气越危险。',
          想要什么: '在死前把这一批“筑基丹”发完。',
          能力: '筑基后期，掌管外门传功堂。',
          和主角的关系: '陈默所在杂役院的上司。',
        },
        now: { 想要: '让陈默吃下丹药', 在哪: '传功堂', 处境: '寿命只剩三天', 活着: '活着' },
        relations: [{ to: 'chenmo', kind: '下属', text: '盯上了这个装傻的杂役' }, { to: 'laozu', kind: '主子', text: '替老祖发丹' }],
      }),
      character({ id: 'laozu', name: '青冥老祖', oneLine: '号称与天地同寿的宗门老祖，头顶的数字只剩一个时辰。', role: '对手', gender: '男', long: {} }),
      character({ id: 'sun', name: '孙婆婆', oneLine: '杂役院做饭的婆婆，头顶的数字从来不动。', role: '配角', gender: '女', age: '不知道', long: { 外貌: '矮，背驼，总系一条洗得发白的围裙。' } }),
    ],
  },
  {
    name: '金手指',
    hints: CATEGORY_HINTS.金手指,
    entries: [
      {
        id: 'eye', kind: 'goldfinger', category: '金手指', name: '窥命之眼', oneLine: '看得见所有人头顶剩下的寿命，看得越久，折自己的寿越多。', tags: ['金手指'], locked: false, holder: 'chenmo',
        facts: [['是什么', '天生的眼睛', GOLDFINGER_PLACEHOLDERS.是什么], ['谁知道', '只有陈默自己', GOLDFINGER_PLACEHOLDERS.谁知道]],
        sections: [
          { label: '能做什么', text: '看得见活人头顶剩下的寿命，精确到时辰。', placeholder: GOLDFINGER_PLACEHOLDERS.能做什么 },
          { label: '规矩和限制', text: '只能看活人；隔着镜子、画像看不见；一次只能盯一个人。', placeholder: GOLDFINGER_PLACEHOLDERS.规矩和限制 },
          { label: '代价', text: '盯着一个人超过十息，自己就少一天寿命。', placeholder: GOLDFINGER_PLACEHOLDERS.代价 },
          { label: '怎么变强', text: '第一阶：看寿命。\n第二阶：看寿命从哪来、往哪去。\n第三阶：以后再定。', placeholder: GOLDFINGER_PLACEHOLDERS.怎么变强 },
          { label: '来历', text: '另有秘密。', placeholder: GOLDFINGER_PLACEHOLDERS.来历 },
        ],
        secret: 'origin', appears: [],
      },
    ],
  },
  {
    name: '等级体系',
    hints: CATEGORY_HINTS.等级体系,
    entries: [
      {
        id: 'realm', kind: 'ladder', category: '等级体系', name: '修炼境界', oneLine: '每破一境多一甲子寿命，所以人人都在拼命往上爬。', tags: [], locked: false, facts: [], sections: [],
        overview: '往上升靠灵气和丹药，越往上越慢。越级极难：境界差一层，寿命差一截，打起来先怕死的那个输。',
        levels: [
          { name: '炼气', text: '分九层，外门弟子大多卡在这里。' },
          { name: '筑基', text: '寿命翻倍。宗门发的“筑基丹”是唯一捷径。' },
          { name: '金丹', text: '可以开宗立派，青冥宗只有七位。' },
          { name: '元婴', text: '' },
        ],
        appears: [],
      },
    ],
  },
  {
    name: '世界与地图',
    hints: CATEGORY_HINTS.世界与地图,
    entries: [
      paragraph('世界与地图', { id: 'world', name: '世界概况', oneLine: '灵气一年比一年稀薄，寿命成了修士最值钱的东西。', body: '东洲七宗分据七山，青冥宗居首。凡人六十而终，修士靠境界续命；境界卡住的人，只能另想办法。钱用灵石，但真正的硬通货是寿元。' }),
      paragraph('世界与地图', { id: 'outer', name: '青冥宗外门', oneLine: '青冥宗山脚的一圈院落，三千外门弟子。', body: '' }),
      paragraph('世界与地图', { id: 'yard', name: '外门杂役院', oneLine: '青冥宗最底下的地方，三百杂役挤在一座山坳里。', parent: 'outer', body: '每月初一发一次丹药，每年一次外门考核。考不过的人就“下山”了，再没人见过。杂役之间互相盯着，谁多领了一口饭，第二天全院都知道。' }),
    ],
  },
  {
    name: '势力划分',
    hints: CATEGORY_HINTS.势力划分,
    entries: [paragraph('势力划分', { id: 'sect', name: '青冥宗', oneLine: '东洲第一宗，表面仙风道骨，暗地敲骨吸髓。', body: '' })],
  },
  {
    name: '物品与功法',
    hints: CATEGORY_HINTS.物品与功法,
    entries: [
      paragraph('物品与功法', { id: 'pill', name: '筑基丹', oneLine: '宗门每年发给外门弟子的“恩赐”，吃过的人寿命都停在同一天。', tags: ['第一卷'], body: '丹房出的，每年初一由传功执事亲手发。吃下去当场破境，三年之内却都会在同一个日子“坐化”。现在陈默手里有一枚没吃的。' }),
    ],
  },
  {
    name: '往事与秘密',
    hints: CATEGORY_HINTS.往事与秘密,
    entries: [
      paragraph('往事与秘密', { id: 'secret', name: '老祖的寿命', oneLine: '老祖靠“筑基丹”把弟子的寿命收到自己身上。', tags: ['底牌'], locked: true, knownBy: '只有你和编辑部', body: '三百年来，每一枚筑基丹都是一张“借命契”。吃丹的人破境越快，被收走的寿命越多。老祖头顶只剩一个时辰，是因为今年的丹还没收回来。' }),
      paragraph('往事与秘密', { id: 'origin', name: '陈默的来历', oneLine: '陈默是老祖当年收命时漏下的一个孩子，所以他的眼睛看得见寿命。', knownBy: '只有你和编辑部；打算第二篇揭开', body: '' }),
    ],
  },
  { name: '特殊规则', hints: CATEGORY_HINTS.特殊规则, starters: ['寿命能不能转给别人', '宗门门规', '“下山”是什么意思'], entries: [] },
]

const outline: VNode = {
  id: 'book', kind: '全书', title: '全书', text: '陈默掀了青冥宗的命簿，自己却成了下一个看守它的人。', uses: ['chenmo', 'laozu', 'secret'],
  children: [
    {
      id: 'part1', kind: '篇', title: '第一篇　外门求生', uses: [],
      text: '舞台是青冥宗外门。陈默想在外门考核前活下来，挡路的是给弟子发“筑基丹”的传功执事。这一篇以陈默揭穿丹药的真相、借执事之死换来进内门的名额收尾。读者一直在等：头顶数字归零的人，到底是怎么死的。',
      children: [
        {
          id: 'v1', kind: '卷', title: '第一卷　杂役院', chapters: 12, locked: true, uses: [],
          text: '这一卷陈默要做成一件事：在不暴露眼睛的前提下，活过赵长河发丹的那一天。卷首他还是任人使唤的杂役；卷末，他看着赵长河在众目睽睽之下化成一具枯骨，而自己手里多了一枚没吃的筑基丹。',
          children: [
            {
              id: 'u1', kind: '单元', title: '单元一　递丹之局', chapters: 4, uses: [],
              text: '赵长河当众点名，要把一枚筑基丹赏给陈默。陈默看见执事头顶只剩三天，也看见吃过丹的师兄寿命全停在同一天。他装病躲丹，被逼到墙角时，借一场意外把丹换了出去。',
              children: [
                { id: 'c1', kind: '章', title: '第1章　三天', text: '', uses: [], sections: [{ label: '发生什么', text: '陈默第一次看见所有人头顶的数字，最长的那个属于传功执事赵长河——只剩三天。' }, { label: '看点', text: '一个杂役看穿了整个宗门的死期。' }, { label: '结尾钩子', text: '执事笑着朝他招手：“陈默，过来领丹。”' }] },
                { id: 'c2', kind: '章', title: '第2章　筑基丹', text: '', uses: [], sections: [{ label: '发生什么', text: '陈默装病躲丹，发现吃过筑基丹的师兄们寿命都停在同一天。' }, { label: '看点', text: '同一个日期，像一张死亡名单。' }, { label: '结尾钩子', text: '那一天，就是三天后。' }] },
                { id: 'c3', kind: '章', title: '第3章　少半截的小指', text: '', uses: [], sections: [{ label: '发生什么', text: '赵长河亲自上门送丹，陈默用断指的旧伤骗过搜身。' }, { label: '看点', text: '装傻和算计。' }, { label: '结尾钩子', text: '执事走时回头看了他一眼，头顶的数字变了。' }] },
                { id: 'c4', kind: '章', title: '第4章　执事的数字', text: '', uses: [], sections: [{ label: '发生什么', text: '陈默发现赵长河的寿命不是在减，而是在被“收走”。' }, { label: '看点', text: '真相露出一角。' }, { label: '结尾钩子', text: '收走寿命的那只手，来自后山的青冥老祖。' }] },
              ],
            },
            { id: 'u2', kind: '单元', title: '单元二　外门考核', chapters: 5, uses: [], text: '考核前夜，外门杂役院死了第一个人。陈默要在考核里不出头、不垫底，还得弄清谁动的手。' },
            { id: 'u3', kind: '单元', title: '单元三　借命', chapters: 3, uses: [], text: '赵长河死期到了。陈默把那枚没吃的筑基丹，换成了进内门的门票。' },
          ],
        },
        { id: 'v2', kind: '卷', title: '第二卷　内门试炼', later: true, uses: [], text: '暂定：进了内门，陈默发现内门弟子头顶的数字，全都指向同一个时辰。' },
      ],
    },
    { id: 'part2', kind: '篇', title: '第二篇', later: true, uses: [], text: '' },
  ],
}

export const SAMPLE_BOOK: VBook = {
  id: 'sample',
  title: '窥命长生',
  channel: '男频',
  genre: '仙侠',
  tags: ['天赋觉醒', '苟道', '宗门', '智斗'],
  length: 200,
  chapterWords: 2500,
  blurb: '头顶还剩三天寿命的传功执事，正一脸慈祥地递来一枚“筑基丹”。\n底层杂役陈默一睁眼，就能看破所有人的剩余寿数。\n在这座表面仙风道骨、暗地敲骨吸髓的吃人宗门里，别人的死期，就是他的生机。\n所有人都以为他平平无奇，直到某天，他撞见了那位号称与天地同寿的宗门老祖——\n老祖头顶上的数字，赫然只剩一个时辰。',
  categories,
  folded: [],
  outline,
  pending: 2,
}
linkMentions(SAMPLE_BOOK)

/** 刚点完「下一步」的书：只有新建页填的几项。设成都市，看「按题材收起用不上的类别」。 */
export function emptyBook(): VBook {
  const genre = '都市'
  const shown = defaultCategories(genre)
  return {
    id: 'empty',
    title: '未命名',
    channel: '男频',
    genre,
    tags: ['系统', '重生'],
    length: 200,
    chapterWords: 2500,
    blurb: '重生回高考前一晚，这次我只想安安静静当个学渣。',
    categories: shown.map((name) => ({ name, hints: CATEGORY_HINTS[name] ?? [], entries: [] })),
    folded: ['等级体系', '物品与功法'],
    outline: { id: 'book', kind: '全书', title: '全书', text: '', uses: [] },
    pending: 0,
  }
}

export const PENDING = [
  { id: 'p1', text: '境界改名后，「外门杂役院」里还写着“灵海”，要不要一起换？' },
  { id: 'p2', text: '大纲里出现了新人物「孙婆婆」，要给她建一张角色卡吗？' },
]

export const CHAT = [
  { who: '主编', text: '简介我看了，开局“递丹”那一下很抓人。设定和大纲还空着，要我按简介先补一版吗？你写过的不会动。' },
  { who: '作者', text: '先别，我自己想想主角。' },
  { who: '主编', text: '好，想好了叫我。主角的“想要什么”写具体些，后面大纲好接。' },
]
