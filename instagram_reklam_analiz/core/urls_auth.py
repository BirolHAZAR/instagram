from django.urls import path
from django.views.generic import RedirectView
from core.views import auth

urlpatterns = [
    path('login/', RedirectView.as_view(pattern_name='account_login', permanent=False), name='login'),
    path('signup/', RedirectView.as_view(pattern_name='account_signup', permanent=False), name='signup'),
    path('profile/', auth.profile_view, name='profile'),
    path('profile/update/', auth.profile_update, name='profile_update'),
    path('password/change/', auth.change_password, name='change_password'),
    path('account/delete/', auth.account_delete, name='account_delete'),
]
