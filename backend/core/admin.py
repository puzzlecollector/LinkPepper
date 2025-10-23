# apps/rewards/admin.py
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.db.models import Count, Sum
import os
from django import forms
from django.core.files.storage import default_storage
from django.utils.text import slugify
from ckeditor_uploader.widgets import CKEditorUploadingWidget
from .models import (
    WalletUser,
    CampaignApplication,
    Campaign,
    Submission,
    Payout,
    SubmissionStatus,
    TaskType,
    Network,
    Event
)

# ---------- Helpers

def _now():
    return timezone.now()

def _is_img_src(val: str) -> bool:
    """
    Accept http(s), data: URIs, and common local dev paths (/media, /static).
    """
    if not val:
        return False
    v = val.strip().lower()
    return (
        v.startswith("http://")
        or v.startswith("https://")
        or v.startswith("data:image/")
        or v.startswith("/media/")
        or v.startswith("/static/")
    )

def _ext_from_data_uri(src: str) -> str:
    """
    Best-effort guess of file extension from a data:image/*;... URI.
    """
    try:
        head = src.split(";")[0]  # e.g. "data:image/png"
        mime = head.split(":")[1]  # e.g. "image/png"
        subtype = mime.split("/")[1]  # e.g. "png"
        # normalize a few common cases
        mapping = {
            "jpeg": "jpg",
            "svg+xml": "svg",
            "x-icon": "ico",
            "webp": "webp",
            "png": "png",
            "gif": "gif",
            "bmp": "bmp",
        }
        return mapping.get(subtype, subtype)
    except Exception:
        return "png"

def _img_with_download(src: str, alt: str, size_px: int = 32, filename_hint: str = "image") -> str:
    """
    Render a small preview and a Download button.
    Works for http(s) URLs and data:image/* base64 URIs.
    """
    if not _is_img_src(src):
        return "-"

    # Decide filename
    if src.strip().lower().startswith("data:image/"):
        ext = _ext_from_data_uri(src)
        dl_name = f"{filename_hint}.{ext}"
    else:
        # try to take last path segment; fallback to hint
        from urllib.parse import urlparse
        try:
            parsed = urlparse(src)
            last = (parsed.path.rsplit("/", 1)[-1] or filename_hint).split("?")[0]
            dl_name = last if "." in last else f"{filename_hint}.png"
        except Exception:
            dl_name = f"{filename_hint}.png"

    return format_html(
        '<div style="display:flex;gap:10px;align-items:center;">'
        '  <img src="{}" alt="{}" style="height:{}px;width:{}px;object-fit:contain;'
        '       border:1px solid #ddd;border-radius:4px;padding:2px;background:#fff;" />'
        '  <a href="{}" download="{}" style="text-decoration:none;">Download</a>'
        '</div>',
        src, alt, size_px, size_px, src, dl_name
    )

