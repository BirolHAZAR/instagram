from django.urls import path
from core.views.control_tower import control_tower, control_tower_archive

urlpatterns = [
    
    path('control-tower/', control_tower, name='control_tower'),
    path('control-tower/archive/', control_tower_archive, name='control_tower_archive'),





]

