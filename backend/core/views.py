# backend/core/views.py
import json
import secrets
from types import SimpleNamespace
from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Count, Sum, Q, Max
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import ensure_csrf_cookie
from eth_account.messages import encode_defunct
from eth_account import Account
from django.template.loader import select_template

from django.conf import settings  # <-- add this

# Defaults for “How to use” guide links (can be overridden in settings.py)
GUIDE_DEFAULTS = {
    "instagram": "https://www.instagram.com/link.hash?igsh=cG0wN2xiODQ2bTh1",
    "twitter":   "https://x.com",
}

# IMPORTANT: import models from the rewards app
from .models import (
    WalletUser,
    CampaignApplication,
    Campaign,
    Submission,
    Payout,
    TaskType,
    SubmissionStatus,
    Network,
    Event
)

# ---------- helpers ----------
# ---------- helpers ----------
# ---------- helpers ----------
def _base_url(request):
    return f"{request.scheme}://{request.get_host()}"

def _is_mobile_host(request) -> bool:
    host = (request.get_host() or "").lower()
    return host.startswith("m.")  # m.link-hash.com => mobile

def _ua_is_mobile(request) -> bool:
    """
    Light UA sniff: catches iOS/Android phones.
    Desktop-site toggles change UA, so this is only a fallback.
    """
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    mobile_hits = ("iphone", "ipod", "android", "mobile", "windows phone")
    return any(k in ua for k in mobile_hits)

def _pref_from_cookie(request):
    v = (request.COOKIES.get("pref_view") or "").lower()
    if v in ("mobile", "m"):
        return True
    if v in ("desktop", "d"):
        return False
    return None

def _query_overrides_mobile(request) -> bool | None:
    """
    Returns True/False when URL explicitly requests a view, else None.
      - ?view=mobile / ?view=desktop
      - ?m=1 / ?m=0
    """
    q = request.GET
    view = (q.get("view") or "").strip().lower()
    if view in ("mobile", "m"):
        return True
    if view in ("desktop", "d"):
        return False
    mflag = q.get("m")
    if mflag == "1":
        return True
    if mflag == "0":
        return False
    return None

def _should_use_mobile(request) -> bool:
    # 1) explicit URL override wins
    override = _query_overrides_mobile(request)
    if override is not None:
        return override

    # 2) m.* host forces mobile
    if _is_mobile_host(request):
        return True

    # 3) persisted cookie preference
    pref = _pref_from_cookie(request)
    if pref is not None:
        return pref

    # 4) fallback UA sniff
    return _ua_is_mobile(request)


def render_mobile_first(request, base_template_name: str, context: dict):
    """
    Try {base}_mobile.html first when mobile is preferred, then fallback.
    Also persists explicit choice into a cookie when present, and sets Vary
    so caches don’t mix variants.

    Additionally: injects guide URLs into meta so all templates can read
    meta.instagram_guide_url and meta.twitter_guide_url.
    """
    # --- Inject guide URLs into meta (with settings overrides) ---
    ctx = dict(context or {})
    meta = dict(ctx.get("meta") or {})

    ig_url = getattr(settings, "INSTAGRAM_GUIDE_URL", GUIDE_DEFAULTS["instagram"])
    tw_url = getattr(settings, "TWITTER_GUIDE_URL",   GUIDE_DEFAULTS["twitter"])
    # Don’t clobber if already set explicitly upstream
    meta.setdefault("instagram_guide_url", ig_url)
    meta.setdefault("twitter_guide_url",   tw_url)
    ctx["meta"] = meta

    # --- Choose template (mobile-first) ---
    template_candidates = []
    use_mobile = _should_use_mobile(request)
    if use_mobile:
        template_candidates.append(f"{base_template_name}_mobile.html")
    template_candidates.append(f"{base_template_name}.html")

    t = select_template(template_candidates)
    resp = render(request, t.template.name, ctx)

    # Persist explicit choice to a cookie (so it sticks across pages)
    override = _query_overrides_mobile(request)
    if override is not None:
        resp.set_cookie(
            "pref_view",
            "mobile" if override else "desktop",
            max_age=60 * 60 * 24 * 365,  # 1 year
            samesite="Lax",
        )

    # Avoid cache/proxy mixing of variants
    vary = resp.get("Vary")
    resp["Vary"] = (vary + ", " if vary else "") + "Cookie, User-Agent, Host, Accept-Language"
    return resp


def _normalize_evm_address(addr: str | None) -> str | None:
    """
    Normalize EVM address (we'll store lowercase consistently to match your current DB scheme).
    """
    if not addr:
        return None
    a = addr.strip()
    if a.startswith("0x") and len(a) == 42:
        return a.lower()
    return None

def _login_message(nonce: str) -> str:
    """
    Canonical message users sign in MetaMask.
    Keeping this fixed guarantees verify() is deterministic and prevents phishing.
    """
    return f"LinkHash login\n\nNonce: {nonce}\n\nThis signature proves you control this wallet."


