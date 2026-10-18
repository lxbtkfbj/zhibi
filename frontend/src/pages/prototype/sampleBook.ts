/** 工作台原型用的假书：只为看样子，不连后台。 */

export interface SampleField {
  label: string
  text: string
}

export interface SampleEntry {
  id: string
  name: string
  oneLine: string
  tags?: string[]
  locked?: boolean
  fields?: SampleField[]
  /** 阶梯样式：一级一级往上排 */
  ladder?: { name: string; text: string }[]
  /** 角色卡每章更新的状态 */
  now?: string[]
  paragraph?: string
}

export interface SampleCategory {
  name: string
  hint: string
  entries: SampleEntry[]
}

export const BOOK = {
  title: '窥命长生',
  channel: '男频',
  genre: '仙侠',
  tags: ['天赋觉醒', '苟道', '宗门', '智斗'],
  length: 200,
  chapters: 800,
  blurb:
    '头顶还剩三天寿命的传功执事，正一脸慈祥地递来一枚“筑基丹”。\n底层杂役陈默一睁眼，就能看破所有人的剩余寿数。\n在这座表面仙风道骨、暗地敲骨吸髓的吃人宗门里，别人的死期，就是他的生机。\n所有人都以为他平平无奇，直到某天，他撞见了那位号称与天地同寿的宗门老祖——\n老祖头顶上的数字，赫然只剩一个时辰。',
}

export const CATEGORIES: SampleCategory[] = [
  {
    name: '角色',
    hint: '有名有姓、会再出场的人',
    entries: [
      {
        id: 'chenmo',
        name: '陈默',
        oneLine: '外门杂役，一睁眼就能看见所有人头顶剩下的寿命。',
        tags: ['主角', '金手指'],
        fields: [
          { label: '定位', text: '主角' },
          { label: '性别年龄', text: '男，十七岁' },
          { label: '外貌', text: '瘦，肤色偏黑，走路总低着头；右手少了半截小指。' },
          { label: '性格', text: '胆小是装的，记仇是真的。话少，开口先算账。' },
          { label: '身世', text: '山下猎户家的孩子，十二岁被卖进宗门做杂役。另有秘密。' },
          { label: '想要什么', text: '长远：活下去，弄清是谁在收割整座宗门。\n眼下：熬过三天后的外门考核。' },
          { label: '能力', text: '窥命之眼：看得见寿命，看久了会折自己的寿。' },
        ],
        now: ['在外门杂役院', '被传功执事盯上', '炼气一层'],
      },
      {
        id: 'zhao',
        name: '赵长河',
        oneLine: '笑眯眯的传功执事，头顶只剩三天寿命，却还在给弟子发丹药。',
        tags: ['对手'],
        fields: [
          { label: '定位', text: '对手' },
          { label: '性格', text: '说话慢，爱拍人肩膀，从不发火。' },
          { label: '想要什么', text: '在死前把这一批“筑基丹”发完。' },
          { label: '和主角的关系', text: '陈默所在杂役院的上司。' },
        ],
        now: ['在传功堂', '寿命：三天'],
      },
      {
        id: 'laozu',
        name: '青冥老祖',
        oneLine: '号称与天地同寿的宗门老祖，头顶的数字只剩一个时辰。',
        fields: [{ label: '定位', text: '幕后' }],
      },
    ],
  },
  {
    name: '等级体系',
    hint: '修炼境界、官阶、物品品阶……一切分高低的',
    entries: [
      {
        id: 'realm',
        name: '修炼境界',
        oneLine: '每破一境多一甲子寿命，所以人人都在拼命往上爬。',
        ladder: [
          { name: '炼气', text: '分九层，外门弟子大多卡在这里。' },
          { name: '筑基', text: '寿命翻倍。宗门发的“筑基丹”是唯一捷径。' },
          { name: '金丹', text: '可以开宗立派，青冥宗只有七位。' },
          { name: '元婴', text: '传说中的境界，只有老祖到过。' },
        ],
      },
    ],
  },
  {
    name: '世界与地图',
    hint: '世界概况，和一个个地方',
    entries: [
      {
        id: 'world',
        name: '世界概况',
        oneLine: '灵气一年比一年稀薄，寿命成了修士最值钱的东西。',
        paragraph: '东洲七宗分据七山，青冥宗居首。凡人六十而终，修士靠境界续命；境界卡住的人，只能另想办法。',
      },
      {
        id: 'yard',
        name: '外门杂役院',
        oneLine: '青冥宗最底下的地方，三百杂役挤在一座山坳里。',
        paragraph: '属于青冥宗外门。每月初一发一次丹药，每年一次外门考核，考不过的人就“下山”了，再没人见过。',
      },
    ],
  },
  {
    name: '势力划分',
    hint: '宗门、家族、国家、公司',
    entries: [{ id: 'sect', name: '青冥宗', oneLine: '东洲第一宗，表面仙风道骨，暗地敲骨吸髓。' }],
  },
  {
    name: '物品与功法',
    hint: '法宝、丹药、功法、血脉',
    entries: [{ id: 'pill', name: '筑基丹', oneLine: '宗门每年发给外门弟子的“恩赐”，吃过的人寿命都停在同一天。' }],
  },
  {
    name: '往事与秘密',
    hint: '过去的事和藏着的真相',
    entries: [
      {
        id: 'secret',
        name: '老祖的寿命',
        oneLine: '老祖靠“筑基丹”把弟子的寿命收到自己身上。',
        tags: ['底牌'],
        locked: true,
        paragraph: '谁知道：只有你和编辑部。',
      },
    ],
  },
  { name: '特殊规则', hint: '这个世界特有的机制：夺舍的限制、系统规则、某种代价', entries: [] },
]

