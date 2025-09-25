# backend/core/views.py
import json
import secrets

from django.db import IntegrityError
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from eth_account.messages import encode_defunct
from eth_account import Account

# NOTE: adjust this import if your models live elsewhere
from .models import WalletUser, Campaign, Submission


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
    m = _meta_for(lang, request).copy()
    if lang == "ko":
        m.update({
            "title": "LinkHash | 이벤트 · 공지",
            "og_title": "LinkHash | 이벤트 · 공지",
            "canonical": f"{_base_url(request)}/ko/events/",
            "url": f"{_base_url(request)}/ko/events/",
        })
    else:
        m.update({
            "title": "LinkHash | Events & Announcements",
            "og_title": "LinkHash | Events & Announcements",
            "canonical": f"{_base_url(request)}/events/",
            "url": f"{_base_url(request)}/events/",
        })
    return m


def events_en(request):
    return render(
        request,
        "events.html",
        {"meta": _meta_for_events("en", request), "wallet_user": get_wallet_user(request)},
    )


def events_ko(request):
    return render(
        request,
        "events.html",
        {"meta": _meta_for_events("ko", request), "wallet_user": get_wallet_user(request)},
    )


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