def get_wallet_user(request):
    wu = getattr(request, "wallet_user", None)
    if wu:
        return wu
    uid = request.session.get("wallet_user_id")
    if not uid:
        return None
    return WalletUser.objects.filter(id=uid).first()

def _lang_from_request(request) -> str:
    lang = getattr(request, "lang", None)
    if lang in {"en", "ko", "ja", "zh"}:
        return lang
    p = request.path or ""
    if p.startswith("/ko/"):
        return "ko"
    if p.startswith("/ja/"):
        return "ja"
    if p.startswith("/zh/"):
        return "zh"
    return "en"


# ---------- META builders ----------
def _meta_for(lang, request, *, page="home"):
    base = _base_url(request)

    if page == "rewards":
        if lang == "ko":
            return {
                "lang": "ko",
                "title": "LinkHash | 리워드 프로그램",
                "description": "백링크 & SEO 캠페인에 참여하고 리워드를 받아가세요.",
                "og_title": "LinkHash 리워드",
                "og_description": "링크 공유/방문 과제 참여하고 USDT 보상을 받으세요.",
                "canonical": f"{base}/ko/rewards/",
                "url": f"{base}/ko/rewards/",
            }
        if lang == "ja":
            return {
                "lang": "ja",
                "title": "LinkHash | リワードプログラム",
                "description": "被リンクとSEOキャンペーンに参加して報酬を獲得。",
                "og_title": "LinkHash リワード",
                "og_description": "リンク共有・訪問タスクでUSDTを獲得。",
                "canonical": f"{base}/ja/rewards/",
                "url": f"{base}/ja/rewards/",
            }
        if lang == "zh":
            return {
                "lang": "zh",
                "title": "LinkHash | 奖励计划",
                "description": "参与外链与SEO活动，领取奖励。",
                "og_title": "LinkHash 奖励",
                "og_description": "完成分享/访问任务，获得USDT奖励。",
                "canonical": f"{base}/zh/rewards/",
                "url": f"{base}/zh/rewards/",
            }
        return {
            "lang": "en",
            "title": "LinkHash | Rewards Program",
            "description": "Join our backlink & SEO campaigns and earn rewards.",
            "og_title": "LinkHash Rewards",
            "og_description": "Complete link share/visit tasks and earn USDT.",
            "canonical": f"{base}/rewards/",
            "url": f"{base}/rewards/",
        }

    if lang == "ko":
        return {
            "lang": "ko",
            "title": "LinkHash | 백링크 · SEO · 페이지 상위",
            "description": "데이터 기반 백링크 & SEO. 백링크, SEO, 페이지 상위 노출을 위한 화이트햇 전략과 투명 리포트.",
            "og_title": "LinkHash | 백링크 · SEO · 페이지 상위",
            "og_description": "데이터 기반 백링크 & SEO. 화이트햇 전략으로 안전하게 순위를 올리세요.",
            "canonical": f"{base}/ko/",
            "url": f"{base}/ko/",
        }
    if lang == "ja":
        return {
            "lang": "ja",
            "title": "LinkHash | 被リンク・SEO・順位向上",
            "description": "データドリブンな被リンクとSEO。ホワイトハット戦略と透明なレポートで安全に順位アップ。",
            "og_title": "LinkHash | 被リンク・SEO・順位向上",
            "og_description": "ホワイトハットで安全にランキングを向上。",
            "canonical": f"{base}/ja/",
            "url": f"{base}/ja/",
        }
    if lang == "zh":
        return {
            "lang": "zh",
            "title": "LinkHash | 外链 · SEO · 排名提升",
            "description": "数据驱动的外链与SEO。白帽策略与透明报告，安全提升排名。",
            "og_title": "LinkHash | 外链 · SEO · 排名提升",
            "og_description": "采用白帽与数据策略，安全提升网站排名。",
            "canonical": f"{base}/zh/",
            "url": f"{base}/zh/",
        }
    return {
        "lang": "en",
        "title": "LinkHash | Backlinks · SEO · Rank Higher",
        "description": "Data-driven backlinks & SEO. White-hat strategy and transparent reporting to rank safely.",
        "og_title": "LinkHash | Backlinks · SEO · Rank Higher",
        "og_description": "Boost rankings safely with white-hat, data-driven link building.",
        "canonical": f"{base}/",
        "url": f"{base}/",
    }

def _meta_for_events(lang, request):
    m = _meta_for(lang, request).copy()
    if lang == "ko":
        m.update({
            "title": "LinkHash | 이벤트 · 공지",
            "og_title": "LinkHash | 이벤트 · 공지",
            "canonical": f"{_base_url(request)}/ko/events/",
            "url": f"{_base_url(request)}/ko/events/",
        })
    elif lang == "ja":
        m.update({
            "title": "LinkHash | イベント・お知らせ",
            "og_title": "LinkHash | イベント・お知らせ",
            "canonical": f"{_base_url(request)}/ja/events/",
            "url": f"{_base_url(request)}/ja/events/",
        })
    elif lang == "zh":
        m.update({
            "title": "LinkHash | 活动与公告",
            "og_title": "LinkHash | 活动与公告",
            "canonical": f"{_base_url(request)}/zh/events/",
            "url": f"{_base_url(request)}/zh/events/",
        })
    else:
        m.update({
            "title": "LinkHash | Events & Announcements",
            "og_title": "LinkHash | Events & Announcements",
            "canonical": f"{_base_url(request)}/events/",
            "url": f"{_base_url(request)}/events/",
        })
    return m

