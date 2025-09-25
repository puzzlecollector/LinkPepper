# frontend/context_processors.py
def wallet_user(request):
    # Accessible in all templates as {{ wallet_user }}
    return {"wallet_user": getattr(request, "wallet_user", None)}
