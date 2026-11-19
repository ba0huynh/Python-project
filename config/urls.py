"""URL configuration: /admin/, /api/auth/ (accounts), /api/ (rides, driver, places)."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('core.urls')),
]


# JSON errors instead of HTML pages (used when DEBUG is off).
def not_found(request, exception=None):
    return JsonResponse({'detail': 'Không tìm thấy.'}, status=404)


def server_error(request):
    return JsonResponse({'detail': 'Lỗi máy chủ. Vui lòng thử lại sau.'}, status=500)


handler404 = not_found
handler500 = server_error
