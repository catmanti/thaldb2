from django import template
from users.permissions import can_user_edit_entry

register = template.Library()


@register.filter
def can_edit_entry(entry, user):
    """
    Template filter to check if a user has permission to edit a clinical entry.
    Usage: {% if adm|can_edit_entry:request.user %}
    """
    return can_user_edit_entry(user, entry)
