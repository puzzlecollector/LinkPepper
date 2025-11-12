# backend/config/urls.py
from django.contrib import admin
from django.urls import path, include
from core import views as v
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # ===== Home
    path("", v.home_en, name="home_en"),          # autodetects & can redirect via middleware
    path("ko/", v.home_ko, name="home_ko"),
    path("ja/", v.home_ja, name="home_ja"),
    path("zh/", v.home_zh, name="home_zh"),

    # ===== Rewards (list)
    path("rewards/", v.rewards_en, name="rewards_en"),
    path("ko/rewards/", v.rewards_ko, name="rewards_ko"),
    path("ja/rewards/", v.rewards_ja, name="rewards_ja"),
    path("zh/rewards/", v.rewards_zh, name="rewards_zh"),

    # ===== Rewards (apply)
    path("rewards/apply/", v.rewards_apply_en, name="rewards_apply_en"),
    path("rewards/apply/ko/", v.rewards_apply_ko, name="rewards_apply_ko"),
    path("rewards/apply/ja/", v.rewards_apply_ja, name="rewards_apply_ja"),
    path("rewards/apply/zh/", v.rewards_apply_zh, name="rewards_apply_zh"),

    # ===== Events
    path("events/", v.events_en, name="events_en"),
    path("ko/events/", v.events_ko, name="events_ko"),
    path("ja/events/", v.events_ja, name="events_ja"),
    path("zh/events/", v.events_zh, name="events_zh"),

    # ===== Leaderboard
    path("leaderboard/", v.leaderboard_en, name="leaderboard_en"),
    path("ko/leaderboard/", v.leaderboard_ko, name="leaderboard_ko"),
    path("ja/leaderboard/", v.leaderboard_ja, name="leaderboard_ja"),
    path("zh/leaderboard/", v.leaderboard_zh, name="leaderboard_zh"),

    # ===== Wallet auth API
    path("api/auth/nonce", v.api_nonce, name="api_nonce"),
    path("api/auth/verify", v.api_verify, name="api_verify"),
    path("api/auth/logout", v.api_logout, name="api_logout"),

    # ===== Reward submission endpoints
    path("rewards/submit/link/<slug:slug>/", v.submit_link, name="submit_link"),
    path("rewards/submit/visit/<slug:slug>/", v.submit_visit, name="submit_visit"),

    # ===== Campaign detail (pretty URL like: /rewards/simplequant-blog-launch-5/)
    path("rewards/<slug:slug>-<int:pk>/", v.rewards_detail, name="rewards_detail"),

    path("api/rewards/apply", v.rewards_apply_submit, name="rewards_apply_submit"),

    path("ckeditor/", include("ckeditor_uploader.urls")), 

    path("advertiser/", v.advertiser_en, name="advertiser_en"),
    path("ko/advertiser/", v.advertiser_ko, name="advertiser_ko"),
    path("ja/advertiser/", v.advertiser_ja, name="advertiser_ja"),
    path("zh/advertiser/", v.advertiser_zh, name="advertiser_zh"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)