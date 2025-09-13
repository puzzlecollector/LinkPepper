# BacklinkCheckerClass.py
# Verify whether a given comment text appears on a page, and report its rough rank among comments.
# Deps: pip install selenium beautifulsoup4 lxml webdriver-manager
# Works headless on Lightsail/Ubuntu with Chrome/Chromium.

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from shutil import which
from typing import Any, Dict, List, Optional, Tuple

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

# Optional: webdriver-manager to fetch the right chromedriver
try:
    from webdriver_manager.chrome import ChromeDriverManager
    _HAVE_WDM = True
except Exception:
    _HAVE_WDM = False


# -------------------------
# Config
# -------------------------
@dataclass
class CheckerConfig:
    headless: bool = True
    window_size: Tuple[int, int] = (1366, 900)
    nav_timeout: int = 45
    action_timeout: int = 15
    retries_on_nav: int = 2
    wait_between_actions: float = 0.5
    # Language / UA
    accept_lang: str = "ko-KR,ko;q=0.9,nb-NO,nb;q=0.8,en-US,en;q=0.7"
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )


# -------------------------
# Helper functions
# -------------------------
def _normalize_text(s: str) -> str:
    # Lowercase + collapse whitespace
    s = re.sub(r"\s+", " ", s or "")
    return s.strip().lower()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _contains_ascii(lower_hay: str, needle: str) -> bool:
    # For ascii-ish checks already lowercased
    return needle in lower_hay


