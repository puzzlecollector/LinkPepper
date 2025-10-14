# backend/core/views.py
import json
import secrets

from django.db import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from types import SimpleNamespace
from django.utils.text import slugify
from eth_account.messages import encode_defunct
from eth_account import Account

# NOTE: adjust this import if your models live elsewhere
from .models import WalletUser, Campaign, Submission, Event


def _base_url(request):
    return f"{request.scheme}://{request.get_host()}"


def _meta_for(lang, request, *, page="home"):
    base = _base_url(request)  # e.g. http://127.0.0.1:8000

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
        else:
            return {
                "lang": "en",
                "title": "LinkHash | Rewards Program",
                "description": "Join our backlink & SEO campaigns and earn rewards.",
                "og_title": "LinkHash Rewards",
                "og_description": "Complete link share/visit tasks and earn USDT.",
                "canonical": f"{base}/rewards/",
                "url": f"{base}/rewards/",
            }

    # 기본 홈 메타
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
    else:
        return {
            "lang": "en",
            "title": "LinkHash | Backlinks · SEO · Rank Higher",
            "description": "Data-driven backlinks & SEO. White-hat strategy and transparent reporting to rank safely.",
            "og_title": "LinkHash | Backlinks · SEO · Rank Higher",
            "og_description": "Boost rankings safely with white-hat, data-driven link building.",
            "canonical": f"{base}/",
            "url": f"{base}/",
        }


# ---------- session helper ----------
def get_wallet_user(request):
    uid = request.session.get("wallet_user_id")
    if not uid:
        return None
    return WalletUser.objects.filter(id=uid).first()


# ================== PAGES ==================
def home_en(request):
    ctx = {
        "meta": _meta_for("en", request),
        "wallet_user": get_wallet_user(request),
    }
    return render(request, "home.html", ctx)


def home_ko(request):
    ctx = {
        "meta": _meta_for("ko", request),
        "wallet_user": get_wallet_user(request),
    }
    return render(request, "home.html", ctx)


# ✅ 리워드 페이지
def _rewards_context(request, lang):
    """
    Provide both campaigns + live lists for the template.
    Slugs to create in admin: 'link-sharing-sq' and 'visit-bitcoin-simplequant'
    """
    wallet_user = get_wallet_user(request)

    link_campaign  = Campaign.objects.filter(slug='link-sharing-sq').first()
    visit_campaign = Campaign.objects.filter(slug='visit-bitcoin-simplequant').first()

    # Lists for the UI (examples)
    link_examples = Submission.objects.filter(campaign=link_campaign).order_by('-proof_score', '-created_at')[:10] if link_campaign else []
    visit_examples = Submission.objects.filter(campaign=visit_campaign).order_by('-created_at')[:12] if visit_campaign else []

    # Progress for visit task
    visit_submitted = Submission.objects.filter(campaign=visit_campaign).count() if visit_campaign else 0
    visit_quota = visit_campaign.quota_total if visit_campaign else 0
    visit_percent = int(visit_submitted * 100 / visit_quota) if (visit_campaign and visit_quota) else 0

    # meta
    meta = _meta_for(lang, request, page="rewards")

    return {
        'meta': meta,
        'lang': lang,
        'wallet_user': wallet_user,
        'link_campaign': link_campaign,
        'visit_campaign': visit_campaign,
        'link_examples': link_examples,
        'visit_examples': visit_examples,
        'visit_percent': visit_percent,
        'visit_submitted': visit_submitted,
        'visit_quota': visit_quota,
    }

def rewards_en(request):
    ctx = {
        "meta": _meta_for("en", request, page="rewards"),
        "lang": "en",
        "wallet_user": get_wallet_user(request),
    }
    return render(request, "rewards.html", ctx)


def rewards_ko(request):
    ctx = {
        "meta": _meta_for("ko", request, page="rewards"),
        "lang": "ko",
        "wallet_user": get_wallet_user(request),
    }
    return render(request, "rewards.html", ctx)


def rewards_apply_en(request):
    base = f"{request.scheme}://{request.get_host()}"
    meta = {
        "lang": "en",
        "title": "Apply | LinkHash Rewards",
        "description": "Apply to run a LinkHash reward campaign.",
        "og_title": "Apply | LinkHash Rewards",
        "og_description": "Submit your campaign request. We reply within 24h.",
        "canonical": f"{base}/rewards/apply/",
        "url": f"{base}/rewards/apply/",
    }
    return render(request, "rewards_apply.html", {"meta": meta, "wallet_user": get_wallet_user(request)})


