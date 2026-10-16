import assert from 'node:assert/strict'
import test from 'node:test'
import { artifactTarget, composerRoute, conversationContains, currentTarget, directionProgressText, nodeFeedback, pendingTarget, progressText, puzzleSidebarActive, retainedNodeFeedback, unreadCount } from '../src/lib/workspace.ts'
const job = { id: 'job', kind: 'book_setup', status: 'running', pending: null }
const msg = (type, data = {}, extra = {}) => ({ id: 1, job_id: 'job', kind: 'artifact', speaker: 'chief', content: '', payload: { type, data }, ...extra })

test('新五块左栏一律按路由匹配，不按当前工作块覆盖导航状态', () => {
  for (const current of ['concept', 'protagonist', 'world', 'segment', 'first_volume', null]) {
    for (const piece of ['concept', 'protagonist', 'world', 'segment', 'first_volume']) assert.equal(puzzleSidebarActive(piece, current), undefined)
  }
})

test('写作顶栏用真实卷位置和距节点章数，并保留工作、等待、失败状态', () => {
  const nodes = [{id: 'opening', kind: 'opening', index: 1}, {id: 'next', kind: 'milestone', index: 2, title: '飞升神界'}]
  const volumes = [{id: 'v3', index: 3, chapter_count: 60, units: [], status: 'approved', target_node_id: 'next', reaches_node: true}]
  const chapters = Array.from({length: 42}, (_, i) => ({id: `c${i}`, index: i + 79, volume_id: 'v3', status: 'final'}))
  const writing = {nodes, volumes, chapters}
  const book = {chapters_final: 120, status: 'writing', active_job: null}
  const base = '第 3 卷 · 已定稿 120 章 · 离「飞升神界」还有 18 章'
  assert.equal(progressText(book, [], null, null, writing), `${base} · 编辑部空闲`)
  assert.equal(progressText({...book,active_job:{...job,kind:'write_book'}}, [msg('',{}, {kind:'status',content:'设定师在备资料…'})], null, null, writing), `${base} · 设定师在备资料`)
  assert.equal(progressText({...book,active_job:{...job,kind:'write_book'}}, [], {job_id:'job',chapter:121,done:false}, null, writing), `${base} · 写手在写第 121 章`)
  assert.equal(progressText({...book,active_job:{...job,kind:'write_book',status:'waiting_author',pending:{kind:'volume_review',volume:3}}}, [], null, {label:'第 3 卷卷纲'}, writing), `${base} · 等你拍板：第 3 卷卷纲`)
  assert.equal(progressText({...book,active_job:{...job,status:'failed'}}, [], null, null, writing), `${base} · 任务出错，可继续`)
})

