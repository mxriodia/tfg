from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils.dateparse import parse_date, parse_time
from django.contrib import messages
from .models import Aula, Reserva, Recurso, Incidencia, Notificacion, Usuario, Edificio, AulaEquipamiento, Valoracion
from django.utils import timezone
from datetime import datetime, timedelta
from django.utils.translation import gettext as _
import calendar
from django.db.models import IntegerField, Count, Q
from django.db.models.functions import Cast
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
import base64
from PIL import Image
from django.contrib.auth import logout

# Create your views here.

# Según el usuario que inicia sesión va al panel correspondiente
@login_required
def redirect_by_role(request):
    if request.user.rol == 'administrador':
        return redirect('/panel_administrador/')
    return redirect('/panel_profesor/')


@login_required
def panel_profesor(request):
    usuario = request.user 
    ahora = timezone.localtime(timezone.now())
    # Busca reservas activas de hoy del usuario logueado que no se hayan validado todavía 
    reservas_hoy = Reserva.objects.filter(
        usuario=usuario,
        fecha=ahora.date(),
        estado='activa',
        fecha_validacion__isnull=True
    )
    
    for res in reservas_hoy:
        # Combina la fecha y hora de inicio de la reserva para calcular el límite de 15 minutos
        inicio_reserva = datetime.combine(res.fecha, res.hora_inicio)
        inicio_reserva = timezone.make_aware(inicio_reserva, timezone.get_current_timezone())
        
        # Si han pasado más de 15 minutos de la hora de inicio, se cancela la reserva
        if ahora > inicio_reserva + timedelta(minutes=15):
            res.estado = 'cancelada'
            res.save()
            
            # Se notifica al administrador
            admin_user = Usuario.objects.filter(rol='administrador').first()
            if admin_user:
                Notificacion.objects.create(
                    usuario=admin_user,
                    reserva=res,
                    titulo="Reserva no utilizada",
                    mensaje=f"La reserva del Aula {res.aula.numero_aula} en el Edificio {res.aula.edificio.numero_edificio} programada para hoy a las {res.hora_inicio.strftime('%H:%M')} ha sido cancelada por ausencia del profesor {usuario.username}.",
                    tipo='incidencia'
                )
            
            messages.error(request, f"Tu reserva en el edificio {res.aula.edificio.numero_edificio}, Aula {res.aula.numero_aula}  ha sido cancelada por superar el límite de 15 minutos.")
    
    busqueda_realizada = False
    aulas_encontradas = None
    post_data = {}
    nombre_dia = None
    
    if request.method == 'POST':
        
        # ACCIÓN: Buscar aulas disponibles
        if 'btn_buscar' in request.POST:
            busqueda_realizada = True
            post_data = request.POST
            fecha_str = request.POST.get('fecha')
            hora_inicio_str = request.POST.get('hora_inicio')
            hora_fin_str = request.POST.get('hora_fin')
            capacidad = request.POST.get('capacidad')
            
            if capacidad and int(capacidad) <= 0:
                messages.error(request, "Error: La capacidad mínima de alumnos debe ser mayor que 0.")
                return redirect('/panel_profesor/?tab=tab-buscar')
            
            # Excluye aulas no operativas
            aulas = Aula.objects.filter(operativa=True, edificio__operativo=True)
            
            if capacidad:
                aulas = aulas.filter(capacidad_max__gte=int(capacidad))
                
            recursos_ids = request.POST.getlist('recursos_seleccionados')
            cantidades = request.POST.getlist('cantidades_recursos')

            # Empareja los IDs con sus cantidades ignorando los vacíos o "Cualquiera"
            filtros_equipamiento = []
            for r_id, cant in zip(recursos_ids, cantidades):
                if r_id and r_id != 'Cualquiera':
                    c_val = int(cant) if cant else 1 # Por defecto 1
                    
                    if c_val <= 0:
                        messages.error(request, "Error: La cantidad de equipamiento requerido debe ser mayor que 0.")
                        return redirect('/panel_profesor/?tab=tab-buscar')
                    
                    filtros_equipamiento.append({'recurso_id': int(r_id), 'cantidad': c_val})

            if filtros_equipamiento:
                # Para cada recurso solicitado, filtra las aulas que cumplen el criterio individual de cantidad
                for filtro in filtros_equipamiento:
                    aulas = aulas.filter(
                        aulaequipamiento__recurso_id=filtro['recurso_id'],
                        aulaequipamiento__cantidad__gte=filtro['cantidad']
                    )
                
            if fecha_str and hora_inicio_str and hora_fin_str:
                fecha_val = parse_date(fecha_str)
                hora_ini_val = parse_time(hora_inicio_str)
                hora_fin_val = parse_time(hora_fin_str)
                
                if fecha_val and hora_ini_val and hora_fin_val:
                    if hora_ini_val >= hora_fin_val:
                        messages.error(request, "Error: La hora de inicio debe ser anterior a la hora de fin.")
                        return redirect('/panel_profesor/?tab=tab-buscar')  
                    
                    # Comprueba si la fecha es anterior a hoy, o si es hoy pero la hora de inicio ya ha pasado
                    if fecha_val < ahora.date() or (fecha_val == ahora.date() and hora_ini_val < ahora.time()):
                        messages.error(request, "Error: No puedes realizar reservas en fechas u horas pasadas.")
                        return redirect('/panel_profesor/?tab=tab-buscar')
                    
                    # Traduce manualmente el nombre del día para la interfaz
                    dias_es = {
                        'Monday': 'lunes', 'Tuesday': 'martes', 'Wednesday': 'miércoles',
                        'Thursday': 'jueves', 'Friday': 'viernes', 'Saturday': 'sábados', 'Sunday': 'domingos'
                    }
                    dia_ingles = fecha_val.strftime('%A')
                    nombre_dia = dias_es.get(dia_ingles, 'lunes')
                    
                    # Si el aula ya está reservada en esa franja, se excluye de la disponibilidad
                    reservas_conflictivas = Reserva.objects.filter(
                        fecha=fecha_val,
                        estado='activa',
                        hora_inicio__lt=hora_fin_val,
                        hora_fin__gt=hora_ini_val
                    ).values_list('aula_id', flat=True)
                    
                    aulas = aulas.exclude(id__in=reservas_conflictivas)
            
            # Adjunta incidencias activas a cada aula para mostrar advertencias visuales
            for aula in aulas:
                aula.incidencias_activas = Incidencia.objects.filter(aula=aula, estado='activa')
                aula.tiene_alerta = aula.incidencias_activas.exists()
                
            aulas_encontradas = aulas

        # ACCIÓN: Crear una reserva
        elif 'btn_reservar' in request.POST:
            aula_id = request.POST.get('aula_id')
            fecha_res = request.POST.get('res_fecha')
            hora_ini_str = request.POST.get('res_hora_inicio')
            hora_fin_str = request.POST.get('res_hora_fin')
            tipo_reserva = request.POST.get('tipo_reserva', 'puntual')
            fecha_base = parse_date(fecha_res)
            h_inicio = parse_time(hora_ini_str)
            h_fin = parse_time(hora_fin_str)
            
            # Si es periódica, se replica el mismo día de la semana durante 16 semanas (un cuatrimestre) 
            iteraciones = 16 if tipo_reserva == 'periodica' else 1
            reservas_creadas = 0
            errores_solapamiento = 0
            
            for i in range(iteraciones):
                fecha_actual = fecha_base + timedelta(weeks=i)
                
                # Crear la reserva si no hay conflicto en esa fecha concreta para ese aula
                conflicto = Reserva.objects.filter(
                    aula_id=int(aula_id),
                    fecha=fecha_actual,
                    estado='activa',
                    hora_inicio__lt=h_fin,
                    hora_fin__gt=h_inicio
                ).exists()
                
                if not conflicto:
                    Reserva.objects.create(
                        usuario=usuario,
                        aula_id=int(aula_id),
                        fecha=fecha_actual,
                        hora_inicio=h_inicio,
                        hora_fin=h_fin,
                        estado='activa',
                        tipo=tipo_reserva
                    )
                    reservas_creadas += 1
                else:
                    errores_solapamiento += 1
            
            if tipo_reserva == 'periodica':
                if reservas_creadas > 0:
                    messages.success(request, f"Reserva periódica procesada: se han programado {reservas_creadas} sesiones para el cuatrimestre .")
                if errores_solapamiento > 0:
                    messages.error(request, f"Aviso: {errores_solapamiento} semanas no pudieron reservarse porque el aula ya estaba ocupada.")
            else:
                if reservas_creadas > 0:
                    messages.success(request, "Reserva puntual realizada con éxito.")
                else:
                    messages.error(request, "Error: El espacio ya no se encuentra disponible.")
                    
            return redirect('/panel_profesor/?tab=tab-reservas')

        # ACCIÓN: Modificar fecha y hora de una reserva
        elif 'btn_modificar_reserva' in request.POST:
            reserva_id = request.POST.get('reserva_id')
            nueva_fecha = request.POST.get('nueva_fecha')
            nueva_hora_inicio = request.POST.get('nueva_hora_inicio')
            nueva_hora_fin = request.POST.get('nueva_hora_fin')
            
            reserva = Reserva.objects.get(id=int(reserva_id), usuario=usuario)
            
            h_ini = parse_time(nueva_hora_inicio)
            h_fin = parse_time(nueva_hora_fin)
            fecha = parse_date(nueva_fecha)
            
            if h_ini >= h_fin:
                messages.error(request, "Error: La hora de inicio debe ser anterior a la hora de finalización.")
                return redirect('/panel_profesor/?tab=tab-reservas')
            
            if fecha < ahora.date() or (fecha == ahora.date() and h_ini < ahora.time()):
                messages.error(request, "Error: No puedes reprogramar una reserva para una fecha u hora que ya ha pasado.")
                return redirect('/panel_profesor/?tab=tab-reservas')
            
            # Verifica conflictos excluyendo la propia reserva que se está modificando
            conflicto = Reserva.objects.filter(
                aula=reserva.aula,
                fecha=parse_date(nueva_fecha),
                estado='activa',
                hora_inicio__lt=h_fin,
                hora_fin__gt=h_ini
            ).exclude(id=reserva.id).exists()
            
            if conflicto:
                messages.error(request, "El aula ya está ocupada en esa nueva fecha u horario.")
            else:
                reserva.fecha = parse_date(nueva_fecha)
                reserva.hora_inicio = h_ini
                reserva.hora_fin = h_fin
                reserva.save()
                messages.success(request, "Reserva modificada correctamente.")
            return redirect('/panel_profesor/?tab=tab-reservas')

        # ACCIÓN: Cancelar reserva
        elif 'btn_eliminar_reserva' in request.POST:
            reserva_id = request.POST.get('reserva_id')
            reserva = Reserva.objects.get(id=int(reserva_id), usuario=usuario)
            reserva.estado = 'cancelada'
            reserva.save()
            messages.success(request, "Reserva cancelada correctamente.")
            return redirect('/panel_profesor/?tab=tab-reservas')
        
        # ACCIÓN: Valorar un aula
        elif 'btn_valorar_aula' in request.POST:
            reserva_id = request.POST.get('reserva_id')
            puntuacion = request.POST.get('puntuacion', 5)
            comentario = request.POST.get('comentario', '')
            try:
                res_a_valorar = Reserva.objects.get(id=int(reserva_id), usuario=usuario)
                Valoracion.objects.create(
                    reserva=res_a_valorar,
                    aula=res_a_valorar.aula,
                    usuario=usuario,
                    puntuacion=int(puntuacion),
                    comentario=comentario
                )
                messages.success(request, "¡Muchas gracias por tus sugerencias! Ayudan a mejorar las aulas.")
            except (Reserva.DoesNotExist, ValueError):
                messages.error(request, "Error al procesar la valoración.")
            return redirect('/panel_profesor/?tab=' + request.GET.get('tab', 'tab-dashboard'))

        # ACCIÓN: Modificar perfil
        elif 'btn_modificar_perfil' in request.POST:
            if 'btn_eliminar_foto' in request.POST:
                if usuario.foto_perfil:
                    usuario.foto_perfil.delete(save=False) # Borra el archivo físico del servidor
                    usuario.foto_perfil = None
                    usuario.save()
                messages.success(request, "Foto de perfil eliminada correctamente.")
            else:
                usuario.first_name = request.POST.get('nombre')
                usuario.last_name = request.POST.get('apellidos')
                usuario.correo_personal = request.POST.get('correo_personal')
                
                try:
                    if usuario.correo_personal:
                        validate_email(usuario.correo_personal)
                except ValidationError:
                    messages.error(request, "Error: El formato del correo personal no es válido.")
                    return redirect('/panel_profesor/?tab=tab-perfil')
                
                usuario.despacho = request.POST.get('despacho')
                if 'foto_perfil' in request.FILES:
                    archivo_subido = request.FILES['foto_perfil']
                    try:
                        # Abrir y verificar que los datos internos son de imagen
                        img = Image.open(archivo_subido)
                        img.verify() # Comprueba la integridad sin cargar toda la imagen en RAM
                        
                        # Devolver el "puntero" al principio para que Django pueda guardarlo correctamente después
                        archivo_subido.seek(0)
                        
                        usuario.foto_perfil = archivo_subido
                    except Exception:
                        messages.error(request, "Error: El archivo está corrupto o tiene una extensión falsa. Sube una imagen real.")
                        return redirect('/panel_profesor/?tab=tab-perfil')
                    
                usuario.save()
                messages.success(request, "Perfil actualizado correctamente.")
            return redirect('/panel_profesor/?tab=tab-perfil')
        
        # ACCIÓN: Reportar incidencia técnica
        elif 'btn_reportar_incidencia' in request.POST:
            reserva_id = request.POST.get('reserva_id')
            descripcion = request.POST.get('descripcion')
            gravedad = request.POST.get('gravedad')
            
            try:
                # Solo se puede reportar una incidencia si el profesor ha validado su presencia con el QR
                reserva = Reserva.objects.get(id=int(reserva_id), usuario=usuario, fecha_validacion__isnull=False)
                
                Incidencia.objects.create(
                    aula=reserva.aula,
                    usuario=usuario,
                    reserva=reserva,
                    descripcion=descripcion,
                    gravedad=gravedad,
                    estado='activa'
                )
                
                # Envía un correo al administrador
                send_mail(
                    subject=f"⚠️ NUEVA INCIDENCIA: Aula {reserva.aula.numero_aula} (Edificio {reserva.aula.edificio.numero_edificio})",
                    message=(
                        f"Se ha registrado una incidencia técnica en la plataforma.\n\n"
                        f"Docente: {usuario.first_name} {usuario.last_name} ({usuario.username})\n"
                        f"Aula afectada: Aula {reserva.aula.numero_aula} - Edificio {reserva.aula.edificio.numero_edificio}\n"
                        f"Nivel de gravedad: {gravedad.upper()}\n"
                        f"Descripción detallada: {descripcion}\n\n"
                        f"Por favor, proceda con la gestión y resolución de esta incidencia."
                    ),
                    from_email=None,
                    recipient_list=['mxriodia@gmail.com'],
                    fail_silently=True
                )
                
                messages.success(request, f"Incidencia reportada con éxito en el Aula {reserva.aula.numero_aula} del Edificio {reserva.aula.edificio.numero_edificio}. El administrador ha sido notificado.")
            except Reserva.DoesNotExist:
                messages.error(request, "Error: Solo puedes reportar incidencias técnicas tras haber realizado el check-in en el aula.")
                
            return redirect('/panel_profesor/?tab=tab-incidencias')
        
        # ACCIÓN: Descartar una notificación (marcar como leída)
        elif 'btn_descartar_notificacion' in request.POST:
            notificacion_id = request.POST.get('notificacion_id')
            try:
                noti = Notificacion.objects.get(id=int(notificacion_id), usuario=usuario)
                noti.leida = True
                noti.save()
                messages.success(request, "Notificación descartada.")
            except Notificacion.DoesNotExist:
                pass
            return redirect('/panel_profesor/?tab=' + request.GET.get('tab', 'tab-dashboard'))

    # Una reserva ha acabado si: su fecha es anterior a hoy, o (es hoy y hora_fin es menor a la hora actual)
    reservas_finalizadas_usuario = Reserva.objects.filter(
        usuario=usuario,
        estado='activa'
    ).filter(
        (Q(fecha__lt=ahora.date())) | 
        (Q(fecha=ahora.date(), hora_fin__lt=ahora.time()))
    ).exclude(
        valoracion__isnull=False # Excluye las que ya tienen una sugerencia guardada
    ).select_related('aula', 'aula__edificio').order_by('-fecha', '-hora_fin')

    # Guarda la primera pendiente para mostrar el aviso emergente o formulario dinámico
    reserva_pendiente_valorar = reservas_finalizadas_usuario.first()

    mis_reservas_activas = Reserva.objects.filter(
            usuario=usuario, 
            estado='activa'
        ).exclude(
            (Q(fecha__lt=ahora.date())) | 
            (Q(fecha=ahora.date(), hora_fin__lt=ahora.time()))
        ).order_by('fecha', 'hora_inicio')    
        
    for res in mis_reservas_activas:
        inicio_res = datetime.combine(res.fecha, res.hora_inicio)
        inicio_res = timezone.make_aware(inicio_res, timezone.get_current_timezone())
        
        # Minutos exactos desde ahora hasta el inicio de la reserva
        diferencia = inicio_res - ahora
        res.tiempo_minutos = int(diferencia.total_seconds() / 60)
        
        # Está dentro de la ventana si faltan 60 min o menos, o han pasado 15 min o menos (-15)
        res.en_ventana_qr = (-15 <= res.tiempo_minutos <= 59)
    
    Reserva.objects.filter(
        usuario=usuario,
        estado='activa'
    ).filter(
        (Q(fecha__lt=ahora.date())) | 
        (Q(fecha=ahora.date(), hora_fin__lt=ahora.time()))
    ).update(estado='finalizada')
    
    mis_reservas_canceladas = Reserva.objects.filter(usuario=usuario, estado='cancelada').order_by('-fecha', '-hora_inicio')
    mis_reservas_expiradas = Reserva.objects.filter(usuario=usuario, estado='finalizada').order_by('-fecha', '-hora_inicio')
      
    todos_los_recursos = Recurso.objects.all()
    
    # Reservas validadas por QR para poder reportar incidencias 
    notificaciones_activas = Notificacion.objects.filter(usuario=usuario, leida=False).order_by('-fecha_envio') # Notificaciones no leídas
    
    # Determina qué pestaña mostrar. Si no se especifica, se carga 'tab-dashboard'
    active_tab = request.GET.get('tab', 'tab-dashboard')
    
    total_activas = mis_reservas_activas.count()
    total_canceladas = mis_reservas_canceladas.count()
    total_validadas = mis_reservas_expiradas.count()
    
    # Porcentaje de reservas que sí llegó a validar (evitando cancelaciones)
    total_historico = total_validadas + total_canceladas
    porcentaje_asistencia = int((total_validadas / total_historico) * 100) if total_historico > 0 else 100

    # Próxima sesión de hoy
    proxima_sesion = None
    tiempo_restante_minutos = None
    necesita_checkin = False

    # Buscamos la reserva activa de hoy que termine en el futuro y se ordene por hora de inicio
    siguiente_reserva_hoy = Reserva.objects.filter(
        usuario=usuario,
        fecha=ahora.date(),
        estado='activa',
        hora_fin__gt=ahora.time()
    ).order_by('hora_inicio').first()

    if siguiente_reserva_hoy:
        proxima_sesion = siguiente_reserva_hoy
        if not proxima_sesion.fecha_validacion:
            necesita_checkin = True
            # Calcular cuántos minutos quedan antes de la cancelación automática (Hora inicio + 15 min)
            inicio_reserva = datetime.combine(proxima_sesion.fecha, proxima_sesion.hora_inicio)
            inicio_reserva = timezone.make_aware(inicio_reserva, timezone.get_current_timezone())
            limite_cancelacion = inicio_reserva + timedelta(minutes=15)
            
            if ahora < limite_cancelacion:
                diferencia = limite_cancelacion - ahora
                tiempo_restante_minutos = int(diferencia.total_seconds() / 60)
            else:
                tiempo_restante_minutos = 0 # Está a punto de ser cancelada por la lógica de control

    # Historial de últimas valoraciones/sugerencias enviadas
    ultimas_valoraciones = Valoracion.objects.filter(usuario=usuario).select_related('aula', 'aula__edificio').order_by('-fecha_creacion')[:4]
    
    # Obtiene la fecha actual del sistema
    hoy_sistema = timezone.localtime(timezone.now()).date()
    
    # Recupera el mes y año de la URL. Si no existen, coge los del día de hoy
    mes_actual = int(request.GET.get('mes', hoy_sistema.month))
    año_actual = int(request.GET.get('ano', hoy_sistema.year))
    
    # Calcula el mes anterior y posterior para las flechas (vista calendario)
    if mes_actual == 1:
        mes_anterior, año_anterior = 12, año_actual - 1
    else:
        mes_anterior, año_anterior = mes_actual - 1, año_actual
        
    if mes_actual == 12:
        mes_siguiente, año_siguiente = 1, año_actual + 1
    else:
        mes_siguiente, año_siguiente = mes_actual + 1, año_actual

    # Construye la matriz de días del mes
    cal = calendar.Calendar(firstweekday=0) # Empieza en lunes
    semanas_mes = cal.monthdayscalendar(año_actual, mes_actual)
    nombre_mes = _(calendar.month_name[mes_actual]).capitalize()
    
    # Mapeo y agrupación de las reservas de este mes en un diccionario ordenado por días {dia: [reservas]}
    agenda_dias = {}
    reservas_mes = Reserva.objects.filter(
        usuario=usuario,
        estado='activa',
        fecha__year=año_actual,
        fecha__month=mes_actual
    ).select_related('aula', 'aula__edificio')
    
    for res in reservas_mes:
        dia_clave = res.fecha.day
        if dia_clave not in agenda_dias:
            agenda_dias[dia_clave] = []
        agenda_dias[dia_clave].append(res)
    
    # Formatea los días del mes en una matriz (semanas y días) para ser dibujada como tabla HTML.
    # Cada día incluye su número, si corresponde a la fecha actual y su lista de eventos.
    matriz_calendario = []
    for semana in semanas_mes:
        semana_render = []
        for dia in semana:
            semana_render.append({
                'numero': dia,
                'es_hoy': (dia == hoy_sistema.day and mes_actual == hoy_sistema.month and año_actual == hoy_sistema.year),
                'eventos': agenda_dias.get(dia, []) if dia != 0 else []
            })
        matriz_calendario.append(semana_render)
    
    # Obtener el Top 5 de aulas más utilizadas por este profesor
    top_aulas = (Reserva.objects.filter(usuario=request.user)
                .exclude(estado='cancelada') # Omite las canceladas
                .values('aula__numero_aula', 'aula__edificio__numero_edificio')
                .annotate(total=Count('aula'))
                .order_by('-total')[:5])
        
    labs_aulas = [f"Aula {item['aula__numero_aula']}, Edificio {item['aula__edificio__numero_edificio']}" for item in top_aulas]
    datos_aulas = [item['total'] for item in top_aulas]

    context = {
        'usuario': usuario,
        'mis_reservas_activas': mis_reservas_activas,       
        'mis_reservas_canceladas': mis_reservas_canceladas,
        'mis_reservas_expiradas': mis_reservas_expiradas,
        'recursos': todos_los_recursos,
        'aulas_encontradas': aulas_encontradas,
        'busqueda_realizada': busqueda_realizada,
        'post_data': post_data,
        'active_tab': active_tab,
        'notificaciones_activas': notificaciones_activas,
        'notificaciones_count': notificaciones_activas.count(),
        'nombre_dia': nombre_dia,
        'matriz_calendario': matriz_calendario,
        'nombre_mes': nombre_mes,
        'año_actual': año_actual,
        'mes_anterior': mes_anterior,
        'ano_anterior': año_anterior,
        'mes_siguiente': mes_siguiente,
        'ano_siguiente': año_siguiente,
        'labs_aulas': labs_aulas,
        'datos_aulas': datos_aulas,
        'reserva_pendiente_valorar': reserva_pendiente_valorar,
        'kpi_total_activas': total_activas,
        'kpi_total_canceladas': total_canceladas,
        'kpi_porcentaje_asistencia': porcentaje_asistencia,
        'proxima_sesion': proxima_sesion,
        'necesita_checkin': necesita_checkin,
        'tiempo_restante_minutos': tiempo_restante_minutos,
        'ultimas_valoraciones': ultimas_valoraciones,
    }
    return render(request, 'reservas/panel_profesor.html', context)