def rewards_apply_ko(request):
    base = f"{request.scheme}://{request.get_host()}"
    meta = {
        "lang": "ko",
        "title": "신청 | LinkHash 리워드",
        "description": "LinkHash 리워드 캠페인 신청 페이지.",
        "og_title": "신청 | LinkHash 리워드",
        "og_description": "캠페인 신청을 남겨 주세요. 24시간 내 회신합니다.",
        "canonical": f"{base}/rewards/apply/ko/",
        "url": f"{base}/rewards/apply/ko/",
    }
    return render(request, "rewards_apply.html", {"meta": meta, "wallet_user": get_wallet_user(request)})


def _meta_for_events(lang, request):
    base = _base_url(request)
    m = _meta_for(lang, request).copy()
    titles = {
        "en": ("LinkHash | Events & Announcements", "LinkHash | Events & Announcements", f"{base}/events/"),
        "ko": ("LinkHash | 이벤트 · 공지",           "LinkHash | 이벤트 · 공지",           f"{base}/ko/events/"),
        "ja": ("LinkHash | イベント・お知らせ",     "LinkHash | イベント・お知らせ",     f"{base}/ja/events/"),
        "zh": ("LinkHash | 活动与公告",            "LinkHash | 活动与公告",            f"{base}/zh/events/"),
    }
    title, og_title, canon = titles.get(lang, titles["en"])
    m.update({
        "title": title,
        "og_title": og_title,
        "canonical": canon,
        "url": canon,
    })
    return m



def _events_context(request, lang):
    qs = Event.objects.filter(is_published=True, lang=lang).order_by("-posted_at", "-id")
    return {
        "meta": _meta_for_events(lang, request),
        "wallet_user": get_wallet_user(request),
        "events": qs,
    }

def events_en(request):
    return render(request, "events.html", _events_context(request, "en"))

def events_ko(request):
    return render(request, "events.html", _events_context(request, "ko"))

def events_ja(request):
    return render(request, "events.html", _events_context(request, "ja"))

def events_zh(request):
    return render(request, "events.html", _events_context(request, "zh"))



# ================== WALLET AUTH API (EVM) ==================
def api_nonce(request):
    addr = (request.GET.get("address") or "").strip().lower()
    if not addr or not addr.startswith("0x") or len(addr) != 42:
        return JsonResponse({"ok": False, "error": "invalid address"}, status=400)
    user, _ = WalletUser.objects.get_or_create(address=addr, defaults={"display_name": addr})
    user.nonce = secrets.token_urlsafe(16)
    user.save(update_fields=["nonce"])
    return JsonResponse({"ok": True, "nonce": user.nonce})


@csrf_exempt
def api_verify(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST required"}, status=405)
    try:
        data = json.loads(request.body.decode("utf-8"))
        address = (data.get("address") or "").strip().lower()
        message = data.get("message") or ""
        signature = data.get("signature") or ""
    except Exception:
        return JsonResponse({"ok": False, "error": "bad json"}, status=400)

    if not address or not message or not signature:
        return JsonResponse({"ok": False, "error": "missing fields"}, status=400)

    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature).lower()
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"bad signature: {e}"}, status=400)

    if recovered != address:
        return JsonResponse({"ok": False, "error": "address mismatch"}, status=400)

    try:
        user = WalletUser.objects.get(address=address)
    except WalletUser.DoesNotExist:
        return JsonResponse({"ok": False, "error": "unknown address"}, status=400)

    if not user.nonce or user.nonce not in message:
        return JsonResponse({"ok": False, "error": "nonce mismatch"}, status=400)

    request.session["wallet_user_id"] = user.id
    user.last_login = timezone.now()
    user.nonce = ""
    user.save(update_fields=["last_login", "nonce"])

    return JsonResponse({
        "ok": True,
        "user": {
            "id": user.id,
            "address": user.address,
            "display_name": user.display_name or user.address
        }
    })


@csrf_exempt
def api_logout(request):
    request.session.pop("wallet_user_id", None)
    return JsonResponse({"ok": True})


# ================== SUBMISSION HANDLERS ==================
def _need_login(request):
    if not get_wallet_user(request):
        return HttpResponseForbidden("Connect wallet first")
    return None


@require_POST
def submit_link(request, slug):
    need = _need_login(request)
    if need:
        return need

    user = get_wallet_user(request)
    campaign = get_object_or_404(Campaign, slug=slug)
    if campaign.task_type != Campaign.TaskType.LINK:
        return HttpResponseBadRequest("wrong task type")
    if not campaign.is_open_now():
        return HttpResponseBadRequest("campaign closed")

    post_url = request.POST.get("post_url") or ""
    comment = request.POST.get("comment") or ""
    wallet = request.POST.get("wallet") or ""

    try:
        Submission.objects.create(
            campaign=campaign,
            user=user,
            comment=comment,
            wallet_used=wallet,
            post_url=post_url,
            status=Submission.Status.PENDING,
            proof_score=0,
        )
    except IntegrityError:
        # unique(campaign,user) prevents duplicates
        pass

    return redirect(request.META.get("HTTP_REFERER", "/rewards/"))


