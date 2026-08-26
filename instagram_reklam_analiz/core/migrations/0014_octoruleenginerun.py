from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0013_reklam_ai_report_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="OctoRuleEngineRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("trigger", models.CharField(choices=[("ad_sync", "Reklam senkronizasyonu"), ("metric_refresh", "Metrik güncellemesi"), ("periodic_sweep", "Periyodik güvenlik taraması"), ("manual", "Manuel")], default="manual", max_length=30)),
                ("status", models.CharField(choices=[("running", "Çalışıyor"), ("completed", "Tamamlandı"), ("failed", "Hatalı"), ("skipped", "Atlandı")], default="running", max_length=20)),
                ("celery_task_id", models.CharField(blank=True, default="", max_length=255)),
                ("active_rule_count", models.PositiveIntegerField(default=0)),
                ("campaigns_evaluated", models.PositiveIntegerField(default=0)),
                ("signals_matched", models.PositiveIntegerField(default=0)),
                ("tasks_created", models.PositiveIntegerField(default=0)),
                ("tasks_skipped", models.PositiveIntegerField(default=0)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("platform_account", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="octo_rule_engine_runs", to="core.platformaccount")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="octo_rule_engine_runs", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.AddConstraint(
            model_name="octoruleenginerun",
            constraint=models.UniqueConstraint(condition=models.Q(("status", "running")), fields=("user",), name="unique_running_octo_engine_per_user"),
        ),
        migrations.AddIndex(
            model_name="octoruleenginerun",
            index=models.Index(fields=["user", "status", "started_at"], name="core_octoru_user_id_3b348a_idx"),
        ),
        migrations.AddIndex(
            model_name="octoruleenginerun",
            index=models.Index(fields=["platform_account", "started_at"], name="core_octoru_platfor_6c83dc_idx"),
        ),
    ]
