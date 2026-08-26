from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0054_replace_example_com_demo_urls"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="active_session_key",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=40,
                verbose_name="Aktif oturum anahtarı",
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="active_session_last_seen",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="Aktif oturum son kullanım",
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="allow_concurrent_sessions",
            field=models.BooleanField(
                default=False,
                help_text="Açık olduğunda kullanıcı aynı anda birden fazla tarayıcıda çalışabilir.",
                verbose_name="Eşzamanlı oturumlara izin ver",
            ),
        ),
    ]