def _img_preview_html(src: str, alt: str, size_px: int = 32):
    # kept for backward-compat in case you use it elsewhere
    return _img_with_download(src, alt, size_px=size_px, filename_hint=alt.replace(" ", "_").lower())

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
        "favicon_small",    # NEW: small preview + download
        "thumbnail_small",  # NEW: small preview + download
        "currency", 
        "currency_network",  
    )
    search_fields = ("email", "phone", "campaign_title", "website_url", "currency", "currency_network")
    list_filter = ("handled", "created_at", "country", "wants_visit", "wants_link",  "currency", "currency_network")
    readonly_fields = ("created_at", "favicon_large_preview", "thumbnail_large_preview")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {
            "fields": ("email", "phone", "country", "campaign_title", "website_url", "handled")
        }),
        ("Task type (from form)", {
            "fields": ("wants_visit", "wants_link"),
            "description": "Exactly one should be true (Visit OR Link).",
        }),
        ("Dates & Budget", {
            "fields": (
                "start_date", "end_date",
                "reward_pool_usdt", "payout_per_task_usdt",
                "currency", "currency_network",   # <<< NEW
            ),
        }),
        ("Verification & SEO", {
            "fields": ("visit_code", "current_seo_keywords"),
        }),
        ("Assets (URL or data URI)", {
            "fields": ("favicon_url", "thumbnail_url", "favicon_large_preview", "thumbnail_large_preview"),
            "description": "Preview + Download works for http(s) and base64 data URIs.",
        }),
        ("Airdrop (optional)", {
            "classes": ("collapse",),
            "fields": ("airdrop_enabled", "airdrop_first_n", "airdrop_amount_per_user",
                       "airdrop_token_symbol", "airdrop_network", "airdrop_note"),
        }),
    )


    # --- Small previews in list view
    @admin.display(description="Favicon")
    def favicon_small(self, obj):
        src = getattr(obj, "favicon_url", "") or ""
        hint = f"app_{obj.pk}_favicon"
        return _img_with_download(src, f"{obj.campaign_title} favicon", size_px=16, filename_hint=hint)

    @admin.display(description="Thumbnail")
    def thumbnail_small(self, obj):
        src = getattr(obj, "thumbnail_url", "") or ""
        hint = f"app_{obj.pk}_thumbnail"
        return _img_with_download(src, f"{obj.campaign_title} thumbnail", size_px=32, filename_hint=hint)

    # --- Large previews on detail page (with Download buttons)
    @admin.display(description="Favicon preview")
    def favicon_large_preview(self, obj):
        src = getattr(obj, "favicon_url", "") or ""
        hint = f"app_{obj.pk}_favicon"
        return _img_with_download(src, f"{obj.campaign_title} favicon", size_px=48, filename_hint=hint)

    @admin.display(description="Thumbnail preview")
    def thumbnail_large_preview(self, obj):
        src = getattr(obj, "thumbnail_url", "") or ""
        hint = f"app_{obj.pk}_thumbnail"
        return _img_with_download(src, f"{obj.campaign_title} thumbnail", size_px=120, filename_hint=hint)

    actions = ("mark_handled", "convert_to_campaigns")

    @admin.action(description="Mark selected as handled")
    def mark_handled(self, request, qs):
        updated = qs.update(handled=True)
        self.message_user(request, f"Marked {updated} application(s) as handled.", level=messages.SUCCESS)

    @admin.action(description="Convert to draft Campaign(s)")
    def convert_to_campaigns(self, request, qs):
        created = 0
        for app in qs:
            camp = Campaign.objects.create(
                title=app.campaign_title or f"Campaign from {app.email}",
                summary=app.website_description or "",
                long_description=app.website_description or "",
                task_type=(
                    TaskType.VISIT if app.wants_visit and not app.wants_link else
                    (TaskType.LINK if app.wants_link and not app.wants_visit else TaskType.VISIT)
                ),
                visit_code=app.visit_code or "",
                code_instructions="",
                client_site_domain=app.website_url or "",
                seo_keywords=app.current_seo_keywords or "",
                image_url=app.thumbnail_url or "",
                favicon_url=app.favicon_url or "",
                pool_usdt=app.reward_pool_usdt or 0,
                payout_usdt=app.payout_per_task_usdt or 0,
                currency=app.currency,
                currency_network=app.currency_network or Network.ETH,
                start=app.start_date or timezone.localdate(),
                end=app.end_date or timezone.localdate(),
                airdrop_enabled=app.airdrop_enabled,
                airdrop_first_n=app.airdrop_first_n,
                airdrop_amount_per_user=app.airdrop_amount_per_user,
                airdrop_token_symbol=app.airdrop_token_symbol or "",
                airdrop_network=app.airdrop_network or "",
                airdrop_note=app.airdrop_note or "",
                is_published=False,
                is_paused=True,
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

# ---------- Campaign

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    """
    Rich text friendly:
    - CKEditor (with uploader) for long_description / code_instructions.
    - Two OPTIONAL file inputs that append an <img> into those fields.
    - Uploaded files are stored under /media/campaigns/body/ and /media/campaigns/instructions/.
    """

    # >>> ADD the two ImageFields to the form so Admin knows these fields exist <<<
    class Form(forms.ModelForm):
        long_desc_image_upload = forms.ImageField(
            required=False, help_text="Append image to Long description"
        )
        code_instr_image_upload = forms.ImageField(
            required=False, help_text="Append image to Code instructions"
        )

        class Meta:
            model = Campaign
            fields = "__all__"
            widgets = {
                "long_description": CKEditorUploadingWidget(config_name="default"),
                "code_instructions": CKEditorUploadingWidget(config_name="default"),
            }

    form = Form

    list_display = (
        "id", "title", "slug", "task_type", "is_published", "is_paused",
        "pool_usdt", "payout_usdt", "participants", "claimed_percent",
        "start", "end", "client_site_domain", "visit_code",
        "favicon_small", "image_small", "preview", "currency", "currency_network", 
    )

    search_fields = (
        "title", "slug", "summary", "long_description",
        "client_site_domain", "seo_keywords", "visit_code", "currency", "currency_network", 
    )

    list_filter = ("task_type", HasVisitCodeFilter, "is_published", "is_paused", "start", "end",
                   "currency", "currency_network", )
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at", "image_large_preview", "favicon_large_preview")
    date_hierarchy = "start"
    ordering = ("-start", "-id")

    fieldsets = (
        (None, {
            "fields": ("title", "slug", "task_type", "summary", "long_description"),
        }),
        ("Verification (VISIT tasks)", {
            "fields": ("code_instructions", "visit_code"),
        }),
        ("Client & SEO", {
            "fields": ("client_site_domain", "seo_keywords"),
        }),
        ("Assets", {
            "fields": ("image_url", "favicon_url", "image_large_preview", "favicon_large_preview"),
        }),
        ("Rewards & Window", {
            "fields": (
                "pool_usdt", "payout_usdt",
                "currency", "currency_network",     # <<< NEW
                "start", "end",
            ),
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


    # small previews for list view (with Download)
    @admin.display(description="Favicon")
    def favicon_small(self, obj):
        src = getattr(obj, "favicon_url", "") or ""
        hint = f"campaign_{obj.pk}_favicon"
        return _img_with_download(src, f"{obj.title} favicon", size_px=16, filename_hint=hint)

    @admin.display(description="Image")
    def image_small(self, obj):
        src = getattr(obj, "image_url", "") or ""
        hint = f"campaign_{obj.pk}_image"
        return _img_with_download(src, f"{obj.title} image", size_px=32, filename_hint=hint)

    # larger previews on the detail page (with Download)
    @admin.display(description="Image preview")
    def image_large_preview(self, obj):
        src = getattr(obj, "image_url", "") or ""
        hint = f"campaign_{obj.pk}_image"
        return _img_with_download(src, f"{obj.title} image", size_px=120, filename_hint=hint)

    @admin.display(description="Favicon preview")
    def favicon_large_preview(self, obj):
        src = getattr(obj, "favicon_url", "") or ""
        hint = f"campaign_{obj.pk}_favicon"
        return _img_with_download(src, f"{obj.title} favicon", size_px=48, filename_hint=hint)

    # frontend preview link
    @admin.display(description="Preview")
    def preview(self, obj):
        if not obj.slug:
            return "-"
        return format_html(
            '<a href="/rewards/{slug}-{id}/" target="_blank" rel="noopener">Open</a>',
            slug=obj.slug, id=obj.id
        )

    # Save uploads and append <img> tags to the HTML fields
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)



# ---------- Submission

# --- Custom form for Submission: relabel fields
class SubmissionAdminForm(forms.ModelForm):
    class Meta:
        model = Submission
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "comment" in self.fields:
            self.fields["comment"].label = "User Comment"  # read-only (via ModelAdmin)
        if "admin_comment" in self.fields:
            self.fields["admin_comment"].label = "Admin Comment"  # editable


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    form = SubmissionAdminForm

    list_display = (
        "id", "campaign", "user", "wallet_address", "network", "status",
        "post_url", "visited_url", "code_entered",
        "campaign_currency", "campaign_currency_network",
        "proof_score", "is_approved", "is_paid",
        "user_comment_short", "admin_comment_short",  # NEW columns
        "created_at", "reviewed_at", "payout_admin_link",
    )

    list_filter = (
        NeedsReviewFilter, HasPayoutFilter, "status", "campaign", "network",
        "is_approved", "is_paid", "created_at",
    )

    search_fields = (
        "wallet_address",
        "user__address", "user__display_name", "user__email",
        "post_url", "visited_url", "code_entered",
        "comment",       # user comment (read-only here)
        "admin_comment", # admin comment (editable)
    )

    autocomplete_fields = ("campaign", "user")

    # Make user comment read-only; admin_comment remains editable
    readonly_fields = ("created_at", "comment")  # <- comment shown but not editable

    inlines = (PayoutInline,)
    list_select_related = ("campaign", "user")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    # Optional: organize the form with fieldsets so comments are obvious
    fieldsets = (
        (None, {
            "fields": (
                "campaign", "user", "wallet_address", "network",
                "status", "proof_score", "is_approved", "is_paid",
            )
        }),
        ("Payout Info", {
            "fields": ("campaign_currency", "campaign_currency_network",),
        }),
        ("Task Data", {
            "fields": ("post_url", "visited_url", "code_entered"),
        }),
        ("Comments", {  # <- clear grouping
            "fields": ("comment", "admin_comment"),
            "description": "“User Comment” is read-only (what the user submitted). “Admin Comment” is visible on the public page."
        }),
        ("Review", {
            "fields": ("reviewed_at",),
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at",),
        }),
    )

    @admin.display(description="Currency")
    def campaign_currency(self, obj):
        return getattr(getattr(obj, "campaign", None), "currency", None) or "-"

    @admin.display(description="Currency Net")
    def campaign_currency_network(self, obj):
        net = getattr(getattr(obj, "campaign", None), "currency_network", None)
        return net or "-"

    # ---------- List table helper columns ----------
    @admin.display(description="User Comment")
    def user_comment_short(self, obj):
        txt = (obj.comment or "").strip()
        return (txt[:80] + "…") if len(txt) > 80 else (txt or "-")

    @admin.display(description="Admin Comment")
    def admin_comment_short(self, obj):
        txt = (obj.admin_comment or "").strip()
        return (txt[:80] + "…") if len(txt) > 80 else (txt or "-")

    # ---------- Payout link ----------
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

    # ---------- Actions (unchanged) ----------
    @admin.action(description="Approve (status=APPROVED)")
    def mark_approved(self, request, qs):
        n = 0
        for s in qs:
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
            amount = s.campaign.payout_usdt or 0
            Payout.objects.create(
                submission=s,
                campaign=s.campaign,
                amount_usdt=amount,
                token_symbol="USDT",
                network=s.network,
                paid_at=_now(),
                paid_by=request.user,
            )
            created += 1
        self.message_user(request, f"Created {created} payout(s).", level=messages.SUCCESS)

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


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    """
    Event CRUD with file-uploaded thumbnail.
    - Shows an <input type="file"> in the form (thumb_upload)
    - Stores the uploaded file in default storage and writes its URL to Event.thumb_src
    - Keeps a large/small preview with a Download link
    """
    class Form(forms.ModelForm):
        thumb_upload = forms.ImageField(
            required=False,
            help_text="Upload a thumbnail image (PNG/JPG/WebP/SVG). "
                      "This will overwrite the current thumbnail."
        )

        class Meta:
            model = Event
            # We exclude thumb_src so users don't edit the raw URL/data URI.
            exclude = ("thumb_src",)

    form = Form

    list_display = (
        "id", "title", "lang", "is_published", "posted_at",
        "thumb_small", "open_link",
    )
    list_filter = ("is_published", "lang", "posted_at")
    search_fields = ("title", "slug", "summary", "body")
    prepopulated_fields = {"slug": ("title",)}
    date_hierarchy = "posted_at"
    ordering = ("-posted_at", "-id")
    readonly_fields = ("created_at", "thumb_large_preview")

    fieldsets = (
        (None, {
            "fields": ("title", "slug", "lang", "is_published", "posted_at"),
        }),
        ("Content", {
            "fields": ("summary", "body"),
        }),
        ("Thumbnail", {
            "fields": ("thumb_upload", "thumb_large_preview"),
            "description": "Upload a new image to replace the thumbnail. "
                           "Preview updates after you save.",
        }),
        ("Timestamps", {
            "classes": ("collapse",),
            "fields": ("created_at",),
        }),
    )

    actions = ("publish_selected", "unpublish_selected", "duplicate_selected")

    # ---------- previews / columns

    @admin.display(description="Thumbnail")
    def thumb_small(self, obj):
        src = getattr(obj, "thumb_src", "") or ""
        hint = f"event_{obj.pk}_thumb"
        return _img_with_download(src, f"{obj.title} thumbnail", size_px=32, filename_hint=hint)

    @admin.display(description="Thumbnail preview")
    def thumb_large_preview(self, obj):
        src = getattr(obj, "thumb_src", "") or ""
        hint = f"event_{obj.pk}_thumb"
        return _img_with_download(src, f"{obj.title} thumbnail", size_px=120, filename_hint=hint)

    @admin.display(description="Open")
    def open_link(self, obj):
        if not obj.slug:
            return "-"
        return format_html('<a href="/events/{}/" target="_blank" rel="noopener">View</a>', obj.slug)

    # ---------- save hook to persist uploaded file

    def save_model(self, request, obj, form, change):
        """
        If an image was uploaded, store it and write its URL to obj.thumb_src.
        """
        upload = form.cleaned_data.get("thumb_upload")
        if upload:
            # Build a stable-ish filename
            base = slugify(obj.slug or obj.title) or "event"
            root, ext = os.path.splitext(upload.name or "")
            if not ext:
                # fallback if no extension present
                ext = ".png"
            filename = f"events/thumbs/{base}{ext}"

            # If file exists, make it unique (append counter)
            if default_storage.exists(filename):
                i = 2
                while default_storage.exists(f"events/thumbs/{base}-{i}{ext}"):
                    i += 1
                filename = f"events/thumbs/{base}-{i}{ext}"

            # Save to storage; default_storage will handle chunks if needed
            saved_path = default_storage.save(filename, upload)
            obj.thumb_src = default_storage.url(saved_path)

        super().save_model(request, obj, form, change)

    # ---------- actions

    @admin.action(description="Publish selected")
    def publish_selected(self, request, qs):
        n = qs.update(is_published=True)
        self.message_user(request, f"Published {n} event(s).", level=messages.SUCCESS)

    @admin.action(description="Unpublish selected")
    def unpublish_selected(self, request, qs):
        n = qs.update(is_published=False)
        self.message_user(request, f"Unpublished {n} event(s).", level=messages.WARNING)

    @admin.action(description="Duplicate selected (adds “-copy” to title/slug)")
    def duplicate_selected(self, request, qs):
        created = 0
        for e in qs:
            base_slug = (e.slug or slugify(e.title) or "event-copy").rstrip("-")
            slug = f"{base_slug}-copy"
            i = 2
            while Event.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-copy-{i}"
                i += 1
            Event.objects.create(
                title=f"{e.title} (copy)",
                slug=slug,
                summary=e.summary,
                body=e.body,
                thumb_src=e.thumb_src,   # keep the same thumbnail for the copy
                lang=e.lang,
                is_published=False,
                posted_at=timezone.now(),
            )
            created += 1
        self.message_user(request, f"Created {created} duplicate event(s). Edit and publish when ready.", level=messages.SUCCESS)
