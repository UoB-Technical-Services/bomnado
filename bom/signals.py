from django.contrib.auth.models import User
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from bom.models import Part, SubAssembly, NamedPiece
from bom.utils.reference_tools import ReferenceSearch
from bom.utils.signals import disable_for_loaddata


def _rename_reference(instance, old_reference, new_reference):
    """ Rewrite every `` `old_reference` `` in the database as `` `new_reference` ``.

    `instance` is the model mid-save whose rename caused this: its own reference
    fields are edited in place (so the change piggy-backs onto the current save)
    and it is excluded from the database sweep.
    """
    oldref = f'`{old_reference}`'
    newref = f'`{new_reference}`'
    for fieldname in instance.REFERENCE_REPLACE_FIELDS:
        setattr(instance, fieldname, getattr(instance, fieldname).replace(oldref, newref))

    references = ReferenceSearch(old_reference)
    references.exclude(instance)
    references.replace(new_reference)


@receiver(pre_save, sender=Part)
@disable_for_loaddata
def rename_part_references(sender, instance=None, created=False, **kwargs):
    # Check if this is a modification of an existing part (i.e. saved in the DB)
    if not created and instance.pk:
        # Get unmodified object from the database
        old_object = Part.objects.filter(pk=instance.pk).first()

        # Bail if reference not changed
        if old_object is None or old_object.reference == instance.reference:
            return

        # Find all occurances of the old part.reference string and replace it with the new one.
        _rename_reference(instance, old_object.reference, instance.reference)

        # A piece reference is `PARENT>SUFFIX`, which a search for `PARENT` does not
        # match (the closing backtick is part of the search), so rename each one too.
        for suffix in instance.named_pieces.values_list('suffix', flat=True):
            _rename_reference(instance, f'{old_object.reference}{NamedPiece.SEPARATOR}{suffix}',
                              f'{instance.reference}{NamedPiece.SEPARATOR}{suffix}')


@receiver(pre_save, sender=NamedPiece)
@disable_for_loaddata
def rename_piece_references(sender, instance=None, **kwargs):
    """ Renaming a piece's suffix (or moving it to another part) rewrites its `PARENT>SUFFIX` references. """
    if not instance.pk:
        return
    old_object = NamedPiece.objects.filter(pk=instance.pk).select_related('part').first()
    if old_object is None:
        return

    # Read the parent's reference from the database: if the parent is itself mid-rename,
    # `rename_part_references` owns rewriting its pieces.
    parent_reference = Part.objects.filter(pk=instance.part_id).values_list('reference', flat=True).first()
    new_reference = f'{parent_reference}{NamedPiece.SEPARATOR}{instance.suffix}'
    if old_object.reference == new_reference:
        return

    _rename_reference(instance, old_object.reference, new_reference)


@receiver(pre_save, sender=SubAssembly)
@disable_for_loaddata
def rename_subassembly_references(sender, instance=None, created=False, **kwargs):
    # Check if this is a modification of an existing subassembly (i.e. saved in the DB)
    if not created and instance.pk:
        # Get unmodified object from the database
        old_object = SubAssembly.objects.get(pk=instance.pk)

        # Bail if reference not changed
        if old_object.reference == instance.reference:
            return

        # Find all occurances of the old subassembly.reference string and replace it with the new one.
        _rename_reference(instance, old_object.reference, instance.reference)


@receiver(post_save, sender=SubAssembly)
@disable_for_loaddata
def set_toplevel_project(sender, instance=None, created=False, **kwargs):
    """ When an `Assembly` is created that has the `is_toplevel` flag set and no `project` reference set
    then set the `project` instance to be itself; indicating that this assembly is regarded as an entrypoint
    within the team.
    """
    if created and instance.pk:
        # Signal needed for top level assembly to set themselves as project once they have a pk
        if instance.project is None and instance.is_toplevel:
            instance.project = instance
            instance.save()


@receiver(pre_save, sender=User)
@disable_for_loaddata
def emails_as_user(sender, instance=None, created=False, **kwargs):
    """ Hook user account creation to ensure the email field is the username.
    In Bomnado, we make the username also the email address on the login form.
    """
    if created:
        instance.email = instance.username
