from django.conf import settings
from django.db import migrations, models


def copy_accepted_by_to_string(apps, schema_editor):
    TenantInvitation = apps.get_model("tenantkit", "TenantInvitation")
    UserModel = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    invitations = TenantInvitation.objects.exclude(accepted_by__isnull=True)
    for invitation in invitations.iterator():
        accepted_by_id = invitation.accepted_by_id
        accepted_by_value = ""

        if accepted_by_id is not None:
            user = UserModel.objects.filter(pk=accepted_by_id).only("username").first()
            if user is not None:
                accepted_by_value = getattr(user, "username", "") or str(accepted_by_id)
            else:
                accepted_by_value = str(accepted_by_id)

        invitation.accepted_by_value = accepted_by_value
        invitation.save(update_fields=["accepted_by_value"])


class Migration(migrations.Migration):
    dependencies = [
        ("tenantkit", "0002_remove_audit_fields_from_shared_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantinvitation",
            name="accepted_by_value",
            field=models.CharField(max_length=255, blank=True, default=""),
        ),
        migrations.RunPython(
            copy_accepted_by_to_string,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="tenantinvitation",
            name="accepted_by",
        ),
        migrations.RenameField(
            model_name="tenantinvitation",
            old_name="accepted_by_value",
            new_name="accepted_by",
        ),
        migrations.AlterField(
            model_name="tenantinvitation",
            name="accepted_by",
            field=models.CharField(
                max_length=255,
                blank=True,
                default="",
                help_text="Identifier of the user who accepted (stored as string for cross-DB compatibility).",
            ),
        ),
        migrations.DeleteModel(
            name="TenantMembership",
        ),
    ]
