# Browser automation bridge

Use the local Python CDP bridge to read webpages with the installed Edge or Chrome browser.

Read a page:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\tools\browser-automation\browser_bridge.py --url https://example.com
```

Read a page with a persisted session profile:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\tools\browser-automation\browser_bridge.py --url https://onlineweb.zhihuishu.com/onlinestuh5 --profile zhihuishu --headed
```

Open a login session and persist cookies/storage:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\tools\browser-automation\browser_bridge.py --url https://onlineweb.zhihuishu.com/onlinestuh5 --profile zhihuishu --login-session --headed
```

Optional screenshot:

```powershell
D:\codex\tools\python311-embed\python.exe D:\codex\tools\browser-automation\browser_bridge.py --url https://example.com --screenshot D:\codex\output\browser\example.png
```

Notes:
- This bridge reuses local Edge/Chrome instead of downloading Playwright browsers.
- Login-gated pages can be handled through a persistent profile created by `browser_bridge.py --login-session`.
- Browser launch may require running outside the sandbox.
