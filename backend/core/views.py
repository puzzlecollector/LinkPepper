# backend/core/views.py
from django.shortcuts import render

def _base_url(request):
    return f"{request.scheme}://{request.get_host()}"

def _meta_for(lang, request, *, page="home"):
    base = _base_url(request)  # e.g. http://127.0.0.1:8000

    if page == "rewards":
        if lang == "ko":
            return {
                "lang": "ko",
                "title": "LinkPepper | 리워드 프로그램",
                "description": "백링크 & SEO 캠페인에 참여하고 리워드를 받아가세요.",
                "og_title": "LinkPepper 리워드",
                "og_description": "링크 공유/방문 과제 참여하고 USDT 보상을 받으세요.",
                "canonical": f"{base}/ko/rewards/",
                "url": f"{base}/ko/rewards/",
            }
        else:
            return {
                "lang": "en",
                "title": "LinkPepper | Rewards Program",
                "description": "Join our backlink & SEO campaigns and earn rewards.",
                "og_title": "LinkPepper Rewards",
                "og_description": "Complete link share/visit tasks and earn USDT.",
                "canonical": f"{base}/rewards/",
                "url": f"{base}/rewards/",
            }

    # 기본 홈 메타
    if lang == "ko":
        return {
            "lang": "ko",
            "title": "LinkPepper | 백링크 · SEO · 페이지 상위",
            "description": "데이터 기반 백링크 & SEO. 백링크, SEO, 페이지 상위 노출을 위한 화이트햇 전략과 투명 리포트.",
            "og_title": "LinkPepper | 백링크 · SEO · 페이지 상위",
            "og_description": "데이터 기반 백링크 & SEO. 화이트햇 전략으로 안전하게 순위를 올리세요.",
            "canonical": f"{base}/ko/",
            "url": f"{base}/ko/",
        }
    else:
        return {
            "lang": "en",
            "title": "LinkPepper | Backlinks · SEO · Rank Higher",
            "description": "Data-driven backlinks & SEO. White-hat strategy and transparent reporting to rank safely.",
            "og_title": "LinkPepper | Backlinks · SEO · Rank Higher",
            "og_description": "Boost rankings safely with white-hat, data-driven link building.",
            "canonical": f"{base}/",
            "url": f"{base}/",
        }

def home_en(request):
    return render(request, "home.html", {"meta": _meta_for("en", request)})

def home_ko(request):
    return render(request, "home.html", {"meta": _meta_for("ko", request)})

# ✅ 리워드 페이지
def rewards_en(request):
    ctx = {"meta": _meta_for("en", request, page="rewards"), "lang": "en"}
    return render(request, "rewards.html", ctx)

def rewards_ko(request):
    ctx = {"meta": _meta_for("ko", request, page="rewards"), "lang": "ko"}
    return render(request, "rewards.html", ctx)


def rewards_apply_en(request):
    base = f"{request.scheme}://{request.get_host()}"
    meta = {
        "lang": "en",
        "title": "Apply | LinkPepper Rewards",
        "description": "Apply to run a LinkPepper reward campaign.",
        "og_title": "Apply | LinkPepper Rewards",
        "og_description": "Submit your campaign request. We reply within 24h.",
        "canonical": f"{base}/rewards/apply/",
        "url": f"{base}/rewards/apply/",
    }
    return render(request, "rewards_apply.html", {"meta": meta})

def rewards_apply_ko(request):
    base = f"{request.scheme}://{request.get_host()}"
    meta = {
        "lang": "ko",
        "title": "신청 | LinkPepper 리워드",
        "description": "LinkPepper 리워드 캠페인 신청 페이지.",
        "og_title": "신청 | LinkPepper 리워드",
        "og_description": "캠페인 신청을 남겨 주세요. 24시간 내 회신합니다.",
        "canonical": f"{base}/rewards/apply/ko/",
        "url": f"{base}/rewards/apply/ko/",
    }
    return render(request, "rewards_apply.html", {"meta": meta})
