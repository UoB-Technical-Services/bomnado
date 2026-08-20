from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bom', '0025_rename_pcbpart_designation_to_value'),
    ]

    operations = [
        migrations.AddField(
            model_name='part',
            name='manufacturer',
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
