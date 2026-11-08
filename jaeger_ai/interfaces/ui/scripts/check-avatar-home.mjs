import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium } from "playwright";

const stylesheet = await readFile(new URL("../src/demo/stableDemo.css", import.meta.url), "utf8");
const avatarStyles = await readFile(new URL("../src/avatar/jaegerAvatar.css", import.meta.url), "utf8");
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
try {
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 375, height: 667 }, { width: 844, height: 390 }]) {
    const page = await browser.newPage({ viewport });
    await page.setContent(`<style>${avatarStyles}\n${stylesheet}</style>
      <div class="jg-stable-demo" data-sidebar="false">
        <main class="jg-stable-demo__main">
          <header class="jg-stable-demo__header">
            <div class="jg-stable-demo__header-start"><button class="jg-stable-demo__top-button">New</button></div>
            <div class="jg-stable-demo__profile">
              <span class="jg-stable-demo__profile-avatar"><span class="jg-jaeger-avatar" style="width:94px;height:94px"></span></span>
              <span class="jg-stable-demo__profile-copy"><strong>Jaeger</strong></span>
            </div>
            <div class="jg-stable-demo__tools"><button class="jg-stable-demo__top-button">Menu</button><button class="jg-stable-demo__top-button">Side</button><button class="jg-stable-demo__top-button">Tabs</button></div>
          </header>
          <section class="jg-stable-demo__body"><div class="jg-chat-home">Jenkins Robotics</div></section>
        </main>
      </div>`);
    const avatar = page.locator(".jg-jaeger-avatar");
    const home = page.locator(".jg-chat-home");
    const expanded = await avatar.boundingBox();
    const controlBoxes = () => page.locator('.jg-stable-demo__top-button').evaluateAll(buttons => buttons.map(button => {
      const { x, y, width, height } = button.getBoundingClientRect();
      return { x, y, width, height };
    }));
    const controls = await controlBoxes();
    const logo = await home.boundingBox();
    assert.ok(expanded.y + expanded.height <= logo.y, "Avatar stays above logo");
    assert.ok(expanded.x >= 0 && expanded.x + expanded.width <= viewport.width, "Avatar fits viewport");
    if (viewport.height > 520) assert.ok(expanded.width > 94, "Empty chat expands avatar");
    await page.evaluate(() => {
      window.originalAvatar = document.querySelector(".jg-jaeger-avatar");
      document.querySelector(".jg-chat-home").remove();
    });
    await page.waitForTimeout(180);
    assert.deepEqual(await controlBoxes(), controls, "Controls stay fixed during retreat");
    await page.waitForTimeout(370);
    assert.deepEqual(await controlBoxes(), controls, "Controls stay fixed after send");
    assert.equal(Math.round((await avatar.boundingBox()).width), 94, "First message docks avatar");
    assert.ok(await page.evaluate(() => window.originalAvatar === document.querySelector(".jg-jaeger-avatar")), "Same avatar survives transition");
    await page.evaluate(() => {
      document.querySelector(".jg-stable-demo__body").innerHTML = '<div class="jg-chat-home">Jenkins Robotics</div>';
    });
    await page.waitForTimeout(550);
    assert.equal(Math.round((await avatar.boundingBox()).width), Math.round(expanded.width), "New chat expands again");
    assert.deepEqual(await controlBoxes(), controls, "Controls stay fixed in a new chat");
    await page.locator(".jg-stable-demo__body").evaluate(element => { element.hidden = true; });
    await page.waitForTimeout(550);
    assert.equal(Math.round((await avatar.boundingBox()).width), 94, "Hidden chat does not expand workspace header");
    await page.emulateMedia({ reducedMotion: "reduce" });
    assert.equal(await page.locator(".jg-stable-demo__profile-avatar").evaluate(element => getComputedStyle(element).transitionDuration), "0s");
    await page.close();
  }
  console.log("Avatar home layout checks passed across desktop, mobile, and landscape.");
} finally {
  await browser.close();
}