@require_POST
def submit_visit(request, slug):
    need = _need_login(request)
    if need:
        return need

    user = get_wallet_user(request)
    campaign = get_object_or_404(Campaign, slug=slug)
    if campaign.task_type not in [Campaign.TaskType.VISIT, Campaign.TaskType.SEARCH]:
        return HttpResponseBadRequest("wrong task type")
    if not campaign.is_open_now():
        return HttpResponseBadRequest("campaign closed")

    code = request.POST.get("code") or ""
    wallet = request.POST.get("wallet2") or ""
    visited_url = campaign.client_site_domain or ""

    # For presentation we **assume** the code is correct.
    try:
        Submission.objects.create(
            campaign=campaign,
            user=user,
            wallet_used=wallet,
            visited_url=visited_url,
            code_entered=code,
            status=Submission.Status.PENDING,
        )
    except IntegrityError:
        pass

    return redirect(request.META.get("HTTP_REFERER", "/rewards/"))


# ---- SAMPLE CAMPAIGNS (for UI-only preview; safe to delete later) ----
SAMPLE_CAMPAIGNS = {
    1: {
        "title": "SEO Suite: Case study tour",
        "summary": "Visit 3 pages, collect codes, then post a short review with insights.",
        "image_url": "https://images.pexels.com/photos/669619/pexels-photo-669619.jpeg?auto=compress&cs=tinysrgb&h=800",
        "has_visit": True, "has_link": True,
        "pool_usdt": 3200, "payout_usdt": 6, "participants": 516,
        "start": "2025-10-01", "end": "2025-11-30",
        "quota_total": 1000, "client_site_domain": "example.com",
        "task_type": "MIXED",
    },
    2: {
        "title": "Wallet onboarding quest",
        "summary": "Create a demo wallet, browse settings, submit the hidden FAQ code.",
        "image_url": "https://images.pexels.com/photos/29831433/pexels-photo-29831433.jpeg?cs=srgb&dl=pexels-tugaykocaturk-29831433.jpg&fm=jpg",
        "has_visit": True, "has_link": False,
        "pool_usdt": 1000, "payout_usdt": 2, "participants": 190,
        "start": "2025-11-01", "end": "2025-12-10",
        "quota_total": 500, "client_site_domain": "wallet.example",
        "task_type": "VISIT",
    },
    3: {
        "title": "Naver review sprint",
        "summary": "Write a genuine Naver Blog review with a contextual dofollow link.",
        "image_url": "/static/img/cards/bitcoin-close.jpg",
        "has_visit": False, "has_link": True,
        "pool_usdt": 5000, "payout_usdt": 15, "participants": 412,
        "start": "2025-10-05", "end": "2025-11-15",
        "quota_total": 600, "client_site_domain": "naver.com",
        "task_type": "LINK",
    },
    4: {
        "title": "Product page engagement",
        "summary": "Scroll & interact; find the verification code at the bottom.",
        "image_url": "/static/img/cards/green-office.jpg",
        "has_visit": True, "has_link": False,
        "pool_usdt": 1500, "payout_usdt": 3, "participants": 230,
        "start": "2025-10-10", "end": "2025-12-01",
        "quota_total": 800, "client_site_domain": "shop.example",
        "task_type": "VISIT",
    },
    5: {
        "title": "DevTools beta feedback",
        "summary": "Publish a thoughtful beta review on your blog with a citation link.",
        "image_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?q=80&w=1200&auto=format&fit=crop",
        "has_visit": False, "has_link": True,
        "pool_usdt": 2750, "payout_usdt": 8, "participants": 304,
        "start": "2025-10-15", "end": "2025-12-05",
        "quota_total": 700, "client_site_domain": "devtools.example",
        "task_type": "LINK",
    },
    6: {
        "title": "SimpleQuant: Blog launch",
        "summary": "Read the post, find the hidden code, submit & earn.",
        "image_url": "/static/img/cards/neon-city.jpg",
        "has_visit": True, "has_link": True,
        "pool_usdt": 2000, "payout_usdt": 4, "participants": 842,
        "start": "2025-09-01", "end": "2025-10-31",
        "quota_total": 1200, "client_site_domain": "simplequant.net",
        "task_type": "MIXED",
    },
    # you can add 101..106 for “Past” if you want to click those too
}