@login_required
def validar_qr_simulado(request, reserva_id):
    # Compueba que la reserva pertenece al usuario logueado y esté activa
    try:
        reserva = Reserva.objects.get(id=reserva_id, usuario=request.user, estado='activa')
    except Reserva.DoesNotExist:
        messages.error(request, "Reserva no válida o ya procesada.")
        return redirect('/panel_profesor/?tab=tab-reservas')
    
    ahora = timezone.localtime(timezone.now())
    inicio_reserva = datetime.combine(reserva.fecha, reserva.hora_inicio)
    inicio_reserva = timezone.make_aware(inicio_reserva, timezone.get_current_timezone())
    
    # Desde 1 hora antes (-60 min) hasta 15 minutos después (+15 min)
    limite_inferior = inicio_reserva - timedelta(hours=1)
    limite_superior = inicio_reserva + timedelta(minutes=15)
    
    if not (limite_inferior <= ahora <= limite_superior):
        messages.error(request, "La validación por QR solo está disponible desde 1 hora antes y hasta 15 minutos después de empezar la clase.")
        return redirect('/panel_profesor/?tab=tab-reservas')

    # Procesa el formulario cuando el usuario escanea/introduce el token
    if request.method == 'POST':
        token_introducido = request.POST.get('token_qr')
        if token_introducido == reserva.aula.codigo_qr_token:
            reserva.fecha_validacion = timezone.now()
            reserva.save()
            messages.success(request, f"¡Presencia validada con éxito en el Aula {reserva.aula.numero_aula} del Edificio {reserva.aula.edificio.numero_edificio}! ")
            return redirect('/panel_profesor/?tab=tab-reservas')
        else:
            messages.error(request, "El código QR escaneado no pertenece a esta aula. Inténtelo de nuevo.")
            
    return render(request, 'reservas/validar_qr.html', {'reserva': reserva})


