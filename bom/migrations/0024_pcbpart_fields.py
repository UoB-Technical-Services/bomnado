# Generated manually to add PCBPart metadata fields.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bom', '0023_pcbsubassembly'),
    ]

    operations = [
        migrations.AddField(
            model_name='pcbpart',
            name='Footprint',
            field=models.CharField(blank=True, default='', max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='pcbpart',
            name='Designation',
            field=models.CharField(blank=True, default='', max_length=200),
            preserve_default=False,
        ),
    ]
