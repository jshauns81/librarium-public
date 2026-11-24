from django.urls import path

from librarium_lab import views

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz/", views.health, name="health"),
    path("api/lab/v1/baseline/", views.baseline, name="baseline"),
    path("api/lab/v1/identity/", views.identity_probe, name="identity"),
]
