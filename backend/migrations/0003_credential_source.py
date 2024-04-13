# Generated by Django 4.2.7 on 2024-04-13 02:20

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0002_file_remote_path_file_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="credential",
            name="source",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="credentials",
                to="backend.endpoint",
            ),
        ),
    ]