def _meta_for_leaderboard(lang, request):
    base = _base_url(request)
    if lang == "ko":
        return {
            "lang": "ko",
            "title": "LinkHash | 리더보드",
            "description": "캠페인 기여도 기준 상위 참여자 리더보드.",
            "og_title": "LinkHash | 리더보드",
            "og_description": "링크/방문 과제 및 점수를 기반으로 한 기여도 순위.",
            "canonical": f"{base}/ko/leaderboard/",
            "url": f"{base}/ko/leaderboard/",
        }
    if lang == "ja":
        return {
            "lang": "ja",
            "title": "LinkHash | リーダーボード",
            "description": "キャンペーン貢献度に基づく上位参加者ランキング。",
            "og_title": "LinkHash | リーダーボード",
            "og_description": "リンク/訪問タスクとスコアに基づく順位。",
            "canonical": f"{base}/ja/leaderboard/",
            "url": f"{base}/ja/leaderboard/",
        }
    if lang == "zh":
        return {
            "lang": "zh",
            "title": "LinkHash | 排行榜",
            "description": "按活动贡献度统计的参与者排行榜。",
            "og_title": "LinkHash | 排行榜",
            "og_description": "基于分享/访问任务与得分的排名。",
            "canonical": f"{base}/zh/leaderboard/",
            "url": f"{base}/zh/leaderboard/",
        }
    return {
        "lang": "en",
        "title": "LinkHash | Leaderboard",
        "description": "Top contributors ranked by campaign participation.",
        "og_title": "LinkHash | Leaderboard",
        "og_description": "Ranks based on link/visit tasks and scores.",
        "canonical": f"{base}/leaderboard/",
        "url": f"{base}/leaderboard/",
    }


# ================== PAGES ==================
@ensure_csrf_cookie
def home_en(request):
    lang = _lang_from_request(request)
    ctx = {
        "meta": _meta_for(lang, request),
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "home", ctx)

@ensure_csrf_cookie
def home_ko(request):
    ctx = {
        "meta": _meta_for("ko", request),
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "home", ctx)

@ensure_csrf_cookie
def home_ja(request):
    ctx = {
        "meta": _meta_for("ja", request),
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "home", ctx)

@ensure_csrf_cookie
def home_zh(request):
    ctx = {
        "meta": _meta_for("zh", request),
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "home", ctx)


# ---- Rewards listing (now sends real campaigns to template) ----
# ---- Rewards listing (now sends real campaigns to template) ----
def _published_campaigns():
    """
    All published campaigns (regardless of dates or pause state).
    Kept for admin/reuse, not used by rewards list directly.
    """
    return Campaign.objects.filter(is_published=True).order_by("-start", "-id")


def _live_campaigns():
    """
    Only campaigns that should appear on the LIVE tab in rewards.html:
    - published
    - not paused
    - within date window (start <= today <= end)
    """
    today = timezone.localdate()
    return (
        Campaign.objects.filter(
            is_published=True,
            is_paused=False,
            start__lte=today,
            end__gte=today,
        )
        .order_by("-start", "-id")
    )

def _past_campaigns():
    """
    PAST tab:
    - published
    - already ended (end < today)
    """
    today = timezone.localdate()
    return (
        Campaign.objects.filter(
            is_published=True,
            end__lt=today,
        )
        # most recently finished first
        .order_by("-end", "-start", "-id")
    )
def rewards_en(request):
    lang = _lang_from_request(request)
    ctx = {
        "meta": _meta_for(lang, request, page="rewards"),
        "lang": lang,
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "rewards", ctx)

def rewards_ko(request):
    ctx = {
        "meta": _meta_for("ko", request, page="rewards"),
        "lang": "ko",
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "rewards", ctx)

def rewards_ja(request):
    ctx = {
        "meta": _meta_for("ja", request, page="rewards"),
        "lang": "ja",
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "rewards", ctx)

def rewards_zh(request):
    ctx = {
        "meta": _meta_for("zh", request, page="rewards"),
        "lang": "zh",
        "wallet_user": get_wallet_user(request),
        "projects": _live_campaigns(),
        "past_projects": _past_campaigns(),
    }
    return render_mobile_first(request, "rewards", ctx)

