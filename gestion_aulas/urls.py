"""
URL configuration for gestion_aulas project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.contrib.auth import views as auth_views
from reservas import views as reservas_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', auth_views.LoginView.as_view(template_name='reservas/login.html'), name='login'),
    path('routing/', reservas_views.redirect_by_role, name='role_routing'),
    path('panel_profesor/', reservas_views.panel_profesor, name='panel_profesor'),
    path('reserva/<int:reserva_id>/validar/', reservas_views.validar_qr_simulado, name='validar_qr'),
    path('push-simular/', reservas_views.lanzar_recordatorios_push_simulados, name='simular_push'),
    path('panel_administrador/', reservas_views.panel_administrador, name='panel_administrador'),
    path('recuperar-clave/', reservas_views.recuperar_contrasena, name='recuperar_contrasena'),
    path('restablecer-contrasena/<str:uidb64>/', reservas_views.restablecer_contrasena, name='restablecer_contrasena'),
    path('logout/', reservas_views.cerrar_sesion, name='logout'),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)