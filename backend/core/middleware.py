# backend/core/middleware.py
from __future__ import annotations
from typing import Optional
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect

from .models import WalletUser

SUPPORTED_LANGS = {"en", "ko", "ja", "zh"}

# Unprefixed pages that are locale-redirected to /ko/... /ja/... /zh/ when detected
UNPREFIXED_REDIRECT_TABLE = {
    "/": "/{lang}/",
    "/rewards/": "/{lang}/rewards/",
    "/events/": "/{lang}/events/",
    "/leaderboard/": "/{lang}/leaderboard/",
}

def _normalize_lang(val: Optional[str]) -> str:
    """
    Accept values like 'ko', 'ko-KR', 'ja', 'ja-JP', 'zh', 'zh-CN', 'zh-Hans'
    and map to 'en' | 'ko' | 'ja' | 'zh'.
    """
    if not val:
        return "en"
    v = val.strip().lower()
    if v in SUPPORTED_LANGS:
        return v
    if v.startswith("ko"):
        return "ko"
    if v.startswith("ja"):
        return "ja"
    if v.startswith("zh"):
        return "zh"
    return "en"

def _country_to_lang(country: Optional[str]) -> str:
    """
    Very light country->language map.
    - KR/KP => ko
    - JP    => ja
    - CN/SG => zh (Simplified Chinese default for now)
    """
    c = (country or "").strip().upper()
    if c in {"KR", "KP"}:
        return "ko"
    if c == "JP":
        return "ja"
    if c in {"CN", "SG"}:
        return "zh"
    return "en"

def _detect_country_from_headers(request: HttpRequest) -> Optional[str]:
    meta = request.META or {}
    return (
        meta.get("HTTP_CF_IPCOUNTRY") or
        meta.get("HTTP_X_COUNTRY") or
        meta.get("HTTP_X_COUNTRY_CODE") or
        meta.get("GEOIP_COUNTRY_CODE") or
        None
    )

def _is_localhost(request: HttpRequest) -> bool:
    host = (request.get_host() or "").split(":")[0]
    ip = request.META.get("REMOTE_ADDR", "")
    return host in {"localhost", "127.0.0.1"} or ip in {"127.0.0.1", "::1"}

class LanguageRoutingMiddleware:
    """
    Sets request.lang and (optionally) redirects unprefixed routes to /ko/, /ja/, or /zh/
    based on this order:

    1) URL prefix (/ko/, /ja/, /zh/) → set & persist session
    2) ?lang=ko|ja|zh|en (explicit) → set & persist session
    3) session['lang']
    4) Country headers (CF-IPCountry, etc.) → set & persist (first hit)
    5) DEV helpers (when DEBUG True)
       - ?dev_lang=ko|ja|zh|en
       - localhost fallback: TIME_ZONE hints
    6) Accept-Language (best-effort)
    7) default 'en'

    Additionally:
    - For unprefixed paths ("/", "/rewards/", "/events/", "/leaderboard/"):
      if detected lang in {'ko','ja','zh'}, we redirect to the prefixed path.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        path = request.path or ""
        session = request.session

        # 1) explicit language from URL prefix wins
        if path.startswith("/ko/") or path == "/ko/":
            session["lang"] = "ko"
            request.lang = "ko"
            return self.get_response(request)

        if path.startswith("/ja/") or path == "/ja/":
            session["lang"] = "ja"
            request.lang = "ja"
            return self.get_response(request)

        if path.startswith("/zh/") or path == "/zh/":
            session["lang"] = "zh"
            request.lang = "zh"
            return self.get_response(request)

        # 2) explicit query override ?lang=
        qlang = request.GET.get("lang")
        if qlang:
            lang = _normalize_lang(qlang)
            session["lang"] = lang
            request.lang = lang
            # After setting, allow redirect logic below to run for unprefixed paths
        else:
            # 3) session sticky
            lang = session.get("lang")
            if not lang:
                # 4) Country headers
                country = _detect_country_from_headers(request)
                if country:
                    lang = _country_to_lang(country)
                else:
                    # 5) DEV helpers (only when DEBUG and localhost)
                    if settings.DEBUG:
                        dev_lang = request.GET.get("dev_lang")
                        if dev_lang:
                            lang = _normalize_lang(dev_lang)
                        elif _is_localhost(request):
                            # Fallback to TIME_ZONE hint for localhost w/o headers
                            tz = (getattr(settings, "TIME_ZONE", "") or "").lower()
                            if any(x in tz for x in ["seoul", "korea"]):
                                lang = "ko"
                            elif any(x in tz for x in ["tokyo", "japan"]):
                                lang = "ja"
                            elif any(x in tz for x in ["shanghai", "beijing", "hong_kong", "hong-kong", "china"]):
                                lang = "zh"
                    # 6) Accept-Language final fallback
                    if not lang:
                        accept = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
                        first = accept.split(",")[0] if accept else ""
                        lang = _normalize_lang(first)
                session["lang"] = lang
            request.lang = _normalize_lang(lang)

        # 7) Redirect unprefixed paths to locale-prefixed variant when lang is ko/ja/zh
        if request.lang in {"ko", "ja", "zh"}:
            target_tpl = UNPREFIXED_REDIRECT_TABLE.get(path)
            if target_tpl:
                return redirect(target_tpl.format(lang=request.lang))

        return self.get_response(request)


class WalletAuthMiddleware:
    """
    Puts `request.wallet_user` on every request based on session.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.wallet_user = None
        uid = request.session.get("wallet_user_id")
        if uid:
            try:
                request.wallet_user = WalletUser.objects.get(id=uid)
            except WalletUser.DoesNotExist:
                request.session.pop("wallet_user_id", None)
        return self.get_response(request)


MOBILE_HOST = "m.link-hash.com"
WWW_HOSTES = {"link-hash.com", "www.link-hash.com"}

class MobileHostRedirectMiddleware:
    """
    If user is on www.* and detected/ preferred view is mobile,
    move them to the m.* host. Respect explicit desktop choice.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = (request.get_host() or "").split(":")[0].lower()

        # Respect explicit override to desktop
        view = (request.GET.get("view") or "").lower()
        cookie_pref = (request.COOKIES.get("pref_view") or "").lower()
        forced_desktop = view in {"desktop", "d"} or cookie_pref in {"desktop", "d"}

        if host in WWW_HOSTES and not forced_desktop:
            # Reuse your view helpers by importing them
            from core.views import _should_use_mobile
            if _should_use_mobile(request):  # mobile preferred
                target = f"https://{MOBILE_HOST}{request.get_full_path()}"
                return HttpResponseRedirect(target)

        return self.get_response(request)