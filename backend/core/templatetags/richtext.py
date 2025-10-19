# core/templatetags/richtext.py
import re
from django import template
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe
from django.template.defaultfilters import linebreaksbr

register = template.Library()

_HTML_RE = re.compile(r"<[a-z][\s\S]*>", re.IGNORECASE)

@register.filter(name="richtext")
def richtext(value):
    """
    If value contains HTML-ish tags => trust & render as-is (admin-authored).
    Otherwise => escape and convert newlines to <br>/<p>.
    """
    if not value:
        return ""
    s = str(value)
    if _HTML_RE.search(s):
        return mark_safe(s)
    # plain text: escape then add <br>/<p>
    return linebreaksbr(conditional_escape(s))
