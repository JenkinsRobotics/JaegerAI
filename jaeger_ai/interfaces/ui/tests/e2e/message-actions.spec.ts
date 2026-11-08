import { test, expect, type Page, type Locator } from '@playwright/test';

// Real isolated Gateway/SQLite/WebUI via ui_browser_contract.py. Only the model
// and clipboard boundaries are scripted. Touch holds dispatch PointerEvents:
// this checks WebKit handling, not iOS's native long-press callout arbitration.
test.beforeEach(async ({ context }) => {
  expect((await context.request.post('/api/auth/login', { data: { password: 'synthetic-contract-password' } })).ok()).toBe(true);
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: async (text: string) => { (window as unknown as { copiedText: string }).copiedText = text; },
    } });
  });
});

async function prepare(page: Page) {
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Message', exact: true });
  const start = page.getByRole('button', { name: 'Start conversation' });
  const skip = page.getByRole('button', { name: 'Skip setup' });
  await expect(input.or(start).or(skip)).toBeVisible();
  if (await skip.isVisible()) await skip.click();
  if (!await input.isVisible()) await Promise.race([start.click().catch(() => undefined), input.waitFor({state: 'visible'})]);
  await expect(input).toBeEnabled();
  const prompt = `Say BROWSER-CONTRACT-ANSWER ${Date.now()}`;
  await input.fill(prompt);
  await expect(page.getByRole('button', {name: 'Send', exact: true})).toBeEnabled();
  await page.getByRole('button', {name: 'Send', exact: true}).click();
  await expect(page.locator('.jg-bubble--user').last()).toHaveText(prompt);
  await expect(page.locator('.jg-bubble--user').last().locator('..').locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER', {timeout: 30000});
  await expect(page.getByRole('button', {name: 'Stop current turn (⌘Esc)', exact: true})).toHaveCount(0);
  const user = page.locator('.jg-bubble--user').last();
  const answer = page.locator('.jg-bubble--assistant').last();
  return {input, user, answer};
}

async function pointer(bubble: Locator, kind: string, x = 30, y = 30) {
  await bubble.dispatchEvent(kind, {pointerId: 7, pointerType: 'touch', isPrimary: true, button: 0, bubbles: true, clientX: x, clientY: y});
}
async function openMenu(page: Page, bubble: Locator, touch: boolean) {
  await bubble.scrollIntoViewIfNeeded();
  // WebKit delivers scroll events after scrollIntoView resolves. A hold starts
  // once scrolling has settled, like a finger resting after a swipe.
  await page.waitForTimeout(250);
  if (touch) {
    await pointer(bubble, 'pointerdown');
    await page.waitForTimeout(520);
    await pointer(bubble, 'pointerup');
  } else await bubble.click({button: 'right'});
  await expect(page.getByRole('menu', {name: 'Message actions'})).toBeVisible();
}
const copied = (page: Page) => page.evaluate(() => (window as unknown as {copiedText?: string}).copiedText);

test('message menu exposes five commands, copies exact targets, quotes and selects text', async ({page, isMobile}) => {
  const {user, answer} = await prepare(page);
  const userText = (await user.textContent())!.trim();
  await openMenu(page, user, isMobile);
  const menu = page.getByRole('menu', {name: 'Message actions'});
  for (const name of ['Reply', 'Mark as unread', 'Copy', 'Select Text', 'Copy Request ID']) await expect(menu.getByRole('menuitem', {name, exact: true})).toBeEnabled();
  expect(await menu.getByRole('menuitemcheckbox').count()).toBeGreaterThan(0);
  if (isMobile) {
    await page.screenshot({path: '/tmp/jaeger-message-actions-mobile-light.png'});
    await page.emulateMedia({colorScheme: 'dark'});
    await page.screenshot({path: '/tmp/jaeger-message-actions-mobile-dark.png'});
    await page.emulateMedia({colorScheme: 'light'});
  }
  const bounds = await menu.boundingBox();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height + 1);
  await menu.getByRole('menuitem', {name: 'Copy', exact: true}).click();
  await expect.poll(() => copied(page)).toBe(userText);
  await openMenu(page, user, isMobile);
  await menu.getByRole('menuitem', {name: 'Copy Request ID', exact: true}).click();
  const id = await copied(page); expect(id).toBeTruthy(); expect(id).not.toBe(userText);
  await openMenu(page, answer, isMobile);
  await menu.getByRole('menuitem', {name: 'Copy Request ID', exact: true}).click();
  await expect.poll(() => copied(page)).toBe(id);
  await openMenu(page, user, isMobile);
  await menu.getByRole('menuitem', {name: 'Reply', exact: true}).click();
  await expect(page.getByLabel('Quoted reply')).toContainText(userText);
  await page.getByRole('button', {name: 'Cancel reply'}).click();
  await openMenu(page, answer, isMobile);
  await menu.getByRole('menuitem', {name: 'Select Text', exact: true}).click();
  const text = page.getByRole('textbox', {name: 'Message text', exact: true});
  await expect(text).toContainText('BROWSER-CONTRACT-ANSWER');
  await text.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(0, 7));
  const selected = (await text.inputValue()).slice(0, 7);
  await page.getByRole('button', {name: 'Copy selection', exact: true}).click();
  await expect.poll(() => copied(page)).toBe(selected);
  await page.getByRole('button', {name: 'Done', exact: true}).click();
  await expect(page.getByRole('dialog', {name: 'Select message text'})).toHaveCount(0);
});

