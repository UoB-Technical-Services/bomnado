from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bom', '0024_pcbpart_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='pcbpart',
            old_name='Designation',
            new_name='Value',
        ),
    ]
