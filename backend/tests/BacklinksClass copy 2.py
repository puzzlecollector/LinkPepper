# CommentClass.py
# DOM-first automation with GPT-guided planning + robust headless nav & graceful exits.
# Deps: selenium, beautifulsoup4, lxml, tiktoken, openai
# Optional: webdriver-manager (works; Selenium Manager also supported)

from __future__ import annotations

import json
import time
import re
import os
from shutil import which
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

# === OpenAI (Responses API) ===
from openai import OpenAI
import openai  # for exceptions

# === Tokenizer for size estimation ===
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def count_tokens(txt: str) -> int:
        return len(_ENC.encode(txt))
except Exception:
    def count_tokens(txt: str) -> int:
        # Fallback heuristic: ~4 chars per token
        return max(1, len(txt) // 4)

# === HTML parsing/pretty ===
from bs4 import BeautifulSoup

# === Selenium ===
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, WebDriverException
)
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# Optional: webdriver-manager (works well on amd64)
try:
    from webdriver_manager.chrome import ChromeDriverManager
    _HAVE_WDM = True
except Exception:
    _HAVE_WDM = False


# -------------------------
# Configuration dataclass
# -------------------------
@dataclass
class CommentConfig:
    api_key: str
    model_primary: str = "gpt-5"     # try GPT-5 first
    model_fallback: str = "gpt-4.1"  # fallback model
    headless: bool = True
    window_size: Tuple[int, int] = (1366, 768)
    nav_timeout: int = 45            # give slow sites more time
    action_timeout: int = 20
    wait_between_actions: float = 0.6
    max_snippets: int = 10           # limit how many candidate snippets we send to LLM
    max_tokens_prompt: int = 60_000  # rough budget for prompt content
    confirm_before_submit: bool = False  # set True for dry-run
    default_name: Optional[str] = None   # for platforms that need author/name
    default_email: Optional[str] = None  # for platforms that need email
    default_website: Optional[str] = None
    retries_on_nav: int = 2          # retry nav with backoff if timeouts


