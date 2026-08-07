import uuid     # Para generar el token del código QR
from django.db import models
from django.contrib.auth.models import AbstractUser

# Create your models here.

class Usuario(AbstractUser):
    # Extiende AbstractUser del que se hereda: username, nombre, apellidos, email y contraseña
    ROL_CHOICES = [
        ('profesor', 'Profesor'),
        ('administrador', 'Administrador'),
    ]
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default='profesor')
    correo_personal = models.EmailField(max_length=254, null=True, blank=True)
    despacho = models.CharField(max_length=50, null=True, blank=True)
    foto_perfil = models.ImageField(upload_to='perfiles/', null=True, blank=True)

    def __str__(self):
        return f"{self.username} ({self.get_rol_display()})"


class Edificio(models.Model):
    numero_edificio = models.IntegerField(primary_key=True)
    nombre = models.CharField(max_length=100)
    operativo = models.BooleanField(default=True)
    
    # Se cuentan las aulas que están asociadas al edificio
    @property
    def cantidad_aulas(self):
        return self.aulas.count()

    def __str__(self):
        return f"Edificio {self.numero_edificio} - {self.nombre}"


class Recurso(models.Model):
    nombre = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre


class Aula(models.Model):
    # Si se borra el edificio, se borran sus aulas
    edificio = models.ForeignKey(Edificio, on_delete=models.CASCADE, related_name='aulas')
    planta = models.IntegerField()
    numero_aula = models.CharField(max_length=10)
    capacidad_max = models.IntegerField()
    # Token único que se utilizará para generar y validar la presencia mediante código QR
    codigo_qr_token = models.CharField(max_length=100, unique=True, null=True, blank=True, editable=False)
    operativa = models.BooleanField(default=True)
    
    # Relación muchos a muchos con Recurso con tabla intermedia
    equipamiento = models.ManyToManyField(Recurso, through='AulaEquipamiento')

    # Sobrescribe el método save
    # Si el aula es nueva, genera un token único aleatorio antes de guardar el registro
    def save(self, *args, **kwargs):
        if not self.id and not self.codigo_qr_token:
            self.codigo_qr_token = str(uuid.uuid4())
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"Aula {self.numero_aula} (Planta {self.planta}) - Edificio: {self.edificio.nombre}"


class AulaEquipamiento(models.Model):
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE)
    recurso = models.ForeignKey(Recurso, on_delete=models.CASCADE)
    cantidad = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.cantidad}x {self.recurso.nombre} en Aula {self.aula.numero_aula} ({self.aula.edificio.nombre})"


class Reserva(models.Model):
    ESTADO_CHOICES = [
        ('activa', 'Activa'),
        ('cancelada', 'Cancelada'),
        ('finalizada', 'Finalizada'),
    ]
    TIPO_CHOICES = [
        ('puntual', 'Puntual'),
        ('periodica', 'Periódica'),
    ]
    
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE)
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='activa')
    fecha_validacion = models.DateTimeField(null=True, blank=True) # Para el check-in del QR
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='puntual')

    def __str__(self):
        return f"Reserva {self.id} - Aula {self.aula.numero_aula} ({self.aula.edificio.nombre}) - {self.fecha}"


class Incidencia(models.Model):
    GRAVEDAD_CHOICES = [
        ('baja', 'Baja'),
        ('media', 'Media'),
        ('alta', 'Alta'),
    ]
    ESTADO_CHOICES = [
        ('activa', 'Activa'),
        ('resuelta', 'Resuelta'),
    ]

    aula = models.ForeignKey(Aula, on_delete=models.CASCADE)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    # Se usa SET_NULL para que, si el recurso o la reserva se borran, la incidencia no desaparezca
    reserva = models.ForeignKey(Reserva, on_delete=models.SET_NULL, null=True, blank=True)
    descripcion = models.TextField()
    gravedad = models.CharField(max_length=20, choices=GRAVEDAD_CHOICES, default='baja')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='activa')

    def __str__(self):
        return f"Incidencia {self.get_gravedad_display()} - Aula {self.aula.numero_aula} ({self.aula.edificio.nombre})"


class Notificacion(models.Model):
    TIPO_CHOICES = [
        ('recordatorio', 'Recordatorio'),
        ('incidencia', 'Incidencia'),
        ('reasignacion', 'Reasignación'),
    ]
    
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    reserva = models.ForeignKey(Reserva, on_delete=models.SET_NULL, null=True, blank=True)
    titulo = models.CharField(max_length=100)
    mensaje = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leida = models.BooleanField(default=False)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='recordatorio')

    def __str__(self):
        return f"[{self.get_tipo_display()}] Notificación para {self.usuario.username}: {self.titulo}"

class Valoracion(models.Model):
    reserva = models.OneToOneField(Reserva, on_delete=models.CASCADE, related_name='valoracion')
    aula = models.ForeignKey(Aula, on_delete=models.CASCADE, related_name='sugerencias')
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE)
    puntuacion = models.PositiveIntegerField(default=5) # Guardará de 1 a 5 estrellas
    comentario = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Valoración {self.puntuacion}★ - Aula {self.aula.numero_aula}, Edificio {self.aula.edificio.numero_edificio} por {self.usuario.username}"