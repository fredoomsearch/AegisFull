#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pwd
import subprocess
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tools import (
    CHROMEDRIVER_AUTOINSTALLER_AVAILABLE,
    SELENIUM_AVAILABLE,
    find_brave_binary,
)
from app.utils.runtime_helpers import print_json as _print


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless browser smoke for the AEGIS UI.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--files-api-key", default="")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--strict", action="store_true", help="Fail instead of skipping when browser runtime is unavailable.")
    return parser.parse_args()


def _skip(reason: str, *, strict: bool) -> int:
    payload = {"ok": not strict, "skipped": True, "reason": reason}
    if strict:
        payload["help"] = (
            "Browser runtime is required for strict mode.\n"
            "- Install a Chromium-compatible browser (chromium/google-chrome/brave)\n"
            "- If your distro uses Snap wrappers (common for chromium-browser), install a non-Snap browser or set AEGIS_BROWSER_BINARY=/path/to/browser\n"
            "- Ensure it can run headless (no sandbox/dev-shm issues)\n"
            "- Ensure Selenium + chromedriver are available\n"
            "Hint (Ubuntu): sudo apt-get install -y chromium-browser || chromium\n"
        )
    _print(payload)
    return 1 if strict else 0


def _safe_home_dir() -> Path:
    """
    Return a writable home-like path for browser smoke temporary profiles.
    """
    env_home = (os.getenv("HOME") or "").strip()
    if env_home:
        p = Path(env_home).expanduser()
        if p.exists():
            return p
    try:
        return Path(pwd.getpwuid(os.getuid()).pw_dir).expanduser()
    except Exception:
        return Path(tempfile.gettempdir())


def _looks_like_browser_runtime_issue(message: str) -> bool:
    """
    Detect common Selenium/Chrome failures that are environment-related (not app-related),
    so non-strict smoke can gracefully skip instead of failing the whole startup gate.
    """
    m = (message or "").lower()
    return any(
        needle in m
        for needle in (
            "devtoolsactiveport file doesn't exist",
            "devtoolsactiveport",
            "session not created",
            "cannot kill chrome",
            "chrome not reachable",
            "failed to start a new chrome session",
            "unable to discover open pages",
            "disconnected: unable to connect to renderer",
            "chrome failed to start",
            "failed to launch chrome",
            "no usable sandbox",
            "zygote could not fork",
            "failed to create chrome process",
            "chrome binary",
            "chrome executable",
            "cannot find chrome binary",
            "cannot start chrome",
            "cannot create temp file",
            "unable to write to temporary directory",
        )
    )


def _looks_like_browser_runtime_exception(exc: Exception) -> bool:
    """
    Best-effort classification for selenium/chrome startup failures.
    We treat these as environment/runtime issues (skip in non-strict mode).
    """
    name = (exc.__class__.__name__ or "").lower()
    if "sessionnotcreated" in name:
        return True
    if "webdriver" in name:
        # Many WebDriverException cases are environment-specific; rely on message heuristics too.
        msg = str(exc)
        return _looks_like_browser_runtime_issue(msg)
    return False


