from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0049_move_pdf_report_to_bottom"),
    ]

    operations = [
        migrations.AlterField(
            model_name="demorequest",
            name="company",
            field=models.CharField(
                blank=True,
                default="",
                max_length=180,
                verbose_name="Firma / Marka",
            ),
        ),
    ]
