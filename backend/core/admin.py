# frontend/admin.py
from django.contrib import admin
from .models import WalletUser, Campaign, CampaignCode, Submission, Payout


@admin.register(WalletUser)
class WalletUserAdmin(admin.ModelAdmin):
    list_display = ("id", "address", "display_name", "email", "last_login", "is_admin", "created_at")
    search_fields = ("address", "display_name", "email")
    list_filter = ("is_admin", "created_at")
    ordering = ("-created_at",)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "slug", "task_type", "is_active",
        "reward_currency", "reward_amount", "quota_total",
        "submissions_count", "quota_remaining", "start_at", "end_at",
    )
    search_fields = ("title", "slug", "description", "client_site_domain")
    list_filter = ("task_type", "is_active", "reward_currency", "start_at", "end_at")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at",)


@admin.register(CampaignCode)
class CampaignCodeAdmin(admin.ModelAdmin):
    list_display = ("id", "campaign", "code", "is_used", "claimed_by", "claimed_at")
    list_filter = ("is_used", "campaign")
    search_fields = ("code",)
    autocomplete_fields = ("campaign", "claimed_by")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "campaign", "user", "status",
        "post_url", "visited_url", "code_entered",
        "proof_score", "rank_guess",
        "created_at", "reviewed_at",
    )
    list_filter = ("status", "campaign", "created_at")
    search_fields = ("user__address", "user__display_name", "post_url", "visited_url", "code_entered")
    autocomplete_fields = ("campaign", "user")
    readonly_fields = ("created_at",)


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "submission", "currency", "amount", "status", "tx_hash", "paid_at", "created_at")
    list_filter = ("status", "currency", "created_at")
    search_fields = ("tx_hash", "submission__user__address")
    autocomplete_fields = ("submission",)
    readonly_fields = ("created_at",)
