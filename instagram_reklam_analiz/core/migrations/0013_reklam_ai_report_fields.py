from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0012_normalize_notification_icons")]

    operations = [
        migrations.AddField(
            model_name="reklamaianaliz",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ad_ai_reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="reklamaianaliz",
            name="report_type",
            field=models.CharField(choices=[("analysis", "Reklam Analizi"), ("recommendation", "Reklam Önerisi")], db_index=True, default="analysis", max_length=20),
        ),
        migrations.AddField(model_name="reklamaianaliz", name="recommendation_summary", field=models.TextField(blank=True, null=True, verbose_name="Öneri Özeti")),
        migrations.AddField(model_name="reklamaianaliz", name="metrics_payload", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="reklamaianaliz", name="creative_payload", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="reklamaianaliz", name="rules_payload", field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="reklamaianaliz", name="strategy_payload", field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name="reklamaianaliz", name="active_rule_count", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="reklamaianaliz", name="matched_rule_count", field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name="reklamaianaliz", name="visual_analyzed", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="reklamaianaliz", name="ai_model_used", field=models.CharField(blank=True, default="", max_length=100)),
        migrations.AddField(model_name="reklamaianaliz", name="updated_at", field=models.DateTimeField(auto_now=True)),
        migrations.AddIndex(
            model_name="reklamaianaliz",
            index=models.Index(fields=["reklam", "report_type", "-created_at"], name="core_reklam_reklam__9f7384_idx"),
        ),
    ]
