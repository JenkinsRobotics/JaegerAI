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
  await expect(page.getByRole('button', { name: 'Start conversation' }).or(page.getByRole('button', { name: 'Skip setup' }))).toBeVisible();
  if (await page.getByRole('button', { name: 'Skip setup' }).isVisible()) {
    await page.getByRole('button', { name: 'Skip setup' }).click();
  }
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
}

test('default screen exposes Chat, Tasks and the preserved preview', async ({ page }) => {
  await openChat(page);
  await expect(page.getByRole('navigation', { name: 'Demo navigation' }).getByRole('button')).toHaveText(['Chat', 'Tasks']);
  await expect(page.getByRole('link', { name: 'Full workspace (preview)' })).toHaveAttribute('href', '/?full=1');
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
  await page.getByRole('button', { name: 'Tasks', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Tasks', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Chat', exact: true }).click();
  await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER');
  await page.reload();
  await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER');
  expect(await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(session);
});

test('Shift+Enter retains an unsent multiline draft across navigation', async ({ page }) => {
  await openChat(page);
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  await input.fill('First line'); await input.press('Shift+Enter'); await input.pressSequentially('Second line');
  await page.getByRole('button', { name: 'Tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Chat', exact: true }).click();
  await expect(input).toHaveValue('First line\nSecond line');
  await expect(page.locator('.jg-bubble--user')).toHaveCount(0);
});

test('missing saved session reports failure without replacing or resending it', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('jaeger.stable-demo.session.v1', 'missing-browser-contract'));
  await page.goto('/');
  if (await page.getByRole('button', { name: 'Skip setup' }).isVisible()) await page.getByRole('button', { name: 'Skip setup' }).click();
  await expect(page.getByRole('alert')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe('missing-browser-contract');
});

for (const width of [390, 1280]) {
  test(`Chat and Tasks fit ${width}px in light and dark without browser exceptions`, async ({ page }) => {
    const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
    await page.setViewportSize({ width, height: 900 });
    await openChat(page);
    for (const colorScheme of ['light', 'dark'] as const) {
      await page.emulateMedia({ colorScheme });
      for (const name of ['Tasks', 'Chat']) {
        await page.getByRole('button', { name, exact: true }).click();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
    }
    expect(errors).toEqual([]);
  });
}