test('写作顶栏兼容旧卷、未开写、最后一段及完结', () => {
  const volume = {id:'v1',index:1,chapter_count:2,units:[],status:'approved',target_node_id:null}
  const chapter = {id:'c1',index:1,volume_id:'v1',status:'final'}
  const book = {chapters_final:1,status:'writing',active_job:null}
  const writing = {nodes:[],volumes:[volume],chapters:[chapter]}
  assert.equal(progressText(book,[],null,null,writing), '第 1 卷 · 已定稿 1 章 · 编辑部空闲')
  assert.equal(progressText({...book,chapters_final:0},[],null,null,{...writing,chapters:[]}), '已定稿 0 章 · 编辑部空闲')
  assert.equal(progressText(book,[],null,null,{...writing,volumes:[{...volume,target_node_id:'deleted-node'}]}), '第 1 卷 · 已定稿 1 章 · 正在写最后一段，离结局还有 1 章 · 编辑部空闲')
  assert.equal(progressText({...book,chapters_final:2},[],null,null,{...writing,chapters:[chapter,{...chapter,id:'c2',index:2}]}), '第 1 卷 · 已定稿 2 章 · 全书完结')
})
for (const [type, suffix] of [['protagonist', '/protagonist'], ['world', '/world'], ['segment', '/spine'], ['segment_volumes', '/spine'], ['concept', '/concept'], ['lore', '/characters'], ['spine', '/spine'], ['threads', '/threads'], ['outline', '/spine']]) {
  test(`setup follows ${type}`, () => assert.equal(currentTarget('book', job, [msg(type)], null).path, `/books/book${suffix}`))
}
test('setup defaults to overview and ignores artifacts from previous jobs', () => assert.equal(currentTarget('book', job, [msg('lore', {}, { job_id: 'old' })], null).path, '/books/book'))
test('setup critique keeps latest manuscript instead of returning to overview', () => assert.equal(currentTarget('book', job, [msg('volume_plan', { volume: 1 }), msg('critique')], null).path, '/books/book/volume/1'))
test('idle does not navigate', () => { for (const status of ['failed','succeeded','cancelled']) assert.equal(currentTarget('book', { ...job, status }, [msg('concept')], null), null); assert.equal(currentTarget('book', null, [], null), null) })
for (const [pending, path] of [[{kind:'setup_questions'},''],[{kind:'setup_review'},''],[{kind:'volume_review',volume:2},'/volume/2'],[{kind:'trial_read',chapters:3},'/chapter/1'],[{kind:'chapter_stuck',chapter:6},'/chapter/6']]) {
  test(`pending ${pending.kind} points to author action`, () => assert.equal(pendingTarget(pending, 'book').path, `/books/book${path}`))
}
test('only current unfinished live draft takes priority', () => {
  const writing = { ...job, kind:'write_book' }
  const messages = [msg('chapter_final', {index:5})]
  const draft = {job_id:'job', chapter:6,done:false}
  assert.equal(currentTarget('book', writing,messages,draft).path, '/books/book/chapter/6')
  assert.equal(currentTarget('book', writing,messages,{...draft,done:true}).path, '/books/book/chapter/5')
  assert.equal(currentTarget('book', writing,messages,{...draft,job_id:'old'}).path, '/books/book/chapter/5')
})
test('chapter plan uses its volume, not first chapter number', () => assert.equal(artifactTarget(msg('chapter_plan',{unit:'第2卷第3单元「破阵」',chapters:[{index:40}]}),'book').path, '/books/book/volume/2'))
test('all pitch stages resolve a volume', () => { for (const type of ['volume_directions','volume_pitch','pitch_scores','volume_audit','volume_plan']) assert.equal(artifactTarget(msg(type,{volume:2}),'book').path, '/books/book/volume/2') })
test('rewrite routes before a live draft starts using persisted author request', () => assert.equal(currentTarget('book',{...job,kind:'rewrite_chapter'},[msg('',{}, {kind:'speech',speaker:'author',content:'第2章《破阵》按我的意见重写：快一点'})],null).path,'/books/book/chapter/2'))
test('unread excludes author and role group speech, and separates private threads', () => {
  const messages = [msg('',{}, {id:1,speaker:'author',payload:{thread:'lorekeeper'}}),msg('',{}, {id:2,speaker:'lorekeeper',payload:{thread:'lorekeeper'}}),msg('',{}, {id:3,speaker:'chief',payload:{thread:'chief'}}),msg('',{}, {id:4,speaker:'lorekeeper',payload:null})]
  assert.equal(unreadCount(messages,'lorekeeper',0),1)
  assert.equal(unreadCount(messages,'lorekeeper',2),0)
  assert.equal(unreadCount(messages,'lorekeeper',4),0)
  assert.equal(unreadCount(messages,'group',0),1)
  assert.equal(conversationContains(messages[3], 'lorekeeper'), false)
  assert.equal(conversationContains(messages[1], 'group'), false)
})

test('unread tracks payload thread even when sender differs and excludes all threaded group notifications', () => {
  const messages = [msg('', {}, {id: 1, speaker: 'system', payload: {thread: 'writer'}}), msg('', {}, {id: 2, speaker: 'author', payload: null}), msg('', {}, {id: 3, speaker: 'chief', payload: null})]
  assert.equal(unreadCount(messages, 'writer', 0), 1)
  assert.equal(unreadCount(messages, 'chief', 0), 0)
  assert.equal(unreadCount(messages, 'group', 0), 1)
  assert.equal(unreadCount(messages, 'group', 3), 0)
})
test('malformed or missing artifact destination never invents chapter 0', () => assert.equal(artifactTarget(msg('chapter_final',{index:0}),'book'),null))

test('rewrite is anchored to the author request even when review references another chapter', () => assert.equal(currentTarget('book',{...job,kind:'rewrite_chapter'},[msg('',{}, {kind:'speech',speaker:'author',content:'第2章《破阵》按我的意见重写：快一点'}),msg('',{}, {id:2,kind:'speech',speaker:'reviewer',content:'请保持与第1章的人物一致'})],null).path,'/books/book/chapter/2'))

