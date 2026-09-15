from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
 page=browser.new_page()
 page.set_content('''<head></head><body><div id="appTitlebarTitle">Jaeger</div><div id="panelChat"><div id="sessionList"></div></div><div class="assistant-turn" data-jaeger-display-name="Test Agent" data-jaeger-agent-id="test"><div class="msg-role assistant"><span class="msg-role-name">Assistant</span><span class="role-icon assistant"></span></div></div><textarea id="msg"></textarea></body>''')
 page.evaluate("window.fetch=async()=>({ok:true,json:async()=>({agents:[]})});window.mutations=0;new MutationObserver(records=>window.mutations+=records.length).observe(document.documentElement,{subtree:true,childList:true,attributes:true})")
 page.add_script_tag(path=str(Path('jaeger_ai/assets/jaeger_webui_branding.js').resolve()))
 page.wait_for_timeout(200)
 before=page.evaluate('window.mutations')
 page.wait_for_timeout(200)
 after=page.evaluate('window.mutations')
 assert before==after,(before,after)
 assert page.locator('.msg-role-name').inner_text()=='Test Agent'
 page.locator('#msg').fill('composer remains responsive')
 assert page.locator('#msg').input_value()=='composer remains responsive'
 page.evaluate("document.querySelector('.assistant-turn').dataset.jaegerDisplayName='Updated Agent'")
 page.wait_for_timeout(200)
 assert page.locator('.msg-role-name').inner_text()=='Updated Agent'
 settled=page.evaluate('window.mutations')
 page.wait_for_timeout(200)
 assert page.evaluate('window.mutations')==settled
 print('PASS: real MutationObserver converges; composer responsive; mutations',after,flush=True)
 browser.close()
