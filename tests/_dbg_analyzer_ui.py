"""Playwright 验证页面9：引擎切换、队列、零JS错误。"""
import subprocess, time, os, sys
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {**os.environ, "PYTHONPATH": os.path.join(ROOT,"src"), "PYTHONIOENCODING":"utf-8"}
p = subprocess.Popen([sys.executable,"-m","uvicorn","paperflow.web.app:app","--host","127.0.0.1","--port","8251"],
                     cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
time.sleep(4)
try:
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True); pg=b.new_page(viewport={"width":1440,"height":1000})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:8251/",wait_until="networkidle",timeout=20000)
        pg.get_by_role("button",name="AI 解析中心").click(); pg.wait_for_timeout(600)
        print("ENGINE_TABS",pg.locator(".engine-tab").count())
        print("CLAUDI_KPIS",pg.locator(".analyzer-kpi").count())
        print("QUEUE_TABLE",pg.locator(".analyzer-queue-tbl").count())
        pg.get_by_role("button",name="🌐 DeepSeek Harness Web (WorkBuddy 协作)").click(); pg.wait_for_timeout(300)
        print("HARNESS_LINKS",pg.locator(".engine-body a.btn").count())
        print("ERRORS",errs[:5])
        b.close()
finally:
    p.terminate()
    try:p.wait(timeout=5)
    except:pass