test('puzzle pending routes each piece and direction selection', () => {
  assert.deepEqual(pendingTarget({kind:'setup_directions'}, 'book'), {path:'/books/book',label:'开书方向'})
  for (const [piece, suffix, number, name] of [['concept','/concept',1,'定调'],['protagonist','/protagonist',2,'主角'],['world','/world',3,'世界与人'],['segment','/spine',4,'第一段'],['first_volume','/volume/1',5,'第一卷']]) {
    assert.deepEqual(pendingTarget({kind:'setup_piece',piece}, 'book'), {path:`/books/book${suffix}`,label:`第 ${number} 块：${name}`})
  }
})
test('puzzle artifacts have human stage labels', () => {
  assert.deepEqual(artifactTarget(msg('directions'),'book'), {path:'/books/book',label:'开书方向'})
  assert.deepEqual(artifactTarget(msg('spine'),'book'), {path:'/books/book/spine',label:'关键节点'})
  assert.deepEqual(artifactTarget(msg('outline'),'book'), {path:'/books/book/spine',label:'填中间'})
})
test('puzzle progress distinguishes work, confirmation, direction selection and legacy mode', () => {
  const book = {active_job:job,setup_progress:{mode:'puzzle',current:'segment'},chapters_final:0,status:'setting_up'}
  const messages = [msg('',{}, {kind:'status',content:'主编在定节点…'})]
  assert.equal(progressText(book,messages,null,null), '开书 · 第 4 块「第一段」· 主编在定节点')
  assert.equal(progressText({...book,active_job:{...job,status:'waiting_author',pending:{kind:'setup_piece',piece:'segment'}}},[],null,null), '等你确认：第一段')
  assert.equal(progressText({...book,active_job:{...job,status:'waiting_author',pending:{kind:'setup_directions'}}},[],null,null), '等你选择：开书方向')
  assert.equal(progressText({...book,setup_progress:{mode:'oneshot'}},messages,null,null),'开书中 · 主编在定节点')
})
test('node conversation routing revises waiting pieces and never grants a removed prefix', () => {
  const selection = nodeFeedback({id:'node-3',index:3,title:'飞升神界'})
  const waiting = {...job,status:'waiting_author',pending:{kind:'setup_piece',piece:'segment'}}
  assert.equal(selection.prefix, '关于节点 3「飞升神界」：')
  assert.deepEqual(composerRoute(waiting,`${selection.prefix}换个敌人`,selection),{kind:'piece',action:'revise',piece:'segment',node_id:'node-3'})
  assert.deepEqual(composerRoute(waiting,'换个敌人',selection),{kind:'piece',action:'revise',piece:'segment'})
  assert.equal(retainedNodeFeedback('',selection),null)
  assert.deepEqual(composerRoute(waiting,selection.prefix,null),{kind:'piece',action:'revise',piece:'segment'})
  assert.deepEqual(composerRoute(job,selection.prefix,selection),{kind:'note'})
  assert.deepEqual(composerRoute(null,selection.prefix,selection),{kind:'note'})
  assert.deepEqual(composerRoute({...waiting,pending:{kind:'setup_directions'}},'换一批',selection),{kind:'directions',action:'redo'})
  for (const piece of ['concept','protagonist','world','first_volume']) {
    assert.deepEqual(composerRoute({...waiting,pending:{kind:'setup_piece',piece}},`${selection.prefix}换个敌人`,selection),{kind:'piece',action:'revise',piece})
  }
})

test('direction loading differentiates preparing options from following an actual author choice', () => {
  assert.equal(directionProgressText('job', []), '主编正在拟定开书方向…')
  assert.equal(directionProgressText('job', [msg('directions')]), '主编正在拟定开书方向…')
  const chosen = msg('',{}, {kind:'decision',speaker:'author',content:'选方向「方向一」。\n混搭：方向二的金手指'})
  assert.equal(directionProgressText('job', [chosen]), '主编正在按你的选择定调…')
  assert.equal(directionProgressText('job', [{...chosen,job_id:'old'}]), '主编正在拟定开书方向…')
  assert.equal(directionProgressText('job', [{...chosen,kind:'note'}]), '主编正在拟定开书方向…')
  assert.equal(directionProgressText('job', [{...chosen,speaker:'chief'}]), '主编正在拟定开书方向…')
})
