/** 拆书进度与逐章记录组件回归：独立 Vite，无代理，API 全部拦截，不连接书库。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
const port = Number(process.env.TEARDOWN_UI_TEST_PORT || 4452)
assert.ok(port > 1024 && ![8000, 4320].includes(port), '必须使用独立端口')
const base = `http://127.0.0.1:${port}`
const output = path.join(root, 'data/teardown-progress-ui')
await fs.mkdir(output, { recursive: true })
const evidence = { base, checks: [], pageErrors: [], unexpectedRequests: [], realModelCalls: 0 }
const harness = `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"></head><body><div id="root"></div><script type="module">
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { TeardownProgress, TeardownControlProvider } from '/src/pages/workspace/TeardownProgress.tsx';
import { ChapterPage, ManuscriptDirectory } from '/src/pages/workspace/Manuscript.tsx';
import { ActionsContext } from '/src/pages/workspace/actions.ts';
import '/src/index.css';
const h = React.createElement;
const originalRecords = {read_version:1,read:{people:[{name:'云澈',shown:'不肯服输',also_called:['萧澈'],change:'离开萧门'}],things:[{kind:'地方',name:'萧门',note:'萧氏所居',belongs:'流云城'},{kind:'秘密',name:'身世',note:'留下线索',secret:'埋下'}],moments:[{who:'云澈',what:'直面长老',shows:'不屈'}],waits:[{action:'立下',what:'如何变强'}],tropes:['退婚','逆袭'],feel:'大爽'}};
const initial = {id:'ui-fixture',source:'teardown',title:'进度组件合成书',categories:[],teardown:{stage:'queued',chapters:40,upto:20,stop_note:'拆到第 20 章了（你定的）。'},outline:{id:'book',kind:'全书',children:[{id:'v1',kind:'卷',title:'第一卷　流云城',children:[{id:'u1',kind:'单元',title:'单元一　离开萧门',children:[{id:'c1',kind:'章',title:'第1章　青石巷',ref:{type:'chapter',id:'1'},range:[1,1],uses:[],teardown:{read:true,failed:false},body:{status:'done',words:20,text:'云澈站在青石巷里，天毒珠泛起微光。',teardown:originalRecords}},{id:'c2',kind:'章',title:'第2章　雾夜',ref:{type:'chapter',id:'2'},range:[2,2],uses:[],teardown:{read:false,failed:true},body:{status:'done',words:20,text:'雨落下来。'}}]}]}]}};
const initialJob={kind:'teardown',status:'queued',pending:{teardown:{doing:'queued',read:8,target:20,total:40,reading:[9,12],range:[1,20],eta_seconds:120,failed:[]}}};
const noop=()=>{};
const loadChapter=async()=>({text:'云澈站在青石巷里，天毒珠泛起微光。',teardown:window.lazyRecords});
function App(){
 const [book,setBook]=useState(initial),[job,setJob]=useState(initialJob),[stopping,setStopping]=useState(false),[retries,setRetries]=useState(0),[opened,setOpened]=useState(0);
 window.teardownUI={setJob:(doing,extra={})=>{setStopping(false);setJob(doing?{...initialJob,status:doing==='queued'?'queued':'running',pending:{teardown:{...initialJob.pending.teardown,doing,...extra}}}:null)},setStage:stage=>setBook(b=>({...b,teardown:{...b.teardown,stage}})),setSource:source=>setBook(b=>({...b,source})),setRecords:record=>setBook(b=>{const next=structuredClone(b);next.outline.children[0].children[0].children[0].body.teardown=record;return next;}),setLazyRecord:read=>{window.lazyRecords=read?originalRecords:{};setBook(b=>{const next=structuredClone(b);const chapter=next.outline.children[0].children[0].children[0];delete chapter.body.text;delete chapter.body.teardown;chapter.teardown={read,failed:false};return next;})},originalRecords};
 const control={job,stopping,starting:false,start:async()=>{},stop:async()=>{setStopping(true);await new Promise(()=>{})},retry:async()=>setRetries(n=>n+1),openStart:()=>setOpened(n=>n+1)};
 const nav={openChapter:noop,openNode:noop,openEntry:noop,toast:noop};
 const writing={status:{state:'idle'},gates:{trial:false},trialDone:false,loadChapter};
 return h(ActionsContext.Provider,{value:{actions:{live:true,saveNode:async()=>{}},report:noop}},h(TeardownControlProvider,{value:control},h('main',{className:'min-h-screen bg-paper text-ink'},h(TeardownProgress,{book}),h('p',{'data-testid':'callbacks'},'retries='+retries+';opened='+opened),h('div',{className:'flex'},h('div',{style:{width:300,flexShrink:0}},h(ManuscriptDirectory,{book,selected:'c1',onSelect:noop,onExport:noop,writing})),h('div',{className:'min-w-0 flex-1'},h(ChapterPage,{book,id:'c1',writing,nav}))))));
}
createRoot(document.getElementById('root')).render(h(App));
</script></body></html>`
const server = await createServer({
  configFile: false, root: path.join(root, 'frontend'), cacheDir: path.join(output, 'vite-cache'),
  plugins: [react(), tailwindcss(), { name: 'isolated-teardown-progress', configureServer(vite) {
    vite.middlewares.use(async (req, res, next) => {
      if (req.url?.startsWith('/api/')) { res.statusCode = 503; res.end('Real API access forbidden'); return }
      if (req.url?.startsWith('/__teardown-progress')) { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(await vite.transformIndexHtml('/__teardown-progress', harness)); return }
      next()
    })
  } }],
  server: { host: '127.0.0.1', port, strictPort: true, proxy: {}, open: false, hmr: false, watch: null },
})
let browser
const check = name => { evidence.checks.push(name); console.log(`PASS ${name}`) }
try {
  await server.listen()
  browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE })
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce' })
  page.on('pageerror', error => evidence.pageErrors.push(error.message))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    if (url.pathname !== '/api/books/ui-fixture/search') { evidence.unexpectedRequests.push(url.pathname); return route.abort() }
    const found = url.searchParams.get('q') === '天毒珠'
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ chapters: found ? 1 : 0, results: found ? [{ index: 1, title: '青石巷', times: 1, near: '云澈站在青石巷里，天毒珠泛起微光。' }] : [] }) })
  })
  await page.goto(`${base}/__teardown-progress`)
  const strip = page.getByTestId('teardown-progress-strip')
  await expect(strip).toContainText('排队中：前面还有书在拆')
  await expect(strip.getByRole('button', { name: '停下', exact: true })).toBeEnabled()
  check('排队中文字与停下入口')
  const setJob = (doing, extra) => page.evaluate(({ doing, extra }) => window.teardownUI.setJob(doing, extra), { doing, extra })
  await setJob('read', { eta_seconds: 59 })
  await expect(strip).toContainText('设定师在读第 9–12 章 · 已拆 8／20 章（拆到第 20 章） · 还要大约 不到 1 分钟')
  await expect(strip.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '8')
  await setJob('units')
  await expect(strip).toContainText('主编在归单元：第 1–20 章 · 已拆 8／20 章（拆到第 20 章） · 还要大约 2 分钟')
  await setJob('read', { eta_seconds: 3660 })
  await expect(strip).toContainText('还要大约 1 小时 1 分钟')
  await setJob('read', { eta_seconds: null, target: 40 })
  await expect(strip).not.toContainText('还要大约')
  await expect(strip).not.toContainText('拆到第')
  await setJob('volumes')
  await expect(strip).toContainText('主编在归卷')
  await setJob('closing')
  await expect(strip).toContainText('在收尾：把最后几章归进单元和卷')
  check('读、归单元、归卷、收尾、三种ETA和全本/部分目标')
  await setJob('read', { failed: [2, 7] })
  await strip.getByRole('button', { name: '· 2 章没读成', exact: true }).click()
  await expect(strip).toContainText('第 2 章、第 7 章')
  await expect(strip.getByRole('button', { name: '再试一次', exact: true })).toBeDisabled()
  await strip.getByRole('button', { name: '停下', exact: true }).click()
  await expect(strip.getByRole('button', { name: '正在停：读完手上这几章就停', exact: true })).toBeDisabled()
  check('失败可展开，运行中不能另开重试，点击停下立即变字禁用')
  await setJob(null)
  await page.evaluate(() => window.teardownUI.setStage('stopped'))
  await expect(strip).toContainText('拆到第 20 章了（你定的）。')
  await expect(strip).toContainText('· 1 章没读成')
  await strip.getByRole('button', { name: '再试一次', exact: true }).click()
  await strip.getByRole('button', { name: '接着拆', exact: true }).click()
  await expect(page.getByTestId('callbacks')).toHaveText('retries=1;opened=1')
  await page.evaluate(() => window.teardownUI.setStage('done'))
  await expect(strip).toContainText('拆完了 · 40 章，1 个单元，1 卷')
  check('终态重建失败章；重试/接着拆控制入口；完成统计')
  const records = page.getByRole('button', { name: '这一章记下的', exact: true })
  await expect(records).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByText('出场的人', { exact: true })).not.toBeVisible()
  await records.click()
  for (const heading of ['出场的人', '新冒出来的', '名场面', '读者在等的', '用了的桥段']) await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  for (const wording of ['也叫 萧澈', '：不肯服输（离开萧门）', '地方「萧门」：萧氏所居 属于 流云城', '秘密（埋下）「身世」：留下线索', '云澈：直面长老——立住了不屈', '立下：如何变强', '退婚、逆袭']) await expect(page.getByText(wording, { exact: false }).last()).toBeVisible()
  await expect(page.getByText('大爽', { exact: true })).not.toBeVisible()
  await page.screenshot({ path: path.join(output, 'records-components.png'), fullPage: true })
  await page.evaluate(() => window.teardownUI.setRecords({ read_version: 1, read: { tropes: ['逆袭'] } }))
  await expect(page.getByRole('heading', { name: '出场的人', exact: true })).not.toBeVisible()
  await expect(page.getByRole('heading', { name: '用了的桥段', exact: true })).toBeVisible()
  await page.evaluate(() => window.teardownUI.setRecords({}))
  await expect(records).not.toBeVisible()
  check('正文记录默认折叠、五段格式、空段隐藏、未读隐藏、不显示感觉')
  await page.evaluate(() => window.teardownUI.setLazyRecord(false))
  await expect(records).not.toBeVisible()
  await page.evaluate(() => window.teardownUI.setLazyRecord(true))
  await expect(records).toBeVisible()
  check('当前章保持打开，目录读状态更新后重新加载详情并显示新记录')
  const search = page.getByPlaceholder('找章节、搜原文……')
  await search.fill('青石')
  await expect(page.getByRole('button', { name: '第1章 青石巷', exact: true })).toBeVisible()
  await expect(page.getByText('没找到「青石」', { exact: true })).not.toBeVisible()
  await search.fill('天毒珠')
  await expect(page.getByText('原文里有「天毒珠」的章（1 章）', { exact: true })).toBeVisible()
  await expect(page.getByText('没找到「天毒珠」', { exact: true })).not.toBeVisible()
  await search.fill('完全不存在')
  await expect(page.getByText('没找到「完全不存在」', { exact: true })).toHaveCount(1)
  await expect(page.getByRole('region', { name: '原文搜索结果', exact: true })).not.toBeVisible()
  await page.evaluate(() => window.teardownUI.setSource('new'))
  await search.fill('天毒珠')
  await expect(page.getByText('原文里有「天毒珠」的章（1 章）', { exact: true })).toBeVisible()
  await expect(page.getByText('没找到「天毒珠」', { exact: true })).not.toBeVisible()
  await expect(strip).not.toBeVisible()
  check('目录三种结果无矛盾，作者自己的书搜索同样修复且不显示拆书条')
  assert.deepEqual(evidence.pageErrors, [])
  assert.deepEqual(evidence.unexpectedRequests, [])
} finally {
  await browser?.close()
  await server.close()
  await fs.writeFile(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
}
console.log(JSON.stringify({ checks: evidence.checks.length, pageErrors: evidence.pageErrors.length, unexpectedRequests: evidence.unexpectedRequests.length }))
