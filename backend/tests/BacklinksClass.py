# CommentClass.py
# DOM-first automation with GPT-guided planning + robust headless nav & graceful exits.
# Deps: pip install --upgrade openai selenium beautifulsoup4 lxml tiktoken webdriver-manager

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
        return max(1, len(txt) // 4)  # heuristic

# === HTML parsing/pretty ===
from bs4 import BeautifulSoup

# === Selenium ===
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

# Optional: webdriver-manager
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
    nav_timeout: int = 45
    action_timeout: int = 20
    wait_between_actions: float = 0.6
    max_snippets: int = 10
    max_tokens_prompt: int = 60_000
    confirm_before_submit: bool = False
    default_name: Optional[str] = None
    default_email: Optional[str] = None
    default_website: Optional[str] = None
    retries_on_nav: int = 2


# -------------------------
# Main Class
# -------------------------
class Commenter:
    """
    DOM-first approach with robust headless navigation and graceful exits.
    """

    # Multilingual keywords (incl. Norwegian)
    KEYWORDS = [
        "reply", "replies", "comment", "comments", "add comment", "post comment",
        "write a comment", "leave a comment", "leave a reply", "discussion", "respond", "submit",
        "message", "post", "send", "publish",
        "댓글", "답글", "코멘트", "댓글쓰기", "댓글 달기", "의견", "등록", "보내기", "작성",
        "返信", "コメント", "書き込み", "送信", "投稿",
        "回复", "评论", "发表评论", "提交", "发布",
        "responder", "respuesta", "comentar", "comentarios", "publicar comentario", "enviar",
        "répondre", "réponse", "commentaire", "commentaires", "publier un commentaire", "envoyer",
        "antworten", "antwort", "kommentar", "kommentare", "kommentieren", "absenden", "senden",
        "rispondi", "risposta", "commento", "commenti", "invia", "pubblica",
        "responder", "resposta", "comentário", "comentários",
        "ответить", "ответ", "комментарий", "комментарии", "отправить",
        "yanıtla", "yanıt", "yorum", "yorum yap", "gönder",
        "trả lời", "bình luận", "đăng bình luận", "gửi",
        "balas", "komentar", "kirim komentar",
        "ตอบกลับ", "แสดงความคิดเห็น", "ส่ง",
        # Nordic (Norwegian etc.)
        "svar", "kommentar", "kommentarer", "kommenter", "kommentere", "skriv kommentar",
        "legg igjen en kommentar", "send", "send inn", "publiser", "send inn kommentar",
        # Field labels
        "navn", "name"
    ]

    # Only used if we found no comment UI at all:
    LOGIN_KEYWORDS = [
        "you must be logged in", "log in to comment", "logged in to comment",
        "logg inn", "innlogging", "pålogging", "du må være logget inn", "logg inn for å kommentere",
        "login", "sign in", "signin", "account", "password",
        "로그인", "비밀번호", "anmelden", "connexion", "accedi", "entrar", "iniciar sesión", "войти"
    ]

    CLOSED_COMMENTS = [
        "comments are closed", "commenting is closed",
        "kommentarer er stengt", "kommentarer lukket", "kommentarfeltet er stengt",
        "댓글이 닫혔습니다", "no comments allowed", "commenting has been closed"
    ]

    # WordPress hints
    WP_TEXTAREA_IDS = ["comment"]
    WP_AUTHOR_IDS = ["author"]
    WP_EMAIL_IDS  = ["email"]
    WP_SUBMIT_IDS = ["submit", "comment-submit"]

    # Realistic desktop UA
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
        opts.set_capability("pageLoadStrategy", "eager")

        if self.cfg.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--window-size={},{}".format(*self.cfg.window_size))
        opts.add_argument(f"--lang={self.ACCEPT_LANG.split(',')[0]}")
        opts.add_argument(f"--user-agent={self.DESKTOP_UA}")

        chrome_bin = self._find_chrome_binary()
        if chrome_bin:
            opts.binary_location = chrome_bin
        else:
            raise RuntimeError(
                "Chrome/Chromium binary not found. Install google-chrome-stable (amd64) "
                or "snap chromium (arm64)."
            )

        if _HAVE_WDM:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=opts)
        else:
            driver = webdriver.Chrome(options=opts)

        driver.set_page_load_timeout(self.cfg.nav_timeout)

        # CDP tweaks
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
        ok, status = self._safe_get(url)
        if not ok:
            return {"ok": False, "submitted": False, "url": url,
                    "reason": f"Navigation failed: {status}", "error_type": "navigation_error"}

        # lazy loaders
        self._scroll_to_bottom_and_wait()
        self._dismiss_cookie_banners()

        # Try main doc first, then iframes
        context_info = self._gather_candidates_all_contexts()

        if not context_info["candidates"]:
            html = self.driver.execute_script("return document.documentElement.outerHTML;") or ""
            pretty_html = self._prettify_html(html)
            down_reason = self._maybe_error_page(pretty_html)
            if down_reason:
                return {"ok": False, "submitted": False, "url": url,
                        "reason": f"Site error or down: {down_reason}", "error_type": "site_down"}
            if self._comments_closed(pretty_html):
                return {"ok": False, "submitted": False, "url": url,
                        "reason": "Comments are closed on this page.", "error_type": "comments_closed"}
            if self._login_required(pretty_html):
                return {"ok": False, "submitted": False, "url": url,
                        "reason": "Login required to comment on this page.", "error_type": "login_required"}
            return {"ok": False, "submitted": False, "url": url,
                    "reason": "No candidate elements found for comments/replies.",
                    "error_type": "no_comment_ui"}

        # Build LLM prompt (optional) - not critical anymore
        html = self.driver.execute_script("return document.documentElement.outerHTML;") or ""
        pretty_html = self._prettify_html(html)
        snippets = self._build_snippets_for_llm(context_info["candidates"], pretty_html)
        prompt_chunks = self._budget_snippets(snippets, self.cfg.max_tokens_prompt)

        plan = self._ask_llm_for_plan(url, prompt_chunks, comment_text)

        # Heuristic fallback using FORM context
        if not plan.get("actions"):
            plan = self._build_form_aware_fallback(context_info["candidates"])

        if not plan.get("actions"):
            return {"ok": False, "submitted": False, "url": url,
                    "reason": "No actionable plan (LLM + fallback heuristics failed).",
                    "error_type": "no_llm_plan", "plan": plan}

        # If plan requires switching into an iframe, switch now
        if context_info["frame"] is not None:
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(context_info["frame"])
            except Exception:
                pass

        result = self._execute_plan(plan, comment_text)
        result["url"] = url
        result["plan"] = plan
        return result

    # -------------------------
    # Navigation helpers
    # -------------------------
    def _safe_get(self, url: str) -> Tuple[bool, str]:
        for attempt in range(1, self.cfg.retries_on_nav + 2):
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                return True, "ok"
            except TimeoutException:
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

    def _scroll_to_bottom_and_wait(self, max_steps: int = 5):
        try:
            for _ in range(max_steps):
                old_h = self.driver.execute_script("return document.body.scrollHeight")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(0.8)
                new_h = self.driver.execute_script("return document.body.scrollHeight")
                if new_h == old_h:
                    break
        except Exception:
            pass

    def _maybe_error_page(self, html: str) -> Optional[str]:
        low = html.lower()
        hints = [
            "this site can’t be reached", "this site can't be reached",
            "err_connection_timed_out", "err_name_not_resolved", "err_ssl",
            "proxy error", "502 bad gateway", "504 gateway timeout",
            "service unavailable", "access denied"
        ]
        return next((h for h in hints if h in low), None)

    # -------------------------
    # Candidate gathering across contexts
    # -------------------------
    def _gather_candidates_all_contexts(self) -> Dict[str, Any]:
        """
        Search in the main document first; if no comment field is found,
        probe each iframe. Return {'frame': WebElement or None, 'candidates': [...] }.
        """
        self.driver.switch_to.default_content()
        cand_main = self._find_candidates_in_current_context()
        if self._has_comment_field(cand_main):
            return {"frame": None, "candidates": cand_main}

        # probe iframes
        try:
            frames = self.driver.find_elements(By.TAG_NAME, "iframe")
        except Exception:
            frames = []

        for f in frames:
            try:
                self.driver.switch_to.default_content()
                self.driver.switch_to.frame(f)
                cand_iframe = self._find_candidates_in_current_context()
                if self._has_comment_field(cand_iframe):
                    return {"frame": f, "candidates": cand_iframe}
            except Exception:
                continue

        # nothing better; return main context results (could be triggers/buttons only)
        self.driver.switch_to.default_content()
        return {"frame": None, "candidates": cand_main}

    def _has_comment_field(self, candidates: List[Dict[str, Any]]) -> bool:
        return any(c["role"] in ("textarea_wp", "textarea", "rich_editor") for c in candidates)

    # -------------------------
    # Helpers: DOM & candidates (single context)
    # -------------------------
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

    def _prettify_html(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "lxml")
            return soup.prettify()
        except Exception:
            return html

    def _find_candidates_in_current_context(self) -> List[Dict[str, Any]]:
        drv = self.driver
        candidates: List[Dict[str, Any]] = []

        # 0) Label → control mapping (for Name / Comment)
        try:
            labels = drv.find_elements(By.TAG_NAME, "label")
            for lb in labels:
                ltxt = (lb.text or "").strip().lower()
                if not ltxt:
                    continue
                # linked via 'for'
                for_id = lb.get_attribute("for") or ""
                target = None
                if for_id:
                    try:
                        target = drv.find_element(By.ID, for_id)
                    except Exception:
                        target = None
                if not target:
                    # closest following control
                    try:
                        target = lb.find_element(By.XPATH, "following::*[(self::input or self::textarea or @contenteditable='true')][1]")
                    except Exception:
                        target = None
                if target and target.is_displayed():
                    if any(k in ltxt for k in ["navn", "name"]):
                        candidates.append(self._pack_candidate(target, role="nameinput"))
                    if any(k in ltxt for k in ["kommenter", "kommentere", "kommentar"]):
                        role = "rich_editor" if (target.get_attribute("contenteditable") == "true" or target.get_attribute("role") == "textbox") else "textarea"
                        candidates.append(self._pack_candidate(target, role=role))
        except Exception:
            pass

        # 1) Visible textareas
        try:
            for ta in drv.find_elements(By.TAG_NAME, "textarea"):
                if ta.is_displayed():
                    candidates.append(self._pack_candidate(ta, role="textarea"))
        except Exception:
            pass

        # 2) Contenteditable editors / role=textbox
        try:
            editors = drv.find_elements(By.XPATH, "//*[@contenteditable='true' or @role='textbox']")
            for ed in editors:
                if ed.is_displayed():
                    candidates.append(self._pack_candidate(ed, role="rich_editor"))
        except Exception:
            pass

        # 3) Buttons/links likely to submit/reply
        try:
            elems = drv.find_elements(By.XPATH, "//button | //a | //input[@type='submit' or @type='button'] | //div[@role='button']")
            for e in elems:
                if not e.is_displayed():
                    continue
                label = (e.text or "").strip()
                label_full = " ".join([
                    label.lower(),
                    (e.get_attribute("value") or "").lower(),
                    (e.get_attribute("aria-label") or "").lower(),
                    (e.get_attribute("title") or "").lower(),
                    (e.get_attribute("type") or "").lower(),
                ])
                if any(k in label_full for k in self._lower_keywords()):
                    role = "submit" if any(x in label_full for x in ["send", "post", "publiser", "submit"]) else "trigger"
                    candidates.append(self._pack_candidate(e, role=role))
                else:
                    # if it's an actual submit without text, still include
                    typ = (e.get_attribute("type") or "").lower()
                    if typ == "submit":
                        candidates.append(self._pack_candidate(e, role="submit"))
        except Exception:
            pass

        # 4) WordPress-known IDs
        for wid in self.WP_TEXTAREA_IDS:
            try:
                e = drv.find_element(By.ID, wid)
                if e.is_displayed():
                    candidates.append(self._pack_candidate(e, role="textarea_wp"))
            except Exception:
                pass
        for wid in self.WP_SUBMIT_IDS:
            try:
                e = drv.find_element(By.ID, wid)
                if e.is_displayed():
                    candidates.append(self._pack_candidate(e, role="submit_wp"))
            except Exception:
                pass

        # Deduplicate by selector
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
            "form_selector": self._closest_form_selector(element) or "",
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

    def _closest_form_selector(self, el) -> str:
        try:
            return self.driver.execute_script("""
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
                var f = arguments[0].closest("form");
                return f ? cssPath(f) : "";
            """, el) or ""
        except Exception:
            return ""

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
        role_order = {"textarea_wp": 0, "submit_wp": 1, "textarea": 2, "rich_editor": 2, "submit": 3, "trigger": 4, "nameinput": 5}
        snippets.sort(key=lambda s: role_order.get(s["role"], 99))
        return snippets[: self.cfg.max_snippets]

    def _budget_snippets(self, snippets: List[Dict[str, Any]], max_tokens: int) -> List[Dict[str, Any]]:
        payload = json.dumps(snippets, ensure_ascii=False)
        if count_tokens(payload) <= max_tokens:
            return snippets
        prioritized = [s for s in snippets if s["role"] in ("textarea_wp", "submit_wp", "textarea", "rich_editor", "submit", "trigger")]
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
    # LLM planning (optional)
    # -------------------------
    def _ask_llm_for_plan(self, url: str, snippets: List[Dict[str, Any]], comment_text: str) -> Dict[str, Any]:
        sys = (
            "You are a reliable web-comment agent.\n"
            "Return ONLY minified JSON with keys: {\"actions\":[{"
            "\"type\":\"click|type|submit_click|submit_js\",\"how\":\"css|xpath\","
            "\"selector\":\"...\",\"field_kind\":\"comment|name|email|website|other\"?}]}\n"
            "If you cannot act, return {\"actions\":[]} with no extra text."
        )
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
                        {"role": "user", "content": "Plan minimal steps to post a comment using only provided selectors."},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}
                    ],
                )
                txt = self._extract_text(resp)
                data = self._coerce_json(txt)
                if isinstance(data, dict) and "actions" in data:
                    data["_model_used"] = model
                    return data
            except Exception as e:
                print(f"[WARN] LLM planning failed on model={model}: {e}")
                continue
        return {"actions": []}

    def _extract_text(self, resp) -> str:
        try:
            if getattr(resp, "output_text", None):
                return resp.output_text
        except Exception:
            pass
        try:
            return resp.output[0].content[0].text
        except Exception:
            return ""

    def _coerce_json(self, s: str) -> Dict[str, Any]:
        if not s:
            return {"actions": []}
        s = s.strip()
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?", "", s).strip()
            s = re.sub(r"```$", "", s).strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return {"actions": []}

    # -------------------------
    # Form-aware fallback plan
    # -------------------------
    def _build_form_aware_fallback(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Pick the best comment field
        fields = [c for c in candidates if c["role"] in ("textarea_wp", "textarea", "rich_editor")]
        if not fields:
            return {"actions": []}
        field = fields[0]

        actions = []

        # If a name input exists & default provided, fill it (prefer same form)
        nameins = [c for c in candidates if c["role"] == "nameinput"]
        if nameins and self.cfg.default_name:
            nm = self._prefer_same_form(nameins, field)
            actions.append({"type": "type", "how": nm["how"], "selector": nm["selector"], "field_kind": "name"})

        # Type into the comment field
        actions.append({"type": "type", "how": field["how"], "selector": field["selector"], "field_kind": "comment"})

        # Submit: prefer a submit button inside the same form
        submit = self._find_submit_in_same_form(field)
        if submit is not None:
            actions.append({"type": "submit_click", "how": submit["how"], "selector": submit["selector"]})
        else:
            # No visible submit -> JS submit on the form itself
            form_sel = field["extra"].get("form_selector") or ""
            if form_sel:
                actions.append({"type": "submit_js", "how": "css", "selector": form_sel})
            else:
                # last resort: click the first 'submit' we saw anywhere
                any_submit = next((c for c in candidates if c["role"] in ("submit_wp", "submit")), None)
                if any_submit:
                    actions.append({"type": "submit_click", "how": any_submit["how"], "selector": any_submit["selector"]})

        return {"actions": actions}

    def _prefer_same_form(self, items: List[Dict[str, Any]], anchor: Dict[str, Any]) -> Dict[str, Any]:
        a_form = anchor["extra"].get("form_selector") or ""
        if not a_form:
            return items[0]
        for it in items:
            if it["extra"].get("form_selector") == a_form:
                return it
        return items[0]

    def _find_submit_in_same_form(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        form_sel = field["extra"].get("form_selector") or ""
        if not form_sel:
            return None
        try:
            form = self._wait_for_element("css", form_sel, 5)
            if not form:
                return None
            # Look for submit-like elements within this form
            possibles = form.find_elements(By.XPATH, ".//button | .//input[@type='submit' or @type='button'] | .//*[@role='button']")
            for e in possibles:
                if not e.is_displayed():
                    continue
                label = (e.text or "").strip().lower()
                value = (e.get_attribute("value") or "").lower()
                aria  = (e.get_attribute("aria-label") or "").lower()
                typ   = (e.get_attribute("type") or "").lower()
                blob = " ".join([label, value, aria, typ])
                if "submit" in typ or any(k in blob for k in ["send", "post", "publiser", "submit"]):
                    return self._pack_candidate(e, role="submit")
        except Exception:
            return None
        return None

    # -------------------------
    # Execute plan
    # -------------------------
    def _execute_plan(self, plan: Dict[str, Any], comment_text: str) -> Dict[str, Any]:
        actions = plan.get("actions", [])
        logs = []
        try:
            self._fill_wordpress_identity_if_present()

            for step in actions:
                t = step["type"]
                sel = step["selector"]
                how = step["how"]
                logs.append(f"Step: {t} via {how} -> {sel}")

                el = None if t == "submit_js" else self._wait_for_element(how, sel, self.cfg.action_timeout)
                if t != "submit_js" and not el:
                    return {"ok": False, "submitted": False, "reason": f"Element not found: {how}:{sel}", "logs": logs}

                if el:
                    self._scroll_into_view(el)

                if t == "click":
                    self._safe_click(el)
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
                elif t == "submit_click":
                    if self.cfg.confirm_before_submit:
                        logs.append("Dry-run: submit skipped")
                        return {"ok": True, "submitted": False, "logs": logs}
                    self._safe_click(el)
                elif t == "submit_js":
                    if self.cfg.confirm_before_submit:
                        logs.append("Dry-run: JS submit skipped")
                        return {"ok": True, "submitted": False, "logs": logs}
                    form = self._wait_for_element(how, sel, self.cfg.action_timeout)
                    if not form:
                        return {"ok": False, "submitted": False, "reason": f"Form not found for JS submit: {sel}", "logs": logs}
                    try:
                        self.driver.execute_script("arguments[0].submit();", form)
                    except Exception as e:
                        return {"ok": False, "submitted": False, "reason": f"JS submit failed: {e}", "logs": logs}
                else:
                    logs.append(f"Unknown step type: {t}")

                time.sleep(self.cfg.wait_between_actions)

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
        for fid in self.WP_AUTHOR_IDS:
            try:
                e = self.driver.find_element(By.ID, fid)
                if e.is_displayed() and self.cfg.default_name:
                    self._scroll_into_view(e)
                    try: e.clear()
                    except: pass
                    e.send_keys(self.cfg.default_name)
            except Exception:
                pass
        for fid in self.WP_EMAIL_IDS:
            try:
                e = self.driver.find_element(By.ID, fid)
                if e.is_displayed() and self.cfg.default_email:
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
    # Soft checks (only when no UI found)
    # -------------------------
    def _login_required(self, html: str) -> bool:
        low = html.lower()
        if "type=\"password\"" in low or "type='password'" in low:
            return True
        return any(kw in low for kw in self.LOGIN_KEYWORDS)

    def _comments_closed(self, html: str) -> bool:
        low = html.lower()
        return any(kw in low for kw in self.CLOSED_COMMENTS)

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