# ---- Rewards apply (landing) ----
def rewards_apply_en(request):
    base = _base_url(request)
    lang = _lang_from_request(request)
    if lang == "ko":
        meta = {
            "lang": "ko",
            "title": "신청 | LinkHash 리워드",
            "description": "LinkHash 리워드 캠페인 신청 페이지.",
            "og_title": "신청 | LinkHash 리워드",
            "og_description": "캠페인 신청을 남겨 주세요. 24시간 내 회신합니다.",
            "canonical": f"{base}/rewards/apply/ko/",
            "url": f"{base}/rewards/apply/ko/",
        }
    elif lang == "ja":
        meta = {
            "lang": "ja",
            "title": "申請 | LinkHash リワード",
            "description": "LinkHashリワードキャンペーンの申請ページ。",
            "og_title": "申請 | LinkHash リワード",
            "og_description": "キャンペーン申請を送信してください。24時間以内にご連絡します。",
            "canonical": f"{base}/rewards/apply/ja/",
            "url": f"{base}/rewards/apply/ja/",
        }
    elif lang == "zh":
        meta = {
            "lang": "zh",
            "title": "申请 | LinkHash 奖励",
            "description": "申请发起 LinkHash 奖励活动。",
            "og_title": "申请 | LinkHash 奖励",
            "og_description": "提交你的活动申请，我们将在24小时内回复。",
            "canonical": f"{base}/rewards/apply/zh/",
            "url": f"{base}/rewards/apply/zh/",
        }
    else:
        meta = {
            "lang": "en",
            "title": "Apply | LinkHash Rewards",
            "description": "Apply to run a LinkHash reward campaign.",
            "og_title": "Apply | LinkHash Rewards",
            "og_description": "Submit your campaign request. We reply within 24h.",
            "canonical": f"{base}/rewards/apply/",
            "url": f"{base}/rewards/apply/",
        }
    ctx = {"meta": meta, "wallet_user": get_wallet_user(request)}
    return render_mobile_first(request, "rewards_apply", ctx)


def rewards_apply_ko(request):
    base = _base_url(request)
    meta = {
        "lang": "ko",
        "title": "신청 | LinkHash 리워드",
        "description": "LinkHash 리워드 캠페인 신청 페이지.",
        "og_title": "신청 | LinkHash 리워드",
        "og_description": "캠페인 신청을 남겨 주세요. 24시간 내 회신합니다.",
        "canonical": f"{base}/rewards/apply/ko/",
        "url": f"{base}/rewards/apply/ko/",
    }
    ctx = {"meta": meta, "wallet_user": get_wallet_user(request)}
    return render_mobile_first(request, "rewards_apply", ctx)

def rewards_apply_ja(request):
    base = _base_url(request)
    meta = {
        "lang": "ja",
        "title": "申請 | LinkHash リワード",
        "description": "LinkHashリワードキャンペーンの申請ページ。",
        "og_title": "申請 | LinkHash リワード",
        "og_description": "キャンペーン申請を送信してください。24時間以内にご連絡します。",
        "canonical": f"{base}/rewards/apply/ja/",
        "url": f"{base}/rewards/apply/ja/",
    }
    ctx = {"meta": meta, "wallet_user": get_wallet_user(request)}
    return render_mobile_first(request, "rewards_apply", ctx)

def rewards_apply_zh(request):
    base = _base_url(request)
    meta = {
        "lang": "zh",
        "title": "申请 | LinkHash 奖励",
        "description": "申请发起 LinkHash 奖励活动。",
        "og_title": "申请 | LinkHash 奖励",
        "og_description": "提交你的活动申请，我们将在24小时内回复。",
        "canonical": f"{base}/rewards/apply/zh/",
        "url": f"{base}/rewards/apply/zh/",
    }
    ctx = {"meta": meta, "wallet_user": get_wallet_user(request)}
    return render_mobile_first(request, "rewards_apply", ctx)

# ---- Client Application submit API ----
@require_POST
@csrf_exempt
def rewards_apply_submit(request):
    """
    Accepts form (multipart/x-www-form-urlencoded) or JSON.
    Creates CampaignApplication.
    """
    if request.content_type and "application/json" in request.content_type:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except Exception:
            return JsonResponse({"ok": False, "error": "bad json"}, status=400)
    else:
        data = request.POST

    email = (data.get("email") or "").strip()
    phone = (data.get("phone") or "").strip()
    if not email or not phone:
        return JsonResponse({"ok": False, "error": "email and phone required"}, status=400)
    

    # NEW: read & normalize currency + network
    currency = (data.get("currency") or "").strip() or None
    raw_net = (data.get("currency_network") or "").strip().upper()
    # Guard against invalid values; fallback to ETH
    valid_nets = {k for k, _ in Network.choices}
    currency_network = raw_net if raw_net in valid_nets else Network.ETH

    app = CampaignApplication.objects.create(
        email=email,
        phone=phone,
        country=(data.get("country") or "").strip(),
        campaign_title=(data.get("campaign_title") or "").strip(),
        website_url=(data.get("website_url") or "").strip(),
        website_description=(data.get("website_description") or "").strip(),
        wants_visit=bool(data.get("wants_visit")),
        wants_link=bool(data.get("wants_link")) if "wants_link" in data else True,
        visit_code=(data.get("visit_code") or "").strip(),
        expected_review_keywords=(data.get("expected_review_keywords") or "").strip(),
        current_seo_keywords=(data.get("current_seo_keywords") or "").strip(),
        reward_pool_usdt=(data.get("reward_pool_usdt") or None) or None,
        payout_per_task_usdt=(data.get("payout_per_task_usdt") or None) or None,
        currency=currency,
        currency_network=currency_network,
        start_date=(data.get("start_date") or None) or None,
        end_date=(data.get("end_date") or None) or None,
        airdrop_enabled=bool(data.get("airdrop_enabled")),
        airdrop_first_n=(data.get("airdrop_first_n") or None) or None,
        airdrop_amount_per_user=(data.get("airdrop_amount_per_user") or None) or None,
        airdrop_token_symbol=(data.get("airdrop_token_symbol") or "").strip(),
        airdrop_network=(data.get("airdrop_network") or "").strip(),
        airdrop_note=(data.get("airdrop_note") or "").strip(),
        thumbnail_url=(data.get("thumbnail_url") or "").strip(),
        favicon_url=(data.get("favicon_url") or "").strip(),
    )
    return JsonResponse({"ok": True, "application_id": str(app.id)})


