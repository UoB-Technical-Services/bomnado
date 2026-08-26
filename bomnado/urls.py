from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include, re_path
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

from rest_framework import routers

from bom import viewsets
import bom.urls
from bom.views.accounts import ThrottledLoginView, ThrottledPasswordResetView


router = routers.DefaultRouter()
router.register(r'parts', viewsets.PartViewSet, basename=r'part')
router.register(r'partsources', viewsets.PartSourceViewSet, basename=r'partsource')
router.register(r'subassemblies', viewsets.SubAssemblyViewSet, basename=r'subassembly')
router.register(r'subassemblylineitems', viewsets.SubAssemblyLineItemViewSet, basename=r'subassemblylineitem')
router.register(r'deals', viewsets.DealViewSet, basename=r'deal')
router.register(r'deallineitems', viewsets.DealLineItemViewSet, basename=r'deallineitem')

urlpatterns = [
    re_path(r'^', include(bom.urls)),
    # Rate-limited sign-in and reset; the include below supplies the rest under the same names.
    path('accounts/login/', ThrottledLoginView.as_view(), name='login'),
    path('accounts/password_reset/', ThrottledPasswordResetView.as_view(), name='password_reset'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/', admin.site.urls),
    re_path(r'^api-auth/', include('rest_framework.urls')),
    path('api/', include(router.urls))
]


if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
