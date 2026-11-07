import { test, expect, type Page } from '@playwright/test';

test.beforeEach(async ({ context }) => {
  const login = await context.request.post('/api/auth/login', { data: { password: 'synthetic-contract-password' } });
  expect(login.ok()).toBe(true);
});

// Real Gateway, SQLite and WebUI; only the model boundary is scripted by the
// shared Python fixture. Real-provider clean-install acceptance is separate.
async function openChat(page: Page) {
  page.on('response', response => { if (response.status() >= 400) console.log('HTTP', response.status(), new URL(response.url()).pathname); });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  const start = page.getByRole('button', { name: 'Start conversation' });
  await expect(start.or(page.getByRole('button', { name: 'Skip setup' })).or(input)).toBeVisible();
  if (await page.getByRole('button', { name: 'Skip setup' }).isVisible()) {
    await page.getByRole('button', { name: 'Skip setup' }).click();
  }
  // A clean Gateway offers Start conversation. A new browser pointed at an
  // existing Gateway resumes its durable active conversation instead. Wait
  // for either stable state so the contract covers both first-use and
  // cross-device continuity without racing the session-list response.
  if (!await input.isVisible()) {
    await Promise.race([
      start.click().catch(() => undefined),
      input.waitFor({ state: 'visible' }),
    ]);
  }
  await expect(input).toBeEnabled();
}

async function pickPage(page: Page, name: string) {
  if (!await page.locator('#jaeger-navigation').isVisible()) await page.getByRole('button', {name:'Toggle navigation'}).click();
  if (['Work','Research','Machine','Tasks'].includes(name) && !await page.locator('.jg-stable-demo__more').evaluate(el => (el as HTMLDetailsElement).open)) await page.getByText('More tools', {exact:true}).click();
  await page.getByRole('navigation', {name:'Jaeger navigation'}).getByRole('button', {name, exact:true}).click();
}

test('default screen exposes the current workspace navigation and chat controls', async ({ page }) => {
  await openChat(page);
  if (!await page.locator('#jaeger-navigation').isVisible()) await page.getByRole('button', {name:'Toggle navigation'}).click();
  await page.getByText('More tools', {exact:true}).click();
  await expect(page.getByRole('navigation', { name: 'Jaeger navigation' }).getByRole('button')).toHaveText(['Chat', 'Imagine', 'Library', 'Automations', 'Feed', 'Agents', 'Work', 'Research', 'Machine', 'Tasks']);
  await expect(page.locator('header[aria-label="Conversation toolbar"]')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Toggle navigation' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled();
});

test('keyboard send reaches Gateway, persists history and keeps chat across Tasks', async ({ page }) => {
  await openChat(page);
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  await input.fill('Say BROWSER-CONTRACT-ANSWER');
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled();
  await input.press('Enter');
  await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER', { timeout: 30000 });
  await expect(input).toHaveValue('');
  const session = await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'));
  expect(session).toBeTruthy();
  await pickPage(page, 'Tasks');
  await expect(page.getByRole('heading', { name: 'Tasks', exact: true })).toBeVisible();
  await pickPage(page, 'Chat');
  await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER');
  await page.reload();
  await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER');
  expect(await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(session);
});

test('Shift+Enter retains an unsent multiline draft across navigation', async ({ page }) => {
  await openChat(page);
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  // Restored history may still arrive after the composer becomes ready.
  // Assert the actual unsent text never enters history rather than racing its count.
  await input.fill('First line');
  await input.evaluate((element: HTMLTextAreaElement) => element.setSelectionRange(element.value.length, element.value.length));
  await input.press('Shift+Enter'); await input.pressSequentially('Second line');
  await pickPage(page, 'Tasks');
  await pickPage(page, 'Chat');
  await expect(input).toHaveValue('First line\nSecond line');
  await expect(page.locator('.jg-bubble--user').filter({hasText:'First line\nSecond line'})).toHaveCount(0);
});

test('a stale device-local selection resumes the durable Gateway conversation', async ({ page }) => {
  await openChat(page);
  const durable = await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'));
  expect(durable).toBeTruthy();
  await page.evaluate(() => localStorage.setItem('jaeger.stable-demo.session.v1', 'missing-browser-contract'));
  await page.reload();
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(durable);
});

for (const width of [301, 320, 390, 1280]) {
  test(`Chat and Tasks fit ${width}px in light and dark without browser exceptions`, async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width, height: 900 });
    await openChat(page);
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme });
      for (const name of ['Tasks', 'Chat']) {
        await pickPage(page, name);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      if (width <= 320) {
        for (const selector of ['.jg-stable-demo__header', '.jg-composer', '.jg-composer__input', '.jg-composer__bar']) {
          const box = await page.locator(selector).boundingBox();
          expect(box, `${selector} must be visible`).not.toBeNull();
          expect(box!.x, `${selector} must stay inside the left edge`).toBeGreaterThanOrEqual(0);
          expect(box!.x + box!.width, `${selector} must stay inside the right edge`).toBeLessThanOrEqual(width);
        }
        await expect(page.locator('.jg-runtime-trigger span')).toBeHidden();
        await expect(page.locator('.jg-stable-demo__mobile-dock')).toHaveCount(0);
        await page.getByRole('button', {name:'Toggle navigation'}).click();
        await expect(page.getByRole('button', {name:'Close sidebar'})).toBeVisible();
        await page.getByRole('button', {name:'Dismiss navigation'}).click({position:{x:width-3,y:450}});
        await expect(page.locator('#jaeger-navigation')).toBeHidden();
      }
    }
    expect(errors).toEqual([]);
  });
}
