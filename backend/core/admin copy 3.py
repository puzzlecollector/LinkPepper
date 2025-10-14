# apps/rewards/admin.py
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.db.models import Count, Sum

from .models import (
    WalletUser,
    CampaignApplication,
    Campaign,
    Submission,
    Payout,
    SubmissionStatus,
    TaskType,
    Network,
)

# ---------- Helpers

def _now():
    return timezone.now()

def _is_img_src(val: str) -> bool:
    """
    Accept http(s) URLs or data: URIs for inline base64 images.
    """
    if not val:
        return False
    v = val.strip().lower()
    return v.startswith("http://") or v.startswith("https://") or v.startswith("data:image/")

def _img_preview_html(src: str, alt: str, size_px: int = 32):
    if not _is_img_src(src):
        return "-"
    # Small, constrained preview so base64 blobs don’t blow up the list view.
    return format_html(
        '<img src="{}" alt="{}" style="height:{}px;width:{}px;object-fit:contain;border:1px solid #ddd;border-radius:4px;padding:2px;background:#fff;" />',
        src, alt, size_px, size_px
    )

# ---------- Reusable Filters

class NeedsReviewFilter(admin.SimpleListFilter):
    title = "Needs review"
    parameter_name = "needs_review"

    def lookups(self, request, model_admin):
        return (("yes", "Pending only"),)

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(status=SubmissionStatus.PENDING)
        return queryset


class HasPayoutFilter(admin.SimpleListFilter):
    title = "Has payout"
    parameter_name = "has_payout"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(payout__isnull=False)
        if self.value() == "no":
            return queryset.filter(payout__isnull=True)
        return queryset


class HasVisitCodeFilter(admin.SimpleListFilter):
    title = "Has visit code"
    parameter_name = "has_visit_code"

    def lookups(self, request, model_admin):
        return (("yes", "Yes"), ("no", "No"))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(visit_code__gt="")
        if self.value() == "no":
            return queryset.filter(visit_code__exact="")
        return queryset


# ---------- Inlines

class PayoutInline(admin.TabularInline):
    """
    Each Submission can have one Payout (OneToOne). Show/edit it inline from the submission.
    """
    model = Payout
    extra = 0
    fields = ("amount_usdt", "token_symbol", "network", "tx_hash", "paid_at", "paid_by", "note")
    readonly_fields = ()
    autocomplete_fields = ("paid_by",)
    show_change_link = True


# ---------- WalletUser

