# frontend/admin.py
from django.contrib import admin
from .models import WalletUser, Campaign, CampaignCode, Submission, Payout, Event


def _is_img_src(val: str) -> bool:
    if not val:
        return False
    v = val.strip().lower()
    return v.startswith("http://") or v.startswith("https://") or v.startswith("data:image/")

def _img_preview_html(src: str, alt: str, size_px: int = 96):
    if not _is_img_src(src):
        return "-"
    return format_html(
        '<img src="{}" alt="{}" style="height:{}px;width:{}px;object-fit:contain;'
        'border:1px solid #ddd;border-radius:8px;padding:4px;background:#fff;" />',
        src, alt, size_px, size_px
    )

def _download_link_html(src: str, filename: str):
    if not _is_img_src(src):
        return "-"
    # Use data: URL directly (works for base64) or normal URL; set download filename hint
    return format_html(
        '<a href="{}" download="{}" class="button" '
        'style="display:inline-block;margin-top:6px;border:1px solid #ccc;'
        'padding:6px 10px;border-radius:6px;background:#f7f7f7;">Download</a>',
        src, filename
    )

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "lang", "is_published", "posted_at", "thumb_small")
    list_filter = ("lang", "is_published", "posted_at")
    search_fields = ("title", "slug", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "thumb_large", "thumb_download")
    date_hierarchy = "posted_at"
    ordering = ("-posted_at", "-id")

    fieldsets = (
        (None, {
            "fields": ("title", "slug", "lang", "is_published", "posted_at")
        }),
        ("Content", {
            "fields": ("summary", "body"),
        }),
        ("Thumbnail", {
            "fields": ("thumb_src", "thumb_large", "thumb_download"),
            "description": "Paste an http(s) URL or a data:image/*;base64,... value.",
        }),
        ("Meta", {
            "classes": ("collapse",),
            "fields": ("created_at",),
        }),
    )

    @admin.display(description="Thumb")
    def thumb_small(self, obj):
        return _img_preview_html(obj.thumb_src or "", f"{obj.title} thumb", size_px=48)

    @admin.display(description="Preview")
    def thumb_large(self, obj):
        return _img_preview_html(obj.thumb_src or "", f"{obj.title} thumb", size_px=160)

    @admin.display(description="Download")
    def thumb_download(self, obj):
        # a nice filename hint, e.g. event-my-slug.png
        return _download_link_html(obj.thumb_src or "", f"event-{obj.slug or obj.id}.png")

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