# -------------------------
# Main Class
# -------------------------
class Commenter:
    """
    DOM-first approach with robust headless navigation and graceful exits.
    """

    # Multilingual keywords commonly seen around comment/reply UIs (expanded with Norwegian)
    KEYWORDS = [
        # English
        "reply", "replies", "comment", "comments", "add comment", "post comment",
        "write a comment", "leave a comment", "leave a reply", "discussion", "respond", "submit",
        "message", "post", "send", "publish",
        # Korean
        "댓글", "답글", "코멘트", "댓글쓰기", "댓글 달기", "의견", "등록", "보내기", "작성",
        # Japanese
        "返信", "コメント", "書き込み", "送信", "投稿",
        # Chinese (Simplified)
        "回复", "评论", "发表评论", "提交", "发布",
        # Spanish
        "responder", "respuesta", "comentar", "comentarios", "publicar comentario", "enviar",
        # French
        "répondre", "réponse", "commentaire", "commentaires", "publier un commentaire", "envoyer",
        # German
        "antworten", "antwort", "kommentar", "kommentare", "kommentieren", "absenden", "senden",
        # Italian
        "rispondi", "risposta", "commento", "commenti", "invia", "pubblica",
        # Portuguese
        "responder", "resposta", "comentário", "comentários", "publicar comentário", "enviar",
        # Russian
        "ответить", "ответ", "комментарий", "комментарии", "оставить комментарий", "отправить",
        # Turkish
        "yanıtla", "yanıt", "yorum", "yorumlar", "yorum yap", "gönder",
        # Vietnamese
        "trả lời", "bình luận", "đăng bình luận", "gửi",
        # Indonesian
        "balas", "komentar", "kirim komentar", "kirim",
        # Thai
        "ตอบกลับ", "แสดงความคิดเห็น", "ส่ง",
        # Nordic & misc (incl. Norwegian)
        "svar", "kommentar", "kommentarer", "kommenter", "skriv kommentar", "legg igjen en kommentar",
        "send inn", "publiser", "send inn kommentar",
    ]

    # Auth/login detection (multilingual)
    LOGIN_KEYWORDS = [
        "login", "log in", "sign in", "sign-in", "signin", "account", "password",
        "로그인", "비밀번호",
        "logg inn", "innlogging", "pålogging",
        "anmelden", "connexion", "accedi", "entrar", "iniciar sesión", "войти"
    ]

    # Comments-closed detection
    CLOSED_COMMENTS = [
        "comments are closed", "kommentarer er stengt", "kommentarer lukket",
        "댓글이 닫혔습니다", "no comments allowed", "commenting has been closed"
    ]

    # Simple platform hints (WordPress-like IDs)
    WP_TEXTAREA_IDS = ["comment"]
    WP_AUTHOR_IDS = ["author"]
    WP_EMAIL_IDS  = ["email"]
    WP_SUBMIT_IDS = ["submit", "comment-submit"]

    # Realistic desktop UA (Chrome 129 on Linux x86_64)
    DESKTOP_UA = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    )
    ACCEPT_LANG = "ko-KR,ko;q=0.9,nb-NO,nb;q=0.8,en-US,en;q=0.7"

    def __init__(self, cfg: CommentConfig):
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key)
        self.driver = self._init_driver()

    # -------------------------
    # Driver setup
    # -------------------------
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

        # PageLoadStrategy eager: don't wait for all subresources
        opts.set_capability("pageLoadStrategy", "eager")

        # Headless & stability flags
        if self.cfg.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--window-size={},{}".format(*self.cfg.window_size))
        opts.add_argument(f"--lang={self.ACCEPT_LANG.split(',')[0]}")

        # Realistic UA
        opts.add_argument(f"--user-agent={self.DESKTOP_UA}")

        # Binary (Chrome/Chromium) autodetect
        chrome_bin = self._find_chrome_binary()
        if chrome_bin:
            opts.binary_location = chrome_bin
        else:
            # We keep going; Selenium Manager might locate a driver, but
            # without a system browser this will still fail—better to raise:
            raise RuntimeError(
                "Chrome/Chromium binary not found. Install google-chrome-stable (amd64) "
                "or snap chromium (arm64)."
            )

        # Choose driver creation path
        if _HAVE_WDM:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        else:
            # Rely on Selenium Manager (Selenium ≥ 4.6)
            driver = webdriver.Chrome(options=opts)

        driver.set_page_load_timeout(self.cfg.nav_timeout)

        # CDP stealth tweaks: set UA/language again and hide webdriver flag
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                "userAgent": self.DESKTOP_UA,
                "acceptLanguage": self.ACCEPT_LANG,
                "platform": "Linux"
            })
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
            )
        except Exception:
            pass

        return driver

    # -------------------------
    # Public entrypoint
    # -------------------------
    def post_comment(self, url: str, comment_text: str) -> Dict[str, Any]:
        drv = self.driver

        ok, status = self._safe_get(url)
        if not ok:
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": f"Navigation failed: {status}",
                "error_type": "navigation_error"
            }

        # Best-effort iframe switch & cookie banners
        self._maybe_switch_to_first_relevant_iframe()
        self._dismiss_cookie_banners()

        # Extract & prettify HTML (may be partial on eager/timeout fallback)
        raw_html = drv.execute_script("return document.documentElement.outerHTML;") or ""
        pretty_html = self._prettify_html(raw_html)

        # Early exit checks: site down / error pages
        down_reason = self._maybe_error_page(pretty_html)
        if down_reason:
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": f"Site error or down: {down_reason}",
                "error_type": "site_down"
            }

        # Check if login seems required
        if self._login_required(pretty_html):
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": "Login required to comment on this page.",
                "error_type": "login_required"
            }

        # Check if comments are closed
        if self._comments_closed(pretty_html):
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": "Comments are closed on this page.",
                "error_type": "comments_closed"
            }

        # Find candidate elements (reply triggers, textareas/inputs, submit buttons)
        candidates = self._find_candidates()
        if not candidates:
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": "No candidate elements found for comments/replies.",
                "error_type": "no_comment_ui"
            }

        # Build small, focused snippets around each candidate
        snippets = self._build_snippets_for_llm(candidates, pretty_html)

        # Trim snippets if token budget exceeded
        prompt_chunks = self._budget_snippets(snippets, self.cfg.max_tokens_prompt)

        # Ask LLM to plan the action sequence
        plan = self._ask_llm_for_plan(url, prompt_chunks, comment_text)

        if not plan.get("actions"):
            return {
                "ok": False,
                "submitted": False,
                "url": url,
                "reason": "LLM did not return an actionable plan.",
                "error_type": "no_llm_plan",
                "plan": plan
            }

        # Execute the plan
        result = self._execute_plan(plan, comment_text)
        result["url"] = url
        result["plan"] = plan
        return result

    # -------------------------
    # Navigation helpers
    # -------------------------
    def _safe_get(self, url: str) -> Tuple[bool, str]:
        """
        Robust navigation with retries & graceful timeout handling.
        Returns (ok, status_str). On timeout, tries window.stop() and checks partial content.
        """
        for attempt in range(1, self.cfg.retries_on_nav + 2):  # e.g., 1 initial + retries
            try:
                self.driver.get(url)
                # wait for DOMContentLoaded / readyState != 'loading'
                ready = WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                return True, "ok"
            except TimeoutException:
                # Try to salvage partial content
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

    def _maybe_error_page(self, html: str) -> Optional[str]:
        low = html.lower()
        # Common Chrome error phrases visible in page source
        hints = [
            "this site can’t be reached",
            "err_connection_timed_out",
            "err_name_not_resolved",
            "err_ssl",
            "proxy error",
            "502 bad gateway",
            "504 gateway timeout",
            "service unavailable",
            "access denied"
        ]
        for h in hints:
            if h in low:
                return h
        return None

    # -------------------------
    # Helpers: DOM & candidates
    # -------------------------
    def _maybe_switch_to_first_relevant_iframe(self):
        drv = self.driver
        try:
            iframes = drv.find_elements(By.TAG_NAME, "iframe")
            for f in iframes:
                attrs = [
                    f.get_attribute("title") or "",
                    f.get_attribute("name") or "",
                    f.get_attribute("src") or "",
                    f.get_attribute("id") or "",
                ]
                text = " ".join(a.lower() for a in attrs)
                if any(k in text for k in ["comment", "disqus", "reply", "댓글", "답글", "kommentar"]):
                    drv.switch_to.frame(f)
                    return
        except Exception:
            pass  # ignore; remain in default context

    def _dismiss_cookie_banners(self):
        drv = self.driver
        possible_texts = ["accept", "agree", "got it", "allow", "확인", "동의", "수락", "허용", "jeg forstår", "ok"]
        try:
            for btn in drv.find_elements(By.XPATH, "//button|//a|//div[@role='button']"):
                t = (btn.text or "").strip().lower()
                if any(p in t for p in possible_texts):
                    try:
                        btn.click()
                        time.sleep(0.2)
                    except Exception:
                        pass
        except Exception:
            pass

    def _prettify_html(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "lxml")
            return soup.prettify()
        except Exception:
            return html

    def _find_candidates(self) -> List[Dict[str, Any]]:
        drv = self.driver
        candidates = []

        button_like_xpath = (
            "//button | //a | //input[@type='submit' or @type='button'] | //div[@role='button']"
        )
        try:
            elems = drv.find_elements(By.XPATH, button_like_xpath)
            for e in elems:
                label = (e.text or "").strip()
                label_full = " ".join([
                    label.lower(),
                    (e.get_attribute("value") or "").lower(),
                    (e.get_attribute("aria-label") or "").lower(),
                    (e.get_attribute("title") or "").lower()
                ])
                if any(k in label_full for k in self._lower_keywords()):
                    candidates.append(self._pack_candidate(e, role="trigger"))
        except Exception:
            pass

        # Textareas / inputs that look like comment fields
        try:
            textareas = drv.find_elements(By.TAG_NAME, "textarea")
            for ta in textareas:
                placeholder = (ta.get_attribute("placeholder") or "").lower()
                aria = (ta.get_attribute("aria-label") or "").lower()
                name = (ta.get_attribute("name") or "").lower()
                if any(k in (placeholder + " " + aria + " " + name) for k in self._lower_keywords()):
                    candidates.append(self._pack_candidate(ta, role="textarea"))
        except Exception:
            pass

        # Generic text inputs (avoid password/email/url by default)
        try:
            inputs = drv.find_elements(By.XPATH, "//input[not(@type) or @type='text']")
            for inp in inputs:
                placeholder = (inp.get_attribute("placeholder") or "").lower()
                name = (inp.get_attribute("name") or "").lower()
                if any(k in (placeholder + " " + name) for k in self._lower_keywords()):
                    candidates.append(self._pack_candidate(inp, role="textinput"))
        except Exception:
            pass

        # WordPress-known IDs (strong hints)
        for wid in self.WP_TEXTAREA_IDS:
            try:
                e = drv.find_element(By.ID, wid)
                candidates.append(self._pack_candidate(e, role="textarea_wp"))
            except Exception:
                pass
        for wid in self.WP_SUBMIT_IDS:
            try:
                e = drv.find_element(By.ID, wid)
                candidates.append(self._pack_candidate(e, role="submit_wp"))
            except Exception:
                pass

        # Deduplicate by selector signature
        uniq = {}
        for c in candidates:
            key = (c["how"], c["selector"])
            uniq[key] = c
        return list(uniq.values())

    def _lower_keywords(self) -> List[str]:
        return [k.lower() for k in self.KEYWORDS]

    def _pack_candidate(self, element, role: str) -> Dict[str, Any]:
        sel, how = self._best_selector(element)
        text = (element.text or "").strip()
        tag = element.tag_name.lower()
        extra = {
            "aria_label": element.get_attribute("aria-label") or "",
            "placeholder": element.get_attribute("placeholder") or "",
            "value": element.get_attribute("value") or "",
            "name": element.get_attribute("name") or "",
            "id": element.get_attribute("id") or "",
            "class": element.get_attribute("class") or "",
            "type": element.get_attribute("type") or "",
        }
        return {
            "role": role,
            "tag": tag,
            "text": text,
            "how": how,
            "selector": sel,
            "extra": extra,
            "outer_html": element.get_attribute("outerHTML") or "",
        }

    def _best_selector(self, el) -> Tuple[str, str]:
        el_id = el.get_attribute("id")
        if el_id:
            return f"#{el_id}", "css"
        name = el.get_attribute("name")
        if name:
            return f"[name='{name}']", "css"
        classes = (el.get_attribute("class") or "").strip().split()
        if classes:
            c = re.sub(r"[^a-zA-Z0-9_-]", "", classes[0])
            if c:
                return f"{el.tag_name}.{c}", "css"
        try:
            path = self.driver.execute_script("""
                function cssPath(el){
                  if (!(el instanceof Element)) return "";
                  var path = [];
                  while (el && el.nodeType === Node.ELEMENT_NODE){
                    var selector = el.nodeName.toLowerCase();
                    if (el.id){
                      selector += "#" + el.id;
                      path.unshift(selector);
                      break;
                    } else {
                      var sib = el, nth = 1;
                      while ((sib = sib.previousElementSibling) != null){
                        if (sib.nodeName.toLowerCase() == selector) nth++;
                      }
                      selector += ":nth-of-type(" + nth + ")";
                    }
                    path.unshift(selector);
                    el = el.parentNode;
                  }
                  return path.join(" > ");
                }
                return cssPath(arguments[0]);
            """, el)
            if path:
                return path, "css"
        except Exception:
            pass
        try:
            xp = self.driver.execute_script("""
                function xPath(el){
                  if (el.id) return "//*[@id='" + el.id + "']";
                  if (el === document.body) return "/html/body";
                  var ix= 0;
                  var siblings = el.parentNode ? el.parentNode.childNodes : [];
                  for (var i=0; i<siblings.length; i++){
                    var sib = siblings[i];
                    if (sib === el){
                      var tagName = el.tagName.toLowerCase();
                      return xPath(el.parentNode) + '/' + tagName + '[' + (ix+1) + ']';
                    }
                    if (sib.nodeType === 1 && sib.tagName === el.tagName) ix++;
                  }
                }
                return xPath(arguments[0]);
            """, el)
            if xp:
                return xp, "xpath"
        except Exception:
            pass
        return el.tag_name, "css"

    def _build_snippets_for_llm(self, candidates: List[Dict[str, Any]], pretty_html: str) -> List[Dict[str, Any]]:
        snippets = []
        for c in candidates:
            outer = c.get("outer_html", "")
            snippet = {
                "role": c["role"],
                "how": c["how"],
                "selector": c["selector"],
                "tag": c["tag"],
                "text": c["text"],
                "attrs": c["extra"],
                "html": outer[:5000]
            }
            snippets.append(snippet)
        role_order = {"textarea_wp": 0, "submit_wp": 1, "trigger": 2, "textarea": 3, "textinput": 4}
        snippets.sort(key=lambda s: role_order.get(s["role"], 99))
        return snippets[: self.cfg.max_snippets]

    def _budget_snippets(self, snippets: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        payload = json.dumps(snippets, ensure_ascii=False)
        if count_tokens(payload) <= max_tokens:
            return snippets
        prioritized = [s for s in snippets if s["role"] in ("textarea_wp", "submit_wp", "textarea", "trigger")]
        payload2 = json.dumps(prioritized, ensure_ascii=False)
        if count_tokens(payload2) <= max_tokens:
            return prioritized
        trimmed = []
        for s in prioritized:
            s = dict(s)
            s["html"] = s["html"][:1500]
            trimmed.append(s)
            if count_tokens(json.dumps(trimmed, ensure_ascii=False)) > max_tokens:
                trimmed.pop()
                break
        return trimmed

    # -------------------------
    # LLM planning
    # -------------------------
    def _ask_llm_for_plan(self, url: str, snippets: List[Dict[str, Any]], comment_text: str) -> Dict[str, Any]:
        sys = (
            "You are a reliable web-comment agent. You receive:\n"
            "1) URL context\n"
            "2) A list of candidate UI elements with small HTML snippets and CSS/XPath selectors\n\n"
            "Goal: produce a safe, minimal plan to leave a comment/reply using these existing elements.\n"
            "- If a reply trigger button is needed, pick ONE likely trigger.\n"
            "- Pick ONE text field (prefer <textarea>) for the comment body.\n"
            "- Pick ONE submit/post button.\n"
            "- Use the provided selectors AS-IS; do NOT invent selectors.\n"
            "- If a field is already visible, trigger can be null.\n"
            "- Output JSON ONLY with the schema below. If not possible, return empty actions.\n"
        )

        schema = {
            "name": "CommentPlanner",
            "schema": {
                "type": "object",
                "properties": {
                    "steps_explanation": {"type": "string"},
                    "actions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["click", "type", "submit_click"]},
                                "how": {"type": "string", "enum": ["css", "xpath"]},
                                "selector": {"type": "string"},
                                "field_kind": {"type": "string", "enum": ["comment", "name", "email", "website", "other"], "nullable": True},
                            },
                            "required": ["type", "how", "selector"],
                            "additionalProperties": False
                        }
                    }
                },
                "required": ["actions"]
            }
        }

        prompt = {
            "url": url,
            "comment_preview": (comment_text[:120] + ("..." if len(comment_text) > 120 else "")),
            "candidates": snippets
        }

        for model in (self.cfg.model_primary, self.cfg.model_fallback):
            try:
                resp = self.client.responses.create(
                    model=model,
                    input=[
                        {"role": "system", "content": sys},
                        {"role": "user", "content": "Decide the best minimal action plan."},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}
                    ],
                    response_format={"type": "json_schema", "json_schema": schema},
                )
                txt = getattr(resp, "output_text", None) or (
                    resp.output[0].content[0].text if getattr(resp, "output", None) else None
                )
                data = None
                if txt:
                    data = json.loads(txt)
                else:
                    try:
                        data = resp.output[0].content[0].json
                    except Exception:
                        pass
                if isinstance(data, dict):
                    data["_model_used"] = model
                    return data
            except Exception as e:
                print(f"[WARN] LLM planning failed on model={model}: {e}")
                continue
        return {"actions": []}

    # -------------------------
    # Execute plan
    # -------------------------
    def _execute_plan(self, plan: Dict[str, Any], comment_text: str) -> Dict[str, Any]:
        drv = self.driver
        actions = plan.get("actions", [])
        logs = []
        try:
            # If WordPress-style convenience fields exist, pre-fill name/email
            self._fill_wordpress_identity_if_present()

            for step in actions:
                t = step["type"]
                sel = step["selector"]
                how = step["how"]
                logs.append(f"Step: {t} via {how} -> {sel}")

                el = self._wait_for_element(how, sel, self.cfg.action_timeout)
                if not el:
                    return {"ok": False, "submitted": False, "reason": f"Element not found: {how}:{sel}", "logs": logs}

                self._scroll_into_view(el)

                if t == "click":
                    self._safe_click(el)
                    time.sleep(self.cfg.wait_between_actions)
                elif t == "type":
                    field_kind = step.get("field_kind") or "other"
                    text = comment_text if field_kind == "comment" else self._default_for(field_kind)
                    if text is None:
                        continue
                    try:
                        el.clear()
                    except Exception:
                        pass
                    el.send_keys(text)
                    time.sleep(self.cfg.wait_between_actions)
                elif t == "submit_click":
                    if self.cfg.confirm_before_submit:
                        logs.append("Dry-run: submit skipped")
                        return {"ok": True, "submitted": False, "logs": logs}
                    self._safe_click(el)
                    time.sleep(self.cfg.wait_between_actions)
                else:
                    logs.append(f"Unknown step type: {t}")

            return {"ok": True, "submitted": True, "logs": logs}
        except Exception as e:
            return {"ok": False, "submitted": False, "reason": f"Execution error: {e}", "logs": logs}

    def _default_for(self, field_kind: str) -> Optional[str]:
        if field_kind == "name":
            return self.cfg.default_name
        if field_kind == "email":
            return self.cfg.default_email
        if field_kind == "website":
            return self.cfg.default_website
        return None

    def _fill_wordpress_identity_if_present(self):
        drv = self.driver
        for fid in self.WP_AUTHOR_IDS:
            try:
                e = drv.find_element(By.ID, fid)
                if self.cfg.default_name:
                    self._scroll_into_view(e)
                    try: e.clear()
                    except: pass
                    e.send_keys(self.cfg.default_name)
            except Exception:
                pass
        for fid in self.WP_EMAIL_IDS:
            try:
                e = drv.find_element(By.ID, fid)
                if self.cfg.default_email:
                    self._scroll_into_view(e)
                    try: e.clear()
                    except: pass
                    e.send_keys(self.cfg.default_email)
            except Exception:
                pass

    def _wait_for_element(self, how: str, selector: str, timeout: int):
        by = By.CSS_SELECTOR if how == "css" else By.XPATH
        try:
            return WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, selector))
            )
        except TimeoutException:
            return None

    def _scroll_into_view(self, el):
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'});", el)
            time.sleep(0.2)
        except Exception:
            pass

    def _safe_click(self, el):
        try:
            el.click()
        except WebDriverException:
            try:
                self.driver.execute_script("arguments[0].click();", el)
            except Exception:
                ActionChains(self.driver).move_to_element(el).click().perform()

    # -------------------------
    # Simple page heuristics
    # -------------------------
    def _login_required(self, html: str) -> bool:
        low = html.lower()
        # obvious login UI / password fields
        if "type=\"password\"" in low or "type='password'" in low:
            return True
        for kw in self.LOGIN_KEYWORDS:
            if kw in low:
                return True
        return False

    def _comments_closed(self, html: str) -> bool:
        low = html.lower()
        for kw in self.CLOSED_COMMENTS:
            if kw in low:
                return True
        return False

    # -------------------------
    # Cleanup
    # -------------------------
    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass


# -------------------------
# TEST HARNESS
# -------------------------
if __name__ == "__main__":
    # === Hard-code your API KEY here (no env/venv/argv). ===
    OPENAI_API_KEY = ""

    cfg = CommentConfig(
        api_key=OPENAI_API_KEY,
        headless=True,
        confirm_before_submit=True,  # set False to actually submit
        default_name="Kevin",
        default_email="kevinkim2657@gmail.com",
        default_website=None,
        nav_timeout=45,
        retries_on_nav=2,
    )

    commenter = Commenter(cfg)
    try:
        test_url = "https://www.nfunorge.org/Om-NFU/NFU-bloggen/samtykke-til-besvar/"
        test_text = "your commentaries are always insightful. Thank you for your insights"

        result = commenter.post_comment(test_url, test_text)
        print("\n=== RESULT ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        commenter.close()
