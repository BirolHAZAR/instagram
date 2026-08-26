from django.db import migrations


def fix_default_site_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=1, domain="example.com").update(
        domain="www.reklamanaliz.net",
        name="ReklamAnaliz.net",
    )


def restore_default_site_domain(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=1, domain="www.reklamanaliz.net", name="ReklamAnaliz.net").update(
        domain="example.com",
        name="example.com",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_legal_documents"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(fix_default_site_domain, restore_default_site_domain),
    ]
