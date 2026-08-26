from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0061_enforce_single_agency_per_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="organization",
            name="additional_seats",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Paketin dahil koltuk sayısına bu kadar ek kontenjan eklenir.",
                verbose_name="Ek alt kullanıcı koltuğu",
            ),
        ),
    ]
