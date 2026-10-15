import assert from 'node:assert/strict'
import test from 'node:test'
import { artifactTarget, conversationContains, currentTarget, pendingTarget, unreadCount } from '../src/lib/workspace.ts'
const job = { id: 'job', kind: 'book_setup', status: 'running', pending: null }
const msg = (type, data = {}, extra = {}) => ({ id: 1, job_id: 'job', kind: 'artifact', speaker: 'chief', content: '', payload: { type, data }, ...extra })
for (const [type, suffix] of [['concept', '/concept'], ['lore', '/characters'], ['spine', '/spine'], ['threads', '/threads'], ['outline', '']]) {
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
