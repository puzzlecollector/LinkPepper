# backend/config/urls.py
from django.contrib import admin
from django.urls import path
from core import views as v   # ← absolute import from the 'core' app

urlpatterns = [
    path('admin/', admin.site.urls),

    # pages
    path("", v.home_en, name="home_en"),
    path("ko/", v.home_ko, name="home_ko"),
    path("rewards/", v.rewards_en, name="rewards_en"),
    path("ko/rewards/", v.rewards_ko, name="rewards_ko"),
    path("rewards/apply/", v.rewards_apply_en, name="rewards_apply_en"),
    path("rewards/apply/ko/", v.rewards_apply_ko, name="rewards_apply_ko"),
    path("events/", v.events_en, name="events_en"),
    path("ko/events/", v.events_ko, name="events_ko"),

    # wallet auth API
    path("api/auth/nonce", v.api_nonce, name="api_nonce"),
    path("api/auth/verify", v.api_verify, name="api_verify"),
    path("api/auth/logout", v.api_logout, name="api_logout"),

    # reward submission endpoints
    path("rewards/submit/link/<slug:slug>/", v.submit_link, name="submit_link"),
    path("rewards/submit/visit/<slug:slug>/", v.submit_visit, name="submit_visit"),

    # Campaign detail (pretty URL like: /rewards/simplequant-blog-launch-5/)
    path("rewards/<slug:slug>-<int:pk>/", v.rewards_detail, name="rewards_detail"),

        # leaderboard
    path("leaderboard/", v.leaderboard_en, name="leaderboard_en"),
    path("ko/leaderboard/", v.leaderboard_ko, name="leaderboard_ko"),



]
