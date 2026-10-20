import assert from 'node:assert/strict'
import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
const ROOT = path.resolve(import.meta.dirname, '../..'), BASE = 'http://127.0.0.1:4351', API = 'http://127.0.0.1:8051/api'
const BOOK = 'ff4aff0b-d1f1-46c4-b120-f7da9ac1ec2a', AUTHOR = '5765c6ea-dcaf-4826-921f-3a568fd42e56'
const OUT = path.join(ROOT, 'docs/新书页装修验收'), REPORT = path.join(ROOT, 'data/desk-v2/extra-ui.json')
const result = { at: new Date().toISOString(), base: BASE, api: API, book: BOOK, readonlyAuthorBook: AUTHOR, policy: '只浏览现有独立库；禁止一切非 GET /api 请求；不重新导入 TXT；不调模型', checks: [], failures: [], errors: [], screenshots: [], requests: [], blockedWrites: [], modelCalls: [], externalRequests: [], measurements: [], boundaries: [] }
fs.mkdirSync(OUT, { recursive: true })
const json = async suffix => { const response = await fetch(API + suffix); if (!response.ok) throw new Error(suffix + ': ' + response.status); return response.json() }
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
const hashBook = async id => createHash('sha256').update(JSON.stringify(canonical(await Promise.all(['', '/library', '/outline-tree', '/bible', '/chapters'].map(p => json('/books/' + id + p)))))).digest('hex')
const tree = await json('/books/' + BOOK + '/outline-tree'), volumes = tree.arcs.flatMap(a => a.volumes), volume = volumes[0], unit = volume.units.find(u => !u.virtual)
result.authorBefore = await hashBook(AUTHOR)
const executablePath = process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const browser = await chromium.launch({ executablePath })
const context = await browser.newContext({ viewport: { width: 2560, height: 1312 }, deviceScaleFactor: 1 })
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url())
  if (url.pathname.startsWith('/api/')) {
    const item = { method: request.method(), path: url.pathname + url.search }
    result.requests.push(item)
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { result.blockedWrites.push(item); if (/chat|write|rewrite|start|generate|model|completion/i.test(item.path)) result.modelCalls.push(item); return route.abort('blockedbyclient') }
  }
  if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) { result.externalRequests.push(url.origin + url.pathname); return route.abort('blockedbyclient') }
  await route.continue()
})
await context.addInitScript(({book,volume,unit}) => {
  if (sessionStorage.getItem('extra-ui-initialized')) return
  sessionStorage.setItem('extra-ui-initialized', 'true')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100, reducedMotion: true }))
  localStorage.setItem('zhibi:editorial-dock', 'ball')
  localStorage.setItem('zhibi:teardown-reading:' + book, JSON.stringify({ chapter: 2, at: Date.now() }))
  sessionStorage.setItem('zhibi:workspace-reading:' + book, JSON.stringify({ tab: '大纲', entry: 'overview', node: 'c4', chapter: 'home', open: ['book', 'v:' + volume, 'u:' + unit] }))
}, { book: BOOK, volume: volume.id, unit: unit.id })
const page = await context.newPage()
page.on('pageerror', error => result.errors.push({ url: page.url(), error: String(error) }))
const stable = async () => { await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(650) }
const screenshot = async name => { await stable(); await page.screenshot({ path: path.join(OUT, name) }); result.screenshots.push(name) }
const run = async (name, test) => { try { await test(); result.checks.push(name); console.log('PASS ' + name) } catch (error) { result.failures.push({ name, error: String(error) }); console.log('FAIL ' + name + ': ' + error); await page.keyboard.press('Escape').catch(()=>{}) } }
const tab = name => page.locator('.desk-v2 .tabs').getByText(name, { exact: true }).click()
const openSettings = async () => { await page.getByRole('button', { name: '系统设置', exact: true }).click(); await page.getByRole('dialog', { name: '系统设置', exact: true }).waitFor(); await page.getByRole('tab', { name: '外观', exact: true }).click() }
const closeSettings = () => page.getByRole('button', { name: '关闭设置', exact: true }).click()
const box = async (selector, name) => page.locator(selector).evaluate((element, name) => { const r = element.getBoundingClientRect(), s = getComputedStyle(element); return { name, viewport: [innerWidth, innerHeight], rect: { x: r.x, y: r.y, width: r.width, height: r.height }, zoom: s.zoom, rootZoom: getComputedStyle(document.documentElement).getPropertyValue('--desk-zoom'), scale: getComputedStyle(document.documentElement).getPropertyValue('--desk-scale'), display: s.display, overflow: s.overflow } }, name)
try {
  await page.goto(BASE + '/desk/' + BOOK, { waitUntil: 'domcontentloaded' }); await page.locator('.page h1').waitFor(); await stable(); result.titleFont=await page.locator('.page h1').evaluate(e=>getComputedStyle(e).fontFamily); assert.match(result.titleFont,/Noto Serif SC/)
  await run('暗色完整变量、纸纹和硬编码颜色映射', async () => {
    await openSettings(); await page.getByRole('button', { name: '墨色·暗', exact: true }).click(); await closeSettings(); await stable()
    const expected = { desk:'#1c1916', chrome:'#23201c', toc:'#211e1a', paper:'#2b2723', 'paper-2':'#302b26', rule:'#3b352f', 'rule-2':'#4a433b', ink:'#e9e0d0', 'ink-2':'#c3b8a6', 'ink-3':'#a29788', seal:'#d0644b', 'seal-dark':'#e78066', 'seal-soft':'#3a2621', 'seal-line':'#5a3529', indigo:'#9fb0d6', 'indigo-soft':'#262b38', 'indigo-line':'#3a4258', jade:'#7cc2b4', 'jade-soft':'#1f2f2b', 'jade-line':'#2f4a43', ochre:'#d9a066', 'ochre-soft':'#33281c', 'ochre-line':'#4d3a26' }
    const actual = await page.locator('.desk-v2').evaluate((element, keys) => { const s = getComputedStyle(element); return { vars: Object.fromEntries(keys.map(key => [key, s.getPropertyValue('--' + key).trim()])), texture: s.backgroundImage, paper: getComputedStyle(element.querySelector('.page')).backgroundColor, rail: getComputedStyle(element.querySelector('.rb')).backgroundColor, ball: getComputedStyle(element.querySelector('.ball')).backgroundColor } }, Object.keys(expected))
    assert.deepEqual(actual.vars, expected); assert.match(actual.texture, /\.035/); assert.equal(actual.paper, 'rgb(43, 39, 35)'); assert.equal(actual.rail, 'rgb(48, 43, 38)'); assert.equal(actual.ball, 'rgb(233, 224, 208)'); result.dark = actual
    await screenshot('extra-暗色-章.png'); await tab('简介'); const wait=await page.locator('.rhythm i.wait').evaluate(e=>({background:getComputedStyle(e).backgroundImage,border:getComputedStyle(e).borderColor})); assert.match(wait.background,/rgb\(33, 30, 26\)/); assert.match(wait.background,/rgb\(59, 53, 47\)/); result.dark.wait=wait; await screenshot('extra-暗色-简介.png')
  })
  await run('界面大小 UI 120% 与宽高 resize 算法', async () => {
    await openSettings(); await page.getByRole('button', { name: '宣纸·亮', exact: true }).click(); await page.getByRole('button', { name: '120%', exact: true }).click(); await closeSettings(); await stable()
    for (const size of [[2560,1312],[1600,900],[1300,700]]) {
      await page.setViewportSize({ width: size[0], height: size[1] }); await stable(); const m = await box('.desk-v2', 'root-resize'); const expected = Math.min(1.5, Math.max(1, size[0]/1700), Math.max(1, size[1]/800))*1.2; assert.ok(Math.abs(Number(m.zoom)-expected)<.0001, JSON.stringify(m)); result.measurements.push(m)
    }
    await page.setViewportSize({ width: 2560, height: 1312 }); await openSettings(); await page.getByRole('button', { name: '100%', exact: true }).click(); await closeSettings(); await stable()
  })
  await run('编辑部浮窗及停靠布局不越界、不发送聊天', async () => {
    await page.locator('.ball').click(); await page.getByTestId('editorial-floating').waitFor(); await stable(); const m=await box('[data-testid=editorial-floating]','editorial-floating'); result.measurements.push(m); assert.ok(m.rect.x>=0 && m.rect.y>=0 && m.rect.x+m.rect.width<=2561 && m.rect.y+m.rect.height<=1313, JSON.stringify(m)); const svg=await page.getByTestId('editorial-floating').locator('button svg').first().evaluate(e=>({fill:getComputedStyle(e).fill,stroke:getComputedStyle(e).stroke,width:getComputedStyle(e).width})); assert.equal(svg.fill,'none'); assert.equal(svg.width,'16px'); result.editorialIcon=svg; await screenshot('extra-编辑部.png')
    await page.getByRole('button', {name:'贴到右边',exact:true}).click(); await page.getByTestId('editorial-docked').waitFor(); result.measurements.push(await box('[data-testid=editorial-docked]','editorial-docked')); await page.getByRole('button',{name:'收起',exact:true}).click()
  })
  await run('存档弹窗与书页使用相同 z、保持居中', async () => {
    await tab('大纲'); await page.locator('.toc-foot').filter({hasText:'存档'}).click(); await page.getByRole('dialog',{name:'存档',exact:true}).waitFor(); await stable(); const m=await box('dialog.saves-dialog','saves'); result.measurements.push(m); assert.equal(Number(m.zoom),Number((await box('.desk-v2','root')).zoom)); assert.ok(Math.abs(m.rect.x+m.rect.width/2-1280)<2); assert.ok(Math.abs(m.rect.y+m.rect.height/2-656)<2); await screenshot('extra-存档.png'); await page.getByRole('button',{name:'关上存档',exact:true}).click()
  })
  await run('拆书小窗同 z 且只打开不启动任务', async () => {
    await page.locator('.progress').getByText('接着拆',{exact:true}).click(); const modal=page.getByRole('dialog',{name:/开始拆/}); await modal.waitFor(); const m=await box('[role=dialog]','teardown-start'); result.measurements.push(m); assert.equal(Number(m.zoom),Number((await box('.desk-v2','root')).zoom)); await page.keyboard.press('Escape')
  })
  await run('新正文目录全文搜索、命中高亮、方向键、读到哪', async () => {
    await tab('正文'); const input=page.getByRole('textbox',{name:'找章节、搜原文……',exact:true}); await input.fill('天毒珠'); const results=page.getByRole('region',{name:'原文搜索结果'}); await results.locator('.row').first().waitFor(); const row=results.locator('.row').first(), at=Number(await row.locator('.no').innerText()); await row.click(); await page.locator('.page.reader').waitFor(); await page.locator('[data-text-match]').first().waitFor(); assert.equal(Number((await page.locator('.reader h1').innerText()).match(/第\s*(\d+)\s*章/)[1]),at); const highlights=await page.locator('[data-text-match]').count(); assert.ok(highlights>0); await page.locator('.page.reader').evaluate(e=>e.scrollTo({top:e.scrollHeight})); await row.click(); await page.waitForTimeout(200); const mark=await page.locator('[data-text-match]').first().boundingBox(); const paper=await page.locator('.page.reader').boundingBox(); assert.ok(mark && paper && mark.y>=paper.y && mark.y<paper.y+paper.height, JSON.stringify({mark,paper}))
    const before=await page.locator('.reader h1').innerText(); await input.focus(); await page.keyboard.press('ArrowRight'); assert.equal(await page.locator('.reader h1').innerText(),before); await page.locator('.page.reader').click({position:{x:10,y:70}}); await page.keyboard.press('ArrowRight'); await page.waitForFunction(n=>document.querySelector('.reader h1')?.textContent.match(/第\s*(\d+)\s*章/)?.[1]===String(n),at+1); await page.keyboard.press('ArrowLeft'); await page.waitForFunction(n=>document.querySelector('.reader h1')?.textContent.match(/第\s*(\d+)\s*章/)?.[1]===String(n),at); const stored=await page.evaluate(book=>JSON.parse(localStorage.getItem('zhibi:teardown-reading:'+book)),BOOK); assert.equal(stored.chapter,at); result.reading={search:'天毒珠',firstHit:at,stored,highlightsBeforeTurning:highlights,repeatedSameWordRelocates:true}; await input.fill(''); await page.locator('.toc .row.top1').filter({hasText:'正文首页'}).click(); assert.match(await page.locator('.continue h2').innerText(),new RegExp('第 '+at+' 章')); assert.match(await page.locator('.continue').innerText(),/接着读/); await page.reload(); await page.locator('.continue h2').waitFor(); assert.match(await page.locator('.continue h2').innerText(),new RegExp('第 '+at+' 章')); result.reading.survivesReload=true
  })
  await run('已有作者书只读打开本书设置、居中同 z', async () => {
    await page.goto(BASE+'/desk/'+AUTHOR,{waitUntil:'domcontentloaded'}); await page.locator('.page h1').waitFor(); await tab('设定'); await page.getByRole('button',{name:/本书设置/}).click(); const dialog=page.getByRole('dialog',{name:'本书设置',exact:true}); await dialog.waitFor(); await stable(); const m=await box('[role=dialog]','book-settings'); result.measurements.push(m); assert.equal(Number(m.zoom),Number((await box('.desk-v2','root')).zoom)); assert.ok(Math.abs(m.rect.x+m.rect.width/2-1280)<2); assert.ok(Math.abs(m.rect.y+m.rect.height/2-656)<2); await screenshot('extra-本书设置.png'); await page.getByRole('button',{name:'关上本书设置',exact:true}).click()
  })
  await run('系统设置外观页、书房、上传、新建页面只浏览截图', async () => {
    await openSettings(); await screenshot('extra-系统设置.png'); await closeSettings(); await page.goto(BASE,{waitUntil:'domcontentloaded'}); await stable(); await screenshot('extra-书房.png'); await page.goto(BASE+'/teardown/new',{waitUntil:'domcontentloaded'}); await page.getByText('选择 TXT 文件，或拖到这里',{exact:true}).waitFor(); await screenshot('extra-上传页.png'); await page.goto(BASE+'/new',{waitUntil:'domcontentloaded'}); await stable(); await screenshot('extra-新建页.png')
  })
  await run('旧确认链接安全跳回已确认书，不重新导入 TXT', async () => {
    const response=await fetch(API+'/teardown/'+BOOK+'/preview'); result.confirmation={status:response.status};
    if(response.status===409) { await page.goto(BASE+'/teardown/'+BOOK,{waitUntil:'domcontentloaded'}); await page.waitForURL(BASE+'/desk/'+BOOK); result.boundaries.push('确认页未截图：真实独立库现有拆书已经确认，GET preview 返回409且确认页路由跳回书页；遵守不重新导入TXT、不改库/不造确认态，本轮不创建新上传。') }
    else { assert.equal(response.status,200); await page.goto(BASE+'/teardown/'+BOOK,{waitUntil:'domcontentloaded'}); await page.locator('#teardown-title').waitFor(); await screenshot('extra-确认页.png') }
  })
  result.authorAfter=await hashBook(AUTHOR); assert.equal(result.authorAfter,result.authorBefore); result.checks.push('已有作者书 book/library/outline-tree/bible/chapters 前后 SHA256 完全相同')
} finally { await browser.close(); result.finishedAt=new Date().toISOString(); fs.writeFileSync(REPORT,JSON.stringify(result,null,2)) }
if(result.failures.length||result.errors.length||result.blockedWrites.length||result.externalRequests.length) process.exitCode=1
console.log(JSON.stringify({checks:result.checks.length,failures:result.failures,errors:result.errors,blockedWrites:result.blockedWrites,screenshots:result.screenshots},null,2))