def rewards_detail(request, slug, pk):
    """
    Detail page for a single campaign.
    Pretty URL format: /rewards/<slugified-name>-<id>/
    Falls back to SAMPLE_CAMPAIGNS when DB row doesn't exist (UI preview mode).
    """
    wallet_user = get_wallet_user(request)

    # Try DB first
    campaign_obj = Campaign.objects.filter(pk=pk).first()
    using_sample = False

    if campaign_obj is None:
        # UI-only fallback
        data = SAMPLE_CAMPAIGNS.get(pk)
        if not data:
            # minimal synthetic data if id isn't in SAMPLE_CAMPAIGNS
            readable = slug.replace("-", " ").title()
            data = {
                "title": readable,
                "summary": "Sample campaign for UI preview.",
                "image_url": "",
                "has_visit": True, "has_link": True,
                "pool_usdt": 0, "payout_usdt": 0, "participants": 0,
                "start": "", "end": "",
                "quota_total": 0, "client_site_domain": "",
                "task_type": "MIXED",
            }
        using_sample = True

        # Provide object-like access in templates
        campaign_obj = SimpleNamespace(
            id=pk,
            slug=slug,  # leave as-is
            title=data["title"],
            summary=data["summary"],
            image_url=data.get("image_url", ""),
            has_visit=data.get("has_visit", False),
            has_link=data.get("has_link", False),
            pool_usdt=data.get("pool_usdt", 0),
            payout_usdt=data.get("payout_usdt", 0),
            participants=data.get("participants", 0),
            start=data.get("start", ""),
            end=data.get("end", ""),
            quota_total=data.get("quota_total", 0),
            client_site_domain=data.get("client_site_domain", ""),
            task_type=data.get("task_type", "MIXED"),
        )

    # canonical slug
    expected_slug = (campaign_obj.slug or slugify(getattr(campaign_obj, "title", "") or "campaign")).lower()
    # Only redirect to canonical when we actually have a DB-backed slug that differs.
    if not using_sample and slug != expected_slug:
        return redirect(f"/rewards/{expected_slug}-{campaign_obj.id}/", permanent=True)

    # language detection
    lang = "ko" if request.path.startswith("/ko/") or request.GET.get("lang") == "ko" else "en"

    # meta
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

    # examples / progress
    if using_sample:
        # lightweight mock submissions for UI
        examples = [
            SimpleNamespace(comment="Fun website. I learnt some stuff lol", user_address="0x6E8960...43bdf", proof_score=150, created_at=timezone.now()),
            SimpleNamespace(comment="방금 글 올렸습니다. 키워드 포함 완료!", user_address="0xAbCDEF...cDeF12", proof_score=120, created_at=timezone.now()),
            SimpleNamespace(comment="みんな、こんにちは :)", user_address="GV1MkAGy...a", proof_score=70, created_at=timezone.now()),
        ]
        submitted = len(examples)
        quota_total = getattr(campaign_obj, "quota_total", 0) or 0
        claimed_percent = int(submitted * 100 / quota_total) if quota_total else 0
    else:
        from .models import Submission
        examples = Submission.objects.filter(campaign=campaign_obj).order_by("-created_at")[:12]
        quota_total = getattr(campaign_obj, "quota_total", 0) or 0
        submitted = Submission.objects.filter(campaign=campaign_obj).count()
        claimed_percent = int(submitted * 100 / quota_total) if quota_total else 0

    ctx = {
        "meta": meta,
        "lang": lang,
        "wallet_user": wallet_user,
        "campaign": campaign_obj,
        "examples": examples,
        "submitted": submitted,
        "quota_total": quota_total,
        "claimed_percent": claimed_percent,
        "using_sample": using_sample,
    }
    return render(request, "rewards_details.html", ctx)


# ======== LEADERBOARD (UI-first with sample fallback) ========
from datetime import timedelta
from django.db.models import Count, Sum, Q

def _meta_for_leaderboard(lang, request):
    base = _base_url(request)
    common = {
        "canonical": f"{base}/leaderboard/",
        "url": f"{base}/leaderboard/",
    }
    if lang == "ko":
        return {
            "lang": "ko",
            "title": "LinkHash | 리더보드",
            "description": "캠페인 기여도 기준 상위 참여자 리더보드.",
            "og_title": "LinkHash | 리더보드",
            "og_description": "링크/방문 과제 및 점수를 기반으로 한 기여도 순위.",
            **common,
        }
    return {
        "lang": "en",
        "title": "LinkHash | Leaderboard",
        "description": "Top contributors ranked by campaign participation.",
        "og_title": "LinkHash | Leaderboard",
        "og_description": "Ranks based on link/visit tasks and scores.",
        **common,
    }

