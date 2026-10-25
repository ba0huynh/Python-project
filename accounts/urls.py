from django.urls import path

from .views import (
    DriverLoginView, DriverMeView, DriverRegisterView, LoginView, LogoutView, MeView, RefreshView,
    RegisterView,
)

app_name = 'accounts'
urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('refresh/', RefreshView.as_view(), name='refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
    path('driver/register/', DriverRegisterView.as_view(), name='driver-register'),
    path('driver/login/', DriverLoginView.as_view(), name='driver-login'),
    path('driver/me/', DriverMeView.as_view(), name='driver-me'),
]
