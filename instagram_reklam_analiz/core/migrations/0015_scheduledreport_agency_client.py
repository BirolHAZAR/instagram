from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0014_octoruleenginerun")]
    operations = [
        migrations.AddField(
            model_name="scheduledreport",
            name="agency_client",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="scheduled_reports", to="core.agencyclient",
                verbose_name="Ajans müşterisi",
            ),
        ),
    ]
