from django.db import models

class Platform(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name="Platform Adı")
    code = models.CharField(max_length=20, unique=True, verbose_name="Platform Kodu")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")
    icon = models.CharField(max_length=50, blank=True, null=True, verbose_name="Icon class")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Platform"
        verbose_name_plural = "Platformlar"
        ordering = ['name']
    
    def __str__(self):
        return self.name