from django.contrib.auth.models import User
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from bom.models import Part, SubAssembly
from bom.utils.reference_tools import ReferenceSearch
from bom.utils.signals import disable_for_loaddata


@receiver(pre_save, sender=Part)
@disable_for_loaddata
def rename_part_references(sender, instance=None, created=False, **kwargs):
    # Check if this is a modification of an existing part (i.e. saved in the DB)
    if not created and instance.pk:
        # Get unmodified object from the database
        old_object = Part.objects.get(pk=instance.pk)

        # Bail if reference not changed
        if old_object.reference == instance.reference:
            return

        # Update the current Part if necessary, this is in pre-save so will piggy back onto the current save
        oldref = f'`{old_object.reference}`'
        newref = f'`{instance.reference}`'
        instance.spec = instance.spec.replace(oldref, newref)

        # Find all occurances of the old part.reference string and replace it with the new one.
        references = ReferenceSearch(old_object.reference)
        references.exclude(instance)
        references.replace(instance.reference)


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

        # Update the current Part if necessary, this is in presave so will piggy back onto the current save
        oldref = f'`{old_object.reference}`'
        newref = f'`{instance.reference}`'
        instance.instructions = instance.instructions.replace(oldref, newref)
        instance.qc_steps = instance.qc_steps.replace(oldref, newref)
        instance.spec = instance.spec.replace(oldref, newref)

        # Find all occurances of the old subassembly.reference string and replace it with the new one.
        references = ReferenceSearch(old_object.reference)
        references.exclude(instance)
        references.replace(instance.reference)


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
