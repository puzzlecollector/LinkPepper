# backend/core/middleware.py
from __future__ import annotations
from typing import Optional
from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from .models import WalletUser

SUPPORTED_LANGS = {"en", "ko", "ja"}

# Unprefixed pages that should be redirected to /ko/... or /ja/... if the detected lang isn't 'en'
UNPREFIXED_REDIRECT_TABLE = {
    "/": "/{lang}/",
    "/rewards/": "/{lang}/rewards/",
    "/events/": "/{lang}/events/",
    "/leaderboard/": "/{lang}/leaderboard/",
}

def _normalize_lang(val: Optional[str]) -> str:
    if not val:
        return "en"
    v = val.strip().lower()
    if v in SUPPORTED_LANGS:
        return v
    if v.startswith("ko"):
        return "ko"
    if v.startswith("ja"):
        return "ja"
    return "en"

def _country_to_lang(country: Optional[str]) -> str:
    c = (country or "").strip().upper()
    if c in {"KR", "KP"}:
        return "ko"
    if c == "JP":
        return "ja"
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
    Sets request.lang and (optionally) redirects unprefixed routes to /ko/ or /ja/
    based on this order:

    1) URL prefix (/ko/, /ja/) → set & persist session
    2) ?lang=ko|ja|en (explicit) → set & persist session
    3) session['lang']
    4) Country headers (CF-IPCountry, etc.) → set & persist (first hit)
    5) DEV helpers (only when DEBUG True)
       - ?dev_lang=ko|ja|en
       - localhost fallback: if TIME_ZONE looks Korean/Japanese, prefer ko/ja
    6) Accept-Language (best-effort)
    7) default 'en'

    Additionally:
    - For unprefixed paths ("/", "/rewards/", "/events/", "/leaderboard/"):
      if detected lang in {'ko','ja'}, we redirect to the prefixed path.
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
                            if "seoul" in tz or "korea" in tz:
                                lang = "ko"
                            elif "tokyo" in tz or "japan" in tz:
                                lang = "ja"
                    # 6) Accept-Language final fallback
                    if not lang:
                        accept = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
                        lang = _normalize_lang(accept.split(",")[0] if accept else "")
                session["lang"] = lang
            request.lang = _normalize_lang(lang)

        # 7) Redirect unprefixed paths to locale-prefixed variant when lang is ko/ja
        if request.lang in {"ko", "ja"}:
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
