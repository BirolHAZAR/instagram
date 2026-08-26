from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0057_organizationmember_managed_subaccount"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "auth_user_email_ci_unique "
                "ON auth_user (LOWER(email)) "
                "WHERE email <> '';"
            ),
            reverse_sql=(
                "DROP INDEX IF EXISTS auth_user_email_ci_unique;"
            ),
        ),
    ]
