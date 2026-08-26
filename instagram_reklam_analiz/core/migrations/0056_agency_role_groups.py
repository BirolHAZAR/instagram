from django.db import migrations, models
import django.db.models.deletion


def migrate_member_permissions_to_groups(apps, schema_editor):
    AgencyRoleGroup = apps.get_model("core", "AgencyRoleGroup")
    OrganizationMember = apps.get_model("core", "OrganizationMember")
    role_permissions = {
        "owner": {
            "can_manage_clients", "can_manage_accounts", "can_manage_competitors",
            "can_view_reports", "can_manage_members", "can_manage_billing",
        },
        "admin": {
            "can_manage_clients", "can_manage_accounts", "can_manage_competitors",
            "can_view_reports", "can_manage_members",
        },
        "editor": {
            "can_manage_clients", "can_manage_accounts", "can_manage_competitors",
            "can_view_reports",
        },
        "viewer": {"can_view_reports"},
    }
    flag_names = [
        "can_manage_clients", "can_manage_accounts", "can_manage_competitors",
        "can_view_reports", "can_manage_members", "can_manage_billing",
    ]

    for member in OrganizationMember.objects.filter(role_group__isnull=True).iterator():
        allowed = set(role_permissions.get(member.role, set()))
        allowed.update(name for name in flag_names if getattr(member, name, False))
        group = AgencyRoleGroup.objects.create(
            organization_id=member.organization_id,
            name=f"Aktarılan {member.get_role_display()} #{member.pk}",
            description="Mevcut kullanıcı yetkilerinden otomatik aktarıldı.",
            menu_permissions=list(member.menu_permissions or []),
            **{name: name in allowed for name in flag_names},
        )
        member.role_group_id = group.pk
        member.save(update_fields=["role_group"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0055_userprofile_concurrent_sessions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgencyRoleGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, verbose_name="Yetki grubu adı")),
                ("description", models.CharField(blank=True, default="", max_length=240, verbose_name="Açıklama")),
                ("system_key", models.CharField(blank=True, default="", editable=False, max_length=30)),
                ("can_manage_clients", models.BooleanField(default=False, verbose_name="Müşteri yönetebilir")),
                ("can_manage_accounts", models.BooleanField(default=False, verbose_name="Hesap bağlayabilir")),
                ("can_manage_competitors", models.BooleanField(default=False, verbose_name="Rakip yönetebilir")),
                ("can_view_reports", models.BooleanField(default=True, verbose_name="Rapor görebilir")),
                ("can_manage_members", models.BooleanField(default=False, verbose_name="Kullanıcı/yetki yönetebilir")),
                ("can_manage_billing", models.BooleanField(default=False, verbose_name="Paket/fatura yönetebilir")),
                ("menu_permissions", models.JSONField(blank=True, default=list, verbose_name="Menü / modül yetkileri")),
                ("is_active", models.BooleanField(default=True, verbose_name="Aktif")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="role_groups", to="core.organization")),
            ],
            options={
                "verbose_name": "Ajans Yetki Grubu",
                "verbose_name_plural": "Ajans Yetki Grupları",
                "ordering": ["organization__name", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="agencyrolegroup",
            constraint=models.UniqueConstraint(fields=("organization", "name"), name="unique_agency_role_group_name"),
        ),
        migrations.AddField(
            model_name="organizationmember",
            name="role_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="members",
                to="core.agencyrolegroup",
                verbose_name="Yetki grubu",
            ),
        ),
        migrations.RunPython(migrate_member_permissions_to_groups, migrations.RunPython.noop),
    ]