@login_required
def lanzar_recordatorios_push_simulados(request):
    ahora = timezone.localtime(timezone.now())
    un_hora_despues = ahora + timedelta(hours=1)
    
    # Busca reservas de hoy que empiecen dentro de la próxima hora
    reservas_proximas = Reserva.objects.filter(
        fecha=ahora.date(),
        estado='activa',
        hora_inicio__gte=ahora.time(),
        hora_inicio__lte=un_hora_despues.time()
    )
    
    alertas_enviadas = 0
    for res in reservas_proximas:
        # Evita duplicar el recordatorio si ya se le envió uno para esta reserva 
        ya_notificado = Notificacion.objects.filter(usuario=res.usuario, reserva=res, tipo='recordatorio').exists()
        
        if not ya_notificado:
            Notificacion.objects.create(
                usuario=res.usuario,
                reserva=res,
                titulo="⏰ Recordatorio de próxima reserva",
                mensaje=f"Hola {res.usuario.first_name}, te recordamos que tu reserva en el Edificio {res.aula.edificio.numero_edificio}, Aula {res.aula.numero_aula} comienza a las {res.hora_inicio.strftime('%H:%M')}. No olvides escanear el código QR al llegar.",
                tipo='recordatorio'
            )
            alertas_enviadas += 1
    
    if request.user.rol == 'administrador':
        return redirect('/panel_administrador/?tab=tab-dashboard')
    else:
        return redirect('/panel_profesor/?tab=tab-dashboard')


