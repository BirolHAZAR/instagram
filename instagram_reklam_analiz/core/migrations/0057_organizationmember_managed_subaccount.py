from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0056_agency_role_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationmember",
            name="is_managed_subaccount",
            field=models.BooleanField(
                default=False,
                editable=False,
                verbose_name="Ajans tarafından oluşturulan alt hesap",
            ),
        ),
    ]
