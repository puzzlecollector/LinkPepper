# backend/core/models.py
from django.db import models
from django.utils import timezone


class WalletUser(models.Model):
    """
    Non-custodial wallet user (EVM). No passwords. Auth via message signature.
    """
    address = models.CharField(max_length=42, unique=True)  # 0x… (lowercased)
    display_name = models.CharField(max_length=120, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)

    # session helpers
    last_login = models.DateTimeField(blank=True, null=True)
    nonce = models.CharField(max_length=64, blank=True, null=True)  # fresh per login attempt

    # optional socials/wallets
    wallet_solana = models.CharField(max_length=64, blank=True, null=True)
    telegram = models.CharField(max_length=120, blank=True, null=True)
    twitter_x = models.CharField(max_length=120, blank=True, null=True)

    is_admin = models.BooleanField(default=False)  # presentation-only flag
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return self.display_name or self.address


class Campaign(models.Model):
    class TaskType(models.TextChoices):
        LINK = "LINK", "Link sharing"
        VISIT = "VISIT", "Visit with footer code"
        SEARCH = "SEARCH", "Google search + visit"
        MAPS = "MAPS", "Google Maps task"

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True, null=True)
    task_type = models.CharField(max_length=12, choices=TaskType.choices, default=TaskType.VISIT)

    start_at = models.DateTimeField(blank=True, null=True)
    end_at = models.DateTimeField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    reward_currency = models.CharField(max_length=24, default="USDT")
    reward_amount = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    quota_total = models.PositiveIntegerField(default=0, help_text="0 = unlimited")

    client_site_domain = models.CharField(max_length=200, blank=True, null=True)
    secret_code = models.CharField(
        max_length=120, blank=True, null=True,
        help_text="If all users read the same footer code, put it here."
    )
    code_case_sensitive = models.BooleanField(default=False)
    extra = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def submissions_count(self) -> int:
        return self.submission_set.count()

    @property
    def quota_remaining(self):
        if not self.quota_total:
            return None
        return max(0, self.quota_total - self.submissions_count)

    def is_open_now(self) -> bool:
        now = timezone.now()
        if not self.is_active: return False
        if self.start_at and now < self.start_at: return False
        if self.end_at and now > self.end_at: return False
        if self.quota_total and self.submissions_count >= self.quota_total: return False
        return True


class CampaignCode(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    code = models.CharField(max_length=120)
    is_used = models.BooleanField(default=False)
    claimed_by = models.ForeignKey(WalletUser, on_delete=models.SET_NULL, blank=True, null=True)
    claimed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = [("campaign", "code")]
        indexes = [models.Index(fields=["campaign", "is_used", "code"])]

    def __str__(self):
        return f"{self.campaign.slug}:{self.code}"


class Submission(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    user = models.ForeignKey(WalletUser, on_delete=models.CASCADE)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    # Common fields
    comment = models.TextField(blank=True, null=True)
    wallet_used = models.CharField(max_length=64, blank=True, null=True)

    # For LINK tasks
    post_url = models.URLField(blank=True, null=True)

    # For VISIT/SEARCH tasks
    visited_url = models.URLField(blank=True, null=True)
    code_entered = models.CharField(max_length=120, blank=True, null=True)

    proof_score = models.IntegerField(default=0)
    rank_guess = models.IntegerField(blank=True, null=True)

    reviewer_note = models.TextField(blank=True, null=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("campaign", "user")]
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.campaign} ({self.status})"


class Payout(models.Model):
    submission = models.OneToOneField(Submission, on_delete=models.CASCADE)
    currency = models.CharField(max_length=24, default="USDT")
    amount = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    tx_hash = models.CharField(max_length=120, blank=True, null=True)
    status = models.CharField(
        max_length=12,
        choices=[("QUEUED", "Queued"), ("SENT", "Sent")],
        default="QUEUED",
    )
    paid_at = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payout #{self.pk} for submission {self.submission_id}"


class Event(models.Model):
    class Lang(models.TextChoices):
        EN = "en", "English"
        KO = "ko", "Korean"
        JA = "ja", "Japanese"
        ZH = "zh", "Chinese"

    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    summary = models.TextField(blank=True, null=True)
    body = models.TextField(blank=True, null=True)  # Markdown or HTML—your call
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
        return self.title