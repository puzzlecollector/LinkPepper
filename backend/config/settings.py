"""
Django settings for config project (unified).

Django 4.2.x
"""

import os
from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/config/
PROJECT_ROOT = BASE_DIR.parent                              # backend/
FRONTEND_DIR = PROJECT_ROOT / "frontend"                    # frontend/
CORE_APP = "core"

# --------------------------------------------------------------------------------------
# Basic
# --------------------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-h-@^*$%uw4*k^v&c(cbs^r760t&ha9-1=^u^j937wo=+@6@k@_"  # dev default
)
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"

# Add your server IP/hosts as needed
ALLOWED_HOSTS = ["link-hash.com", "www.link-hash.com", "54.180.247.151", "localhost", "127.0.0.1", "m.link-hash.com"]

CSRF_TRUSTED_ORIGINS = [
    "https://link-hash.com",
    "https://www.link-hash.com",
    "http://link-hash.com",   # keep until SSL is issued
    "http://www.link-hash.com",
    "https://m.link-hash.com", 
    "http://m.link-hash.com", 
]

# --------------------------------------------------------------------------------------
# Apps
# --------------------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "csp",
    "ckeditor",
    "ckeditor_uploader",
    CORE_APP,  # core
]

# --------------------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.LanguageRoutingMiddleware",
    "core.middleware.WalletAuthMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

# --- New django-csp 4.x format ---
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),

        # Inline <script> blocks exist in your pages => keep 'unsafe-inline' (dev-friendly)
        "script-src": (
            "'self'",
            "'unsafe-inline'",
            "https://cdn.jsdelivr.net",
            "https://unpkg.com",
            "https://cdn.walletconnect.com",
        ),

        # Inline <style> blocks exist in your pages => add 'unsafe-inline'
        "style-src": (
            "'self'",
            "'unsafe-inline'",
            "https://fonts.googleapis.com",
        ),

        "img-src": (
            "'self'",
            "data:",
            "blob:",                      # optional but handy for modern APIs
            "https://cdn.jsdelivr.net",
            "https://unpkg.com",
            "https://cdn.walletconnect.com",
        ),

        "font-src": (
            "'self'",
            "data:",                      # in case you inline fonts later
            "https://fonts.gstatic.com",
        ),

        "connect-src": (
            "'self'",
            "https://*.walletconnect.com",
            "wss://*.walletconnect.com",
        ),

        "frame-src": ("'self'",),
    },

    # If you want to start in report-only mode, set this to True
    # (content will NOT be blocked; only reported). For now keep False.
    "REPORT_ONLY": True,
}


# OPTIONAL hardening
SECURE_CONTENT_TYPE_NOSNIFF = True
# SECURE_BROWSER_XSS_FILTER = True

SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# --------------------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Keep using the frontend/templates directory
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # If you implemented a wallet_user context processor in core/context_processors.py
                # leave this line; otherwise remove/comment it.
                "core.context_processors.wallet_user",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --------------------------------------------------------------------------------------
# Database (SQLite dev default)
# --------------------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": (PROJECT_ROOT / "db.sqlite3"),
    }
}

# --------------------------------------------------------------------------------------
# Password validation
# --------------------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------------------
# I18N / TZ
# --------------------------------------------------------------------------------------
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------------------
# Static / Media
# --------------------------------------------------------------------------------------
# Where uploaded images go (under /media/)
# Where uploaded images go (relative to MEDIA_ROOT).  NO date tokens here.
CKEDITOR_UPLOAD_PATH = "campaigns/uploads/"

CKEDITOR_IMAGE_BACKEND = "pillow"
CKEDITOR_ALLOW_NONIMAGE_FILES = False

CKEDITOR_CONFIGS = {
    "default": {
        "height": 380,
        "width": "100%",
        "toolbar": [
            {"name": "styles", "items": ["Format", "Font", "FontSize"]},
            {"name": "basicstyles", "items": ["Bold", "Italic", "Underline", "Strike", "-", "RemoveFormat"]},
            {"name": "paragraph", "items": [
                "NumberedList", "BulletedList", "-", "Outdent", "Indent", "-",
                "Blockquote", "JustifyLeft", "JustifyCenter", "JustifyRight", "JustifyBlock"
            ]},
            {"name": "links", "items": ["Link", "Unlink"]},
            # The Image button opens the dialog; with the uploader enabled, it shows an **Upload** tab.
            {"name": "insert", "items": ["Image", "Table", "HorizontalRule"]},
            {"name": "clipboard", "items": ["Undo", "Redo"]},
            {"name": "document", "items": ["Source", "Maximize"]},
        ],
        # Drag-and-drop / paste upload support
        "extraPlugins": ",".join([
            "uploadimage",
            "justify",
            "font",
            "colorbutton",
        ]),
        # DO NOT remove the 'image' plugin; it provides the Image button & upload tab.
        # "removePlugins": "image",   # <-- remove this line entirely

        # Uploader endpoints (served by django-ckeditor)
        "filebrowserUploadUrl": "/ckeditor/upload/",
        "filebrowserBrowseUrl": "/ckeditor/browse/",

        # Allow the tags CKEditor will generate
        "extraAllowedContent": "img[!src,alt,width,height]{*}(*);figure;figcaption",
        "forcePasteAsPlainText": False,
    }
}


# serve user uploads from /media/
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# App/static collection target (for collectstatic in prod)
STATIC_URL = "/static/"
STATIC_ROOT = PROJECT_ROOT / "staticfiles"

# Where your working assets live during development (your current structure)
STATICFILES_DIRS = [
    FRONTEND_DIR / "static",
]

MEDIA_URL = "/media/"
MEDIA_ROOT = PROJECT_ROOT / "media"

# --------------------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
