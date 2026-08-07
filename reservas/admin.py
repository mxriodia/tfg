from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Edificio, Recurso, Aula, AulaEquipamiento, Reserva, Incidencia, Notificacion

# Register your models here.
# Customizamos el panel de usuarios para que muestre el rol claramente
class CustomUserAdmin(UserAdmin):
    model = Usuario
    list_display = ['username', 'email', 'rol', 'is_staff', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('Información de Rol', {'fields': ('rol',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Información de Rol', {'fields': ('rol',)}),
    )

# Para poder gestionar el equipamiento directamente desde la ficha del Aula
class AulaEquipamientoInline(admin.TabularInline):
    model = AulaEquipamiento
    extra = 1

class AulaAdmin(admin.ModelAdmin):
    list_display = ['numero_aula', 'edificio', 'planta', 'capacidad_max', 'operativa']
    list_filter = ['edificio', 'operativa']
    search_fields = ['numero_aula', 'codigo_qr_token']
    inlines = [AulaEquipamientoInline]
    
class EdificioAdmin(admin.ModelAdmin):
    list_display = ['numero_edificio', 'nombre', 'cantidad_aulas', 'operativo']
    search_fields = ['nombre', 'numero_edificio']

class ReservaAdmin(admin.ModelAdmin):
    list_display = ['id', 'usuario', 'aula', 'fecha', 'hora_inicio', 'hora_fin', 'estado', 'tipo']
    list_filter = ['estado', 'tipo', 'fecha']
    search_fields = ['usuario__username', 'aula__numero_aula']

class IncidenciaAdmin(admin.ModelAdmin):
    list_display = ['id', 'aula', 'usuario', 'gravedad', 'estado']
    list_filter = ['gravedad', 'estado']
    search_fields = ['descripcion', 'aula__numero_aula']
    
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'titulo', 'tipo', 'fecha_envio', 'leida']
    list_filter = ['tipo', 'leida']

# Registramos todos los modelos en el administrador de Django
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Edificio, EdificioAdmin)
admin.site.register(Recurso)
admin.site.register(Aula, AulaAdmin)
admin.site.register(Reserva, ReservaAdmin)
admin.site.register(Incidencia, IncidenciaAdmin)
admin.site.register(Notificacion, NotificacionAdmin)