@admin.register(WalletUser)
class WalletUserAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "address",
        "display_name",
        "email",
        "last_login",
        "is_admin",
        "created_at",
        "submissions_count",
        "total_paid_usdt",
    )
    search_fields = ("address", "display_name", "email")
    list_filter = ("is_admin", "created_at")
    readonly_fields = ("created_at", "updated_at", "last_login")
    ordering = ("-created_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Count submissions and sum payouts linked via submission
        return qs.annotate(
            _subs=Count("submissions", distinct=True),
            _paid_sum=Sum("submissions__payout__amount_usdt"),
        )

    @admin.display(description="Submissions")
    def submissions_count(self, obj):
        return getattr(obj, "_subs", 0)

    @admin.display(description="Total paid (USDT)")
    def total_paid_usdt(self, obj):
        val = getattr(obj, "_paid_sum", None)
        return "0" if val is None else val


# ---------- CampaignApplication

@admin.register(CampaignApplication)
class CampaignApplicationAdmin(admin.ModelAdmin):
    """
    Intake applications from /rewards/apply/. Admins can review and convert to Campaigns.
    """
    list_display = (
        "id",
        "email",
        "phone",
        "country",
        "campaign_title",
        "website_url",
        "created_at",
        "handled",
        "wants_visit",
        "wants_link",
    )
    search_fields = ("email", "phone", "campaign_title", "website_url")
    list_filter = ("handled", "created_at", "country", "wants_visit", "wants_link")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    actions = ("mark_handled", "convert_to_campaigns")

    @admin.action(description="Mark selected as handled")
    def mark_handled(self, request, qs):
        updated = qs.update(handled=True)
        self.message_user(request, f"Marked {updated} application(s) as handled.", level=messages.SUCCESS)

    @admin.action(description="Convert to draft Campaign(s)")
    def convert_to_campaigns(self, request, qs):
        created = 0
        for app in qs:
            # Create a draft/paused campaign with safe defaults; admin can edit then publish.
            camp = Campaign.objects.create(
                title=app.campaign_title or f"Campaign from {app.email}",
                summary=app.website_description or "",
                long_description=app.website_description or "",
                task_type=(
                    TaskType.VISIT if app.wants_visit and not app.wants_link else
                    (TaskType.LINK if app.wants_link and not app.wants_visit else TaskType.VISIT)
                ),
                # carry over visit code if provided
                visit_code=app.visit_code or "",
                code_instructions="",
                client_site_domain=app.website_url or "",
                seo_keywords=app.current_seo_keywords or "",
                image_url=app.thumbnail_url or "",
                favicon_url=app.favicon_url or "",
                pool_usdt=app.reward_pool_usdt or 0,
                payout_usdt=app.payout_per_task_usdt or 0,
                start=app.start_date or timezone.localdate(),
                end=app.end_date or timezone.localdate(),
                airdrop_enabled=app.airdrop_enabled,
                airdrop_first_n=app.airdrop_first_n,
                airdrop_amount_per_user=app.airdrop_amount_per_user,
                airdrop_token_symbol=app.airdrop_token_symbol or "",
                airdrop_network=app.airdrop_network or "",
                airdrop_note=app.airdrop_note or "",
                is_published=False,   # hidden until admin reviews
                is_paused=True,       # paused by default
                source_application=app,
            )
            app.handled = True
            app.save(update_fields=["handled"])
            created += 1
        self.message_user(
            request, f"Created {created} draft campaign(s). Edit and publish when ready.",
            level=messages.SUCCESS
        )


# ---------- Campaign

# ---------- Campaign

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "slug",
        "task_type",
        "is_published",
        "is_paused",
        "pool_usdt",
        "payout_usdt",
        "participants",
        "claimed_percent",
        "start",
        "end",
        "client_site_domain",
        "visit_code",
        "favicon_small",  # small preview
        "image_small",    # small preview
        "preview",        # clickable frontend preview
    )

    # REQUIRED so other admins can autocomplete Campaign:
    search_fields = (
        "title",
        "slug",
        "summary",
        "long_description",
        "client_site_domain",
        "seo_keywords",
        "visit_code",
    )

    list_filter = ("task_type", HasVisitCodeFilter, "is_published", "is_paused", "start", "end")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at", "image_large_preview", "favicon_large_preview")
    date_hierarchy = "start"
    ordering = ("-start", "-id")

    fieldsets = (
        (None, {
            "fields": ("title", "slug", "task_type", "summary", "long_description")
        }),
        ("Verification (VISIT tasks)", {
            "fields": ("code_instructions", "visit_code"),
            "description": "For VISIT campaigns, provide user-facing instructions and the actual verification code.",
        }),
        ("Client & SEO", {
            "fields": ("client_site_domain", "seo_keywords"),
        }),
        ("Assets", {
            "fields": ("image_url", "favicon_url", "image_large_preview", "favicon_large_preview"),
            "description": "You can use an http(s) URL or a data:image/*;base64,... data URI.",
        }),
        ("Rewards & Window", {
            "fields": ("pool_usdt", "payout_usdt", "start", "end"),
        }),
        ("Airdrop (optional)", {
            "classes": ("collapse",),
            "fields": ("airdrop_enabled", "airdrop_first_n", "airdrop_amount_per_user",
                       "airdrop_token_symbol", "airdrop_network", "airdrop_note"),
        }),
        ("Publishing", {
            "fields": ("is_published", "is_paused", "source_application"),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at", "updated_at"),
        }),
    )

    # small previews for list view
    @admin.display(description="Favicon")
    def favicon_small(self, obj):
        return _img_preview_html(getattr(obj, "favicon_url", ""), f"{obj.title} favicon", size_px=16)

    @admin.display(description="Image")
    def image_small(self, obj):
        return _img_preview_html(getattr(obj, "image_url", ""), f"{obj.title} image", size_px=32)

    # larger previews on the detail page
    @admin.display(description="Image preview")
    def image_large_preview(self, obj):
        return _img_preview_html(getattr(obj, "image_url", ""), f"{obj.title} image", size_px=120)

    @admin.display(description="Favicon preview")
    def favicon_large_preview(self, obj):
        return _img_preview_html(getattr(obj, "favicon_url", ""), f"{obj.title} favicon", size_px=48)

    # frontend preview link (restores the missing callable)
    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.slug:
            return "-"
        return format_html(
            '<a href="/rewards/{slug}-{id}/" target="_blank" rel="noopener">Open</a>',
            slug=obj.slug, id=obj.id
        )

