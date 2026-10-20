"""给 Casdoor 登录页换上「三年级六班集团」品牌：左侧品牌区 + 右侧登录表单，跟随浏览器的亮 / 暗色。

可重复运行：只改 hub-console 与 hub-agent 两个应用的外观字段（登录页由应用决定），不动授权配置。
    uv run python scripts/casdoor_brand.py --env-file ../../hub/.env
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

APPS = {"hub-console": "智能体中枢控制台", "hub-agent": "员工端 agent"}

BADGE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="5" y="5" width="24" height="24" rx="6" fill="#f7d054"/>'
         '<g transform="rotate(-6 16 16)"><rect x="3" y="3" width="24" height="24" rx="6" fill="#e0533c"/>'
         '<text x="15" y="20.5" text-anchor="middle" font-family="Arial, sans-serif" font-size="12" font-weight="800" fill="#fff">3·6</text></g></svg>')

SIDE_HTML = f"""<div class="brand-side">
  <div class="brand-top">
    <span class="brand-badge">{BADGE}</span>
    <span class="brand-name">三年级六班集团</span>
  </div>
  <div class="brand-main">
    <h1>企业智能体中枢</h1>
    <p>员工的 agent、公司知识库、技能和 GPU 算力，在这里统一接入、统一授权、统一留痕。</p>
    <ul>
      <li><b>一次登录</b><span>控制台与员工端 agent 共用同一个账号</span></li>
      <li><b>按岗位授权</b><span>能查什么资料、能用什么工具，由岗位包决定</span></li>
      <li><b>全程可追溯</b><span>每一次调用都有同一个追踪 ID</span></li>
    </ul>
  </div>
  <div class="brand-foot">© 三年级六班集团</div>
