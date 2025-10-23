# apps/rewards/models.py
from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.template.defaultfilters import slugify
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP 

# ---------- Core choices ----------
class TaskType(models.TextChoices):
    VISIT = "VISIT", "Visit"
    LINK = "LINK", "Link"
    # Kept only so old rows (if any) don't blow up in templates.
    # We normalize MIXED_LEGACY => VISIT in views/templates.
    MIXED_LEGACY = "MIXED", "Mixed (legacy)"


class Network(models.TextChoices):
    ETH = "ETH", "Ethereum"
    SOL = "SOL", "Solana"
    BNB = "BNB", "BNB Chain"
    POL = "POL", "Polygon"


class SubmissionStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    PAID = "PAID", "Paid"  # convenience terminal state; also see Payout


# ---------- Wallet-based user (address-first identity) ----------
class WalletUser(models.Model):
    """
    Lightweight user table for address-based login.
    Users authenticate by signing a server-provided nonce with their wallet.
    No password is stored here.
    """
    id = models.BigAutoField(primary_key=True)

    # EVM or other chain address. For EVM, store checksum/lowercase consistently on write.
    address = models.CharField(max_length=128, unique=True, db_index=True)

    # Optional profile-ish fields
    display_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)

    # Login helpers
    nonce = models.CharField(max_length=180, blank=True, help_text="Random challenge for signature verification")
    last_login = models.DateTimeField(null=True, blank=True)

    # Admin toggle for your own use (not Django's is_staff/is_superuser)
    is_admin = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.display_name or self.address

    def set_new_nonce(self, token: str):
        self.nonce = token
        self.save(update_fields=["nonce"])


