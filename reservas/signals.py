from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import Incidencia, Aula, Edificio, Reserva, Notificacion
from django.db.models import Q
from datetime import timedelta
from django.core.mail import send_mail

# Si la gravedad de una incidencia es alta, inhabilita el aula y sugiere aulas alternativas con características similares
@receiver(post_save, sender=Incidencia)
def inhabilitar_y_reubicar_aulas(sender, instance, **kwargs):
    if instance.estado == 'activa':
        if instance.gravedad == 'alta':
            aula_afectada = instance.aula 
            if aula_afectada.operativa:
                # Deshabilita el aula
                aula_afectada.operativa = False
                aula_afectada.save()
            
            equipamiento_afectado_ids = aula_afectada.equipamiento.values_list('id', flat=True)
            
            # Busca reservas activas en el aula no operativa
            ahora = timezone.localtime(timezone.now())
            # Se reubican solo las reservas de las próximas 48h
            limite_48h = ahora + timedelta(hours=48)
            reservas_afectadas = Reserva.objects.filter(
                aula=aula_afectada,
                estado='activa'
            ).filter(
                # Caso 1: Es hoy, pero empieza más tarde de la hora actual
                Q(fecha=ahora.date(), hora_inicio__gte=ahora.time()) |
                # Caso 2: Días completamente metidos en el rango intermedio
                Q(fecha__gt=ahora.date(), fecha__lt=limite_48h.date()) |
                # Caso 3: Es el día límite, pero empieza antes de la hora límite exacta
                Q(fecha=limite_48h.date(), hora_inicio__lte=limite_48h.time())
            )
            
            for res in reservas_afectadas:
                # Busca un aula alternativa que esté operativa, en un edificio operativo, que no sea la misma aula rota, que tenga igual o mayor capacidad, y con el mismo equipamiento mínimo requerido
                aulas_candidatas = Aula.objects.filter(
                    operativa=True,
                    edificio__operativo=True,
                    capacidad_max__gte=aula_afectada.capacidad_max
                ).exclude(id=aula_afectada.id)
                
                for recurso_id in equipamiento_afectado_ids:
                    aulas_candidatas = aulas_candidatas.filter(equipamiento__id=recurso_id)
                
                aula_sugerida = None
                
                for cand in aulas_candidatas:
                    # Comprueba si esta aula alternativa está libre en la fecha y hora de la reserva
                    solapamientos = Reserva.objects.filter(
                        aula=cand,
                        fecha=res.fecha,
                        estado='activa',
                        hora_inicio__lte=res.hora_inicio,
                        hora_fin__gt=res.hora_inicio
                    ).exists()
                    
                    if not solapamientos:
                        aula_sugerida = cand
                        break # Se detiene la búsqueda al encontrar la primera opción válida
                
                # Reasigna la reserva al aula encontrada y envía una notificación al profesor tanto si se ha encontrado un aula alternativa como si no se encuentra
                if aula_sugerida:
                    res.aula = aula_sugerida
                    res.save()
                    
                    txt_mensaje = (
                        f"El Aula {aula_afectada.numero_aula} ha quedado inhabilitada por una incidencia grave "
                        f"({instance.descripcion}). El sistema ha reubicado tu sesión del día "
                        f"{res.fecha} al Aula {aula_sugerida.numero_aula} (Planta {aula_sugerida.planta}, Edificio {aula_sugerida.edificio.numero_edificio})."
                    )
                else:
                    txt_mensaje = (
                        f"El Aula {aula_afectada.numero_aula} ha quedado inhabilitada por una incidencia grave "
                        f"({instance.descripcion}). Lamentablemente, no se han encontrado otras aulas libres "
                        f"con capacidad suficiente o el equipamiento necesario en esa franja horaria."
                    )
                
                Notificacion.objects.create(
                    usuario=res.usuario,
                    reserva=res,
                    titulo="⚠️ Alerta de reubicación de aula",
                    mensaje=txt_mensaje,
                    tipo='reasignacion'
                )
                
                # Envía un correo a los profesores afectados
                send_mail(
                    subject="⚠️ CAMBIO DE AULA: Modificación automática de reserva",
                    message=(
                        f"Estimado/a profesor/a,\n\n"
                        f"Le notificamos una modificación en su reserva.\n\n"
                        f"{txt_mensaje}\n\n"
                        f"Puede revisar los detalles actualizados del espacio asignado en su panel docente."
                    ),
                    from_email=None,
                    recipient_list=[res.usuario.email],
                    fail_silently=True
                )


# Si un edificio pasa a estar no operativo, todas las aulas vinculadas a ese edificio pasan a inhabilitarse
@receiver(post_save, sender=Edificio)
def inhabilitar_aulas_por_edificio(sender, instance, **kwargs):
    if not instance.operativo:
        instance.aulas.filter(operativa=True).update(operativa=False)
        