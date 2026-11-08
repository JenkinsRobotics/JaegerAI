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
  if (['Work','Research','Machine','Tasks'].includes(name) && !await page.locator('.jg-stable-demo__more').evaluate(el => (el as HTMLDetailsElement).open)) await page.getByLabel('More tools', {exact:true}).click();
  await page.getByRole('navigation', {name:'Jaeger navigation'}).getByRole('button', {name, exact:true}).click();
  if ((page.viewportSize()?.width ?? 1280) <= 820) await expect(page.locator('#jaeger-navigation')).toBeHidden();
}

test('default screen exposes the current workspace navigation and chat controls', async ({ page }) => {
  await openChat(page);
  if (!await page.locator('#jaeger-navigation').isVisible()) await page.getByRole('button', {name:'Toggle navigation'}).click();
  await page.getByLabel('More tools', {exact:true}).click();
  await expect(page.getByRole('navigation', { name: 'Jaeger navigation' }).getByRole('button')).toHaveText(['Chat', 'Imagine', 'Library', 'Automations', 'Feed', 'Agents', 'Work', 'Research', 'Machine', 'Tasks']);
  await expect(page.locator('header[aria-label="Conversation toolbar"]')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Close sidebar', exact: true })).toBeVisible();
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
  const answerCount = await page.locator('.jg-bubble--assistant').count();
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.reload();
    await expect(page.locator('.jg-bubble--assistant').last()).toContainText('BROWSER-CONTRACT-ANSWER');
    await expect(page.locator('.jg-bubble--assistant')).toHaveCount(answerCount);
    expect(await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(session);
  }
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
  await page.goto('/');
  await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(durable);
});

for (const width of [301, 320, 390, 502, 1280]) {
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
      if (width <= 520) {
        const composer = await page.locator('.jg-composer').boundingBox();
        expect(composer, '.jg-composer must be visible').not.toBeNull();
        expect(900 - composer!.y - composer!.height, '.jg-composer must use the bottom edge when the mobile dock is absent').toBeLessThanOrEqual(32);
      }
      if (width === 502) {
        const form = page.locator('.jg-composer');
        await form.evaluate((node) => {
          const input = node.querySelector('textarea');
          for (let index = 0; index < 3; index += 1) {
            const notice = document.createElement('div');
            notice.dataset.layoutProbe = '';
            notice.setAttribute('role', 'status');
            notice.textContent = 'A long Gateway recovery notice must wrap inside the composer without creating another flex column.';
            node.insertBefore(notice, input);
          }
        });
        const formBox = await form.boundingBox();
        expect(formBox).not.toBeNull();
        for (const probe of await form.locator(':scope > [data-layout-probe]').all()) {
          const box = await probe.boundingBox();
          expect(box).not.toBeNull();
          expect(box!.x).toBeGreaterThanOrEqual(formBox!.x);
          expect(box!.x + box!.width).toBeLessThanOrEqual(formBox!.x + formBox!.width + 1);
        }
        await form.locator(':scope > [data-layout-probe]').evaluateAll(nodes => nodes.forEach(node => node.remove()));
      }
      if (width <= 320) {
        await page.getByRole('textbox', {name:'Message', exact:true}).focus();
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

for (const width of [390, 794, 1280, 1600]) {
  test(`conversation details do not obscure chat at ${width}px`, async ({ page }) => {
    await page.setViewportSize({width,height:975});
    await openChat(page);
    const chat = page.locator('.jg-stable-demo__main');
    const profile = await page.locator('.jg-stable-demo__profile').boundingBox();
    const body = await page.locator('section[aria-label="Chat"]:not([hidden])').boundingBox();
    expect(profile!.y + profile!.height).toBeLessThanOrEqual(body!.y + 1);
    await page.getByRole('button',{name:'Toggle pinned summary',exact:true}).click();
    const summary = page.getByRole('dialog',{name:'Pinned workspace summary'});
    await expect(summary).toBeVisible();
    if(width > 1100) {
      const left = await chat.boundingBox();
      const right = await summary.boundingBox();
      expect(left!.x + left!.width).toBeLessThanOrEqual(right!.x + 1);
      await expect(page.getByRole('textbox',{name:'Message',exact:true})).toBeVisible();
    } else {
      await expect(chat).toBeHidden();
    }
    await page.getByRole('button',{name:'Close summary',exact:true}).click();
    await expect(chat).toBeVisible();
    await expect(page.getByRole('textbox',{name:'Message',exact:true})).toBeEnabled();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('approval selections persist through the real isolated Gateway and refresh',async({page},testInfo)=>{
 test.setTimeout(90000);
 await openChat(page);
 const initial=await (await page.request.get('/v1/runtime/autonomy')).json();
 const expandComposer=async()=>{
  const field=page.getByRole('textbox',{name:'Message',exact:true});
  if(testInfo.project.use.isMobile) await field.tap(); else await field.focus();
  await expect(page.getByRole('button',{name:/^Approval mode:/})).toBeVisible();
 };
 try {
  for(const [mode,label] of [['scoped','Approve for me'],['auto','Full access'],['ask','Ask for approval']]) {
   // The phone composer intentionally collapses secondary controls until it is
   // focused. Expand it before operating or asserting on the approval control.
   await expandComposer();
   const approval=page.getByRole('button',{name:/^Approval mode:/});
   if(testInfo.project.use.isMobile) await approval.tap(); else await approval.click();
   const option=page.getByRole('menuitemradio',{name:new RegExp(label)});
   await expect(option).toBeEnabled();await option.click();
   await expect(page.getByRole('button',{name:`Approval mode: ${label}`})).toBeVisible();
   expect((await (await page.request.get('/v1/runtime/autonomy')).json()).autonomy).toBe(mode);
   await page.reload();
   await expandComposer();
   await expect(page.getByRole('button',{name:`Approval mode: ${label}`})).toBeVisible();
  }
 } finally {await page.request.post('/v1/runtime/autonomy',{data:{autonomy:initial.autonomy}});}
});
test('minimap jumps to loaded turns without sending a message',async({page},testInfo)=>{
 test.setTimeout(90000);
 await openChat(page);
 const field=page.getByRole('textbox',{name:'Message',exact:true});
 for(let i=0;i<2;i++){
  const marker=`BROWSER-CONTRACT-ANSWER ${testInfo.project.name} retry-${testInfo.retry} turn-${i}`;
  await field.fill(`Say ${marker}`);
  await expect(page.getByRole('button',{name:'Send',exact:true})).toBeEnabled();
  await field.press('Enter');
  await expect(field).toHaveValue('');
  // History pagination can add older bubbles while the turn runs. Observe the
  // unique durable answer instead of racing the total rendered bubble count.
  await expect(page.locator('.jg-bubble--assistant').filter({hasText:marker}).last()).toBeVisible({timeout:30000});
  await expect(page.getByRole('button',{name:/^Stop current turn/})).toHaveCount(0,{timeout:30000});
 }
 const minimap=page.getByRole('navigation',{name:'Conversation minimap'});
 if((page.viewportSize()?.width??0)<=600){
  // The compact layout deliberately removes this desktop-only rail and its
  // chat margin. The turns remain loaded and the page must stay in bounds.
  await expect(page.locator('.jg-conversation-minimap')).toBeHidden();
  expect(await page.locator('.jg-conversation-minimap button').count()).toBeGreaterThanOrEqual(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  return;
 }
 await expect(minimap).toBeVisible();
 const count=await minimap.getByRole('button').count();expect(count).toBeGreaterThanOrEqual(2);
 await minimap.getByRole('button').first().click();
 await expect(minimap.getByRole('button').first()).toHaveAttribute('aria-current','location');
 await expect(minimap.getByRole('button')).toHaveCount(count);
});

// Simulated iOS safe areas and visual viewport: desktop emulation alone cannot
// expose the notch, Home indicator, or Safari's non-resizing layout viewport.
for (const scenario of [
 {name:'Safari',width:393,height:694,standalone:false,top:0,bottom:0},
 {name:'Home Screen',width:393,height:852,standalone:true,top:59,bottom:34},
 {name:'small iPhone',width:320,height:568,standalone:true,top:20,bottom:0},
 {name:'landscape iPhone',width:852,height:393,standalone:true,top:0,bottom:21},
]) {
 test(`iPhone ${scenario.name} keeps chat, safe areas and keyboard inside the screen`,async({page})=>{
  await page.setViewportSize({width:scenario.width,height:scenario.height});
  await page.addInitScript(({standalone,height})=>{
   Object.defineProperty(navigator,'standalone',{configurable:true,value:standalone});
   const viewport=Object.assign(new EventTarget(),{height,offsetTop:0,scale:1});
   Object.defineProperty(window,'visualViewport',{configurable:true,value:viewport});
  },scenario);
  await openChat(page);
  const shell=page.locator('.jg-stable-demo');
  await shell.evaluate((node,{top,bottom})=>{
   (node as HTMLElement).style.setProperty('--jg-safe-top',`${top}px`);
   (node as HTMLElement).style.setProperty('--jg-safe-bottom',`${bottom}px`);
  },scenario);
  await expect(page.locator('html')).toHaveAttribute('data-jaeger-display-mode',scenario.standalone?'standalone':'browser');
  const header=await page.locator('.jg-stable-demo__header').boundingBox();
  expect(header!.height,'phone chrome must not inherit the desktop hero').toBeLessThanOrEqual(72);
  expect(header!.y).toBeGreaterThanOrEqual(scenario.top);
  const input=page.getByRole('textbox',{name:'Message',exact:true});
  const check=async(height:number,bottom:number)=>{
   expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(scenario.width);
   const composer=await page.locator('.jg-composer').boundingBox();
   expect(composer!.y+composer!.height).toBeLessThanOrEqual(height-bottom);
   expect(height-bottom-composer!.y-composer!.height,'safe area is reserved once, not twice').toBeLessThanOrEqual(12);
   expect(await input.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
   const transcript=await page.locator('.jg-chat__scroll').boundingBox();
   expect(transcript!.height).toBeGreaterThan(height < 300 ? 40 : 80);
  };
  await check(scenario.height,scenario.bottom);
  await input.fill('An unsent draft');
  // Two open/close cycles catch stale dimensions and a composer stuck offscreen.
  for(let cycle=0;cycle<2;cycle++) {
   await input.focus();
   const visibleHeight=Math.min(360,scenario.height-140);
   await page.evaluate(height=>{Object.assign(visualViewport!,{height,offsetTop:0});visualViewport!.dispatchEvent(new Event('resize'));},visibleHeight);
   await expect(shell).toHaveAttribute('data-keyboard','true');
   await check(visibleHeight,0);
   await page.evaluate(height=>{Object.assign(visualViewport!,{height,offsetTop:0});visualViewport!.dispatchEvent(new Event('resize'));},scenario.height);
   await expect(shell).toHaveAttribute('data-keyboard','false');
   await check(scenario.height,scenario.bottom);
  }
  await expect(input).toHaveValue('An unsent draft');
  await input.fill(''); await input.blur();
  await page.getByRole('button',{name:'Toggle navigation'}).click();
  await expect(page.getByRole('button',{name:'Close sidebar'})).toBeVisible();
  await page.getByRole('button',{name:'Close sidebar'}).click();
  await expect(input).toBeVisible();
 });
}

test('conversation deep links override device selection and survive reload', async ({page}) => {
  await openChat(page);
  const linked = await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'));
  expect(linked).toBeTruthy();
  await page.evaluate(() => localStorage.setItem('jaeger.stable-demo.session.v1', 'different-device-selection'));
  await page.goto(`/?session=${encodeURIComponent(linked!)}`);
  await expect(page.getByRole('textbox', {name:'Message',exact:true})).toBeEnabled();
  expect(await page.evaluate(() => localStorage.getItem('jaeger.stable-demo.session.v1'))).toBe(linked);
  await page.reload();
  await expect(page.getByRole('textbox', {name:'Message',exact:true})).toBeEnabled();
  expect(new URL(page.url()).searchParams.get('session')).toBe(linked);
});

test('existing settings deep links render real appearance controls', async ({page}) => {
  await openChat(page);
  await page.goto('/settings/appearance');
  await expect(page.locator('.jg-sheet__page')).toBeVisible();
  await expect(page.locator('.jg-sheet__page')).toContainText('Appearance');
  await expect(page.getByRole('radio', {name:'Light',exact:true})).toBeVisible();
});
