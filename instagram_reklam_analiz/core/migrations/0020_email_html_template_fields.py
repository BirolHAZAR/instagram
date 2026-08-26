from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0019_upgrade_sales_email_copy")]
    operations = [
        migrations.AddField(model_name="lifecycleemailcampaign", name="html_template", field=models.TextField(blank=True, default="", help_text="İsteğe bağlıdır. Boş bırakırsanız profesyonel varsayılan tasarım kullanılır. {{ first_name }}, {{ campaign.subject }}, {{ campaign.body }}, {{ campaign.cta_url }} değişkenlerini kullanabilirsiniz.")),
        migrations.AddField(model_name="announcement", name="html_template", field=models.TextField(blank=True, default="", help_text="Boş bırakırsanız profesyonel varsayılan duyuru tasarımı kullanılır. {{ announcement.title }}, {{ announcement.message }} ve {{ announcement.link }} değişkenlerini kullanabilirsiniz.", verbose_name="Özel e-posta HTML şablonu")),
    ]
