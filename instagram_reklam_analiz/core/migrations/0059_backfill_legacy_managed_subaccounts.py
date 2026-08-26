from django.db import migrations
from django.db.models import F, Q


def mark_legacy_managed_subaccounts(apps, schema_editor):
    OrganizationMember = apps.get_model("core", "OrganizationMember")
    OrganizationMember.objects.exclude(
        user_id=F("organization__owner_id"),
    ).filter(
        Q(user__email="") | Q(user__password__startswith="!")
    ).update(is_managed_subaccount=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0058_unique_user_email_case_insensitive"),
    ]

    operations = [
        migrations.RunPython(
            mark_legacy_managed_subaccounts,
            migrations.RunPython.noop,
        ),
    ]