def main() -> int:
    args = parse_args()
    if not SELENIUM_AVAILABLE:
        return _skip("selenium-unavailable", strict=args.strict)
    if not CHROMEDRIVER_AUTOINSTALLER_AVAILABLE:
        return _skip("chromedriver-autoinstaller-unavailable", strict=args.strict)

    browser_binary = find_brave_binary()
    if not browser_binary:
        return _skip("chromium-browser-unavailable", strict=args.strict)
    # Some distros ship chromium-browser as a Snap wrapper. In restricted envs this fails with snap-confine errors,
    # which then surface as DevToolsActivePort / session-not-created in Selenium.
    try:
        probe = subprocess.run(
            [browser_binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if probe.returncode != 0:
            msg = (probe.stderr or probe.stdout or "").strip()[:400]
            return _skip(f"chromium-binary-unusable:{msg or 'exit='+str(probe.returncode)}", strict=args.strict)
    except Exception as exc:  # noqa: BLE001
        return _skip(f"chromium-binary-unusable:{exc}", strict=args.strict)

    try:
        import chromedriver_autoinstaller  # type: ignore
        from selenium import webdriver  # type: ignore
        from selenium.webdriver.chrome.options import Options as ChromeOptions  # type: ignore
        from selenium.webdriver.chrome.service import Service as ChromeService  # type: ignore
        from selenium.webdriver.common.by import By  # type: ignore
        from selenium.webdriver.common.keys import Keys  # type: ignore
        from selenium.webdriver.support import expected_conditions as EC  # type: ignore
        from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return _skip(f"selenium-import-error:{exc}", strict=args.strict)

    try:
        chromedriver_path = chromedriver_autoinstaller.install()
    except Exception as exc:  # noqa: BLE001
        return _skip(f"chromedriver-install-failed:{exc}", strict=args.strict)

    driver = None
    profile_dir = None
    xdg_dir = None
    wait_timeout = max(10, int(args.timeout))
    started = time.monotonic()
    try:
        options = ChromeOptions()
        options.binary_location = browser_binary
        try:
            options.add_argument("--headless=new")
        except Exception:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-features=TranslateUI,VizDisplayCompositor,UseDBus")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--password-store=basic")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        # Pipe is typically more reliable than DevToolsActivePort in constrained Linux hosts.
        options.add_argument("--remote-debugging-pipe")
        options.add_argument("--window-size=1440,1200")

        # Chrome can fail to boot headless in some minimal/locked-down environments unless it can write
        # a profile dir. Use a temporary user-data-dir to reduce flakiness (DevToolsActivePort issues).
        try:
            profile_root = _safe_home_dir() / ".cache" / "aegis_browser_smoke"
            profile_root.mkdir(parents=True, exist_ok=True)
            profile_dir = tempfile.mkdtemp(prefix="profile_", dir=str(profile_root))
            options.add_argument(f"--user-data-dir={profile_dir}")
        except Exception:
            profile_dir = None

        # Some systems (or systemd services) may not have a usable XDG_RUNTIME_DIR, which can break
        # headless Chrome startup. Provide a writable temp runtime dir for the process.
        try:
            if not str(os.getenv("XDG_RUNTIME_DIR") or "").strip():
                runtime_root = _safe_home_dir() / ".cache" / "aegis_browser_smoke"
                runtime_root.mkdir(parents=True, exist_ok=True)
                xdg_dir = tempfile.mkdtemp(prefix="xdg_runtime_", dir=str(runtime_root))
                os.environ["XDG_RUNTIME_DIR"] = xdg_dir
        except Exception:
            xdg_dir = None

        driver = webdriver.Chrome(service=ChromeService(executable_path=chromedriver_path), options=options)
        wait = WebDriverWait(driver, wait_timeout)

        driver.get(args.base_url.rstrip("/") + "/")
        wait.until(EC.presence_of_element_located((By.ID, "msg")))

        api_key = (args.api_key or "").strip()
        files_key = (args.files_api_key or api_key).strip()
        if api_key:
            # Also set a manual root to ensure UI doesn't drift into "manual root" when active project id exists.
            # This validates the "single project identity" UX contract.
            driver.execute_script(
                """
                window.localStorage.setItem("aegis_project_root", arguments[0]);
                """,
                str(ROOT),
            )
            driver.execute_script(
                """
                window.localStorage.setItem("aegis_api_key", arguments[0]);
                window.localStorage.setItem("aegis_files_api_key", arguments[1]);
                """,
                api_key,
                files_key,
            )
            # Selenium Python WebDriver uses refresh() directly.
            driver.refresh()
            wait.until(EC.presence_of_element_located((By.ID, "msg")))

        # Keep the message area unobstructed when optional side panel is open.
        try:
            side_toggle = driver.find_element(By.ID, "chatSideToggle")
            if side_toggle.is_displayed():
                driver.execute_script("arguments[0].click();", side_toggle)
        except Exception:
            pass

        chat = driver.find_element(By.ID, "chat")
        chat_before = chat.text
        msg = driver.find_element(By.ID, "msg")
        msg.clear()
        msg.send_keys("what time is it in new york?")
        # Use keyboard submit first (more robust when UI overlays intercept button clicks).
        msg.send_keys(Keys.ENTER)
        # Fallback chain without Selenium click (avoids click-intercept flakiness on overlays):
        # synthetic Enter event -> JS click on send button.
        try:
            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(chat_before.strip()))
        except Exception:
            driver.execute_script(
                """
                const input = document.getElementById("msg");
                if (input) {
                  input.dispatchEvent(new KeyboardEvent("keydown", {
                    key: "Enter",
                    code: "Enter",
                    keyCode: 13,
                    which: 13,
                    bubbles: true
                  }));
                }
                """,
            )
            try:
                wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(chat_before.strip()))
            except Exception:
                send_btn = driver.find_element(By.ID, "sendBtn")
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center', inline:'center'});",
                    send_btn,
                )
                try:
                    send_btn.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", send_btn)

        wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(chat_before.strip()))
        wait.until(EC.presence_of_element_located((By.ID, "modeIndicator")))
        wait.until(EC.presence_of_element_located((By.ID, "activeProjectBadge")))
        try:
            badge_txt = driver.find_element(By.ID, "activeProjectBadge").text.lower()
            # When there is an active project id, the badge must not show the manual-root fallback text.
            if "manual root" in badge_txt:
                raise RuntimeError("UI drift: active project badge shows manual root fallback")
        except Exception:
            # Let the main try/except handle strict vs non-strict.
            raise

        payload = {
            "ok": True,
            "mode": driver.find_element(By.ID, "modeIndicator").text,
            "chat_chars": len(driver.find_element(By.ID, "chat").text.strip()),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "browser": browser_binary,
        }
        _print(payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        # If Chrome/runtime couldn't start (or flaked due to host constraints), treat as environment issue (best-effort)
        # unless strict. Keep the heuristics broad; these failures are common on CI/minimal servers.
        if not args.strict:
            if driver is None:
                return _skip(f"browser-runtime-unavailable:{msg}", strict=args.strict)
            if _looks_like_browser_runtime_exception(exc) or _looks_like_browser_runtime_issue(msg):
                return _skip(f"browser-runtime-unavailable:{msg}", strict=args.strict)
        _print({"ok": False, "skipped": False, "reason": msg, "browser": browser_binary})
        return 1
    finally:
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
        if profile_dir:
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass
        if xdg_dir:
            try:
                shutil.rmtree(xdg_dir, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
