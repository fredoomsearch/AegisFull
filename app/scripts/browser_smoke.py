#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import os
import pwd
import subprocess
import shutil
import sys
import tempfile
import time
import zipfile
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


def _chat_mode_contract_ready(
    *,
    body_mode: str,
    mode_indicator: str,
    chat_pressed: str,
    crypto_pressed: str,
    send_label: str,
) -> bool:
    mode_value = str(body_mode or "").strip().lower()
    indicator_value = str(mode_indicator or "").strip().lower()
    chat_on = str(chat_pressed or "").strip().lower() == "true"
    crypto_on = str(crypto_pressed or "").strip().lower() == "true"
    send_value = str(send_label or "").strip().lower()
    return (
        mode_value == "chat"
        and "chat" in indicator_value
        and chat_on
        and not crypto_on
        and "predict" not in send_value
        and "predecir" not in send_value
    )


def _web_mode_contract_ready(*, body_mode: str, mode_indicator: str, web_pressed: str) -> bool:
    mode_value = str(body_mode or "").strip().lower()
    indicator_value = str(mode_indicator or "").strip().lower()
    web_on = str(web_pressed or "").strip().lower() == "true"
    return mode_value == "web" and "web" in indicator_value and web_on


def _chat_only_web_contract_ready(*, body_mode: str, mode_indicator: str, chat_pressed: str) -> bool:
    mode_value = str(body_mode or "").strip().lower()
    indicator_value = str(mode_indicator or "").strip().lower()
    chat_on = str(chat_pressed or "").strip().lower() == "true"
    return (
        mode_value == "chat"
        and "chat" in indicator_value
        and chat_on
        and any(sub in indicator_value for sub in ("auto web/local", "local only", "solo local"))
    )


def _new_chat_segment(before: str, after: str) -> str:
    before_text = str(before or "")
    after_text = str(after or "")
    if before_text and after_text.startswith(before_text):
        return after_text[len(before_text) :].strip()
    return after_text.strip()


def _strict_web_proof_ready(*, web_badge: str, source_cards: int) -> bool:
    badge_value = str(web_badge or "").strip().lower()
    cards = max(0, int(source_cards or 0))
    if cards <= 0:
        return False
    if "cache" in badge_value or "cach" in badge_value:
        return False
    if "cooldown" in badge_value:
        return False
    if "unavailable" in badge_value or "no disp" in badge_value:
        return False
    return "live" in badge_value or "vivo" in badge_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless browser smoke for the AEGIS UI.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--files-api-key", default="")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--strict", action="store_true", help="Fail instead of skipping when browser runtime is unavailable.")
    parser.add_argument(
        "--cleanup-orphans",
        action="store_true",
        help="Print and kill Chrome/Chromium processes started by this smoke run's temp profile.",
    )
    parser.add_argument(
        "--crypto-proof",
        action="store_true",
        help="Exercise the crypto panel after the base smoke and verify visible crypto resources.",
    )
    parser.add_argument(
        "--geo-proof",
        action="store_true",
        help="Send a geography question after the base smoke and verify the fast local answer on the page.",
    )
    parser.add_argument(
        "--memory-speed-proof",
        action="store_true",
        help="Send a capital question after the base smoke and verify the fast local concise answer on the page.",
    )
    parser.add_argument(
        "--web-proof",
        action="store_true",
        help="Switch the UI to Web mode, run a live search, and verify the sources panel updates.",
    )
    parser.add_argument(
        "--project-proof",
        action="store_true",
        help="Verify the project/files panel loads the active project tree and summary cards.",
    )
    parser.add_argument(
        "--files-proof",
        action="store_true",
        help="Upload a tiny ZIP from the files panel and verify upload + ingest coverage.",
    )
    parser.add_argument(
        "--image-proof",
        action="store_true",
        help="Switch to image mode, upload a reference image, and verify the image attach path.",
    )
    parser.add_argument(
        "--url-proof",
        action="store_true",
        help="Switch to URL mode and verify a local live URL search/read turn.",
    )
    parser.add_argument(
        "--extended-ui-proofs",
        action="store_true",
        help="Bundle the heavier project/files/image/url browser checks for a separate optional pass.",
    )
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