def _leaderboard_range(request):
    """
    Supports ?range=7d|30d|3m|6m|12m (default 3m).
    Returns (since_dt, 'label', 'code')
    """
    now = timezone.now()
    code = (request.GET.get("range") or "").lower()
    mapping = {
        "7d": 7, "30d": 30, "3m": 90, "6m": 180, "12m": 365,
    }
    days = mapping.get(code, 90)
    label = [k.upper() for k, v in mapping.items() if v == days][0]
    norm_code = [k for k, v in mapping.items() if v == days][0]
    return now - timedelta(days=days), label, norm_code

def _mask_addr(addr: str) -> str:
    if not addr:
        return "----....----"
    a = addr.strip()
    if a.startswith("0x") and len(a) >= 10:
        return f"{a[:6]}...{a[-4:]}"
    return f"{a[:4]}...{a[-4:]}"

def _score_points(links: int, visits: int, score: int) -> int:
    # Tunable scoring for early UI: 10/link + 5/visit + proof_score
    return 10 * links + 5 * visits + score

def _normalize_rows(rows):
    """Compute rank, mindshare %, and split ratios for bars."""
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
    """
    Used when there is no data in DB yet (UI preview mode).
    Wallets are fake-looking, scores are illustrative.
    """
    demo = [
        {"address":"0x1a2b3c4d5e6f7890aBcD1234aBcD5678EFabC111", "links":42, "visits":310, "score":520},
        {"address":"0x9f8e7d6c5b4a3210fedcBA98aa77665544332222", "links":37, "visits":280, "score":610},
        {"address":"0x7777aAaA2222bBbB3333cCcC4444dDdD5555eeee", "links":29, "visits":260, "score":440},
        {"address":"0xA1B2C3D4E5F607182736455463728190AbCdEf12", "links":21, "visits":198, "score":305},
        {"address":"0xFfFf000011112222333344445555666677778888", "links":19, "visits":205, "score":250},
        {"address":"0x1357ace02468bdf91357ACE02468BDF91357aCe0", "links":18, "visits":172, "score":240},
        {"address":"0xDEADbeefDEADbeefDEADbeefDEADbeef00001234", "links":14, "visits":160, "score":210},
        {"address":"0x0a0A0b0B0c0C0d0D0e0E1234567890abcdefABCD", "links":12, "visits":141, "score":160},
        {"address":"0x2222333344445555666677778888999900001111", "links":11, "visits":120, "score":155},
        {"address":"0x8888777766665555444433332222111100009999", "links":10, "visits":118, "score":130},
        {"address":"0x1234abcd5678efab1234abcd5678efab1234abcd", "links":9,  "visits":102, "score":120},
        {"address":"0xabcd0000abcd0000abcd0000abcd0000abcd9999", "links":8,  "visits":95,  "score":95},
    ]
    rows = []
    for d in demo:
        points = _score_points(d["links"], d["visits"], d["score"])
        rows.append({**d, "points": points})
    return _normalize_rows(rows)

def _leaderboard_from_db(since_dt):
    qs = Submission.objects.filter(created_at__gte=since_dt)
    if not qs.exists():
        return []
    agg = (
        qs.values("user_id", "user__address")
          .annotate(
              links=Count("id", filter=Q(post_url__isnull=False) & ~Q(post_url="")),
              visits=Count("id", filter=Q(visited_url__isnull=False) & ~Q(visited_url="")),
              score=Sum("proof_score"),
          )
    )
    rows = []
    for a in agg:
        links = int(a.get("links") or 0)
        visits = int(a.get("visits") or 0)
        score = int(a.get("score") or 0)
        points = _score_points(links, visits, score)
        rows.append({
            "user_id": a["user_id"],
            "address": a["user__address"] or "",
            "links": links, "visits": visits, "score": score, "points": points,
        })
    return _normalize_rows(rows)

def leaderboard_en(request):
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard("en", request),
        "wallet_user": get_wallet_user(request),
        "rows": rows,
        "range_label": label,
        "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render(request, "leaderboard.html", ctx)

def leaderboard_ko(request):
    since, label, code = _leaderboard_range(request)
    rows = _leaderboard_from_db(since) or _sample_leaderboard_rows()
    ctx = {
        "meta": _meta_for_leaderboard("ko", request),
        "wallet_user": get_wallet_user(request),
        "rows": rows,
        "range_label": label,
        "range_code": code,
        "using_sample": not Submission.objects.filter(created_at__gte=since).exists(),
    }
    return render(request, "leaderboard.html", ctx)

