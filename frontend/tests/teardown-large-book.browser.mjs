/** 真 API、合成大书、真实鼠标；仅允许独立端口，禁止模型/写请求。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'
import { cn } from '../src/pages/workspace/model.ts'

const BASE = process.env.ZHIBI_LARGE_URL, API = process.env.ZHIBI_LARGE_API
assert.ok(BASE && API && process.env.ZHIBI_LARGE_FIXTURE)
for (const address of [BASE, API]) {
  const url = new URL(address)
  assert.ok(['127.0.0.1', 'localhost'].includes(url.hostname) && url.port && !['8000', '4320'].includes(url.port))
}
const fixture = JSON.parse(fs.readFileSync(process.env.ZHIBI_LARGE_FIXTURE, 'utf8'))
const OUT = path.resolve(import.meta.dirname, '../../docs/拆书导入验收')
const browser = await chromium.launch({ executablePath: process.env.ZHIBI_CHROMIUM ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe' })
const context = await browser.newContext({ viewport: { width: 1024, height: 1000 } })
const errors = [], external = [], writes = [], results = []
await context.route('**/*', route => {
  const request = route.request(), url = new URL(request.url())
  if (url.protocol.startsWith('http') && !['127.0.0.1', 'localhost'].includes(url.hostname)) { external.push(url.origin); return route.abort() }
  if (url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { writes.push(url.pathname); return route.abort() }
  return route.continue()
})
await context.addInitScript(books => {
  localStorage.setItem('zhibi:editorial-dock', 'ball')
  localStorage.setItem('zhibi:appearance', JSON.stringify({ theme: 'paper', deskScale: 100 }))
  for (const { book } of Object.values(books)) sessionStorage.setItem('zhibi:workspace-reading:'+book, JSON.stringify({ tab:'简介',entry:'overview',node:'book',chapter:'home',open:[],directoryVersion:2 }))
}, fixture)
const page = await context.newPage()
page.on('pageerror', error => errors.push(String(error)))
const tab = name => page.locator('header.top nav').getByText(name, { exact: true })
const check = async (name, run) => { const detail = await run(); results.push({ name, passed:true, detail }); console.log('PASS', name) }
const open = async key => {
  await page.goto(`${BASE}/desk/${fixture[key].book}`)
  await expect(page.locator('.intro2 .statline .ochre')).toHaveText(`${fixture[key].units} 个单元`)
  await page.evaluate(() => document.fonts.ready)
}
const tiles = () => page.locator('.tiles > .tile')
const noOverflow = () => page.evaluate(() => {
  const widths = [...document.querySelectorAll('.tiles > .tile')].map(el => el.getBoundingClientRect().width)
  const regions = [document.documentElement, document.querySelector('.desk'), document.querySelector('.page')]
  return { widths, regions:regions.map(el => ({ client:el.clientWidth,scroll:el.scrollWidth })), ell:[...document.querySelectorAll('.tiles .ell')].filter(el => el.getClientRects().length).map(el => ({ client:el.clientWidth,scroll:el.scrollWidth,overflow:getComputedStyle(el).textOverflow })) }
})
try {
  await open('large')
  await check('大书设定：1024px两列等宽、无横向溢出，省略号限制千像素说明', async () => {
    await tab('设定').click()
    await expect(page.locator('.page h1')).toHaveText('设定')
    await expect(tiles().first().locator('.hd span')).toHaveText('244 人，其中 40 人写了全卡')
    const detail = await noOverflow()
    assert.ok(detail.widths.every(width => Math.abs(width-detail.widths[0])<.6))
    assert.ok(detail.regions.every(region => region.scroll<=region.client+1))
    assert.ok(detail.ell.some(row => row.scroll>1000 && row.client<300 && row.overflow==='ellipsis'))
    assert.equal(await tiles().nth(2).locator('.hd > b').first().evaluate(el=>getComputedStyle(el).flexShrink),'0')
    return detail
  })
  await check('四种More默认上限与展开：5条、2套、8处、3行，展开不跳转', async () => {
    const gold=tiles().nth(1), ladder=tiles().nth(2), places=tiles().nth(3)
    await expect(gold.locator('.kv b:visible')).toHaveCount(5)
    await expect(ladder.locator('.hd:visible')).toHaveCount(2)
    await expect(places.locator('.sub:visible')).toHaveCount(3)
    assert.ok((await places.innerText()).includes('顶层地点08'))
    assert.ok(!(await places.innerText()).includes('顶层地点09'))
    await page.setViewportSize({width:1600,height:1200})
    await page.screenshot({ path:path.join(OUT,'小修2-设定总览.png') })
    await page.setViewportSize({width:1024,height:1000})
    for (const [tile, text] of [[gold,'还有 39 条，展开'],[ladder,'还有 5 套，展开'],[places,'还有 4 处，展开'],[places,'还有 9 行，展开']]) {
      await tile.getByText(text,{exact:true}).click()
      await expect(page.locator('.page h1')).toHaveText('设定')
    }
    await expect(gold.locator('.kv b:visible')).toHaveCount(44)
    await expect(ladder.locator('.hd:visible')).toHaveCount(7)
    await expect(places.locator('.sub:visible')).toHaveCount(12)
    assert.ok((await places.innerText()).includes('顶层地点12'))
    const detail=await noOverflow()
    assert.ok(detail.regions.every(region=>region.scroll<=region.client+1))
    return { default:[5,2,8,3],expanded:[44,7,12,12],...detail }
  })
  await check('空作者五页顶栏都只有拆的书', async () => {
    for (const name of ['简介','精髓','设定','大纲','正文']) {
      await tab(name).click()
      await expect(page.locator('header.top .tag')).toHaveText('拆的书')
    }
  })
  await check('159单元自动28卷、8篇头，中文编号一至二十八、范围与单元数正确', async () => {
    await page.setViewportSize({width:1600,height:1800})
    await tab('简介').click()
    await expect(page.locator('.ugrid .ucard')).toHaveCount(28)
    await expect(page.locator('.intro-volume-arc')).toHaveCount(8)
    await expect(page.locator('.ugrid .seal-no')).toHaveText(Array.from({length:28},(_,i)=>cn(i+1)))
    await expect(page.locator('.label .n').filter({hasText:'一格一卷'})).toHaveText('一格一卷，点进去看这一卷的单元')
    for(let i=0;i<28;i++) {
      const [a,b]=fixture.large.ranges[i]
      await expect(page.locator('.ucard').nth(i).locator('small')).toHaveText(`第 ${a}–${b} 章 · ${b-a+1} 章 · ${i<19?6:5} 个单元`)
      await expect(page.locator('.ucard').nth(i).locator('b')).toHaveText(`${cn(i+1)}剧情卷${i+1}`)
    }
    const heads=await page.locator('.intro-volume-arc').evaluateAll(rows=>rows.map(el=>({title:el.querySelector('b').textContent,font:getComputedStyle(el.querySelector('b')).fontSize,weight:getComputedStyle(el.querySelector('b')).fontWeight,small:getComputedStyle(el.querySelector('small')).fontSize,margin:getComputedStyle(el).marginTop,span:getComputedStyle(el).gridColumn})))
    assert.deepEqual(heads.map(row=>row.title),fixture.large.arc_titles.map((title,i)=>`第${cn(i+1)}篇 ${title}`))
    assert.ok(heads.every((row,i)=>row.font==='13px'&&row.weight==='700'&&row.small==='12px'&&row.margin===(i?'6px':'0px')&&row.span==='1 / -1'))
    await page.screenshot({path:path.join(OUT,'小修2-简介页.png')})
    return heads
  })
  await check('卷格真实鼠标跳到大纲对应卷，并展开已收起的父篇', async () => {
    for(const index of [0,19,27]) {
      await page.locator('.ucard').nth(index).click()
      await expect(tab('大纲')).toHaveClass(/on/)
      await expect(page.locator('.page h1')).toContainText(`剧情卷${index+1}`)
      await expect(page.locator('.toc .row.on')).toContainText(`剧情卷${index+1}`)
      await tab('简介').click()
    }
  })
  await check('还在归的末卷不出格，尾卡范围从上一卷后到已读末章且章号可跳转', async () => {
    await open('open')
    await expect(page.locator('.ucard:not(.wait)')).toHaveCount(27)
    const a=fixture.open.ranges[26][1]+1,b=fixture.open.read
    await expect(page.locator('.ucard.wait')).toHaveText(`…还没收尾第 ${a}–${b} 章`)
    await page.locator('.ucard.wait').click()
    await expect(tab('大纲')).toHaveClass(/on/)
    await expect(page.locator('.page h1')).toContainText(`合成章${a}`)
    return {first:a,last:b}
  })
  await check('无篇大书不添加篇头；24单元保留单元格、25自动卷格；还没分卷只出尾卡', async () => {
    await open('direct')
    await expect(page.locator('.intro-volume-arc')).toHaveCount(0)
    await expect(page.locator('.ucard')).toHaveCount(28)
    await open('small24')
    await expect(page.locator('.ucard')).toHaveCount(24)
    await expect(page.locator('.label .n').filter({hasText:'一格一个单元'})).toBeVisible()
    await expect(page.locator('.ucard').nth(19).locator('.seal-no')).toHaveText('二十')
    await page.locator('.ucard').nth(23).click()
    await expect(page.locator('.page h1')).toContainText('剧情单元24')
    await open('small25')
    await expect(page.locator('.ucard')).toHaveCount(1)
    await expect(page.locator('.ucard small')).toContainText('25 个单元')
    await open('unassigned')
    await expect(page.locator('.ucard:not(.wait)')).toHaveCount(0)
    await expect(page.locator('.ucard.wait small')).toHaveText('第 1–100 章')
  })
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(writes,[])
  fs.writeFileSync(path.join(OUT,'小修2-界面交互.json'),JSON.stringify({results,errors,external,writes,real_model_calls:0},null,2)+'\n')
} catch(error) {
  await page.screenshot({path:path.join(process.env.ZHIBI_LARGE_DEBUG ?? path.resolve(OUT,'../../data/import-small2-20261021'),'browser-failure.png')}).catch(()=>{})
  throw error
} finally { await browser.close() }