def _cleanup_orphan_browsers(profile_dir: str | None) -> list[dict[str, object]]:
    """
    Best-effort cleanup for Chromium sessions launched with our temp profile.
    We only target processes whose command line mentions the profile path.
    """
    if not profile_dir:
        return []

    cleaned: list[dict[str, object]] = []
    try:
        proc = subprocess.run(
            ["pgrep", "-af", profile_dir],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return cleaned

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    pids: list[int] = []
    for line in lines:
        try:
            pid = int(line.split(None, 1)[0])
        except Exception:
            continue
        pids.append(pid)

    if not pids:
        return cleaned

    unique_pids = sorted(set(pids))
    for pid in unique_pids:
        cleaned.append({"pid": pid, "signal": "TERM", "profile": profile_dir})
        try:
            subprocess.run(["kill", "-TERM", str(pid)], capture_output=True, text=True, check=False, timeout=5)
        except Exception:
            pass

    time.sleep(0.4)

    survivors: list[int] = []
    for pid in unique_pids:
        try:
            probe = subprocess.run(["kill", "-0", str(pid)], capture_output=True, text=True, check=False, timeout=5)
            if probe.returncode == 0:
                survivors.append(pid)
        except Exception:
            continue

    for pid in survivors:
        cleaned.append({"pid": pid, "signal": "KILL", "profile": profile_dir})
        try:
            subprocess.run(["kill", "-KILL", str(pid)], capture_output=True, text=True, check=False, timeout=5)
        except Exception:
            pass

    return cleaned


_SINGLE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO8L1z8AAAAASUVORK5CYII="
)


def _prepare_browser_proof_assets(root: Path) -> dict[str, Path]:
    proof_dir = Path(tempfile.mkdtemp(prefix="proof_", dir=str(root)))
    image_path = proof_dir / "proof.png"
    image_path.write_bytes(_SINGLE_PIXEL_PNG)

    zip_path = proof_dir / "proof_project.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", "AEGIS browser smoke proof project.\n")
        zf.writestr("src/app.py", "print('aegis browser smoke proof')\n")

    return {"dir": proof_dir, "image": image_path, "zip": zip_path}


