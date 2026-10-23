/** 新书页第五步第一批原型（聊天：去私聊、@ 点名、停、边写边显示、重新回答／重试）：在原型里点一遍，截图放进 docs/新书页验收/第五步原型/。
 *  先起好预览（.claude/launch.json 的 zhibi-step2，网页 4322），再在 frontend 下运行：node tests/workspace-step5.browser.mjs */
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const base = process.env.TEST_BASE_URL ?? 'http://127.0.0.1:4322'
const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'docs/新书页验收/第五步原型')
await fs.mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true, executablePath: process.env.ZHIBI_CHROMIUM || undefined })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

const shot = async (name) => {
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(output, `${name}.jpg`), quality: 88 })
  console.log(name)
}
const box = page.getByRole('textbox', { name: '给编辑部发消息' })
const openChat = async (book = '') => {
  await page.goto(`${base}/prototype/workspace${book ? `?book=${book}` : ''}`)
  await page.locator('button[title="编辑部"]').click()
  await expect(box).toBeVisible()
}

try {
  // 1. 只有一个聊天：没有左边那一排私聊
  await openChat()
  await shot('1-只有一个聊天')

  // 2. 打 @：输入框上面弹出四个人
  await box.click()
  await page.keyboard.type('@')
  await expect(page.getByRole('listbox', { name: '点名让谁来答' })).toBeVisible()
  await shot('2-打@弹出四个人')

  // 3. 点了设定师：输入框上面是名牌，话里的 @ 拿掉
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await page.keyboard.type('主角现在什么境界？前后对得上吗？')
  await shot('3-点了名-输入框上面是名牌')

  // 4. 发出去：设定师边写边显示，发送键变成「停」
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '停下' })).toBeVisible()
  await page.waitForTimeout(3200)
  await shot('4-边写边显示-发送键变停')

  // 5. 停下：写出来的留着，下面能重新回答
  await page.getByRole('button', { name: '停下' }).click()
  await expect(page.getByText('你让它停下了，写出来的留着')).toBeVisible()
  await shot('5-停下了-写出来的留着')

  // 6. 重新回答：这一条换成新的一段
  await page.getByRole('button', { name: '重新回答' }).click()
  await expect(page.getByRole('button', { name: '重新回答' })).toBeVisible({ timeout: 30000 })
  await shot('6-重新回答-换成新的一段')

  // 7. 没点名：主编来答；这一句演示没答上来，给「重试」
  await box.fill('演示一下出错：这一卷节奏拖不拖？')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible({ timeout: 10000 })
  await shot('7-没答上来-重试')
  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByRole('button', { name: '重新回答' })).toBeVisible({ timeout: 30000 })
  await shot('8-重试答上来了')

  // 9. 空书第一次打开：说一句怎么用，点一个人就是点他的名
  await openChat('empty')
  await shot('9-空书-第一次打开')
  await page.getByRole('button', { name: /写手/ }).click()
  await expect(page.getByText('问写手')).toBeVisible()

  if (errors.length) throw new Error(`页面报错：${errors.join('；')}`)
} finally {
  await browser.close()
}