# 2) helper: get events for a language, with fallback to EN, then any
def _events_for_lang(lang: str, limit: int = 40):
    qs_lang = Event.objects.filter(is_published=True, lang=lang).order_by("-posted_at", "-id")
    if qs_lang.exists():
        return list(qs_lang[:limit])

    # fallback to English
    qs_en = Event.objects.filter(is_published=True, lang="en").order_by("-posted_at", "-id")
    if qs_en.exists():
        return list(qs_en[:limit])

    # final fallback: any language
    return list(Event.objects.filter(is_published=True).order_by("-posted_at", "-id")[:limit])

# 3) update Events views to include real data
def events_en(request):
    lang = _lang_from_request(request)
    events = _events_for_lang(lang)
    ctx = {
        "meta": _meta_for_events(lang, request),
        "wallet_user": get_wallet_user(request),
        "lang": lang,
        "events": events,
    }
    return render_mobile_first(request, "events", ctx)

def events_ko(request):
    lang = "ko"
    events = _events_for_lang(lang)
    ctx = {
        "meta": _meta_for_events(lang, request),
        "wallet_user": get_wallet_user(request),
        "lang": lang,
        "events": events,
    }
    return render_mobile_first(request, "events", ctx)

def events_ja(request):
    lang = "ja"
    events = _events_for_lang(lang)
    ctx = {
        "meta": _meta_for_events(lang, request),
        "wallet_user": get_wallet_user(request),
        "lang": lang,
        "events": events,
    }
    return render_mobile_first(request, "events", ctx)

def events_zh(request):
    lang = "zh"
    events = _events_for_lang(lang)
    ctx = {
        "meta": _meta_for_events(lang, request),
        "wallet_user": get_wallet_user(request),
        "lang": lang,
        "events": events,
    }
    return render_mobile_first(request, "events", ctx)

# ================== WALLET AUTH API (EVM) ==================
@require_GET
def api_nonce(request):
    raw = request.GET.get("address")
    addr = _normalize_evm_address(raw)
    if not addr:
        return JsonResponse({"ok": False, "error": "invalid address"}, status=400)

    user, _ = WalletUser.objects.get_or_create(address=addr, defaults={"display_name": addr})
    user.nonce = secrets.token_urlsafe(24)  # a bit longer; still URL-safe
    user.save(update_fields=["nonce"])

    message = _login_message(user.nonce)
    return JsonResponse({"ok": True, "address": user.address, "nonce": user.nonce, "message": message})

@require_POST
def api_verify(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "bad json"}, status=400)

    address = _normalize_evm_address(data.get("address"))
    message = (data.get("message") or "").strip()
    signature = (data.get("signature") or "").strip()

    if not address or not message or not signature:
        return JsonResponse({"ok": False, "error": "missing fields"}, status=400)

    try:
        user = WalletUser.objects.get(address=address)
    except WalletUser.DoesNotExist:
        return JsonResponse({"ok": False, "error": "unknown address"}, status=400)

    if not user.nonce:
        return JsonResponse({"ok": False, "error": "no nonce; request /api/auth/nonce first"}, status=400)

    # Require exact canonical message for the stored nonce
    expected_message = _login_message(user.nonce)
    if message != expected_message:
        return JsonResponse({"ok": False, "error": "message mismatch"}, status=400)

    # Recover signer and compare
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature).lower()
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"bad signature: {e}"}, status=400)

    if recovered != address:
        return JsonResponse({"ok": False, "error": "address mismatch"}, status=400)

    # Success: bind session + invalidate nonce
    request.session["wallet_user_id"] = user.id
    user.last_login = timezone.now()
    user.nonce = ""
    user.save(update_fields=["last_login", "nonce"])

    return JsonResponse({
        "ok": True,
        "user": {"id": user.id, "address": user.address, "display_name": user.display_name or user.address}
    })