</div>"""

CSS = """
:root{--b-bg:#fbf9f3;--b-surface:#fffdf8;--b-line:#e7e1d3;--b-ink:#23211c;--b-ink2:#4f4b42;--b-ink3:#8b8578;--b-accent:#e0533c;--b-accent-ink:#b83a25;--b-side:#f7f4ec}
@media (prefers-color-scheme: dark){:root{--b-bg:#1a1814;--b-surface:#221f1a;--b-line:#3a352c;--b-ink:#f1ece0;--b-ink2:#cfc8b8;--b-ink3:#8f887a;--b-accent:#ee6a52;--b-accent-ink:#f2a090;--b-side:#25221c}}
html,body,#root,.loginBackground{background:var(--b-bg)!important;font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.loginBackground{background-image:none!important}
.login-content{background:var(--b-surface)!important;border:1px solid var(--b-line);border-radius:14px!important;box-shadow:0 12px 40px rgba(35,33,28,.08)!important;color:var(--b-ink)}
.login-content *{color:inherit}
.ant-input,.ant-input-affix-wrapper{background:var(--b-bg)!important;border-color:var(--b-line)!important;color:var(--b-ink)!important;border-radius:8px!important}
.ant-input-affix-wrapper:focus-within,.ant-input:focus{border-color:var(--b-accent)!important;box-shadow:0 0 0 2px rgba(224,83,60,.15)!important}
.ant-btn-primary{background:var(--b-accent)!important;border-color:var(--b-accent)!important;border-radius:8px!important;color:#fff!important;box-shadow:none!important}
.ant-btn-primary:hover{background:var(--b-accent-ink)!important;border-color:var(--b-accent-ink)!important}
a{color:var(--b-accent-ink)!important}
.login-logo-box img{display:none!important}
.login-logo-box a::before{content:"三年级六班集团";display:block;font-size:22px;font-weight:800;letter-spacing:.04em;color:var(--b-accent)!important;text-align:center}
.login-button,button.bg-primary{background:var(--b-accent)!important;color:#fff!important;border-radius:8px!important;box-shadow:none!important}
.login-button:hover{background:var(--b-accent-ink)!important}
.brand-side{height:100%;min-height:100vh;box-sizing:border-box;padding:48px 56px;display:flex;flex-direction:column;justify-content:space-between;background:var(--b-side);border-right:1px solid var(--b-line);color:var(--b-ink)}
.brand-top{display:flex;align-items:center;gap:12px}
.brand-badge svg{width:40px;height:40px;display:block}
.brand-name{font-size:20px;font-weight:700;letter-spacing:.02em}
.brand-main h1{font-size:34px;line-height:1.25;margin:0 0 14px;font-weight:800;color:var(--b-ink)}
.brand-main h1::after{content:"";display:block;width:56px;height:6px;margin-top:16px;border-radius:3px;background:#f7d054}
.brand-main p{font-size:15px;line-height:1.8;color:var(--b-ink2);max-width:440px;margin:0 0 28px}
.brand-main ul{list-style:none;margin:0;padding:0;display:grid;gap:14px;max-width:440px}
.brand-main li{display:grid;gap:2px;padding-left:14px;border-left:3px solid var(--b-accent)}
.brand-main li b{font-size:14px;color:var(--b-ink)}
.brand-main li span{font-size:13px;color:var(--b-ink3)}
.brand-foot{font-size:12px;color:var(--b-ink3)}
"""

CSS_MOBILE = ".brand-side{display:none}"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，打印 ✓ 会报错
    ap = argparse.ArgumentParser(description="给 Casdoor 登录页换上三年级六班集团品牌")
    ap.add_argument("--env-file", default="../../hub/.env")
    ap.add_argument("--casdoor-url", default="")
    args = ap.parse_args()
    env = dotenv_values(Path(args.env_file))
    base = args.casdoor_url or env.get("CASDOOR_ORIGIN") or sys.exit("缺少 CASDOOR_ORIGIN")
    c = httpx.Client(base_url=base, timeout=15)
    r = c.post("/api/login", json={"application": "app-built-in", "organization": "built-in", "username": "admin",
                                    "password": env["CASDOOR_ADMIN_PASSWORD"], "type": "login", "signinMethod": "Password"})
    if r.json().get("status") != "ok":
        sys.exit(f"登录 Casdoor 失败：{r.text[:200]}")
    # Casdoor 的 logo / favicon 字段最长 200 字符，放不下内嵌图片：用 Casdoor 自己托管的徽标（hub/casdoor-static，见 docker-compose.yml）
    logo, favicon = f"{base.rstrip('/')}/static-cdn/logo.svg", f"{base.rstrip('/')}/static-cdn/favicon.svg"
    for name, display in APPS.items():
        app = c.get("/api/get-application", params={"id": f"admin/{name}"}).json().get("data")
        if not app:
            print(f"· 应用 {name} 不存在，跳过")
            continue
        app.update({"displayName": display, "title": "三年级六班集团", "logo": logo, "favicon": favicon,
                    "formOffset": 4, "formSideHtml": SIDE_HTML, "formCss": CSS, "formCssMobile": CSS_MOBILE})
        res = c.post("/api/update-application", params={"id": f"admin/{name}"}, json=app).json()
        print(("✓ " if res.get("status") == "ok" else "✗ ") + f"登录页品牌：{name} {res.get('msg', '')}")
    # 其余应用与组织只换徽标，去掉默认指向 cdn.casbin.org 的地址
    for name in ("app-built-in", "hub-external"):
        app = c.get("/api/get-application", params={"id": f"admin/{name}"}).json().get("data")
        if app:
            app.update({"logo": logo, "favicon": favicon})
            c.post("/api/update-application", params={"id": f"admin/{name}"}, json=app)
    for org_name in ("built-in", env.get("HUB_ORG") or ""):
        org = org_name and c.get("/api/get-organization", params={"id": f"admin/{org_name}"}).json().get("data")
        if org:
            org.update({"logo": logo, "favicon": favicon})
            res = c.post("/api/update-organization", params={"id": f"admin/{org_name}"}, json=org).json()
            print(("✓ " if res.get("status") == "ok" else "✗ ") + f"组织徽标：{org_name} {res.get('msg', '')}")


if __name__ == "__main__":
    main()
