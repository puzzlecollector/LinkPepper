from django.shortcuts import render

def _base_url(request):
    return f"{request.scheme}://{request.get_host()}"

def _meta_for(lang, request):
    base = _base_url(request)  # 예: http://127.0.0.1:8000  /  https://linkpepper.com
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
