from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bom', '0026_add_part_manufacturer'),
    ]

    operations = [
        migrations.AddField(
            model_name='pcbpart',
            name='Category',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='pcbpart',
            name='DatasheetLink',
            field=models.URLField(blank=True),
        ),
    ]
