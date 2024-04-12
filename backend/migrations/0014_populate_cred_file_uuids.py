# Generated by Django 4.2.7 on 2024-04-12 21:35

from django.db import migrations
import uuid

def gen_uuids(apps, schema_editor):
    """
    Generate the UUIDs for all existing elements in the database.
    
    In general, this should be non-destructive; if through some miracle a
    credential/file was made before the UUID system was implemented, it does
    not need to be synchronized with the agents. 
    """
    file_model = apps.get_model("backend", "File")
    for row in file_model.objects.all():
        if row.file_id is None:
            row.file_id = uuid.uuid4()
            row.save(update_fields=["file_id"])
            
    credential_model = apps.get_model("backend", "Credential")
    for row in credential_model.objects.all():
        if row.credential_id is None:
            row.credential_id = uuid.uuid4()
            row.save(update_fields=["credential_id"])

class Migration(migrations.Migration):

    dependencies = [
        ("backend", "0013_remove_credential_id_remove_file_id_and_more"),
    ]

    operations = [
        migrations.RunPython(gen_uuids, reverse_code=migrations.RunPython.noop)
    ]
