from collections import Counter
from functools import reduce
from operator import or_

from django.apps import apps
from django.db.models import Q


class ReferenceSearch:
    """ A cursor class that contains a list of objects from multiple models
    that contain a Part.refrence or SubAssembly.reference in one of their
    nominated fields.

    This is used to rename references in text fields to foreign keys.
    For example: "PART-A" can be renamed to "PART-B" in the DB and all text fields.
    """

    def __init__(self, reference):
        self.search = f'`{reference}`'

        # Get all models that have reference fields to be replaced.
        models = apps.get_app_config('bom').get_models()
        models = [m for m in models if hasattr(m, 'REFERENCE_REPLACE_FIELDS')]
        self.items = {}

        # For each model, find all instances that contain the search term
        # in any of the reference fields.
        for model in models:
            # Create a query that uses `<field>__contains` looking for our search term.
            query = reduce(or_, [
                Q(**{f'{field}__contains': self.search}) for field in model.REFERENCE_REPLACE_FIELDS
            ], Q())

            # Store it.
            self.items[model] = model.objects.filter(query)

    def exclude(self, instance):
        """ Exclude a specific model instance from being counted / operated on. """
        self.items[instance.__class__] = self.items[instance.__class__].exclude(pk=instance.pk)

    def replace(self, new_reference):
        """ Using the results find all occurrences of the reference it in special fields:
            e.g. instructions, notes, specifications and replace them with the `new_reference`
        """
        wrapped_new_reference = f'`{new_reference}`'

        # For each model and items queried.
        for model, queryset in self.items.items():

            # For each instance of that model resulting from the query.
            for instance in queryset:

                # For each field in that model that needs to be updated.
                for fieldname in model.REFERENCE_REPLACE_FIELDS:
                    # Get the text field.
                    instance_field = getattr(instance, fieldname)

                    # Find and replace it.
                    setattr(instance, fieldname, instance_field.replace(self.search, wrapped_new_reference))

                # Save changes to the model instance. The reason shows in the activity strip.
                instance._change_reason = f'reference {self.search} renamed to {wrapped_new_reference}'
                instance.save()

    def count(self):
        """ Return a dictionary that contains how many times each individual model field references the item. """

        counter = Counter()
        for model, queryset in self.items.items():
            for instance in queryset:
                for fieldname in model.REFERENCE_REPLACE_FIELDS:
                    class_field = model._meta.get_field(fieldname)
                    instance_field = getattr(instance, fieldname)

                    # Increment the "<app.model.field>@INSTANCESTRING" counter.
                    counter[f'{class_field}@{instance}'] += instance_field.count(self.search)

        return counter