@require_POST
def api_logout(request):
    request.session.pop("wallet_user_id", None)
    return JsonResponse({"ok": True})



# ================== SUBMISSION HANDLERS ==================
def _need_login(request):
    if not get_wallet_user(request):
        return HttpResponseForbidden("Connect wallet first")
    return None

def _clean_network(value: str) -> str | None:
    v = (value or "").upper().strip()
    if v in dict(Network.choices).keys():
        return v
    return None

@require_POST
def submit_link(request, slug):
    # need = _need_login(request)
    # if need:
    #     return need

    user = get_wallet_user(request)
    campaign = get_object_or_404(Campaign, slug=slug)

    if campaign.task_type != TaskType.LINK:
        return HttpResponseBadRequest("wrong task type")
    if not campaign.is_open_now:
        return HttpResponseBadRequest("campaign closed")

    post_url = (request.POST.get("post_url") or "").strip()
    comment = (request.POST.get("comment") or "").strip()
    wallet = (request.POST.get("wallet") or request.POST.get("wallet_address") or "").strip()
    network = _clean_network(request.POST.get("network"))

    if not wallet or not network:
        return HttpResponseBadRequest("wallet and network required")

    try:
        Submission.objects.create(
            campaign=campaign,
            user=user,
            wallet_address=wallet,
            network=network,
            post_url=post_url,
            comment=comment,
            status=SubmissionStatus.PENDING,
            proof_score=0,
        )
    except IntegrityError:
        pass

    return redirect(request.META.get("HTTP_REFERER", "/rewards/"))

@require_POST
def submit_visit(request, slug):
    # need = _need_login(request)
    # if need:
    #     return need

    user = get_wallet_user(request)
    campaign = get_object_or_404(Campaign, slug=slug)

    if campaign.task_type != TaskType.VISIT:
        return HttpResponseBadRequest("wrong task type")
    if not campaign.is_open_now:
        return HttpResponseBadRequest("campaign closed")

    code = (request.POST.get("code") or request.POST.get("visit_code") or "").strip()
    wallet = (request.POST.get("wallet2") or request.POST.get("wallet") or request.POST.get("wallet_address") or "").strip()
    network = _clean_network(request.POST.get("network"))
    visited_url = campaign.client_site_domain or (request.POST.get("visited_url") or "").strip()

    if not wallet or not network:
        return HttpResponseBadRequest("wallet and network required")

    try:
        Submission.objects.create(
            campaign=campaign,
            user=user,
            wallet_address=wallet,
            network=network,
            visited_url=visited_url,
            code_entered=code,
            status=SubmissionStatus.PENDING,
        )
    except IntegrityError:
        pass

    return redirect(request.META.get("HTTP_REFERER", "/rewards/"))


# ---- SAMPLE CAMPAIGNS (UI preview) ----
SAMPLE_CAMPAIGNS = {
    1: {"title": "SEO Suite: Case study tour", "summary": "Visit 3 pages, collect codes, then post a short review with insights.",
        "image_url": "https://images.pexels.com/photos/669619/pexels-photo-669619.jpeg?auto=compress&cs=tinysrgb&h=800",
        "has_visit": True, "has_link": True, "pool_usdt": 3200, "payout_usdt": 6, "participants": 516,
        "start": "2025-10-01", "end": "2025-11-30", "quota_total": 1000, "client_site_domain": "example.com",
        "task_type": "MIXED"},
    2: {"title": "Wallet onboarding quest", "summary": "Create a demo wallet, browse settings, submit the hidden FAQ code.",
        "image_url": "https://images.pexels.com/photos/29831433/pexels-photo-29831433.jpeg?cs=srgb&dl=pexels-tugaykocaturk-29831433.jpg&fm=jpg",
        "has_visit": True, "has_link": False, "pool_usdt": 1000, "payout_usdt": 2, "participants": 190,
        "start": "2025-11-01", "end": "2025-12-10", "quota_total": 500, "client_site_domain": "wallet.example",
        "task_type": "VISIT"},
    3: {"title": "Naver review sprint", "summary": "Write a genuine Naver Blog review with a contextual dofollow link.",
        "image_url": "/static/img/cards/bitcoin-close.jpg",
        "has_visit": False, "has_link": True, "pool_usdt": 5000, "payout_usdt": 15, "participants": 412,
        "start": "2025-10-05", "end": "2025-11-15", "quota_total": 600, "client_site_domain": "naver.com",
        "task_type": "LINK"},
    4: {"title": "Product page engagement", "summary": "Scroll & interact; find the verification code at the bottom.",
        "image_url": "/static/img/cards/green-office.jpg",
        "has_visit": True, "has_link": False, "pool_usdt": 1500, "payout_usdt": 3, "participants": 230,
        "start": "2025-10-10", "end": "2025-12-01", "quota_total": 800, "client_site_domain": "shop.example",
        "task_type": "VISIT"},
    5: {"title": "DevTools beta feedback", "summary": "Publish a thoughtful beta review on your blog with a citation link.",
        "image_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=1200&auto=format&fit=crop",
        "has_visit": False, "has_link": True, "pool_usdt": 2750, "payout_usdt": 8, "participants": 304,
        "start": "2025-10-15", "end": "2025-12-05", "quota_total": 700, "client_site_domain": "devtools.example",
        "task_type": "LINK"},
    6: {"title": "SimpleQuant: Blog launch", "summary": "Read the post, find the hidden code, submit & earn.",
        "image_url": "/static/img/cards/neon-city.jpg",
        "has_visit": True, "has_link": True, "pool_usdt": 2000, "payout_usdt": 4, "participants": 842,
        "start": "2025-09-01", "end": "2025-10-31", "quota_total": 1200, "client_site_domain": "simplequant.net",
        "task_type": "MIXED"},
}