# ---------- Client application (from /rewards/apply/) ----------
class CampaignApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Minimal required
    email = models.EmailField()
    phone = models.CharField(max_length=64)

    # Optional meta (maps to rewards_apply.html)
    country = models.CharField(max_length=64, blank=True)
    campaign_title = models.CharField(max_length=180, blank=True)
    website_url = models.URLField(blank=True)
    website_description = models.TextField(blank=True)

    # “Task types” requested by client (checkboxes). We store flags.
    wants_visit = models.BooleanField(default=False)
    wants_link = models.BooleanField(default=True)

    # VISIT-specific
    visit_code = models.CharField(
        max_length=64, blank=True, help_text="Verification code users must find"
    )

    # LINK-specific SEO fields
    expected_review_keywords = models.CharField(max_length=400, blank=True)
    current_seo_keywords = models.CharField(max_length=400, blank=True)

    # Rewards (optional)
    reward_pool_usdt = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))]
    )
    payout_per_task_usdt = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))]
    )
    currency = models.CharField(
        max_length=8, choices=Network.choices, default=Network.ETH
    )

    # Dates (optional)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # Airdrop optional
    airdrop_enabled = models.BooleanField(default=False)
    airdrop_first_n = models.PositiveIntegerField(null=True, blank=True)
    airdrop_amount_per_user = models.DecimalField(
        max_digits=18, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))]
    )
    airdrop_token_symbol = models.CharField(max_length=24, blank=True)
    airdrop_network = models.CharField(max_length=48, blank=True)
    airdrop_note = models.CharField(max_length=240, blank=True)

    # Assets (store URLs your upload layer writes to; keeps models lean)
    thumbnail_url = models.URLField(blank=True)
    favicon_url = models.URLField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField(
        default=False,
        help_text="Mark true once an admin has responded/converted to a Campaign.",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Application {self.email} ({self.campaign_title or 'Untitled'})"


# ---------- Admin-created campaign (what powers Rewards pages) ----------
class Campaign(models.Model):
    id = models.BigAutoField(primary_key=True)
    slug = models.SlugField(max_length=220, unique=True, blank=True)

    # Display
    title = models.CharField(max_length=180)
    summary = models.CharField(max_length=300, blank=True)
    long_description = models.TextField(blank=True)

    # Task type (only LINK or VISIT are considered active)
    task_type = models.CharField(
        max_length=12, choices=TaskType.choices, default=TaskType.VISIT
    )

    # Client/site specifics used by the details page
    client_site_domain = models.CharField(max_length=180, blank=True)
    rules = models.TextField(blank=True)

    # VISIT flow: how to find code + the actual code users must submit
    code_instructions = models.TextField(
        blank=True, help_text="How VISIT participants can find the code"
    )
    visit_code = models.CharField(  # <<< NEW
        max_length=64, blank=True, help_text="The verification code users must enter for VISIT tasks"
    )

    # LINK SEO helpers
    seo_keywords = models.CharField(max_length=400, blank=True)

    # Assets (used by cards/hero/favibox)
    image_url = models.URLField(blank=True)        # card/hero image
    favicon_url = models.URLField(blank=True)      # small icon in details

    # Rewards and window
    pool_usdt = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    payout_usdt = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    currency = models.CharField(
        max_length=8, choices=Network.choices, default=Network.ETH
    )
    start = models.DateField()
    end = models.DateField()

    # Optional: airdrop knobs for announcements sidebar logic
    airdrop_enabled = models.BooleanField(default=False)
    airdrop_first_n = models.PositiveIntegerField(null=True, blank=True)
    airdrop_amount_per_user = models.DecimalField(
        max_digits=18, decimal_places=8, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))]
    )
    airdrop_token_symbol = models.CharField(max_length=24, blank=True)
    airdrop_network = models.CharField(max_length=48, blank=True)
    airdrop_note = models.CharField(max_length=240, blank=True)

    # Admin toggles
    is_published = models.BooleanField(
        default=False,
        help_text="Published campaigns appear on /rewards and details pages.",
    )
    is_paused = models.BooleanField(
        default=False,
        help_text="Pause to stop accepting new submissions without unpublishing.",
    )

    # Optional link to the application that spawned this campaign
    source_application = models.ForeignKey(
        CampaignApplication, null=True, blank=True, on_delete=models.SET_NULL, related_name="campaigns"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start", "-id"]

    # ----- Derived fields used by templates -----
    @property
    def has_visit(self) -> bool:
        return self.task_type in (TaskType.VISIT, TaskType.MIXED_LEGACY)

    @property
    def has_link(self) -> bool:
        return self.task_type in (TaskType.LINK, TaskType.MIXED_LEGACY)

    @property
    def is_open_now(self) -> bool:
        today = timezone.localdate()
        return (self.start <= today <= self.end) and not self.is_paused and self.is_published

    @property
    def participants(self) -> int:
        # Number of distinct users that have at least one submission
        return (
            self.submissions.exclude(wallet_address__isnull=True)
            .exclude(wallet_address__exact="")
            .values("wallet_address")
            .distinct()
            .count()
        )

    @property
    def claimed_percent(self) -> int:
        """
        (# distinct wallets with an approved submission) * payout / pool, as a whole %.
        Counts approval by either status==APPROVED or is_approved=True.
        Returns 0..100, but any non-zero fraction below 1% is shown as 1%.
        """
        from django.db.models import Q

        approved_user_count = (
            self.submissions.filter(Q(status=SubmissionStatus.PAID) | Q(is_paid=True))
            .exclude(wallet_address__isnull=True)
            .exclude(wallet_address__exact="")
            .values("wallet_address")
            .distinct()
            .count()
        )

        if not self.pool_usdt or self.pool_usdt == 0 or not self.payout_usdt or self.payout_usdt == 0:
            return 0

        claimed_amount = Decimal(approved_user_count) * self.payout_usdt
        if claimed_amount <= 0:
            return 0

        pct = (claimed_amount / self.pool_usdt) * Decimal("100")

        # If there is any progress but < 1%, show 1 so the UI isn’t stuck at 0.
        if pct > 0 and pct < 1:
            return 1

        pct_int = int(pct.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return max(0, min(100, pct_int))


    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title) or "campaign"
            candidate = base
            i = 2
            while Campaign.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f"{base}-{i}"
                i += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.title} ({self.get_task_type_display()})"


