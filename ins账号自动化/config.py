"""Configuration — loads .env and exports constants."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

PACKAGE_DIR = Path(__file__).resolve().parent

# Load .env from: project data/, project root, or package data/
for p in [BASE_DIR / "data" / ".env", BASE_DIR / ".env", PACKAGE_DIR / "data" / ".env"]:
    if p.exists():
        load_dotenv(p)
        break

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "your-openrouter-api-key-here")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
IG_USERNAME = os.getenv("IG_USERNAME", "your-instagram-username")
IG_PASSWORD = os.getenv("IG_PASSWORD", "your-instagram-password")


def _system_proxy() -> str:
    """Windows system (WinINet) proxy as a Playwright server URL, or ''.

    Playwright's Chromium does not reliably follow the Windows system
    proxy, so we read it ourselves and pass it explicitly to the browser.
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        ) as key:
            try:
                enabled = winreg.QueryValueEx(key, "ProxyEnable")[0]
            except FileNotFoundError:
                enabled = 0
            if not enabled:
                return ""
            try:
                server = str(winreg.QueryValueEx(key, "ProxyServer")[0]).strip()
            except FileNotFoundError:
                return ""
    except Exception:
        return ""

    if not server:
        return ""
    if "=" in server:
        # e.g. "http=127.0.0.1:7890;https=127.0.0.1:7890" or "socks=127.0.0.1:1080"
        parts = {}
        for item in server.split(";"):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        if parts.get("https") or parts.get("http"):
            server = parts.get("https") or parts.get("http")
            scheme = "http"
        elif parts.get("socks"):
            server = parts["socks"]
            scheme = "socks5"
        else:
            return ""
    else:
        scheme = "http"

    if "://" in server:
        return server
    return f"{scheme}://{server}"


# Browser proxy for Instagram: .env override wins, else the Windows
# system proxy (so a running Clash/V2Ray in System Proxy mode just works).
IG_PROXY = os.getenv("IG_PROXY", "").strip() or _system_proxy()
