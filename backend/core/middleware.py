# frontend/middleware.py
from .models import WalletUser

class WalletAuthMiddleware:
    """
    Puts `request.wallet_user` on every request based on session.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.wallet_user = None
        uid = request.session.get("wallet_user_id")
        if uid:
            try:
                request.wallet_user = WalletUser.objects.get(id=uid)
            except WalletUser.DoesNotExist:
                request.session.pop("wallet_user_id", None)
        return self.get_response(request)
