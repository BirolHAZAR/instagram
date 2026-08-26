from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0060_backfill_user_profiles"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="organizationmember",
            constraint=models.UniqueConstraint(
                condition=models.Q(("role", "owner"), _negated=True),
                fields=("user",),
                name="unique_agency_membership_per_user",
            ),
        ),
    ]
