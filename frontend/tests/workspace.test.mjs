import assert from 'node:assert/strict'
import test from 'node:test'
import { artifactTarget, composerRoute, conversationContains, currentTarget, directionProgressText, nodeFeedback, pendingTarget, progressText, retainedNodeFeedback, unreadCount } from '../src/lib/workspace.ts'
const job = { id: 'job', kind: 'book_setup', status: 'running', pending: null }
const msg = (type, data = {}, extra = {}) => ({ id: 1, job_id: 'job', kind: 'artifact', speaker: 'chief', content: '', payload: { type, data }, ...extra })
for (const [type, suffix] of [['concept', '/concept'], ['lore', '/characters'], ['spine', '/spine'], ['threads', '/threads'], ['outline', '/spine']]) {
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
  for (const [piece, suffix, number, name] of [['concept','/concept',1,'定调'],['nodes','/spine',2,'关键节点'],['cast','/characters',3,'人物上轴'],['fill','/spine',4,'填中间'],['first_volume','/volume/1',5,'第一卷']]) {
    assert.deepEqual(pendingTarget({kind:'setup_piece',piece}, 'book'), {path:`/books/book${suffix}`,label:`第 ${number} 块：${name}`})
  }
})
test('puzzle artifacts have human stage labels', () => {
  assert.deepEqual(artifactTarget(msg('directions'),'book'), {path:'/books/book',label:'开书方向'})
  assert.deepEqual(artifactTarget(msg('spine'),'book'), {path:'/books/book/spine',label:'关键节点'})
  assert.deepEqual(artifactTarget(msg('outline'),'book'), {path:'/books/book/spine',label:'填中间'})
})
test('puzzle progress distinguishes work, confirmation, direction selection and legacy mode', () => {
  const book = {active_job:job,setup_progress:{mode:'puzzle',current:'nodes'},chapters_final:0,status:'setting_up'}
  const messages = [msg('',{}, {kind:'status',content:'主编在定节点…'})]
  assert.equal(progressText(book,messages,null,null), '开书 · 第 2 块「关键节点」· 主编在定节点')
  assert.equal(progressText({...book,active_job:{...job,status:'waiting_author',pending:{kind:'setup_piece',piece:'nodes'}}},[],null,null), '等你确认：关键节点')
  assert.equal(progressText({...book,active_job:{...job,status:'waiting_author',pending:{kind:'setup_directions'}}},[],null,null), '等你选择：开书方向')
  assert.equal(progressText({...book,setup_progress:{mode:'oneshot'}},messages,null,null),'开书中 · 主编在定节点')
})
test('node conversation routing revises waiting pieces and never grants a removed prefix', () => {
  const selection = nodeFeedback({id:'node-3',index:3,title:'飞升神界'})
  const waiting = {...job,status:'waiting_author',pending:{kind:'setup_piece',piece:'nodes'}}
  assert.equal(selection.prefix, '关于节点 3「飞升神界」：')
  assert.deepEqual(composerRoute(waiting,`${selection.prefix}换个敌人`,selection),{kind:'piece',action:'revise',piece:'nodes',node_id:'node-3'})
  assert.deepEqual(composerRoute(waiting,'换个敌人',selection),{kind:'piece',action:'revise',piece:'nodes'})
  assert.equal(retainedNodeFeedback('',selection),null)
  assert.deepEqual(composerRoute(waiting,selection.prefix,null),{kind:'piece',action:'revise',piece:'nodes'})
  assert.deepEqual(composerRoute(job,selection.prefix,selection),{kind:'note'})
  assert.deepEqual(composerRoute(null,selection.prefix,selection),{kind:'note'})
  assert.deepEqual(composerRoute({...waiting,pending:{kind:'setup_directions'}},'换一批',selection),{kind:'directions',action:'redo'})
  for (const piece of ['concept','cast','fill','first_volume']) {
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