test('role-specific reactions and unread boundary survive reload and clear durably', async ({page, isMobile}) => {
  const {user, answer} = await prepare(page);
  await openMenu(page, user, isMobile);
  await page.getByRole('menuitemcheckbox', {name: 'React 👍', exact: true}).click();
  await expect(user.locator('..').getByRole('button', {name: 'Remove reaction 👍'})).toBeVisible();
  await openMenu(page, answer, isMobile);
  await page.getByRole('menuitem', {name: 'Mark as unread', exact: true}).click();
  await expect(page.getByText('Conversation marked as unread', {exact: true})).toBeVisible();
  const session = await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'));
  const state = await (await page.request.get(`/v1/sessions/${session}/read-state`)).json();
  expect(state.unread.role).toBe('assistant');
  await page.reload();
  await expect(page.getByRole('button', {name: 'Mark read', exact: true})).toBeVisible();
  await expect(page.locator('.jg-bubble--user').last().locator('..').getByRole('button', {name: 'Remove reaction 👍'})).toBeVisible();
  await page.getByRole('button', {name: 'Mark read', exact: true}).click();
  await expect(page.getByText('Conversation marked as unread', {exact: true})).toHaveCount(0);
  await page.getByRole('button', {name: 'Remove reaction 👍'}).last().click();
  await page.reload();
  await expect(page.getByRole('textbox', {name: 'Message', exact: true})).toBeEnabled();
  expect((await (await page.request.get(`/v1/sessions/${session}/read-state`)).json()).unread).toBeNull();
  const reactions = await (await page.request.get(`/v1/sessions/${session}/feedback`)).json();
  expect(reactions.reactions[`${state.unread.request_id}|user`]).toEqual([]);
});

test('synthetic touch tap, drag and cancellation do not open message actions', async ({page}) => {
  const {user} = await prepare(page);
  for (const action of ['tap', 'drag', 'cancel']) {
    await pointer(user, 'pointerdown');
    if (action === 'drag') await pointer(user, 'pointermove', 70, 80);
    if (action === 'cancel') await pointer(user, 'pointercancel');
    if (action === 'tap') await pointer(user, 'pointerup');
    await page.waitForTimeout(520);
    await expect(page.getByRole('menu', {name: 'Message actions'})).toHaveCount(0);
    await pointer(user, 'pointerup');
  }
  await openMenu(page, user, true);
  await page.getByRole('menuitem', {name: 'Close', exact: true}).click();
  await expect(page.getByRole('menu', {name: 'Message actions'})).toHaveCount(0);
});

test('historical messages without request identity explain unavailable actions', async ({page, isMobile}) => {
  await prepare(page);
  const session = await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'));
  // Script only the historical response shape to represent pre-request-ID data.
  await page.route(url => [ `/v1/sessions/${session}`, `/v1/sessions/${session}/messages` ].includes(url.pathname), async route => {
    const response = await route.fetch();
    const detail = await response.json();
    for (const message of detail.messages ?? []) delete message.request_id;
    await route.fulfill({response, json: detail});
  });
  await page.reload();
  const bubble = page.locator('.jg-bubble--user').last();
  await expect(bubble).toBeVisible();
  await openMenu(page, bubble, isMobile);
  await expect(page.getByRole('menuitem', {name: 'Copy Request ID', exact: true})).toBeDisabled();
  await expect(page.getByRole('menuitem', {name: 'Copy Request ID', exact: true})).toHaveAttribute('title', 'No request ID was recorded for this message');
  await expect(page.getByRole('menuitem', {name: 'Mark as unread', exact: true})).toBeDisabled();
  await expect(page.getByRole('menuitemcheckbox')).toHaveCount(0);
  await expect(page.getByRole('menuitem', {name: 'Copy', exact: true})).toBeEnabled();
  await page.unrouteAll({behavior: 'wait'});
});
