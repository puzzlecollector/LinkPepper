def wallet_user(request):
    return {"wallet_user": getattr(request, "wallet_user", None)}

def gtm(request):
    from django.conf import settings
    return {"GTM_CONTAINER_ID": getattr(settings, "GTM_CONTAINER_ID", "")}
