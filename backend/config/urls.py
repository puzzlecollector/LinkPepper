"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from core.views import home_en, home_ko, rewards_en, rewards_ko, rewards_apply_en, rewards_apply_ko

urlpatterns = [
    path('admin/', admin.site.urls),

    path("", home_en, name="home_en"),
    path("ko/", home_ko, name="home_ko"), # https://linkpepper.com/ko/

    path("rewards/", rewards_en, name="rewards_en"),
    path("ko/rewards/", rewards_ko, name="rewards_ko"),

    path("rewards/apply/", rewards_apply_en, name="rewards_apply_en"),
    path("rewards/apply/ko/", rewards_apply_ko, name="rewards_apply_ko"),
]
