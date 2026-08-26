from django.conf import settings
from django.db import migrations


def create_missing_user_profiles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    UserProfile = apps.get_model("core", "UserProfile")
    existing_user_ids = set(UserProfile.objects.values_list("user_id", flat=True))
    UserProfile.objects.bulk_create(
        UserProfile(user_id=user_id)
        for user_id in User.objects.exclude(id__in=existing_user_ids).values_list("id", flat=True)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0059_backfill_legacy_managed_subaccounts"),
    ]

    operations = [
        migrations.RunPython(
            create_missing_user_profiles,
            migrations.RunPython.noop,
        ),
    ]