export interface SampleNode {
  id: string
  kind: '全书' | '篇' | '卷' | '单元' | '章'
  title: string
  text: string
  chapters?: number
  later?: boolean
  children?: SampleNode[]
}

export const OUTLINE: SampleNode = {
  id: 'book',
  kind: '全书',
  title: '全书',
  text: '结局：陈默掀了青冥宗的命簿，自己却成了下一个看守它的人。',
  children: [
    {
      id: 'part1',
      kind: '篇',
      title: '第一篇　外门求生',
      text: '舞台是青冥宗外门。陈默想在外门考核前活下来，挡路的是给弟子发“筑基丹”的传功执事。这一篇以陈默揭穿丹药的真相、借执事之死换来进内门的名额收尾。读者一直在等：头顶数字归零的人，到底是怎么死的。',
      children: [
        {
          id: 'v1',
          kind: '卷',
          title: '第一卷　杂役院',
          chapters: 12,
          text: '这一卷陈默要做成一件事：在不暴露眼睛的前提下，活过赵长河发丹的那一天。卷首他还是任人使唤的杂役；卷末，他看着赵长河在众目睽睽之下化成一具枯骨，而自己手里多了一枚没吃的丹药。',
          children: [
            {
              id: 'u1',
              kind: '单元',
              title: '单元一　递丹之局',
              chapters: 4,
              text: '赵长河当众点名，要把一枚“筑基丹”赏给陈默。陈默看见执事头顶只剩三天，也看见吃过丹的师兄寿命全停在同一天。他装病躲丹，被逼到墙角时，借一场意外把丹换了出去。',
              children: [
                { id: 'c1', kind: '章', title: '第1章　三天', text: '发生什么：陈默第一次看见所有人头顶的数字，最长的那个属于传功执事——只剩三天。\n看点：一个杂役看穿了整个宗门的死期。\n结尾钩子：执事笑着朝他招手：“陈默，过来领丹。”' },
                { id: 'c2', kind: '章', title: '第2章　筑基丹', text: '发生什么：陈默装病躲丹，发现吃过丹的师兄们寿命都停在同一天。\n看点：同一个日期，像一张死亡名单。\n结尾钩子：那一天，就是三天后。' },
                { id: 'c3', kind: '章', title: '第3章　少半截的小指', text: '发生什么：执事亲自上门送丹，陈默用断指的旧伤骗过搜身。\n看点：装傻和算计。\n结尾钩子：执事走时回头看了他一眼，头顶的数字变了。' },
                { id: 'c4', kind: '章', title: '第4章　执事的数字', text: '发生什么：陈默发现执事的寿命不是在减，而是在被“收走”。\n看点：真相露出一角。\n结尾钩子：收走寿命的那只手，来自后山。' },
              ],
            },
            { id: 'u2', kind: '单元', title: '单元二　外门考核', chapters: 5, text: '考核前夜，杂役院死了第一个人。陈默要在考核里不出头、不垫底，还得弄清谁动的手。' },
            { id: 'u3', kind: '单元', title: '单元三　借命', chapters: 3, text: '执事死期到了。陈默把那枚没吃的丹药，换成了进内门的门票。' },
          ],
        },
        { id: 'v2', kind: '卷', title: '第二卷　内门试炼', later: true, text: '暂定：进了内门，陈默发现内门弟子头顶的数字，全都指向同一个时辰。' },
      ],
    },
    { id: 'part2', kind: '篇', title: '第二篇', later: true, text: '写到再定。' },
  ],
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
