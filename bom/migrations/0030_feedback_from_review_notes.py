# Carry the free-text "Comments and Feedback" box over as Feedback entries before the column goes.

from django.db import migrations


def forwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Feedback = apps.get_model('bom', 'Feedback')
    for model_name in ('part', 'subassembly'):
        Model = apps.get_model('bom', model_name)
        content_type, _ = ContentType.objects.get_or_create(app_label='bom', model=model_name)
        for obj in Model.objects.exclude(review_notes='').iterator():
            Feedback.objects.create(content_type=content_type, object_id=str(obj.pk),
                                    text=obj.review_notes, created=obj.updated)
            Model.objects.filter(pk=obj.pk).update(has_open_feedback=True)


def backwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Feedback = apps.get_model('bom', 'Feedback')
    for model_name in ('part', 'subassembly'):
        Model = apps.get_model('bom', model_name)
        content_type = ContentType.objects.filter(app_label='bom', model=model_name).first()
        if content_type is None:
            continue
        for item in Feedback.objects.filter(content_type=content_type, resolved__isnull=True).order_by('created'):
            Model.objects.filter(pk=item.object_id).update(review_notes=item.text)


class Migration(migrations.Migration):

    dependencies = [
        ('bom', '0029_history_and_feedback'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
