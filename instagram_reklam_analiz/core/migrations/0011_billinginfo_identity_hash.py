import hashlib

from django.db import migrations, models


BILLING_IDENTITY_FIELDS = [
    "customer_type",
    "first_name",
    "last_name",
    "email",
    "phone",
    "company_name",
    "tax_office",
    "tax_number",
    "tc_kimlik",
    "address",
    "city",
    "district",
    "zip_code",
]


def normalize_identity_value(value, lower=False):
    value = str(value or "").strip()
    value = " ".join(value.split())
    return value.lower() if lower else value


def build_identity_hash(billing_info):
    parts = [
        normalize_identity_value(getattr(billing_info, "customer_type", "")) or "individual",
        normalize_identity_value(getattr(billing_info, "first_name", "")),
        normalize_identity_value(getattr(billing_info, "last_name", "")),
        normalize_identity_value(getattr(billing_info, "email", ""), lower=True),
        normalize_identity_value(getattr(billing_info, "phone", "")),
        normalize_identity_value(getattr(billing_info, "company_name", "")),
        normalize_identity_value(getattr(billing_info, "tax_office", "")),
        normalize_identity_value(getattr(billing_info, "tax_number", "")),
        normalize_identity_value(getattr(billing_info, "tc_kimlik", "")),
        normalize_identity_value(getattr(billing_info, "address", "")),
        normalize_identity_value(getattr(billing_info, "city", "")),
        normalize_identity_value(getattr(billing_info, "district", "")),
        normalize_identity_value(getattr(billing_info, "zip_code", "")),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def populate_hashes_and_merge_duplicates(apps, schema_editor):
    BillingInfo = apps.get_model("core", "BillingInfo")
    Invoice = apps.get_model("core", "Invoice")
    Payment = apps.get_model("core", "Payment")

    canonical_by_key = {}
    duplicates = []

    for billing_info in BillingInfo.objects.order_by("user_id", "created_at", "id").iterator():
        identity_hash = build_identity_hash(billing_info)
        key = (billing_info.user_id, identity_hash)
        canonical = canonical_by_key.get(key)
        if canonical is None:
            billing_info.identity_hash = identity_hash
            billing_info.save(update_fields=["identity_hash"])
            canonical_by_key[key] = billing_info
            continue
        duplicates.append((billing_info.id, canonical.id))

    for duplicate_id, canonical_id in duplicates:
        Payment.objects.filter(billing_info_id=duplicate_id).update(billing_info_id=canonical_id)
        Invoice.objects.filter(billing_info_id=duplicate_id).update(billing_info_id=canonical_id)
        BillingInfo.objects.filter(id=duplicate_id).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_marketplace_supported_platforms"),
    ]

    operations = [
        migrations.AddField(
            model_name="billinginfo",
            name="identity_hash",
            field=models.CharField(blank=True, db_index=True, default="", max_length=64),
        ),
        migrations.RunPython(populate_hashes_and_merge_duplicates, noop_reverse),
        migrations.AddConstraint(
            model_name="billinginfo",
            constraint=models.UniqueConstraint(
                fields=("user", "identity_hash"),
                name="uniq_billing_info_user_identity",
            ),
        ),
    ]
