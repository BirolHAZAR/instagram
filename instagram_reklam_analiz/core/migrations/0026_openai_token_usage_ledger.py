import re

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


TOKEN_NOTE = re.compile(r"input=(\d+), output=(\d+), total=(\d+)")


def move_token_rows_out_of_credit_ledger(apps, schema_editor):
    Credit = apps.get_model("core", "AICreditLedger")
    Token = apps.get_model("core", "OpenAITokenUsageLedger")
    Balance = apps.get_model("core", "UserAICreditBalance")

    bad_rows = Credit.objects.filter(action="consume", note__startswith="OpenAI token kullanimi:")
    for row in bad_rows.iterator():
        match = TOKEN_NOTE.search(row.note or "")
        if not match:
            continue
        input_tokens, output_tokens, total_tokens = map(int, match.groups())
        Token.objects.create(
            user_id=row.user_id,
            organization_id=row.organization_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            reference=row.reference,
            used_at=row.created_at,
        )
        row.delete()

    # Cached balances must reflect the cleaned credit ledger immediately.
    for balance in Balance.objects.all().iterator():
        consumed = Credit.objects.filter(
            user_id=balance.user_id,
            organization_id=balance.organization_id,
            action="consume",
            amount__lt=0,
            created_at__date__gte=balance.cycle_start,
            created_at__date__lt=balance.cycle_end,
        ).aggregate(total=models.Sum("amount"))["total"] or 0
        balance.used_credits = abs(int(consumed))
        balance.current_balance = max(
            0, int(balance.plan_credits or 0) + int(balance.purchased_credits or 0) - balance.used_credits
        )
        balance.save(update_fields=["used_credits", "current_balance"])


class Migration(migrations.Migration):
    dependencies = [("core", "0025_link_env_notifications_to_error_logs")]

    operations = [
        migrations.CreateModel(
            name="OpenAITokenUsageLedger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("model_name", models.CharField(blank=True, default="", max_length=120)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("total_tokens", models.PositiveIntegerField(default=0)),
                ("reference", models.CharField(blank=True, default="", max_length=120)),
                ("note", models.TextField(blank=True, default="")),
                ("used_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="openai_token_usage", to="core.organization")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="openai_token_usage", to="auth.user")),
            ],
            options={"verbose_name": "OpenAI Token Kullanimi", "verbose_name_plural": "OpenAI Token Kullanimlari", "ordering": ["-used_at", "-id"]},
        ),
        migrations.AddIndex(model_name="openaitokenusageledger", index=models.Index(fields=["user", "used_at"], name="core_openai_user_id_8195c0_idx")),
        migrations.AddIndex(model_name="openaitokenusageledger", index=models.Index(fields=["organization", "used_at"], name="core_openai_organiz_666e28_idx")),
        migrations.AddIndex(model_name="openaitokenusageledger", index=models.Index(fields=["reference", "used_at"], name="core_openai_referen_1d5934_idx")),
        migrations.RunPython(move_token_rows_out_of_credit_ledger, migrations.RunPython.noop),
    ]