# -------------------------
# Main class
# -------------------------
class BacklinkChecker:
    """
    Given a URL and a comment snippet, determine:
      - site availability
      - whether the comment text exists (exact, normalized match)
      - a rough rank (1-based) among detected comment items
    Searches main document first, then each iframe.
    """

    # Keywords to find comment containers/items (English + Norwegian + misc)
    _KWS = [
        "comment", "comments", "comment-body", "comment_content", "commenttext",
        "comment-entry", "comment-item", "commentlist", "comment-list",
        "reply", "replies", "discussion",
        "kommentar", "kommentarer", "kommentar-body", "kommentar-list",
        "댓글",  # Korean
    ]

    # Phrases indicating the site/page might be down/errored
    _DOWN_HINTS = [
        "this site can’t be reached", "this site can't be reached",
        "err_connection_timed_out", "err_name_not_resolved", "err_ssl",
        "proxy error", "502 bad gateway", "504 gateway timeout",
        "service unavailable", "access denied", "origin error"
    ]

    def __init__(self, cfg: CheckerConfig):
        self.cfg = cfg
        self.driver = self._init_driver()

    # ---------- Driver ----------
    def _find_chrome_binary(self) -> Optional[str]:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]:
            p = which(name)
            if p:
                return p
        return None

    def _init_driver(self) -> webdriver.Chrome:
        opts = ChromeOptions()
        opts.set_capability("pageLoadStrategy", "eager")
        if self.cfg.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--window-size={},{}".format(*self.cfg.window_size))
        opts.add_argument(f"--lang={self.cfg.accept_lang.split(',')[0]}")
        opts.add_argument(f"--user-agent={self.cfg.user_agent}")

        chrome_bin = self._find_chrome_binary()
        if chrome_bin:
            opts.binary_location = chrome_bin
        else:
            raise RuntimeError(
                "Chrome/Chromium binary not found. Install google-chrome-stable (amd64) "
                "or 'snap install chromium' on arm64."
            )

        if _HAVE_WDM:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        else:
            driver = webdriver.Chrome(options=opts)

        driver.set_page_load_timeout(self.cfg.nav_timeout)

        # Small stealth tweaks
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                "userAgent": self.cfg.user_agent,
                "acceptLanguage": self.cfg.accept_lang,
                "platform": "Linux"
            })
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
            )
        except Exception:
            pass

        return driver

    # ---------- Public API ----------
    def check_comment(self, url: str, comment_snippet: str) -> Dict[str, Any]:
        # 1) Navigate
        ok, load_state = self._safe_get(url)
        if not ok:
            return {
                "url": url,
                "site": {"reachable": False, "load_state": load_state, "error_hint": load_state, "title": None},
                "comment": {"query": comment_snippet, "exists": False, "match_type": "not_checked", "position": None,
                            "total_candidates": 0, "closest_score": 0.0, "context": None}
            }

        title = ""
        try:
            title = self.driver.title
        except Exception:
            pass

        # 2) Scroll to trigger lazy content
        self._scroll_to_bottom_and_wait()

        # 3) Quick site-down heuristic using current HTML
        html = self.driver.page_source or ""
        down_hint = self._maybe_error_page(html)
        site_ok = down_hint is None

        # 4) Try main document first
        self.driver.switch_to.default_content()
        result = self._check_in_current_context(comment_snippet)
        context = "main_document"
        if not result["exists"]:
            # 5) Probe iframes (one by one)
            try:
                frames = self.driver.find_elements(By.TAG_NAME, "iframe")
            except Exception:
                frames = []
            for idx, f in enumerate(frames):
                try:
                    self.driver.switch_to.default_content()
                    self.driver.switch_to.frame(f)
                    r2 = self._check_in_current_context(comment_snippet)
                    if r2["exists"] or r2["closest_score"] > result["closest_score"]:
                        result = r2
                        context = f"iframe_index_{idx}"
                    if result["exists"]:
                        break
                except Exception:
                    continue
            self.driver.switch_to.default_content()

        result["context"] = context

        return {
            "url": url,
            "site": {"reachable": site_ok, "load_state": load_state, "error_hint": down_hint, "title": title},
            "comment": result,
        }

    # ---------- Context-scoped check ----------
    def _check_in_current_context(self, comment_snippet: str) -> Dict[str, Any]:
        """
        In the current browsing context (main doc or an iframe), collect comment items,
        and try to find the snippet. Returns existence + position + meta.
        """
        # Try to reduce cookie banners noise
        self._dismiss_cookie_banners()

        # Heuristic: gather comment *items* (not just containers)
        items = self._collect_comment_items()

        # If none found, fall back to long text blocks under/near comment form
        if not items:
            items = self._fallback_blocks_after_form()

        total = len(items)
        needle = _normalize_text(comment_snippet)
        best_score = 0.0
        best_idx = None
        match_type = "not_found"

        for i, el in enumerate(items, start=1):
            txt = self._visible_text(el)
            norm = _normalize_text(txt)
            if not norm:
                continue
            if _contains_ascii(norm, needle):
                best_idx = i
                best_score = 1.0
                match_type = "exact"
                break
            else:
                # fuzzy backup
                sc = _similarity(norm, needle)
                if sc > best_score:
                    best_score = sc
                    best_idx = i

        exists = (match_type == "exact")
        if not exists and best_score >= 0.88:
            match_type = "fuzzy_high"

        return {
            "query": comment_snippet,
            "exists": exists,
            "match_type": match_type if exists or best_score >= 0.88 else "not_found",
            "position": best_idx if (exists or best_score >= 0.88) else None,
            "total_candidates": total,
            "closest_score": round(best_score, 4),
            "context": None,  # filled by caller
        }

    # ---------- Collectors ----------
    def _collect_comment_items(self) -> List[Any]:
        """
        Try several targeted selectors that usually map to individual comments.
        Order is DOM order by Selenium's find_elements.
        """
        d = self.driver
        out: List[Any] = []

        # 1) <li class*="comment">
        xpaths = [
            "//li[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'comment')]",
            "//li[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'comment')]",
        ]

        # 2) items with comment-ish classes/ids (div/article/section)
        for kw in self._KWS:
            xpaths.append(f"//div[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
            xpaths.append(f"//article[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
            xpaths.append(f"//section[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
            xpaths.append(f"//div[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
            xpaths.append(f"//article[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
            xpaths.append(f"//section[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{kw}')]")
        # Korean keyword '댓글' (ID/class contains exact unicode)
        xpaths.extend([
            "//*[contains(@class,'댓글') or contains(@id,'댓글')]"
        ])

        # 3) schema/ARIA hints
        xpaths.extend([
            "//*[@itemtype='http://schema.org/Comment' or @itemprop='comment' or @role='comment']",
        ])

        # 4) Comments inside known lists
        xpaths.extend([
            "//*[self::ol or self::ul][contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'comment')]/*",
        ])

        seen = set()
        for xp in xpaths:
            try:
                for el in d.find_elements(By.XPATH, xp):
                    if not el.is_displayed():
                        continue
                    key = el.id
                    if key not in seen:
                        seen.add(key)
                        out.append(el)
            except Exception:
                continue

        # Filter out massive containers that clearly hold many items (heuristic by child count)
        filtered: List[Any] = []
        for el in out:
            try:
                # if it has MANY direct children that are blocks, it's probably a container
                kids = el.find_elements(By.XPATH, "./*")
                if len(kids) > 20:
                    continue
            except Exception:
                pass
            filtered.append(el)

        return filtered

    def _fallback_blocks_after_form(self) -> List[Any]:
        """
        If we couldn't confidently detect comment items, try to
        locate the comment form (labels like 'Kommentere', 'Comment') and then
        take sibling blocks after it as candidate comments.
        """
        d = self.driver
        form = None
        # Find label containing 'komment' or 'comment'
        try:
            label = None
            label = d.find_element(By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZÆØÅ','abcdefghijklmnopqrstuvwxyzæøå'),'komment')]")
        except Exception:
            try:
                label = d.find_element(By.XPATH, "//label[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'comment')]")
            except Exception:
                label = None
        if label:
            # nearest form ancestor
            try:
                form = label.find_element(By.XPATH, "ancestor::form")
            except Exception:
                form = None

        blocks: List[Any] = []
        if form:
            # Take a handful of following block siblings as candidates
            try:
                siblings = form.find_elements(By.XPATH, "following::*[self::div or self::article or self::section or self::li]")
                for el in siblings[:80]:  # cap to avoid huge scans
                    if el.is_displayed():
                        blocks.append(el)
            except Exception:
                pass

        # If still nothing, grab long text blocks across the page (last resort)
        if not blocks:
            try:
                longs = d.find_elements(By.XPATH, "//div[normalize-space(string())!=''] | //article | //section")
                for el in longs:
                    if not el.is_displayed():
                        continue
                    txt = self._visible_text(el)
                    if len(txt.strip()) > 120:  # only long-ish blocks
                        blocks.append(el)
                        if len(blocks) >= 100:
                            break
            except Exception:
                pass

        return blocks

    # ---------- Small utils ----------
    def _visible_text(self, el) -> str:
        try:
            txt = el.text
            if txt and txt.strip():
                return txt
            # try innerText via JS
            return self.driver.execute_script("return arguments[0].innerText || '';", el) or ""
        except Exception:
            return ""

    def _dismiss_cookie_banners(self):
        possible_texts = [
            "accept", "agree", "got it", "allow", "ok",
            "확인", "동의", "수락", "허용",
            "godta", "jeg godtar", "aksepter", "jeg samtykker", "tillat"
        ]
        try:
            for btn in self.driver.find_elements(By.XPATH, "//button|//a|//div[@role='button']"):
                t = (btn.text or "").strip().lower()
                if any(p in t for p in possible_texts):
                    try:
                        btn.click()
                        time.sleep(0.2)
                    except Exception:
                        pass
        except Exception:
            pass

    def _maybe_error_page(self, html: str) -> Optional[str]:
        low = (html or "").lower()
        for h in self._DOWN_HINTS:
            if h in low:
                return h
        return None

    def _safe_get(self, url: str) -> Tuple[bool, str]:
        for attempt in range(1, self.cfg.retries_on_nav + 2):
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                return True, "ok"
            except TimeoutException:
                # stop loading; treat partially loaded as OK if we have HTML
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
                html = (self.driver.page_source or "").strip()
                if len(html) > 1000:
                    return True, "partial_load"
                status = f"timeout_on_attempt_{attempt}"
            except WebDriverException as e:
                status = f"webdriver_error_on_attempt_{attempt}: {e}"
            time.sleep(1.5 * attempt)
        return False, status

    def _scroll_to_bottom_and_wait(self, max_steps: int = 6):
        try:
            for _ in range(max_steps):
                old_h = self.driver.execute_script("return document.body.scrollHeight")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.9)
                new_h = self.driver.execute_script("return document.body.scrollHeight")
                if new_h == old_h:
                    break
        except Exception:
            pass

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass


# -------------------------
# TEST HARNESS
# -------------------------
if __name__ == "__main__":
    checker = BacklinkChecker(CheckerConfig(
        headless=True,
        nav_timeout=45,
        retries_on_nav=2,
    ))

    try:
        test_url = "https://www.nfunorge.org/Om-NFU/NFU-bloggen/samtykke-til-besvar/"
        test_comment = (
            "This is a very informative article, thank you for sharing these insights. "
            "Discussions around rights and consent are crucial, and I appreciate the detailed explanation. "
            "On another note, for those working in digital communication and customer support,"
        )

        result = checker.check_comment(test_url, test_comment)
        print("\n=== RESULT ===")
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        checker.close()
