/** 新书页第四步原型（开写、正文、拍板）：在原型里点一遍，截图放进 docs/新书页验收/第四步原型/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322），再在 frontend 下运行：node tests/workspace-step4.browser.mjs */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第四步原型')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

const shot = async (name) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(400)
  await page.screenshot({ path: path.join(output, `${name}.jpg`), quality: 88 })
  console.log(name)
}
const open = async (book = '') => {
  await page.goto(`${base}/prototype/workspace${book ? `?book=${book}` : ''}`)
  await page.getByRole('button', { name: '正文', exact: true }).click()
}
const demo = async (label) => {
  await page.getByRole('button', { name: '原型 · 演示写作' }).click()
  await page.getByRole('button', { name: label, exact: true }).click()
  await page.waitForTimeout(300)
}
const scrollMain = (to) => page.evaluate((y) => { const m = document.querySelector('main'); m.scrollTop = y === 'end' ? m.scrollHeight : y }, to)

try {
  // 1. 示例书：正文首页，开写
  await open()
  await expect(page.getByRole('heading', { name: '接着写' })).toBeVisible()
  await shot('1-正文首页-这一轮写多少和停在哪')

  // 2. 开写：写手一句句写，顶栏下面一条在说谁在干什么
  await page.getByRole('main').getByRole('button', { name: '接着写', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '写手在写' })).toBeVisible({ timeout: 15000 })
  await page.getByRole('status').getByRole('button', { name: '去看' }).click()
  await page.waitForTimeout(3500)
  await shot('2-正在写-字一句句出来')

  // 3. 写完第 3 章：停下来请你试读
  await expect(page.getByRole('status').filter({ hasText: '试读前 3 章' })).toBeVisible({ timeout: 30000 })
  await page.getByRole('status').getByRole('button', { name: '去看' }).click()
  await shot('3-试读前3章-卡片在第1章上面')

  // 4. 读完了，接着写：写第 4 章、给单元二出章纲、写第 5 章，写够 3 章停
  await page.getByRole('button', { name: '读完了，接着写' }).click()
  await expect(page.getByRole('status').filter({ hasText: '这一轮写完了' })).toBeVisible({ timeout: 60000 })
  await page.getByRole('button', { name: '第5章 井边的老刘' }).click()
  await shot('4-这一轮写完了-单元二出了章纲')
  await scrollMain('end')
  await page.getByRole('button', { name: '设定师记下的变化' }).click()
  await page.getByRole('button', { name: /^审稿/ }).click()
  await scrollMain('end')
  await shot('5-一章的末尾-章纲设定变化审稿')

  // 6~9. 几种要你拍板的样子
  await demo('等你看卷纲')
  await expect(page.getByText('等你拍板 · 第二卷的卷纲')).toBeVisible()
  await shot('6-卷纲-卡片在第二卷那一页')
  await page.getByRole('button', { name: '让主编改' }).click()
  await page.getByRole('textbox').last().fill('单元三放宽到 5 章，讲经堂加一个能说话的女弟子')
  await shot('7-卷纲-让主编改')
  await demo('等你看下一篇怎么走')
  await expect(page.getByText('等你拍板 · 第二篇怎么走')).toBeVisible()
  await shot('8-下一篇怎么走')
  await demo('等你看章纲')
  await expect(page.getByText('等你拍板 · 单元二的章纲')).toBeVisible()
  await shot('9-单元二的章纲')
  await demo('一章重写两次还过不了')
  await expect(page.getByText(/要你定夺 · 第3章/).first()).toBeVisible()
  await shot('10-一章重写两次还过不了')
  await demo('出错停下了')
  await shot('11-出错停下了')

  // 12. 按意见重写一章
  await demo('回到开头（写好了 2 章）')
  await page.getByRole('button', { name: '第2章 筑基丹' }).click()
  await page.locator('article').hover()
  await page.getByRole('button', { name: '更多' }).click()
  await page.getByRole('button', { name: '按意见重写这一章' }).click()
  await page.getByPlaceholder(/打斗再写足一点/).fill('装病那段压短一点，七个师兄的数字那里再吓人一些')
  await shot('12-按意见重写这一章')

  // 16~21. 编辑部帮拆：单元出章纲、卷拆成单元。先出一版草稿，收下才放进大纲
  await demo('回到开头（写好了 2 章）')
  await page.getByRole('button', { name: '大纲', exact: true }).click()
  await page.getByRole('button', { name: /外门考核/ }).first().click()
  await page.getByRole('button', { name: '编辑部出章纲' }).click()
  await page.getByPlaceholder(/考核那场戏多给两章/).fill('第一章就要死人')
  await shot('16-编辑部出章纲-先说想要什么')
  await page.getByRole('button', { name: '出章纲', exact: true }).click()
  await expect(page.getByText('草稿 · 还没放进大纲')).toBeVisible({ timeout: 15000 })
  await page.getByText('主编出的章纲').scrollIntoViewIfNeeded()
  await page.locator('.group\\/draft').nth(1).hover()
  await shot('17-出好的章纲-草稿还没放进大纲')
  await page.locator('.group\\/draft').nth(3).hover()
  await page.getByRole('button', { name: '不要这一章' }).nth(3).click()
  await page.getByRole('button', { name: '再出一版' }).first().scrollIntoViewIfNeeded()
  await shot('18-不要第8章-后面的章号往前补')
  await page.getByRole('button', { name: '再出一版' }).first().click()
  await page.getByPlaceholder(/考场那场戏太短/).fill('考场那场戏太短，拆成两章')
  await page.getByRole('button', { name: '再出一版' }).last().click()
  await expect(page.getByText('第 2 版')).toBeVisible({ timeout: 15000 })
  await page.getByText('主编出的章纲').scrollIntoViewIfNeeded()
  await shot('19-再出一版-照你说的改')
  await page.getByRole('button', { name: /^收下这/ }).click()
  await expect(page.getByText(/收下了 6 章/)).toBeVisible()
  await shot('20-收下了-放进大纲还能撤销')
  await page.getByRole('button', { name: /递丹之局/ }).first().click()
  await page.getByRole('button', { name: '编辑部出章纲' }).click()
  await page.getByRole('button', { name: '出章纲', exact: true }).click()
  await expect(page.getByText(/^收下以后/)).toBeVisible({ timeout: 15000 })
  await page.getByText('主编出的章纲').scrollIntoViewIfNeeded()
  await shot('21-写了一半的单元-只换没写的')
  await page.getByRole('button', { name: /内门试炼/ }).first().click()
  await page.getByRole('button', { name: '编辑部拆成单元' }).click()
  await page.getByRole('button', { name: '拆', exact: true }).click()
  await expect(page.getByText('主编出的单元')).toBeVisible({ timeout: 15000 })
  await page.getByText('主编出的单元').scrollIntoViewIfNeeded()
  await shot('22-第二卷拆成单元')

  // 13. 以前用真模型写的旧书：真正文、真审稿
  await open('snap:nisu')
  await page.getByRole('button', { name: '第1章 暗格绝笔' }).click()
  await shot('13-真模型旧书-第1章')

  // 14. 写了 60 章的书：目录默认只展开在写的那一卷
  await open('live:522ce242-c634-49b4-a536-e03a1086e077')
  await shot('14-写了60章的书-正文首页')

  // 15. 刚开的空书：大纲还空着，先去大纲
  await open('empty')
  await shot('15-空书-大纲还空着')

  if (errors.length) throw new Error(`页面报错：${errors.join('；')}`)
  console.log('都点通了')
} finally {
  await browser.close()
}