def main() -> int:
    args = parse_args()
    if args.extended_ui_proofs:
        args.project_proof = True
        args.files_proof = True
        args.image_proof = True
        args.url_proof = True
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
    proof_assets: dict[str, Path] = {}
    wait_timeout = max(10, int(args.timeout))
    started = time.monotonic()
    cleanup_report: list[dict[str, object]] = []
    current_stage = "startup"
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

        try:
            if profile_dir and (args.files_proof or args.image_proof):
                proof_assets = _prepare_browser_proof_assets(Path(profile_dir))
        except Exception:
            proof_assets = {}

        driver = webdriver.Chrome(service=ChromeService(executable_path=chromedriver_path), options=options)
        wait = WebDriverWait(driver, wait_timeout)

        def _wait_for_idle_chat() -> None:
            wait.until(
                lambda d: (
                    not bool(d.execute_script("return document.getElementById('typing-bubble');"))
                    and str(d.find_element(By.ID, "sendBtn").get_attribute("disabled") or "").strip().lower() not in {"true", "disabled"}
                )
            )

        def _read_chat_mode_contract() -> dict[str, str]:
            return {
                "body_mode": str(driver.execute_script("return document.body?.dataset?.mode || '';") or ""),
                "mode_indicator": driver.find_element(By.ID, "modeIndicator").text,
                "chat_pressed": str(driver.find_element(By.ID, "chatBtn").get_attribute("aria-pressed") or ""),
                "crypto_pressed": str(driver.find_element(By.ID, "cryptoBtn").get_attribute("aria-pressed") or ""),
                "send_label": driver.find_element(By.ID, "sendBtn").text,
            }

        def _read_web_mode_contract() -> dict[str, str]:
            return {
                "body_mode": str(driver.execute_script("return document.body?.dataset?.mode || '';") or ""),
                "mode_indicator": driver.find_element(By.ID, "modeIndicator").text,
                "web_pressed": str(driver.find_element(By.ID, "webBtn").get_attribute("aria-pressed") or ""),
            }

        def _read_chat_only_web_contract() -> dict[str, str]:
            return {
                "body_mode": str(driver.execute_script("return document.body?.dataset?.mode || '';") or ""),
                "mode_indicator": driver.find_element(By.ID, "modeIndicator").text,
                "chat_pressed": str(driver.find_element(By.ID, "chatBtn").get_attribute("aria-pressed") or ""),
            }

        def _ensure_chat_mode() -> None:
            _wait_for_idle_chat()
            if _chat_mode_contract_ready(**_read_chat_mode_contract()):
                return
            chat_btn = driver.find_element(By.ID, "chatBtn")
            driver.execute_script("arguments[0].click();", chat_btn)
            wait.until(
                lambda _d: _chat_mode_contract_ready(**_read_chat_mode_contract())
            )

        def _ensure_web_mode() -> None:
            _wait_for_idle_chat()
            if _chat_only_web_contract_ready(**_read_chat_only_web_contract()):
                return
            web_buttons = driver.find_elements(By.ID, "webBtn")
            if not web_buttons:
                raise RuntimeError("web mode button is unavailable and chat-only auto-web contract is not active")
            if _web_mode_contract_ready(**_read_web_mode_contract()):
                return
            web_btn = web_buttons[0]
            driver.execute_script("arguments[0].click();", web_btn)
            wait.until(
                lambda _d: _web_mode_contract_ready(**_read_web_mode_contract())
            )

        current_stage = "browser-startup"
        _print({"browser_stage": current_stage})
        driver.get(args.base_url.rstrip("/") + "/")
        current_stage = "page-load"
        _print({"browser_stage": current_stage})
        wait.until(EC.presence_of_element_located((By.ID, "msg")))

        api_key = (args.api_key or "").strip()
        files_key = (args.files_api_key or api_key).strip()
        if api_key:
            current_stage = "auth-seed"
            _print({"browser_stage": current_stage})
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
                window.sessionStorage.setItem("aegis_api_key", arguments[0]);
                window.sessionStorage.setItem("aegis_files_api_key", arguments[1]);
                window.localStorage.removeItem("aegis_api_key");
                window.localStorage.removeItem("aegis_files_api_key");
                """,
                api_key,
                files_key,
            )
            # Selenium Python WebDriver uses refresh() directly.
            current_stage = "refresh-after-auth"
            _print({"browser_stage": current_stage})
            driver.refresh()
            wait.until(EC.presence_of_element_located((By.ID, "msg")))

        # Keep the message area unobstructed when optional side panel is open.
        try:
            current_stage = "panel-toggle"
            _print({"browser_stage": current_stage})
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

        wait.until(
            lambda d: (
                len(d.find_element(By.ID, "chat").text.strip()) > len(chat_before.strip())
                and not bool(d.execute_script("return document.getElementById('typing-bubble');"))
            )
        )
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

        crypto_proof = {}
        if args.crypto_proof:
            current_stage = "crypto-proof"
            _print({"browser_stage": current_stage})
            crypto_chat_before = driver.find_element(By.ID, "chat").text

            try:
                crypto_btn = driver.find_element(By.ID, "cryptoBtn")
                driver.execute_script("arguments[0].click();", crypto_btn)
            except Exception:
                pass

            wait.until(
                lambda d: "crypto" in d.find_element(By.ID, "modeIndicator").text.lower()
                or "cripto" in d.find_element(By.ID, "modeIndicator").text.lower()
            )

            show_crypto = driver.find_element(By.ID, "showCryptoPanelBtn")
            driver.execute_script("arguments[0].click();", show_crypto)
            wait.until(lambda d: "chart-hidden" not in (d.find_element(By.ID, "chartPanel").get_attribute("class") or ""))

            crypto_msg = driver.find_element(By.ID, "msg")
            crypto_msg.clear()
            crypto_msg.send_keys("BTCUSDT H=2m")
            crypto_msg.send_keys(Keys.ENTER)

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(crypto_chat_before.strip()))
            wait.until(
                lambda d: (
                    "h=" in d.find_element(By.ID, "cryptoContextPill").text.lower()
                    or "p=" in d.find_element(By.ID, "cryptoContextPill").text.lower()
                    or d.find_element(By.ID, "cryptoContextPill").text.strip() not in {"", "—"}
                )
            )
            wait.until(lambda d: "BTCUSDT" in d.find_element(By.ID, "predictionCompareTitle").text.upper())

            stats_btn = driver.find_element(By.ID, "statsBtn")
            driver.execute_script("arguments[0].click();", stats_btn)
            wait.until(
                lambda d: (
                    "stats" in d.find_element(By.ID, "sources-content").text.lower()
                    or "no stats data" in d.find_element(By.ID, "sources-content").text.lower()
                    or "sin datos de stats" in d.find_element(By.ID, "sources-content").text.lower()
                )
            )

            preds_btn = driver.find_element(By.ID, "predsBtn")
            driver.execute_script("arguments[0].click();", preds_btn)
            wait.until(
                lambda d: (
                    "predictions" in d.find_element(By.ID, "sources-content").text.lower()
                    or "recent predictions" in d.find_element(By.ID, "sources-content").text.lower()
                    or "últimas predicciones" in d.find_element(By.ID, "sources-content").text.lower()
                    or "no predictions" in d.find_element(By.ID, "sources-content").text.lower()
                    or "sin predicciones" in d.find_element(By.ID, "sources-content").text.lower()
                )
            )

            crypto_proof = {
                "mode": driver.find_element(By.ID, "modeIndicator").text,
                "crypto_context": driver.find_element(By.ID, "cryptoContextPill").text,
                "price_source": driver.find_element(By.ID, "priceSourceBadge").text,
                "compare_title": driver.find_element(By.ID, "predictionCompareTitle").text,
                "sources_preview": driver.find_element(By.ID, "sources-content").text[:240],
            }

        geo_proof = {}
        if args.geo_proof:
            current_stage = "geo-proof"
            _print({"browser_stage": current_stage})
            _ensure_chat_mode()
            geo_chat_before = driver.find_element(By.ID, "chat").text
            geo_msg = driver.find_element(By.ID, "msg")
            geo_msg.clear()
            geo_msg.send_keys("where is russia?")
            geo_msg.send_keys(Keys.ENTER)

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(geo_chat_before.strip()))
            wait.until(
                lambda d: (
                    "russia spans eastern europe and northern asia" in d.find_element(By.ID, "chat").text.lower()
                    or "rusia se extiende entre europa oriental y el norte de asia" in d.find_element(By.ID, "chat").text.lower()
                    or "if you want live sources" in d.find_element(By.ID, "chat").text.lower()
                    or "si quieres fuentes en vivo" in d.find_element(By.ID, "chat").text.lower()
                    or "web: where is" in d.find_element(By.ID, "chat").text.lower()
                )
            )
            chat_text = driver.find_element(By.ID, "chat").text
            new_chat_text = _new_chat_segment(geo_chat_before, chat_text)
            geo_proof = {
                "question": "where is russia?",
                "answer_preview": new_chat_text[-500:],
                "contains_fast_fact": (
                    "russia spans eastern europe and northern asia" in new_chat_text.lower()
                    or "rusia se extiende entre europa oriental y el norte de asia" in new_chat_text.lower()
                ),
                "contains_web_prompt": "web: where is" in new_chat_text.lower(),
            }

        memory_speed_proof = {}
        if args.memory_speed_proof:
            current_stage = "memory-speed-proof"
            _print({"browser_stage": current_stage})
            _ensure_chat_mode()
            cap_chat_before = driver.find_element(By.ID, "chat").text
            cap_msg = driver.find_element(By.ID, "msg")
            cap_msg.clear()
            cap_msg.send_keys("what is the capital of japan?")
            cap_msg.send_keys(Keys.ENTER)

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(cap_chat_before.strip()))
            wait.until(
                lambda d: (
                    "tokyo" in d.find_element(By.ID, "chat").text.lower()
                    or "tokio" in d.find_element(By.ID, "chat").text.lower()
                )
            )
            chat_text = driver.find_element(By.ID, "chat").text
            new_chat_text = _new_chat_segment(cap_chat_before, chat_text)
            memory_speed_proof = {
                "question": "what is the capital of japan?",
                "answer_preview": new_chat_text[-500:],
                "contains_fast_fact": "tokyo" in new_chat_text.lower() or "tokio" in new_chat_text.lower(),
                "contains_web_prompt": "web: what is the capital of <country>" in new_chat_text.lower(),
                "looks_concise": len(new_chat_text.strip()) <= 1200,
            }

        web_proof = {}
        if args.web_proof:
            current_stage = "web-proof"
            _print({"browser_stage": current_stage})
            web_chat_before = driver.find_element(By.ID, "chat").text
            web_query = f"web: latest python 3.12 release notes {int(time.time())}"

            def _web_submit_started() -> bool:
                return bool(
                    len(driver.find_element(By.ID, "chat").text.strip()) > len(web_chat_before.strip())
                    or str(driver.find_element(By.ID, "msg").get_attribute("value") or "").strip() == ""
                    or bool(driver.execute_script("return document.getElementById('typing-bubble');"))
                )

            _ensure_web_mode()

            current_stage = "web-proof-submit"
            _print({"browser_stage": current_stage})
            web_msg = driver.find_element(By.ID, "msg")
            web_msg.clear()
            web_msg.send_keys(web_query)
            if not str(web_msg.get_attribute("value") or "").strip():
                driver.execute_script(
                    """
                    const input = document.getElementById("msg");
                    if (input) {
                      input.value = arguments[0];
                      input.dispatchEvent(new Event("input", { bubbles: true }));
                    }
                    """,
                    web_query,
                )
            web_msg.send_keys(Keys.ENTER)

            current_stage = "web-proof-response"
            _print({"browser_stage": current_stage})
            try:
                wait.until(lambda _d: _web_submit_started())
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
                    wait.until(lambda _d: _web_submit_started())
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
                    wait.until(lambda _d: _web_submit_started())
            _wait_for_idle_chat()
            current_stage = "web-proof-sources"
            _print({"browser_stage": current_stage})
            wait.until(
                lambda d: (
                    d.find_element(By.ID, "sources-content").text.strip() not in {"", "No additional URLs.", "Sin URLs adicionales."}
                    or d.find_element(By.ID, "webStatusBadge").text.strip() not in {"WEB: —", "WEB: auto"}
                    or int(d.execute_script("return document.querySelectorAll('#sources-content .source-card').length;") or 0) > 0
                )
            )
            web_badge = driver.find_element(By.ID, "webStatusBadge").text
            source_cards = driver.execute_script(
                "return document.querySelectorAll('#sources-content .source-card').length;"
            )
            if args.strict and not _strict_web_proof_ready(web_badge=web_badge, source_cards=int(source_cards or 0)):
                raise AssertionError(
                    f"strict-web-proof-requires-live-web badge={web_badge!r} source_cards={int(source_cards or 0)}"
                )
            web_proof = {
                "question": web_query.replace("web: ", "", 1),
                "mode": driver.find_element(By.ID, "modeIndicator").text,
                "web_badge": web_badge,
                "sources_preview": driver.find_element(By.ID, "sources-content").text[:240],
                "source_cards": int(source_cards or 0),
            }

        url_proof = {}
        if args.url_proof:
            current_stage = "url-proof"
            _print({"browser_stage": current_stage})
            url_chat_before = driver.find_element(By.ID, "chat").text

            try:
                url_btn = driver.find_element(By.ID, "urlBtn")
                driver.execute_script("arguments[0].click();", url_btn)
            except Exception:
                pass

            wait.until(lambda d: "url" in d.find_element(By.ID, "modeIndicator").text.lower())

            url_msg = driver.find_element(By.ID, "msg")
            url_msg.clear()
            url_msg.send_keys(args.base_url.rstrip("/") + "/")
            url_msg.send_keys(Keys.ENTER)

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(url_chat_before.strip()))
            wait.until(
                lambda d: d.find_element(By.ID, "sources-content").text.strip() not in {"", "No additional URLs.", "Sin URLs adicionales."}
            )
            url_chat_text = driver.find_element(By.ID, "chat").text
            url_proof = {
                "question": args.base_url.rstrip("/") + "/",
                "mode": driver.find_element(By.ID, "modeIndicator").text,
                "sources_preview": driver.find_element(By.ID, "sources-content").text[:240],
                "contains_read_prefix": "read:" in url_chat_text.lower() or "leído:" in url_chat_text.lower(),
            }

        image_proof = {}
        if args.image_proof and proof_assets.get("image"):
            current_stage = "image-proof"
            _print({"browser_stage": current_stage})
            img_chat_before = driver.find_element(By.ID, "chat").text

            try:
                img_btn = driver.find_element(By.ID, "imgBtn")
                driver.execute_script("arguments[0].click();", img_btn)
            except Exception:
                pass

            wait.until(
                lambda d: "image" in d.find_element(By.ID, "modeIndicator").text.lower()
                or "imagen" in d.find_element(By.ID, "modeIndicator").text.lower()
            )

            img_input = driver.find_element(By.ID, "imgInput")
            img_input.send_keys(str(proof_assets["image"]))

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(img_chat_before.strip()))
            wait.until(
                lambda d: (
                    "reference image ready" in d.find_element(By.ID, "chat").text.lower()
                    or "imagen de referencia lista" in d.find_element(By.ID, "chat").text.lower()
                )
            )
            image_proof = {
                "mode": driver.find_element(By.ID, "modeIndicator").text,
                "image_ready": True,
                "chat_preview": driver.find_element(By.ID, "chat").text[-240:],
            }

        files_proof = {}
        if args.files_proof and proof_assets.get("zip"):
            current_stage = "files-proof"
            _print({"browser_stage": current_stage})
            files_chat_before = driver.find_element(By.ID, "chat").text

            try:
                files_panel_btn = driver.find_element(By.ID, "showFilesPanelBtn")
                driver.execute_script("arguments[0].click();", files_panel_btn)
            except Exception:
                pass

            upload_input = driver.find_element(By.ID, "projectUploadInput")
            upload_input.send_keys(str(proof_assets["zip"]))

            wait.until(lambda d: len(d.find_element(By.ID, "chat").text.strip()) > len(files_chat_before.strip()))
            wait.until(
                lambda d: (
                    "zip uploaded" in d.find_element(By.ID, "chat").text.lower()
                    or "zip subido" in d.find_element(By.ID, "chat").text.lower()
                )
            )
            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#projectTree .tree-node")) > 0)

            try:
                ingest_btn = driver.find_element(By.ID, "ingestStatusBtn")
                driver.execute_script("arguments[0].click();", ingest_btn)
            except Exception:
                pass

            wait.until(
                lambda d: (
                    "ingest" in d.find_element(By.ID, "chat").text.lower()
                    or "ingesta" in d.find_element(By.ID, "chat").text.lower()
                )
            )
            wait.until(
                lambda d: (
                    "done" in d.find_element(By.ID, "ingestStatusText").text.lower()
                    or "finished" in d.find_element(By.ID, "ingestStatusText").text.lower()
                    or "finalizada" in d.find_element(By.ID, "ingestStatusText").text.lower()
                )
            )
            files_proof = {
                "uploaded_zip": str(proof_assets["zip"].name),
                "active_project": driver.find_element(By.ID, "activeProjectBadge").text,
                "tree_nodes": int(driver.execute_script("return document.querySelectorAll('#projectTree .tree-node').length;") or 0),
                "ingest_status": driver.find_element(By.ID, "ingestStatusText").text,
            }

        project_proof = {}
        if args.project_proof:
            current_stage = "project-proof"
            _print({"browser_stage": current_stage})
            try:
                files_panel_btn = driver.find_element(By.ID, "showFilesPanelBtn")
                driver.execute_script("arguments[0].click();", files_panel_btn)
            except Exception:
                pass

            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, "#projectTree .tree-node")) > 0)
            wait.until(
                lambda d: (
                    d.find_element(By.ID, "activeProjectBadge").text.strip() not in {"", "Sin proyecto activo", "No active project"}
                    and len(d.find_elements(By.CSS_SELECTOR, "#projectTree .tree-node")) > 0
                )
            )
            tree_nodes = driver.execute_script(
                "return document.querySelectorAll('#projectTree .tree-node').length;"
            )
            project_meta_text = driver.find_element(By.ID, "projectMeta").text
            project_proof = {
                "tree_nodes": int(tree_nodes or 0),
                "project_meta_preview": project_meta_text[:240],
                "active_project_badge": driver.find_element(By.ID, "activeProjectBadge").text,
            }

        payload = {
            "ok": True,
            "mode": driver.find_element(By.ID, "modeIndicator").text,
            "chat_chars": len(driver.find_element(By.ID, "chat").text.strip()),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "browser": browser_binary,
        }
        if crypto_proof:
            payload["crypto_proof"] = crypto_proof
        if geo_proof:
            payload["geo_proof"] = geo_proof
        if memory_speed_proof:
            payload["memory_speed_proof"] = memory_speed_proof
        if web_proof:
            payload["web_proof"] = web_proof
        if url_proof:
            payload["url_proof"] = url_proof
        if image_proof:
            payload["image_proof"] = image_proof
        if files_proof:
            payload["files_proof"] = files_proof
        if project_proof:
            payload["project_proof"] = project_proof
        _print(payload)
        return 0
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or "").strip()
        if msg in {"", "Message:", "Message"}:
            msg = exc.__class__.__name__
        msg = f"{current_stage}:{msg}"
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
        # Best-effort orphan cleanup: kill only browsers started with this run's
        # temporary profile directory, not any user-owned Chromium session.
        try:
            if args.cleanup_orphans:
                cleanup_report = _cleanup_orphan_browsers(profile_dir)
                if cleanup_report:
                    _print({"cleanup_orphans": cleanup_report})
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
        if proof_assets:
            try:
                shutil.rmtree(proof_assets.get("dir"), ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