def rewards_detail(request, slug, pk):
    wallet_user = get_wallet_user(request)

    campaign_obj = Campaign.objects.filter(pk=pk).first()
    using_sample = False

    if campaign_obj is None:
        data = SAMPLE_CAMPAIGNS.get(pk)
        if not data:
            readable = slug.replace("-", " ").title()
            data = {
                "title": readable, "summary": "Sample campaign for UI preview.",
                "image_url": "", "has_visit": True, "has_link": True,
                "pool_usdt": 0, "payout_usdt": 0, "participants": 0,
                "start": "", "end": "", "quota_total": 0, "client_site_domain": "",
                "task_type": "MIXED",
            }
        using_sample = True
        campaign_obj = SimpleNamespace(
            id=pk, slug=slug, title=data["title"], summary=data["summary"],
            image_url=data.get("image_url", ""), has_visit=data.get("has_visit", False),
            has_link=data.get("has_link", False), pool_usdt=data.get("pool_usdt", 0),
            payout_usdt=data.get("payout_usdt", 0), participants=data.get("participants", 0),
            start=data.get("start", ""), end=data.get("end", ""), quota_total=data.get("quota_total", 0),
            client_site_domain=data.get("client_site_domain", ""), task_type=data.get("task_type", "MIXED"),
        )

    expected_slug = (getattr(campaign_obj, "slug", None) or slugify(getattr(campaign_obj, "title", "") or "campaign")).lower()
    if not using_sample and slug != expected_slug:
        return redirect(f"/rewards/{expected_slug}-{campaign_obj.id}/", permanent=True)

    lang = _lang_from_request(request)
    base = _base_url(request)
    meta = {
        "lang": lang,
        "title": f"LinkHash | {getattr(campaign_obj, 'title', 'Campaign')}",
        "description": getattr(campaign_obj, "summary", "Join this LinkHash campaign and earn rewards."),
        "og_title": getattr(campaign_obj, "title", "LinkHash Campaign"),
        "og_description": getattr(campaign_obj, "summary", "White-hat tasks with transparent rewards."),
        "canonical": f"{base}/rewards/{expected_slug}-{campaign_obj.id}/",
        "url": f"{base}/rewards/{expected_slug}-{campaign_obj.id}/",
    }

    if using_sample:
        examples = [
            SimpleNamespace(comment="Fun website. I learnt some stuff lol", user_address="0x6E8960...43bdf", proof_score=150, created_at=timezone.now()),
            SimpleNamespace(comment="방금 글 올렸습니다. 키워드 포함 완료!", user_address="0xAbCDEF...cDeF12", proof_score=120, created_at=timezone.now()),
            SimpleNamespace(comment="みんな、こんにちは :)", user_address="GV1MkAGy...a", proof_score=70, created_at=timezone.now()),
        ]
        submitted = len(examples)
        quota_total = getattr(campaign_obj, "quota_total", 0) or 0
        claimed_percent = int(submitted * 100 / quota_total) if quota_total else 0
    else:
        examples = Submission.objects.filter(campaign=campaign_obj).order_by("-created_at")[:12]
        quota_total = 0  # your template can ignore quota if you don't track it here
        submitted = Submission.objects.filter(campaign=campaign_obj).count()
        # claimed percent comes from model property; mirror template usage if needed
        claimed_percent = campaign_obj.claimed_percent if hasattr(campaign_obj, "claimed_percent") else 0

    ctx = {
        "meta": meta, "lang": lang, "wallet_user": wallet_user,
        "campaign": campaign_obj, "examples": examples,
        "submitted": submitted, "quota_total": quota_total, "claimed_percent": claimed_percent,
        "using_sample": using_sample,
    }
    return render_mobile_first(request, "rewards_details", ctx)


# ======== LEADERBOARD ========
NETWORK_VERBOSE = {
    "ETH": "Ethereum",
    "SOL": "Solana",
    "BNB": "BNB Chain",
    "POL": "Polygon",
    "BASE": "Base",
}

EXPLORER_BASE = {
    "ETH": "https://etherscan.io/address/",
    "POL": "https://polygonscan.com/address/",
    "BNB": "https://bscscan.com/address/",
    "SOL": "https://solscan.io/account/",
    "BASE": "https://etherscan.io/address/"
}