@login_required
def panel_administrador(request):
    # Comprobar que el usuario es el administrador
    if request.user.rol != 'administrador':
        return redirect('panel_profesor')

    usuario = request.user
    active_tab = request.GET.get('tab', 'tab-dashboard')

    total_usuarios = Usuario.objects.count()
    total_edificios = Edificio.objects.count()
    total_aulas = Aula.objects.count()
    
    # 1. Gráfica: Las 5 Aulas MÁS USADAS por TODOS los profesores (acumulado histórico de reservas activas o realizadas)
    # Contamos cuántas reservas totales tiene cada aula y ordenamos de mayor a menor
    aulas_top_uso = Aula.objects.annotate(
        total_reservas=Count('reserva')
    ).order_by('-total_reservas')[:5]
    
    labs_aulas_utilizadas = [f"Aula {a.numero_aula}" for a in aulas_top_uso]
    datos_aulas_utilizadas = [a.total_reservas for a in aulas_top_uso]

    # 2. Gráfica: Las 5 Aulas con MÁS INCIDENCIAS reportadas por TODOS los profesores (historial total de incidencias)
    # Contamos cuántas incidencias totales tiene cada aula y ordenamos de mayor a menor
    aulas_top_incidencias = Aula.objects.annotate(
        total_incidencias=Count('incidencia')
    ).order_by('-total_incidencias')[:5]
    
    labs_aulas_incidencias = [f"Aula {a.numero_aula}" for a in aulas_top_incidencias]
    datos_aulas_incidencias = [a.total_incidencias for a in aulas_top_incidencias]
    
    if request.method == 'POST':
        
        # ACCIÓN: Crear un usuario
        if 'btn_crear_usuario' in request.POST:
            username = request.POST.get('username')
            email = request.POST.get('email')
            correo_personal = request.POST.get('correo_personal')
            
            try:
                # Valida el correo institucional
                validate_email(email)
                # Valida el correo personal si el usuario ha escrito algo
                if correo_personal:
                    validate_email(correo_personal)
            except ValidationError:
                messages.error(request, "Error: El formato de uno de los correos introducidos no es válido.")
                return redirect('/panel_administrador/?tab=tab-usuarios')
            
            # Comprobar que el usuario no existe (nombre de usuario y email)
            if Usuario.objects.filter(username=username).exists():
                messages.error(request, f"Error: El nombre de usuario '{username}' ya está registrado.")
                return redirect('/panel_administrador/?tab=tab-usuarios')
            
            if email and Usuario.objects.filter(email=email).exists():
                messages.error(request, f"Error: El correo electrónico '{email}' ya está registrado.")
                return redirect('/panel_administrador/?tab=tab-usuarios')
            
            nuevo_usuario=Usuario.objects.create_user(    # .create_user gestiona el hashing interno de la contraseña
                            username=username,
                            first_name=request.POST.get('nombre'),
                            last_name=request.POST.get('apellidos'),
                            email=email,
                            correo_personal = request.POST.get('correo_personal'),
                            despacho = request.POST.get('despacho'),
                            password=request.POST.get('password'),
                            rol=request.POST.get('rol')
                        )
            
            if 'foto_perfil' in request.FILES:
                archivo_subido = request.FILES['foto_perfil']
                try:
                    img = Image.open(archivo_subido)
                    img.verify()
                    archivo_subido.seek(0)
                    nuevo_usuario.foto_perfil = archivo_subido
                except Exception:
                    # Si falla, borrar el usuario y mostrar error
                    nuevo_usuario.delete() 
                    messages.error(request, "Error: El archivo de foto subido está corrupto o tiene una extensión falsa.")
                    return redirect('/panel_administrador/?tab=tab-usuarios')
                nuevo_usuario.save()
            
            messages.success(request, "Usuario creado correctamente.")
            return redirect('/panel_administrador/?tab=tab-usuarios')
        
        # ACCIÓN: Eliminar un usuario
        elif 'btn_eliminar_usuario' in request.POST:
            id_u = request.POST.get('usuario_id')
            Usuario.objects.filter(id=id_u).delete()
            messages.success(request, "Usuario eliminado correctamente.")
            return redirect('/panel_administrador/?tab=tab-usuarios')

        # ACCIÓN: Modificar un usuario
        elif 'btn_modificar_usuario' in request.POST:
            u_id = request.POST.get('usuario_id')
            u = Usuario.objects.get(id=u_id)
            u.first_name = request.POST.get('nombre')
            u.last_name = request.POST.get('apellidos')
            u.correo_personal = request.POST.get('correo_personal')
            
            try:
                if u.correo_personal: # Solo valida si el campo no está vacío
                    validate_email(u.correo_personal)
            except ValidationError:
                messages.error(request, "Error: El formato del correo personal no es válido.")
                return redirect('/panel_administrador/?tab=tab-usuarios')
            
            u.despacho = request.POST.get('despacho')
            u.rol = request.POST.get('rol')
            
            if 'foto_perfil' in request.FILES:
                archivo_subido = request.FILES['foto_perfil']
                try:
                    img = Image.open(archivo_subido)
                    img.verify()
                    archivo_subido.seek(0)
                    u.foto_perfil = archivo_subido
                except Exception:
                    messages.error(request, "Error: El archivo de foto subido está corrupto o tiene una extensión falsa.")
                    return redirect('/panel_administrador/?tab=tab-usuarios')
                
            u.save()
            messages.success(request, f"Usuario '{u.username}' actualizado correctamente.")
            return redirect('/panel_administrador/?tab=tab-usuarios')

        # ACCIÓN: Crear un edificio
        elif 'btn_crear_edificio' in request.POST:
            numero_edificio=request.POST.get('numero_edificio')
            
            # Comprobar que el edificio no existe (numero de edificio)
            if Edificio.objects.filter(numero_edificio=numero_edificio).exists():
                messages.error(request, f"Error: Ya existe un edificio con el número {numero_edificio}.")
                return redirect('/panel_administrador/?tab=tab-edificios')
            
            Edificio.objects.create(
                numero_edificio=numero_edificio,
                nombre=request.POST.get('nombre'),
                operativo=request.POST.get('operativo') == 'True'
            )
            messages.success(request, "Edificio creado correctamente.")
            return redirect('/panel_administrador/?tab=tab-edificios')
            
        # ACCIÓN: Eliminar un edificio
        elif 'btn_eliminar_edificio' in request.POST:
            id_e = request.POST.get('edificio_id')
            Edificio.objects.filter(numero_edificio=id_e).delete()
            messages.success(request, "Edificio eliminado correctamente.")
            return redirect('/panel_administrador/?tab=tab-edificios')

        # ACCIÓN: Modificar un edificio
        elif 'btn_modificar_edificio' in request.POST:
            e_id = request.POST.get('edificio_id_original')
            e = Edificio.objects.get(numero_edificio=e_id)
            e.nombre = request.POST.get('nombre')
            
            nuevo_operativo = request.POST.get('operativo') == 'True'
            e.operativo = nuevo_operativo
            e.save()
            
            # Si el edificio pasa a estar no operativo, las aulas vinculadas a él se inhabilitan
            if not nuevo_operativo:
                e.aulas.filter(operativa=True).update(operativa=False)
            
            messages.success(request, f"Edificio {e.numero_edificio} actualizado correctamente.")
            return redirect('/panel_administrador/?tab=tab-edificios')

        # ACCIÓN: Crear un aula
        elif 'btn_crear_aula' in request.POST:
            edificio_id = request.POST.get('edificio_id')
            planta = request.POST.get('planta')
            numero_aula = request.POST.get('numero_aula')

            # Comprobar que el aula no existe (no puede haber dos aulas con el mismo número y planta en el mismo edificio)
            if Aula.objects.filter(edificio_id=edificio_id, planta=planta, numero_aula=numero_aula).exists():
                messages.error(request, f"Error: El Aula {numero_aula} (Planta {planta}) ya existe en el Edificio {edificio_id}.")
                return redirect('/panel_administrador/?tab=tab-aulas')
            
            capacidad_recibida = int(request.POST.get('capacidad_max'))
            if capacidad_recibida <= 0:
                messages.error(request, "Error: La capacidad máxima debe ser mayor que 0.")
                return redirect('/panel_administrador/?tab=tab-aulas')
            
            nueva_aula = Aula.objects.create(
                edificio_id=edificio_id,
                planta=planta,
                numero_aula=numero_aula,
                capacidad_max=request.POST.get('capacidad_max'),
                operativa=request.POST.get('operativa') == 'True'
            )
            
            recursos_seleccionados = request.POST.getlist('recursos_equipamiento')
            for rec_id in recursos_seleccionados:
                # Capturamos la cantidad correspondiente a este recurso específico
                cantidad_val = request.POST.get(f'cantidad_recurso_{rec_id}', 1)
                if cantidad_val and int(cantidad_val) > 0:
                    AulaEquipamiento.objects.create(
                        aula=nueva_aula,
                        recurso_id=int(rec_id),
                        cantidad=int(cantidad_val)
                    )
            messages.success(request, "Aula creada correctamente.")
            return redirect('/panel_administrador/?tab=tab-aulas')
        
        # ACCIÓN: Eliminar un aula
        elif 'btn_eliminar_aula' in request.POST:
            id_a = request.POST.get('aula_id')
            Aula.objects.filter(id=id_a).delete()
            messages.success(request, "Aula eliminada correctamente.")
            return redirect('/panel_administrador/?tab=tab-aulas')

        # ACCIÓN: Modificar un aula
        elif 'btn_modificar_aula' in request.POST:
            a_id = request.POST.get('aula_id')
            a = Aula.objects.get(id=a_id)
            a.edificio_id = request.POST.get('edificio_id')
            a.planta = request.POST.get('planta')
            a.numero_aula = request.POST.get('numero_aula')
            a.capacidad_max = int(request.POST.get('capacidad_max'))
            
            if a.capacidad_max <= 0:
                messages.error(request, "Error: La capacidad máxima debe ser mayor que 0.")
                return redirect('/panel_administrador/?tab=tab-aulas')
            
            a.operativa = request.POST.get('operativa') == 'True'
            a.save()
            
            AulaEquipamiento.objects.filter(aula=a).delete()
            
            recursos_seleccionados = request.POST.getlist('recursos_equipamiento')
            for rec_id in recursos_seleccionados:
                cantidad_val = request.POST.get(f'cantidad_recurso_{rec_id}', 1)
                if cantidad_val and int(cantidad_val) > 0:
                    AulaEquipamiento.objects.create(
                        aula=a,
                        recurso_id=int(rec_id),
                        cantidad=int(cantidad_val)
                    )
            
            messages.success(request, f"Aula {a.numero_aula} del Edificio {a.edificio.numero_edificio} actualizada correctamente.")
            return redirect('/panel_administrador/?tab=tab-aulas')
        
        # ACCIÓN: Crear un recurso
        elif 'btn_crear_recurso' in request.POST:
            nombre = request.POST.get('nombre')

            # Comprobar que el recurso no existe (__iexact para evitar duplicados por mayúsculas/minúsculas)
            if Recurso.objects.filter(nombre__iexact=nombre).exists():
                messages.error(request, f"Error: Ya existe un recurso registrado como '{nombre}'.")
                return redirect('/panel_administrador/?tab=tab-recursos')
            
            Recurso.objects.create(nombre=nombre)
            messages.success(request, "Recurso creado correctamente.")
            return redirect('/panel_administrador/?tab=tab-recursos')
            
        # ACCIÓN: Eliminar un recurso
        elif 'btn_eliminar_recurso' in request.POST:
            id_r = request.POST.get('recurso_id')
            Recurso.objects.filter(id=id_r).delete()
            messages.success(request, "Recurso eliminado correctamente.")
            return redirect('/panel_administrador/?tab=tab-recursos')
        
        # ACCIÓN: Modificar un recurso
        elif 'btn_modificar_recurso' in request.POST:
            r_id = request.POST.get('recurso_id')
            r = Recurso.objects.get(id=r_id)
            r.nombre = request.POST.get('nombre')
            r.save()
            
            messages.success(request, f"Equipamiento técnico actualizado.")
            return redirect('/panel_administrador/?tab=tab-recursos')

        # ACCIÓN: Resolver una incidencia
        elif 'btn_resolver_incidencia' in request.POST:
            inc_id = request.POST.get('incidencia_id')
            incidencia = Incidencia.objects.get(id=inc_id)
            incidencia.estado = 'resuelta'
            incidencia.save()
            
            aula = incidencia.aula
            aula.operativa = True  
            aula.save()

            # Notifica a profesores con reservas futuras en este aula de que la incidencia ha sido resuelta
            ahora = timezone.localtime(timezone.now())
            reservas_futuras = Reserva.objects.filter(
                aula=incidencia.aula,
                estado='activa',
                fecha__gte=ahora.date()
            )

            for res in reservas_futuras: 
                Notificacion.objects.create(
                    usuario=res.usuario,
                    reserva=res,
                    titulo="✅ Incidencia resuelta en tu aula",
                    mensaje=f"Hola {res.usuario.first_name}, te informamos de que la incidencia técnica registrada en el Edficio {incidencia.aula.edificio.numero_edificio}, Aula {incidencia.aula.numero_aula} para tu reserva del día {res.fecha} ha sido resuelta por mantenimiento. El aula y sus recursos ya están completamente operativos.",
                    tipo='recordatorio'
                )
                
                # Envía un correo a los profesores afectados
                if res.usuario.email:
                    send_mail(
                        subject=f"✅ INCIDENCIA RESUELTA: Aula {incidencia.aula.numero_aula} (Edificio {incidencia.aula.edificio.numero_edificio})",
                        message=(
                            f"Estimado/a profesor/a,\n\n"
                            f"Le informamos que el incidencia técnica reportada en el Aula {incidencia.aula.numero_aula} "
                            f"(Edificio {incidencia.aula.edificio.numero_edificio}) ha sido resuelta por mantenimiento.\n\n"
                            f"Los recursos y el espacio se encuentran al 100% de operatividad para su próxima reserva programada para el día {res.fecha}."
                        ),
                        from_email=None,
                        recipient_list=[res.usuario.email],
                        fail_silently=True
                    )

            messages.success(request, f"Incidencia marcada como resuelta. Se ha notificado a los profesores afectados.")
            return redirect('/panel_administrador/?tab=tab-incidencias')

        # ACCIÓN: Descartar una notificación (marcar como leída) 
        elif 'btn_descartar_notificacion' in request.POST:
            notificacion_id = request.POST.get('notificacion_id')
            try:
                noti = Notificacion.objects.get(id=int(notificacion_id), usuario=usuario)
                noti.leida = True # Cambia el campo a TRUE 
                noti.save()
                messages.success(request, "Notificación descartada.")
            except Notificacion.DoesNotExist:
                pass
            return redirect('/panel_administrador/?tab=tab-usuarios')

    notificaciones_admin = Notificacion.objects.filter(usuario=usuario, leida=False).order_by('-fecha_envio')
    
    context = {
        'usuario': usuario,
        'active_tab': active_tab,
        'usuarios_list': Usuario.objects.all().order_by('date_joined'),
        'edificios_list': Edificio.objects.all().order_by('numero_edificio'),
        'aulas_list': Aula.objects.annotate(numero_aula_int=Cast('numero_aula', output_field=IntegerField())).order_by('edificio', 'planta', 'numero_aula_int'),
        'recursos_list': Recurso.objects.all().order_by('id'),
        'incidencias_list': Incidencia.objects.filter(estado='activa').order_by('-id'),
        'notificaciones_admin': notificaciones_admin,
        'notificaciones_count': notificaciones_admin.count(), 
        'kpi_usuarios': total_usuarios,
        'kpi_edificios': total_edificios,
        'kpi_aulas': total_aulas,
        'labs_aulas_utilizadas': labs_aulas_utilizadas,
        'datos_aulas_utilizadas': datos_aulas_utilizadas,
        'labs_aulas_incidencias': labs_aulas_incidencias,
        'datos_aulas_incidencias': datos_aulas_incidencias,
    }
    return render(request, 'reservas/panel_administrador.html', context)


