import { fileURLToPath } from 'node:url'
/** 第三包任务6：真实浏览器交互，所有写入经 UI；GET 仅用于核对。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium, expect as baseExpect } from '@playwright/test'
const base = 'http://127.0.0.1:4356'
assert.equal(process.env.TEST_BASE_URL, base)
const root = fileURLToPath(new URL('../../',import.meta.url))
const data = path.join(root,'data/third-package-task6')
const output = path.join(root,'docs/第三包验收')
const statePath = path.join(data,'browser-state.json')
const evidence = await fs.readFile(statePath,'utf8').then(JSON.parse).catch(() => ({ screenshots:[], requests:[], errors:[] }))
const browser = await chromium.launch({ headless:true, executablePath:process.env.ZHIBI_CHROMIUM })
const page = await browser.newPage({ viewport:{ width:1720,height:1100 },reducedMotion:'reduce' })
const expect = baseExpect.configure({ timeout:120000 })
page.on('pageerror',e => evidence.errors.push(e.message))
page.on('request',r => { if(['POST','PATCH','DELETE'].includes(r.method()))evidence.requests.push({ method:r.method(),url:r.url(),body:r.postData() }) })
const api = async route => { const r=await page.request.get(`${base}/api${route}`);assert.equal(r.status(),200,route);return r.json() }
const bid=()=>evidence.book_id
const book=()=>api(`/books/${bid()}`)
const history=()=>api(`/books/${bid()}/meeting?limit=2000`)
const reqs=()=>api(`/books/${bid()}/requirements`)
const shot=async name=>{ await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(450);const file=`任务6-${name}.png`;await page.screenshot({path:path.join(output,file)});if(!evidence.screenshots.includes(file))evidence.screenshots.push(file);console.log(file) }
const nav=async suffix=>{await page.goto(`${base}/books/${bid()}/${suffix}`);const tab=page.getByRole('tab',{name:'稿件',exact:true});if(await tab.isVisible())await tab.click()}
const conversation=()=>page.getByRole('region',{name:'会话消息与输入'})
const send=async(text,_role='group')=>{const input=conversation().locator('textarea');await input.fill(text);await conversation().getByRole('button',{name:'发送',exact:true}).click();await expect(input).toHaveValue('')}
const selectRole=async role=>{await page.getByRole('button',{name:role,exact:true}).first().click()}
const latestNote=async()=> (await history()).filter(m=>m.speaker==='author'&&m.kind==='note').at(-1)
const waitReply=async id=>expect.poll(async()=>(await history()).some(m=>m.payload?.reply_to?.includes(id))).toBe(true)
try {
 if(process.argv[2]==='setup') {
  await page.goto(base)
  await page.locator('textarea').first().fill('第三包任务6独立演示：楚风凭青灯修行，追查前世之死。')
  await page.getByRole('button',{name:'一步一步看',exact:true}).click()
  await page.getByRole('button',{name:'交给编辑部',exact:true}).click()
  await page.waitForURL(/\/books\//);evidence.book_id=new URL(page.url()).pathname.split('/')[2]
  await expect(page.getByRole('region',{name:'选择短版定调'}).getByRole('button',{name:'用这个',exact:true})).toHaveCount(3)
  await page.getByRole('region',{name:'选择短版定调'}).getByRole('button',{name:'用这个',exact:true}).first().click()
  await page.getByRole('button',{name:'确认，去建设定',exact:true}).click()
  await page.getByRole('button',{name:'设定先这样，去出大纲',exact:true}).click()
  await expect(page.getByRole('button',{name:'确认，开写',exact:true})).toBeVisible()
  await nav('settings')
  await page.getByRole('button',{name:'省时',exact:true}).click()
  await page.getByRole('switch',{name:'新书前 3 章先给我试读',exact:true}).uncheck()
  await page.getByRole('switch',{name:'每卷卷纲都要我拍板',exact:true}).uncheck()
  await page.getByRole('spinbutton',{name:'每章字数',exact:true}).fill('600')
  await page.getByRole('heading',{name:'本书设置',exact:true}).click()
  await expect.poll(async()=>(await api(`/books/${bid()}/settings`)).settings.chapter_words).toBe(600)
  await nav('outline?node=volume-1')
  await page.getByRole('button',{name:'确认，开写',exact:true}).click()
  await expect.poll(async()=>{const b=await book();if(b.active_job?.status==='failed')throw new Error(b.active_job.error);return b.chapters_final}).toBe(3)
  await expect.poll(async()=>(await book()).active_job?.status||'idle').toBe('idle')
  await shot('00-独立演示书已写三章')
 }
 if(process.argv[2]==='chat') {
  await nav('library')
  evidence.requirements_before=(await reqs()).length
  await send('楚风现在什么境界？')
  const q=await latestNote();await waitReply(q.id)
  await expect(page.getByTestId(`outcome-${q.id}`)).toContainText('只是聊天，没有记')
  assert.equal((await reqs()).length,evidence.requirements_before)
  await shot('01-群聊设定师回答不记要求')
  await send('下一章节奏快一点')
  let m=await latestNote();let outcome=page.getByTestId(`outcome-${m.id}`)
  await expect(outcome).toContainText('只管第 4 章')
  await shot('02-要求只管下一章')
  await outcome.getByRole('button',{name:'撤销',exact:true}).click();await expect(outcome).toContainText('已撤销')
  await shot('03-撤销要求')
  await send('下一章节奏快一点');evidence.scoped_requirement=(await latestNote()).payload.outcome.requirement_id
  await page.getByTestId(`outcome-${q.id}`).getByRole('button',{name:'其实要记下',exact:true}).click()
  await page.getByRole('dialog').getByRole('textbox',{name:'要记下的要求',exact:true}).fill('群聊结论：楚风的境界以设定库为准')
  await page.getByRole('dialog').getByRole('combobox',{name:'有效范围'}).selectOption('always')
  await page.getByRole('dialog').getByRole('button',{name:'记下',exact:true}).click()
  await shot('04-聊天明确转成要求')
  await selectRole('主编')
  await send('把境界名称重想一下','chief');m=await latestNote();await waitReply(m.id)
  await expect(conversation().getByText('这里只聊天，不会改动书稿，也不会记成要求。聊出结论，点最新回复下面的「记成要求」或「照这个改」。')).toBeVisible()
  await shot('05-私聊零修改与结论按钮')
  await conversation().getByRole('button',{name:'记成要求',exact:true}).click()
  await page.getByRole('dialog').getByRole('button',{name:'记下',exact:true}).click()
  await expect(conversation().getByText(/^已记成要求：/)).toBeVisible()
  await shot('06-私聊明确记下结论')
  await conversation().getByRole('button',{name:'照这个改',exact:true}).click()
  await page.getByRole('dialog').getByRole('button',{name:'发到群聊',exact:true}).click()
  await expect(conversation().getByText(/^已交给编辑部：/)).toBeVisible()
  await shot('07-私聊结论明确交给群聊')
  await selectRole('编辑部群聊')
  await expect(conversation().getByText(/给了三个写法：/)).toBeVisible()
  await shot('08-群聊按改设定处理')
 }
 if(process.argv[2]==='summary') {
  await nav('library');await selectRole('主编')
  for(let i=0;i<26;i++){await send(`旧话题验收${i}：楚风为什么这样安排？`,'chief');await waitReply((await latestNote()).id)}
  await shot('09-私聊超过二十五次')
  await conversation().getByRole('button',{name:'换个话题',exact:true}).click()
  await expect(conversation().getByText('—— 换了个话题，前面的对话不再带给主编 ——')).toBeVisible()
  await send('新话题验收：后面打算怎么走？','chief');await waitReply((await latestNote()).id)
  await shot('10-换个话题')
 }
 if(process.argv[2]==='quote-tidy' || process.argv[2]==='quote-refresh') {
  await nav('library')
  const library=await api(`/books/${bid()}/library`);const entry=library.entries.find(e=>e.content&&e.category==='世界与地图')
  await nav(`library?cat=${encodeURIComponent(entry.category)}&id=${entry.id}`)
  const text=page.locator('[data-selectable-text]').filter({hasText:entry.content}).first()
  await text.evaluate(element=>{const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);walker.nextNode();const range=document.createRange();range.setStart(walker.currentNode,0);range.setEnd(walker.currentNode,Math.min(25,walker.currentNode.textContent.length));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range)})
  await page.getByRole('button',{name:'问问主编',exact:true}).click()
  await expect(conversation().getByText(/^引用：设定库 ·/)).toBeVisible()
  await send('这句设定是什么意思？','chief');const m=await latestNote();await waitReply(m.id);evidence.quote_message=m.id
  await shot('11-选中原文问主编')
  if(process.argv[2]==='quote-tidy') {
  await nav('settings')
  for(const text of ['主角是不是太弱了？','对主编：节奏快一点']) {
   await page.getByRole('button',{name:'＋ 添加',exact:true}).click()
   await page.getByRole('dialog').getByRole('textbox',{name:'要记下的要求',exact:true}).fill(text)
   await page.getByRole('dialog').getByRole('button',{name:'记下',exact:true}).click()
  }
  await page.getByRole('button',{name:'整理一下',exact:true}).click()
  await expect(page.getByText('这是一句提问，不是要求')).toBeVisible()
  await shot('12-主编整理建议')
  await page.getByRole('button',{name:'照勾的改',exact:true}).click()
  await expect.poll(async()=>(await reqs()).some(r=>r.text==='主角是不是太弱了？')).toBe(false)
  await shot('13-按勾选删改清单')
  }
 }
 if(process.argv[2]==='writing') {
  await nav('outline?node=volume-1');await selectRole('编辑部群聊')
  const before=(await book()).chapters_final
  await page.getByRole('button',{name:'写 1 章',exact:true}).first().click();await page.getByRole('button',{name:'继续写',exact:true}).first().click()
  await expect.poll(async()=>(await book()).active_job?.status).toMatch(/queued|running/)
  await send('楚风现在什么境界？');await waitReply((await latestNote()).id)
  await shot('14-写作中独立回答')
  await send('把境界名称重想一下');const m=await latestNote()
  await expect(page.getByTestId(`outcome-${m.id}`)).toContainText('编辑部写完再改')
  await shot('15-写作中改设定挂建议')
  await expect.poll(async()=>{const b=await book();if(b.active_job?.status==='failed')throw new Error(b.active_job.error);return b.chapters_final}).toBe(before+1)
  await expect.poll(async()=>(await book()).active_job?.status||'idle').toBe('idle')
  assert.equal((await reqs()).find(r=>r.id===evidence.scoped_requirement).active,false)
  await nav('settings');await expect(page.locator('.settings-row-hint').filter({hasText:'已过期 · 只管第 4 章'})).toBeVisible();await shot('16-第四章完成要求过期')
  await nav('library');await page.getByText('展开建议',{exact:true}).click()
  await page.getByRole('button',{name:'现在改',exact:true}).click()
  await expect.poll(async()=>(await api(`/books/${bid()}/suggestions`)).some(s=>s.id===m.payload.outcome.suggestion_id)).toBe(false)
  await shot('17-空闲后现在改')
  await page.getByRole('button',{name:'写 1 章',exact:true}).first().click();await page.getByRole('button',{name:'继续写',exact:true}).first().click()
  await expect.poll(async()=>(await book()).chapters_final).toBe(before+2)
  await expect.poll(async()=>(await book()).active_job?.status||'idle').toBe('idle')
 }
 if(process.argv[2]==='writing-finish') {
  const m=(await history()).filter(m=>m.payload?.outcome?.kind==='later').at(-1)
  await nav('settings');await expect(page.locator('.settings-row-hint').filter({hasText:'已过期 · 只管第 4 章'})).toBeVisible();await shot('16-第四章完成要求过期')
  await nav('library');await selectRole('编辑部群聊');await page.getByText('展开建议',{exact:true}).click()
  await page.getByRole('button',{name:'现在改',exact:true}).click()
  await expect.poll(async()=>(await api(`/books/${bid()}/suggestions`)).some(s=>s.id===m.payload.outcome.suggestion_id)).toBe(false)
  await shot('17-空闲后现在改')
  const target=(await book()).chapters_final+1
  await page.getByRole('button',{name:'写 1 章',exact:true}).first().click();await page.getByRole('button',{name:'继续写',exact:true}).first().click()
  await expect.poll(async()=>(await book()).chapters_final).toBe(target)
  await expect.poll(async()=>(await book()).active_job?.status||'idle').toBe('idle')
 }
 if(process.argv[2]==='gate' || process.argv[2]==='gate-finish') {
  if(process.argv[2]==='gate') {
  await nav('settings')
  await page.getByRole('switch',{name:'每卷卷纲都要我拍板',exact:true}).check()
  await expect.poll(async()=>(await api(`/books/${bid()}/settings`)).settings.volume_approval).toBe(true)
  await nav('outline?node=volume-1');await selectRole('编辑部群聊')
  await page.getByRole('button',{name:'一直写到完本',exact:true}).first().click();await page.getByRole('button',{name:'继续写',exact:true}).first().click()
  await expect.poll(async()=>{const b=await book();if(b.active_job?.status==='failed')throw new Error(b.active_job.error);return b.active_job?.pending?.kind},{timeout:600000}).toBe('volume_review')
  }
  if(process.argv[2]==='gate-finish') { await nav('outline?node=volume-2');await selectRole('编辑部群聊') }
  const before=await api(`/books/${bid()}/outline-tree`);evidence.gate_before=before
  await send('第三个单元为什么这样安排？');const q=await latestNote();await waitReply(q.id)
  assert.deepEqual(await api(`/books/${bid()}/outline-tree`),before)
  await shot('18-等卷纲拍板提问不重写')
  const callsBefore=(await api(`/llm-calls?book_id=${bid()}&limit=100`)).items.length
  await send('第三个单元换个对手')
  await expect.poll(async()=>{const b=await book();return b.active_job?.status==='waiting_author'?b.active_job.pending?.kind:b.active_job?.status}).toBe('volume_review')
  await shot('19-明确提意见后卷纲重出')
  evidence.gate_calls_before=callsBefore
 }
 if(process.argv[2]==='settings-refresh') {
  await nav('settings')
  const row=page.locator('.settings-row').filter({hasText:'已过期 · 只管第 4 章'})
  await row.scrollIntoViewIfNeeded();await shot('16-第四章完成要求过期')
 }
 if(process.argv[2]==='final-smoke') {
  await nav('outline?node=volume-2');await selectRole('主编')
  const before=await api(`/books/${bid()}/outline-tree`);const requirements=(await reqs()).map(r=>r.id);const job=(await book()).active_job.id
  await send('把境界名称重想一下','chief');await waitReply((await latestNote()).id)
  assert.deepEqual(await api(`/books/${bid()}/outline-tree`),before);assert.deepEqual((await reqs()).map(r=>r.id),requirements);assert.equal((await book()).active_job.id,job)
  await shot('28-等拍板时私聊仍不改不记')
  await conversation().getByRole('button',{name:'照这个改',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'发到群聊',exact:true}).click()
  await expect(page.getByRole('dialog',{name:'交给编辑部的话',exact:true})).toHaveCount(0)
  await expect(conversation().getByText(/^已交给编辑部：/).last()).toBeVisible()
  await expect.poll(async()=>{const b=await book();return b.active_job?.status==='waiting_author'?b.active_job.pending?.kind:b.active_job?.status}).toBe('volume_review')
  await shot('29-长会话结论明确发到拍板意见')
  evidence.final_smoke=true
 }
 if(process.argv[2]==='calls') {
  await page.goto(`${base}/prompts`);await page.getByRole('tab',{name:'调用记录',exact:true}).click();await page.getByRole('combobox',{name:'按书筛选'}).selectOption(bid())
  const dialog=()=>page.getByRole('dialog',{name:'调用详情',exact:true})
  const findRow=async purpose=>{
   await expect(page.locator('tbody tr').first()).toBeVisible()
   const row=page.locator('tbody tr').filter({hasText:purpose}).first()
   for(let i=0;i<30 && !(await row.count());i++){
    const more=page.getByRole('button',{name:'加载更早的记录',exact:true})
    if(!(await more.count())){await page.waitForTimeout(300);if(!(await more.count()))break}
    const count=await page.locator('tbody tr').count();await more.click();await expect.poll(()=>page.locator('tbody tr').count()).toBeGreaterThan(count)
   }
   await expect(row).toBeVisible();return row
  }
  await page.getByRole('combobox',{name:'按角色筛选'}).selectOption('lorekeeper')
  await (await findRow('chat_summary')).getByRole('button',{name:'查看',exact:true}).click()
  await expect(dialog()).toContainText('【要并进去的对话】');await shot('22-调用记录中的对话摘要');await dialog().getByRole('button',{name:'关闭',exact:true}).click()
  await page.getByRole('combobox',{name:'按角色筛选'}).selectOption('chief')
  await (await findRow('聊天·主编')).getByRole('button',{name:'查看',exact:true}).click()
  await expect(dialog()).toContainText('【最近的对话】');await shot('23-聊天回答上下文');await dialog().getByRole('button',{name:'关闭',exact:true}).click()
  const rows=page.locator('tbody tr').filter({hasText:'聊天·主编'})
  const found=new Set()
  for(let i=0;i<await rows.count();i++){
   await rows.nth(i).getByRole('button',{name:'查看',exact:true}).click()
   const user=dialog().locator('section').filter({has:page.getByRole('heading',{name:'用户提示',exact:true})})
   const text=await user.innerText()
   let target=null
   if(text.includes('【作者这次说的】\n这句设定是什么意思？')&&!found.has('quote'))target=['quote','【作者选中的原文】','24-调用记录含选中原文']
   else if(text.includes('【作者这次说的】\n新话题验收：')&&!found.has('reset')){assert.equal(text.includes('旧话题验收'),false);target=['reset','【最近的对话】','25-换话题后不带旧对话']}
   else if(text.includes('【作者这次说的】\n旧话题验收25：')&&!found.has('recent'))target=['recent','【最近的对话】','26-摘要加最近二十条']
   if(target){
    await user.locator('pre').evaluate((element,needle)=>{const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);while(walker.nextNode()){const at=walker.currentNode.textContent.indexOf(needle);if(at<0)continue;const range=document.createRange();range.setStart(walker.currentNode,at);range.setEnd(walker.currentNode,at+needle.length);let parent=element.parentElement;while(parent&&!(/auto|scroll/.test(getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight))parent=parent.parentElement;if(parent)parent.scrollTop+=range.getBoundingClientRect().top-parent.getBoundingClientRect().top-120;return}},target[1]);await shot(target[2]);found.add(target[0])
   }
   await dialog().getByRole('button',{name:'关闭',exact:true}).click()
   if(found.size===3)break
  }
  assert.equal(found.size,3)
  await page.getByRole('combobox',{name:'按角色筛选'}).selectOption('writer')
  await (await findRow('写作·正文')).getByRole('button',{name:'查看',exact:true}).click()
  await expect(dialog()).not.toContainText('下一章节奏快一点')
  await dialog().locator('section').filter({has:page.getByRole('heading',{name:'用户提示',exact:true})}).locator('pre').evaluate(element=>{const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);while(walker.nextNode()){const needle='【作者的要求';const at=walker.currentNode.textContent.indexOf(needle);if(at<0)continue;const range=document.createRange();range.setStart(walker.currentNode,at);range.setEnd(walker.currentNode,at+needle.length);let parent=element.parentElement;while(parent&&!(/auto|scroll/.test(getComputedStyle(parent).overflowY)&&parent.scrollHeight>parent.clientHeight))parent=parent.parentElement;if(parent)parent.scrollTop+=range.getBoundingClientRect().top-parent.getBoundingClientRect().top-100;return}throw new Error('没有要求块')});await shot('27-后续正文调用不含过期要求');await dialog().getByRole('button',{name:'关闭',exact:true}).click()
  evidence.calls_visible=true
 }
 if(process.argv[2]==='responsive') {
  await nav('library');await selectRole('主编')
  await page.setViewportSize({width:390,height:844})
  await page.getByRole('tab',{name:'讨论',exact:true}).click()
  await shot('20-窄屏会议室')
  await page.setViewportSize({width:1720,height:1100})
  await page.getByRole('button',{name:'设置',exact:true}).click()
  await page.getByRole('tab',{name:'外观',exact:true}).click()
  await page.getByRole('button',{name:'墨色·暗',exact:true}).click()
  await page.getByRole('dialog').getByRole('button',{name:'关闭设置',exact:true}).click()
  await expect(page.locator('html')).toHaveAttribute('data-theme','ink')
  await shot('21-暗色会议室')
 }
 assert.deepEqual(evidence.errors,[])
} finally { await fs.writeFile(statePath,JSON.stringify(evidence,null,2));await browser.close() }
