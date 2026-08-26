from django.db import migrations


TARGET_PLAN_NAMES = {"gold", "platinum", "platinyum"}
PDF_REPORT = "pdf rapor"


def move_pdf_report_to_bottom(apps, schema_editor):
    MembershipPlan = apps.get_model("core", "MembershipPlan")

    for plan in MembershipPlan.objects.filter(name__in=TARGET_PLAN_NAMES).iterator():
        feature_lines = plan.features.splitlines()
        pdf_lines = [line for line in feature_lines if line.strip().casefold() == PDF_REPORT]
        if not pdf_lines:
            continue

        other_lines = [line for line in feature_lines if line.strip().casefold() != PDF_REPORT]
        updated_features = "\n".join([*other_lines, pdf_lines[0]])

        if updated_features != plan.features:
            plan.features = updated_features
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0048_remove_priority_email_support_feature"),
    ]

    operations = [
        migrations.RunPython(move_pdf_report_to_bottom, migrations.RunPython.noop),
    ]
