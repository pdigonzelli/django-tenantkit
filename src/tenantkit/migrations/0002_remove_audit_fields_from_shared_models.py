from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenantkit", "0001_initial"),
    ]

    operations = [
        # Tenant
        migrations.RemoveField(model_name="tenant", name="created_by"),
        migrations.RemoveField(model_name="tenant", name="updated_by"),
        migrations.RemoveField(model_name="tenant", name="deleted_by"),
        # TenantMembership
        migrations.RemoveField(model_name="tenantmembership", name="created_by"),
        migrations.RemoveField(model_name="tenantmembership", name="updated_by"),
        migrations.RemoveField(model_name="tenantmembership", name="deleted_by"),
        # TenantInvitation
        migrations.RemoveField(model_name="tenantinvitation", name="created_by"),
        migrations.RemoveField(model_name="tenantinvitation", name="updated_by"),
        migrations.RemoveField(model_name="tenantinvitation", name="deleted_by"),
        # TenantSetting
        migrations.RemoveField(model_name="tenantsetting", name="created_by"),
        migrations.RemoveField(model_name="tenantsetting", name="updated_by"),
        migrations.RemoveField(model_name="tenantsetting", name="deleted_by"),
    ]