def _explorer_url(address: str, network: str | None) -> str | None:
    if not address or not network:
        return None
    base = EXPLORER_BASE.get(network)
    if not base:
        return None
    return f"{base}{address}"

def _leaderboard_range(request):
    now = timezone.now()
    code = (request.GET.get("range") or "").lower()
    mapping = {"7d": 7, "30d": 30, "3m": 90, "6m": 180, "12m": 365}
    days = mapping.get(code, 90)
    label = [k.upper() for k, v in mapping.items() if v == days][0]
    norm_code = [k for k, v in mapping.items() if v == days][0]
    return now - timedelta(days=days), label, norm_code

def _mask_addr(addr: str) -> str:
    """Show first 5 and last 5 characters, preserving 0x if present."""
    if not addr:
        return "-----...-----"
    a = addr.strip()
    # Normalize hex addresses to keep 0x then 5+...+5 after it
    if a.startswith("0x") and len(a) > 12:
        return f"{a[:7]}...{a[-5:]}"  # '0x' + 5 -> total 7 at the start
    if len(a) > 10:
        return f"{a[:5]}...{a[-5:]}"
    return a


def _score_points(links: int, visits: int, score: int) -> int:
    return 10 * links + 5 * visits + score

def _normalize_rows(rows):
    total_points = sum(r["points"] for r in rows) or 1
    rows.sort(key=lambda r: (-r["points"], -r["score"], -r["links"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["mindshare"] = (r["points"] / total_points) * 100.0
        total_lv = max(r["links"] + r["visits"], 1)
        r["ratio_links"] = (r["links"] / total_lv) * 100.0
        r["ratio_visits"] = 100.0 - r["ratio_links"]
        r["masked"] = _mask_addr(r["address"])
    return rows

def _sample_leaderboard_rows():
    demo = [
        {"address":"0x1a2b3c4d5e6f7890aBcD1234aBcD5678EFabC111", "links":42, "visits":310, "score":520, "network":"ETH"},
        {"address":"0x9f8e7d6c5b4a3210fedcBA98aa77665544332222", "links":37, "visits":280, "score":610, "network":"POL"},
        {"address":"0x7777aAaA2222bBbB3333cCcC4444dDdD5555eeee", "links":29, "visits":260, "score":440, "network":"BNB"},
        # If you want a Solana example, use a real-looking base58 (not 0x) address:
        {"address":"9xQeWvG816bUx9EPjHmaTjAaZ4K4fS5zVPa6G5x6QQ3F",  "links":24, "visits":190, "score":300, "network":"SOL"},
    ]
    rows = []
    for d in demo:
        points = _score_points(d["links"], d["visits"], d["score"])
        net = d.get("network")
        rows.append({
            **d,
            "points": points,
            "network_verbose": NETWORK_VERBOSE.get(net) if net else None,
            "explorer_url": _explorer_url(d["address"], net),
        })
    return _normalize_rows(rows)


def _leaderboard_from_db(since_dt):
    qs = Submission.objects.filter(created_at__gte=since_dt)
    if not qs.exists():
        return []
    # Aggregate by wallet (works even if user is null). Prefer user.address if present.
    agg = (
        qs.values("wallet_address", "user__address")
          .annotate(
              links=Count("id", filter=Q(post_url__isnull=False) & ~Q(post_url="")),
              visits=Count("id", filter=Q(visited_url__isnull=False) & ~Q(visited_url="")),
              score=Sum("proof_score"),
              network=Max("network"),  # <-- pick any non-null network seen for this wallet
          )
    )
    rows = []
    for a in agg:
        links = int(a.get("links") or 0)
        visits = int(a.get("visits") or 0)
        score = int(a.get("score") or 0)
        points = _score_points(links, visits, score)
        display_addr = a.get("user__address") or a.get("wallet_address") or ""
        net = a.get("network") or None  # 'ETH','SOL','BNB','POL' or None

        rows.append({
            "address": display_addr,
            "links": links,
            "visits": visits,
            "score": score,
            "points": points,
            "network": net,
            "network_verbose": NETWORK_VERBOSE.get(net) if net else None,
            "explorer_url": _explorer_url(display_addr, net),
        })
    return _normalize_rows(rows)


def leaderboard_en(request):
    lang = _lang_from_request(request)
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard(lang, request),
        "wallet_user": get_wallet_user(request),
        "rows": rows, "range_label": label, "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render_mobile_first(request, "leaderboard", ctx)

def leaderboard_ko(request):
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard("ko", request),
        "wallet_user": get_wallet_user(request),
        "rows": rows, "range_label": label, "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render_mobile_first(request, "leaderboard", ctx)

def leaderboard_ja(request):
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard("ja", request),
        "wallet_user": get_wallet_user(request),
        "rows": rows, "range_label": label, "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render_mobile_first(request, "leaderboard", ctx)

def leaderboard_zh(request):
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard("zh", request),
        "wallet_user": get_wallet_user(request),
        "rows": rows, "range_label": label, "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render_mobile_first(request, "leaderboard", ctx)
