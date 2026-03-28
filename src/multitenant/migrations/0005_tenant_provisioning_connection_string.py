# Generated manually on 2026-03-22

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("multitenant", "0004_tenant_provisioning_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="provisioning_connection_string",
            field=models.TextField(
                blank=True,
                help_text="Encrypted admin connection URL used to provision tenant databases.",
                null=True,
            ),
        ),
    ]