# ---------- User submissions ----------
class Submission(models.Model):
    id = models.BigAutoField(primary_key=True)
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="submissions")

    # Link to wallet user (address-login). Keep admins on AUTH_USER for reviews/payouts.
    user = models.ForeignKey(
        WalletUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="submissions"
    )

    # Wallet info (required on forms)
    wallet_address = models.CharField(max_length=128)
    network = models.CharField(max_length=8, choices=Network.choices)

    # Two task shapes (only one will be actually used depending on campaign.task_type):
    # LINK
    post_url = models.URLField(blank=True)
    comment = models.TextField(blank=True)

    # VISIT
    visited_url = models.URLField(blank=True)  # optional if you want to capture landing
    code_entered = models.CharField(max_length=64, blank=True)

    # Review / moderation
    status = models.CharField(max_length=12, choices=SubmissionStatus.choices, default=SubmissionStatus.PENDING)
    proof_score = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Admin-assigned proof-of-work score (e.g., quality/DA)"
    )
    reviewer_note = models.TextField(blank=True)

    admin_comment = models.TextField(null=True, blank=True)

    reviewed_by = models.ForeignKey(
        getattr(settings, "AUTH_USER_MODEL", "auth.User"),
        null=True, blank=True, on_delete=models.SET_NULL, related_name="reviewed_submissions"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Convenience “approved & paid” toggles for quick admin filtering.
    is_approved = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["wallet_address"]),
        ]

    def mark_approved(self, reviewer=None, score: int | None = None, note: str | None = None):
        self.status = SubmissionStatus.APPROVED
        self.is_approved = True
        self.reviewed_at = timezone.now()
        if reviewer:
            self.reviewed_by = reviewer
        if score is not None:
            self.proof_score = score
        if note:
            self.reviewer_note = (self.reviewer_note + "\n" if self.reviewer_note else "") + note
        self.save(update_fields=[
            "status", "is_approved", "reviewed_at", "reviewed_by", "proof_score", "reviewer_note"
        ])

    def __str__(self) -> str:
        return f"Submission #{self.pk} to {self.campaign}"


# ---------- Payout ledger (manual transfer logging) ----------
class Payout(models.Model):
    """
    Optional but recommended for transparency.
    Admins log the actual coin payout (after manual transfer), tying it to a submission.
    """
    id = models.BigAutoField(primary_key=True)
    submission = models.OneToOneField(
        Submission, on_delete=models.CASCADE, related_name="payout",
        help_text="One payout per submission (simplest model)."
    )
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="payouts")
    amount_usdt = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    token_symbol = models.CharField(max_length=16, default="USDT", help_text="What was sent (e.g., USDT, PEPE, BONK)")
    network = models.CharField(max_length=8, choices=Network.choices)
    tx_hash = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(default=timezone.now)
    paid_by = models.ForeignKey(
        getattr(settings, "AUTH_USER_MODEL", "auth.User"),
        null=True, blank=True, on_delete=models.SET_NULL, related_name="payouts_made"
    )
    note = models.CharField(max_length=240, blank=True)

    class Meta:
        ordering = ["-paid_at"]
        constraints = [
            models.UniqueConstraint(fields=["submission"], name="one_payout_per_submission"),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Reflect state on submission for fast admin filters
        if self.submission and (not self.submission.is_paid or self.submission.status != SubmissionStatus.PAID):
            Submission.objects.filter(pk=self.submission_id).update(
                is_paid=True, status=SubmissionStatus.PAID
            )

    def __str__(self) -> str:
        return f"Payout {self.amount_usdt} {self.token_symbol} for Sub#{self.submission_id}"


# ---------- Events / Announcements ----------
class Event(models.Model):
    class Lang(models.TextChoices):
        EN = "en", "English"
        KO = "ko", "Korean"
        JA = "ja", "Japanese"
        ZH = "zh", "Chinese"

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, max_length=220)
    summary = models.TextField(blank=True, null=True)
    body = models.TextField(blank=True, null=True)  # You can store Markdown or HTML
    # Accepts http(s) or data:image/*;base64,... so admins can paste either.
    thumb_src = models.TextField(blank=True, null=True)

    lang = models.CharField(max_length=2, choices=Lang.choices, default=Lang.EN)
    is_published = models.BooleanField(default=True)
    posted_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-posted_at", "-id"]
        indexes = [models.Index(fields=["is_published", "lang", "posted_at"])]

    def __str__(self):
        return f"[{self.lang}] {self.title}"