def recuperar_contrasena(request):
    exito = False
    email_enviado = ""
    if request.method == 'POST':
        email = request.POST.get('email')
        
        try:
            validate_email(email)
        except ValidationError:
            # Si el formato es inválido, muestra el mismo error sin consultar la base de datos
            messages.error(request, "ERROR")
            return render(request, 'reservas/recuperar_contrasena.html', {'exito': exito, 'email_enviado': email_enviado})
        
        try:
            user = Usuario.objects.get(email=email)
            # Encripta el ID del usuario en base64 de forma sencilla para meterlo en la URL segura
            token_seguro = f"{user.id}:{user.password}"
            user_id_b64 = base64.b64encode(token_seguro.encode('utf-8')).decode('utf-8')
            enlace_restaurar = f"http://127.0.0.1:8000/restablecer-contrasena/{user_id_b64}/"
                
            # Envía el correo al email indicado
            send_mail(
                subject="🔒 Restablecimiento de contraseña - Gestión Aulas UPO",
                message=(
                    f"Se ha solicitado un enlace de recuperación para su cuenta vinculada al correo: {email}.\n\n"
                    f"Haga clic en el siguiente enlace para establecer una nueva contraseña:\n"
                    f"{enlace_restaurar}\n\n"
                    f"Si no ha realizado esta solicitud, puede ignorar este mensaje de seguridad de la UPO."
                ),
                from_email=None,
                recipient_list=[email],
                fail_silently=True
            )
            messages.success(request, "SUCCESS")
            email_enviado = email
            exito = True
        except Usuario.DoesNotExist:
            messages.error(request, "ERROR")
            
    return render(request, 'reservas/recuperar_contrasena.html', {'exito': exito, 'email_enviado': email_enviado})


def restablecer_contrasena(request, uidb64):
    exito_cambio = False
    try:
        # Decodifica el ID del usuario del enlace
        token_decodificado = base64.b64decode(uidb64.encode('utf-8')).decode('utf-8')
        user_id_str, password_fragmento = token_decodificado.split(':', 1)
        user = Usuario.objects.get(id=int(user_id_str))
        
        # Valida que la contraseña no haya cambiado desde que se envió el correo
        if user.password != password_fragmento:
            raise ValueError("El enlace ya ha sido utilizado.")
    except (TypeError, ValueError, OverflowError, Usuario.DoesNotExist, Exception):
        messages.error(request, "ERROR_LINK")
        return render(request, 'reservas/login.html')

    if request.method == 'POST':
        pass1 = request.POST.get('pass1')
        pass2 = request.POST.get('pass2')

        if pass1 != pass2:
            messages.error(request, "ERROR")
        else:
            user.set_password(pass1)
            user.save()
            exito_cambio = True
            messages.success(request, "SUCCESS")

    return render(request, 'reservas/restablecer_contrasena.html', {'exito_cambio': exito_cambio})

def cerrar_sesion(request):
    logout(request)
    return redirect('/')