# ---------- Submission

@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "campaign",
        "user",
        "wallet_address",
        "network",
        "status",
        "post_url",
        "visited_url",
        "code_entered",
        "proof_score",
        "is_approved",
        "is_paid",
        "created_at",
        "reviewed_at",
        "payout_admin_link",
    )
    list_filter = (
        NeedsReviewFilter,
        HasPayoutFilter,
        "status",
        "campaign",
        "network",
        "is_approved",
        "is_paid",
        "created_at",
    )
    search_fields = (
        "wallet_address",
        "user__address",
        "user__display_name",
        "user__email",
        "post_url",
        "visited_url",
        "code_entered",
        "comment",
    )
    autocomplete_fields = ("campaign", "user")
    readonly_fields = ("created_at",)
    inlines = (PayoutInline,)
    list_select_related = ("campaign", "user")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    actions = (
        "mark_approved",
        "mark_rejected",
        "create_payouts_for_selected",
        "set_score_1",
        "set_score_3",
        "set_score_5",
    )

    @admin.display(description="Payout")
    def payout_admin_link(self, obj):
        payout = getattr(obj, "payout", None)
        if not payout:
            return "-"
        return format_html(
            '<a href="/admin/{app}/{model}/{pk}/change/">View</a>',
            app=Payout._meta.app_label,
            model=Payout._meta.model_name,
            pk=payout.pk,
        )

    # ----- Actions

    @admin.action(description="Approve (status=APPROVED)")
    def mark_approved(self, request, qs):
        n = 0
        for s in qs:
            # Use model helper to keep fields consistent
            s.mark_approved(reviewer=request.user)
            n += 1
        self.message_user(request, f"Approved {n} submission(s).", level=messages.SUCCESS)

    @admin.action(description="Reject (status=REJECTED)")
    def mark_rejected(self, request, qs):
        n = qs.update(
            status=SubmissionStatus.REJECTED,
            is_approved=False,
            reviewed_at=_now(),
            reviewed_by=request.user,
        )
        self.message_user(request, f"Rejected {n} submission(s).", level=messages.WARNING)

    @admin.action(description="Create payouts for selected (if missing)")
    def create_payouts_for_selected(self, request, qs):
        created = 0
        for s in qs.select_related("campaign"):
            if getattr(s, "payout", None):
                continue
            if not s.campaign:
                continue
            # Default values: use campaign.payout_usdt, submission.network, token USDT
            amount = s.campaign.payout_usdt or 0
            Payout.objects.create(
                submission=s,
                campaign=s.campaign,
                amount_usdt=amount,
                token_symbol="USDT",
                network=s.network,
                paid_at=_now(),           # editable later if needed
                paid_by=request.user,
            )
            created += 1
        self.message_user(request, f"Created {created} payout(s).", level=messages.SUCCESS)

    # quick proof_score helpers (tweak as desired)
    @admin.action(description="Set proof score = 1")
    def set_score_1(self, request, qs):
        n = qs.update(proof_score=1)
        self.message_user(request, f"Set score=1 for {n} submission(s).", level=messages.INFO)

    @admin.action(description="Set proof score = 3")
    def set_score_3(self, request, qs):
        n = qs.update(proof_score=3)
        self.message_user(request, f"Set score=3 for {n} submission(s).", level=messages.INFO)

    @admin.action(description="Set proof score = 5")
    def set_score_5(self, request, qs):
        n = qs.update(proof_score=5)
        self.message_user(request, f"Set score=5 for {n} submission(s).", level=messages.INFO)


# ---------- Payout

@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "submission",
        "campaign",
        "amount_usdt",
        "token_symbol",
        "network",
        "tx_hash",
        "paid_at",
        "paid_by",
        "user_wallet",
    )
    list_filter = ("token_symbol", "network", "paid_at", "paid_by")
    search_fields = (
        "tx_hash",
        "submission__wallet_address",
        "submission__user__address",
        "submission__user__display_name",
        "campaign__title",
    )
    autocomplete_fields = ("submission", "campaign", "paid_by")
    date_hierarchy = "paid_at"
    ordering = ("-paid_at",)

    @admin.display(description="User wallet")
    def user_wallet(self, obj):
        try:
            return obj.submission.wallet_address
        except Exception:
            return "-"
