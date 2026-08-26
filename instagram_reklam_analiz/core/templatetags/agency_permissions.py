from django import template
from core.services.agency_permission_matrix import user_has_agency_menu_permission


register = template.Library()


@register.filter
def contains(value, item):
    return item in (value or [])


@register.simple_tag
def can_agency_menu(user, permission_key):
    return user_has_agency_menu_permission(user, permission_key)
