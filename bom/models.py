import math
import os
import re
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import FileSystemStorage
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse
from django.utils.timezone import now
from django.templatetags.static import static

""" Offical Semantic Version Regex. https://regex101.com/r/vkijKf/1/ """
SEMVER = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
                    r'(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)'
                    r'(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?'
                    r'(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$')


def validate_semver(value):
    """ Validate that the given value conforms to semantic versioning.
    """
    if not SEMVER.match(value):
        raise ValidationError('not a valid sematic semantic string')


def validate_reference():
    return RegexValidator('^[0-9A-Z-]*$', 'Only uppercase letters, numbers, and dashes are allowed.')


class OverwriteStorage(FileSystemStorage):
    def get_available_name(self, name, *args, **kwargs):
        # TODO: convert image to PNG
        if self.exists(name):
            os.remove(os.path.join(settings.MEDIA_ROOT, name))
        return name


def upload_part_picture_path(instance, filename):
    """ Generate a path based on the part `reference`.
    """
    name, ext = os.path.splitext(filename)
    return os.path.join('parts', f'{instance.id}_{instance.reference}{ext}')


def upload_assembly_picture_path(instance, filename):
    """ Generate a path based on the assembly `reference`.
    """
    name, ext = os.path.splitext(filename)
    return os.path.join('assemblies', f'{instance.id}_{instance.reference}{ext}')


def get_default_reference():
    return str(uuid.uuid4())[:8].upper()


class Team(models.Model):
    """ Represents a team of users and can own many projects. Has an owner (creator)."""
    name = models.TextField(unique=True, max_length=150)
    users = models.ManyToManyField(to=User)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_teams', null=True, blank=True)

    def projects(self):
        return self.assemblies.filter(is_toplevel=True)

    def can_access(self, user):
        return not user.is_anonymous and self in user.team_set.all()

    def is_owner(self, user):
        return self.owner == user

    def __str__(self):
        return self.name

    def __repr__(self):
        return str(self)


# Create your models here.
class Part(models.Model):
    """ A `Part` represents something that can be purchased.
    """

    """ Fields subject to find-and-replace when `reference` is updated on selected models. """
    REFERENCE_REPLACE_FIELDS = ['spec', 'qc_steps']

    NATURE_STANDARD = 'S'
    NATURE_BESPOKE = 'B'
    NATURE = [
        (NATURE_STANDARD, 'Standard'),
        (NATURE_BESPOKE, 'Bespoke'),
    ]

    """ Unique part reference. For example: `M8-200MM-BTN-BZP`. """
    reference = models.CharField(
        unique=True,
        max_length=100,
        validators=[validate_reference()],
        default=get_default_reference,
        blank=False
    )

    """ Human readable part name. """
    name = models.CharField(max_length=200)

    """ Estimated weight of the part (kilograms). """
    kgs = models.FloatField(default=0.00)

    """ Unpacked dimensions of the part in mm. Follows the format: "L x W x H". """
    dimensions = models.CharField(blank=True, max_length=100)

    """ The prominent part colours or material appearance. For example: "Matte Black" """
    colour = models.CharField(blank=True, max_length=100)

    """ Is the part an off-the-shelf standard (S) or made-to-order bespoke (B). """
    nature = models.CharField(max_length=1, choices=NATURE, default=NATURE_STANDARD)

    """ Part specification text. Markdown. """
    spec = models.TextField(blank=True)

    """ Bullet pointed quality control instructions / steps. Accepts markdown. """
    qc_steps = models.TextField(blank=True)

    """ An icon that represents this part. """
    picture = models.ImageField(upload_to=upload_part_picture_path, blank=True, storage=OverwriteStorage())

    """ A sale code for if this part is resold. Eg. PROD-123. If blank the part is not resold. """
    sale_code = models.CharField(max_length=100, blank=True)

    """ Commodity code for customs declarations """
    hs_code = models.CharField(max_length=10, blank=True)

    """ If set, the date that this part is due to be end-of-lifed. """
    end_of_life = models.DateTimeField(blank=True, null=True)

    """ If set, the date this part was deprecated. """
    deprecated = models.DateTimeField(blank=True, null=True)

    """ Review notes - causal notes on how to improve this document. Markdown. """
    review_notes = models.TextField(blank=True)

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    """ The owning team"""
    team = models.ForeignKey(
        to=Team,
        on_delete=models.CASCADE,
        verbose_name='Team',
        related_name='parts',
        db_index=True
    )

    @property
    def is_orphan(self):
        """ Is this part an orphan. """
        return SubAssemblyLineItem.objects.filter(child_part=self.id).count() == 0

    def replace_references(self, old_term, new_term):
        """ Update a reference string with a new term.
        Used to update the text fields when renaming models (e.g. "PART-A" -> "PART-B")
        """
        self.spec = self.spec.replace(old_term, new_term)

    def count_usage(self):
        """
        Count the number of times this part is used (i.e referenced by other sub-assemblies)
        in the entire database, not just a particular tree.
        """
        # TODO: Ideally do this based on a project or from a given sub-assembly.
        lines = SubAssemblyLineItem.objects.filter(child_part=self.id)
        qty = 0
        for line in lines:
            if line.subassembly:
                qty += line.subassembly.count_usage() * line.quantity
        return qty

    def find_using_assemblies(self):
        """ Reference to all the assemblies that use this part.
        NOTE: The returned assemblies may be orphaned.
        """
        lines = SubAssemblyLineItem.objects.filter(child_part=self.id)
        return [line.subassembly for line in lines]

    def cheapest(self):
        # TODO - take into account shipping and quantity
        return PartSource.objects.filter(part=self.id).order_by('rrp').first()

    def __str__(self):
        return self.reference

    def can_access(self, user):
        """ Can the given user access this part."""
        return not user.is_anonymous and self.team in user.team_set.all()

    @property
    def picture_url(self):
        """ Return the URL for the picture, or a placeholder if none exists. """
        if self.picture:
            return self.picture.url
        return static('assets/placeholders/part_placeholder.png')

    def clean(self):
        super().clean()
        if not self.reference:
            raise ValidationError({'reference': 'Part reference is required.'})

    @classmethod
    def all_available_to_user(cls, user):
        """ Get all the parts that are available to the given user."""
        teams = user.team_set.values_list('id')
        return Part.objects.filter(team__in=teams)


class PartSource(models.Model):
    """
    A `PartSource` describes a supplier (and purchasing details) for a part.
    """

    """ Fields subject to find-and-replace when `reference` is updated on selected models. """
    REFERENCE_REPLACE_FIELDS = ['order_notes']

    """ The `Part` that this source details. """
    part = models.ForeignKey(to=Part, on_delete=models.CASCADE, verbose_name='Part', related_name='sources')

    """ Unique suppliers unique part reference or part model number. """
    partcode = models.CharField(max_length=100, default='')

    """ A URL that links directly to the part. """
    url = models.URLField(blank=True)

    """ The recommended retail price (not discounted price) for a single unit of the part. Prices are ex VAT. """
    rrp = models.FloatField(default=0.0)

    """ The cost of shipping the `min-order` number of this part. Prices are ex VAT. """
    shipping = models.FloatField(default=0.0)

    """ The smallest number of units per single order. Eg. A box of 200 bolts. """
    minimum_order = models.IntegerField(default=1)

    """ The number of business days taken to arrive. """
    lead_time = models.IntegerField(default=1)

    """ Notes for the purchasing manager and important points for the supplier. Markdown. """
    order_notes = models.TextField(blank=True)

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    @property
    def source(self):
        """
        We don't currently have a unique source, so scrape out the start of the URL to
        allow source based grouping in reports to allow purchaser to purchase multiple items in the same order.
        """
        try:
            domain = urlparse(self.url).netloc
            return domain.replace('www.', '')
        except (ValueError, AttributeError):
            return self.url

    def cost_quantity_for(self, quantity, include_shipping):
        """ Calculate the cost for a given quantity of this unit based on the RRP and minimum order.
        NOTE: Minimum order costs are assumed to be discrete (e.g. bags of X) and cannot be split up.
        :param quantity: The number of units to order.
        :param include_shipping: Should shipping cost be included in the calculation.
        :return (cost, quantity): The total cost paid, and the total amount of units recieved.
        """
        order_qty = math.ceil(quantity / self.minimum_order)
        order_cost = (self.minimum_order * order_qty) * self.rrp
        ship = self.shipping if include_shipping else 0
        return (order_cost + ship, self.minimum_order * order_qty)

    @staticmethod
    def rank(sources, quantity, include_shipping):
        """ Rank the part sources according to their cost-per-unit. Cheapest first.
        :param sources: The `PartSource` instances to rank.
        :param quantity: The amount to order.
        :param include_shipping: Should shipping cost be added to the calculation.
        """

        def _evaluate_buy_cost(src):
            cost, recieved = src.cost_quantity_for(quantity, include_shipping)
            return cost / recieved

        return sorted(sources, key=_evaluate_buy_cost, reverse=True)


class SubAssembly(models.Model):
    """
    A `SubAssembly` is a collection of sub-parts and further sub-assemblies that
    are assembled separately but designed to be incorporated with other units into
    a larger manufactured product.
    """

    """ Fields subject to find-and-replace when `reference` is updated on selected models. """
    REFERENCE_REPLACE_FIELDS = ['instructions', 'qc_steps', 'spec']

    """ Unique sub-assembly reference. For example: `CHASSIS`. """
    reference = models.CharField(
        unique=True,
        max_length=100,
        validators=[validate_reference()],
        default=get_default_reference,
        blank=False
    )

    """ A human readable name for this sub-assmebly. """
    name = models.CharField(max_length=200)

    """ The semnatic version number of this part. """
    revision = models.CharField(max_length=20, validators=[validate_semver])

    """ An icon that represents this assembly. """
    picture = models.ImageField(upload_to=upload_assembly_picture_path, blank=True, storage=OverwriteStorage())

    is_toplevel = models.BooleanField(default=False)

    """ A sale code for if this assembly is resold. Eg. PROD-123. If blank the assembly is not resold. """
    sale_code = models.CharField(max_length=100, blank=True)

    """ Commodity code for customs declarations """
    hs_code = models.CharField(max_length=10, blank=True)

    """ A 20-char string that describes the production phase of this assembly.
    (e.g. "Phase 01" or "Prebuild" or "SiteBuild" etc) """
    production_phase = models.CharField(max_length=20, blank=True)

    """ Part specification text. Markdown. """
    spec = models.TextField(blank=True)

    """ High level assembly instructions. Accepts markdown. """
    instructions = models.TextField(blank=True)

    """ Bullet pointed quality control instructions / steps. Accepts markdown. """
    qc_steps = models.TextField(blank=True)

    """ Review notes - notes on how to improve this document. Markdown. """
    review_notes = models.TextField(blank=True)

    """ If set, the date this assembly was deprecated. """
    deprecated = models.DateTimeField(blank=True, null=True)

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    """ The owning team"""
    team = models.ForeignKey(
        to=Team, on_delete=models.CASCADE, verbose_name='Team', related_name='assemblies', db_index=True)

    """ Is this part shared"""
    shared = models.BooleanField(default=False)

    """ The top level assembly i.e. the project that this subassembly is associated with"""
    project = models.ForeignKey(
        'self', on_delete=models.SET_DEFAULT, default=None, verbose_name='Project', related_name='children', null=True)

    @property
    def is_orphan(self):
        """ Is this assembly an orphan. Top level assemblies are not considered orphans. """
        if self.is_toplevel:
            return False
        return SubAssemblyLineItem.objects.filter(child_subassembly=self.id).count() == 0

    def find_using_assemblies(self):
        """ Reference to all the assemblies that use this assembly. """
        lines = SubAssemblyLineItem.objects.filter(child_subassembly=self.id)
        return [line.subassembly for line in lines]

    def sellable_line_items(self):
        """ Collect a list of line items that have sales codes. """
        return [line for line in self.line_items.all() if line.item.sale_code]

    def collect_and_count_parts(self, parts, assemblies):
        """
        Traverse the assembly tree and count the uses of each part and assembly.

        Usage:
            root = SubAssembly.objects.get(is_toplevel=True)
            parts = Counter()
            assemblies = Counter()
            root.collect_and_count_parts(parts, assemblies)
        """
        # For all line items.
        for line in self.line_items.all():

            # Count each part.
            if line.child_part:
                parts[line.child_part] += line.quantity

            # Count each sub-assembly and sub-parts the required number of times
            if line.child_subassembly:
                for count in range(line.quantity):
                    assemblies[line.child_subassembly] += 1
                    line.child_subassembly.collect_and_count_parts(parts, assemblies)

    @property
    def kgs(self):
        """ Calculate the weight of all the parts and sub-assemblies. """
        weight = 0
        lines = self.line_items.all()
        for line in lines:
            weight += line.item.kgs * line.quantity
        return weight

    @property
    def end_of_life(self):
        """ Return the soonest end of life date or `None`. """
        lines = self.line_items.all()
        dates = [line.item.end_of_life for line in lines]
        dates = [date for date in dates if date]
        return min(dates) if dates else None

    @property
    def colour(self):
        """ Return a comma-separated string of all the colours used in this assembly. """
        lines = self.line_items.all()
        colours = [line.item.colour for line in lines]
        colours = [colour.lower() for colour in colours if colour]
        colours = set(colours)
        return ', '.join(sorted(colours))

    def count_usage(self):
        """ Count the number of times this subassembly is used in the database. """
        # TODO: Ideally do this based on a project or from a given sub-assembly.
        lines = SubAssemblyLineItem.objects.filter(child_subassembly=self.id)
        qty = 0
        if lines.count() > 0:
            for line in lines:
                if line.subassembly:
                    qty += line.subassembly.count_usage() * line.quantity
        else:
            # Root/Orphan Node
            qty = 1
        return qty

    def __str__(self):
        return self.name

    def can_access(self, user):
        return not user.is_anonymous and self.team in user.team_set.all()

    @property
    def picture_url(self):
        """ Return the URL for the picture, or a placeholder if none exists. """
        if self.picture:
            return self.picture.url
        if self.is_toplevel:
            return static('assets/placeholders/root_assembly_placeholder.png')
        return static('assets/placeholders/assembly_placeholder.png')

    def get_all_descendants(self, visited=None):
        """
        Get all descendant assemblies (children, grandchildren, etc.) to detect circular references

        Args:
            visited: Set of assemblies already visited (to prevent infinite recursion)

        Returns:
            Set of assembly IDs that are descendants of this assembly
        """
        if visited is None:
            visited = set()

        # If we've already visited this node, return the current set to avoid recursion
        if self.id in visited:
            return visited

        # Mark this node as visited
        visited.add(self.id)

        # Get all child sub-assemblies
        for line in self.line_items.filter(child_subassembly__isnull=False):
            if line.child_subassembly and line.child_subassembly.id != self.id:
                # Add this child's descendants recursively
                line.child_subassembly.get_all_descendants(visited)

        return visited

    def would_create_cycle(self, potential_parent_id):
        """
        Check if adding this assembly as a child of the assembly with potential_parent_id
        would create a cycle in the hierarchy

        Args:
            potential_parent_id: ID of the assembly that would be the parent

        Returns:
            bool: True if a cycle would be created, False otherwise
        """
        # If the potential parent is the same as this assembly, it's a cycle
        if self.id == potential_parent_id:
            return True

        # If the potential parent is already a descendant of this assembly, it would create a cycle
        descendants = self.get_all_descendants()
        return potential_parent_id in descendants

    def clean(self):
        super().clean()
        if not self.reference:
            raise ValidationError({'reference': 'Project name is required.'})


class SubAssemblyLineItem(models.Model):
    """
    A `SubAssemblyLineItem` a line item within a `SubAssembly` that attaches
    a part or another sub-assembly, quantity, and notes.
    """

    """ Fields subject to find-and-replace when `reference` is updated on selected models. """
    REFERENCE_REPLACE_FIELDS = ['notes']

    # TODO: Remove the null here
    """ The parent `SubAssembly` that contains this line item. """
    subassembly = models.ForeignKey(to=SubAssembly, on_delete=models.CASCADE, related_name='line_items', null=True,
                                    db_index=True)

    """ The `Part` added. """
    child_part = models.ForeignKey(to=Part, on_delete=models.CASCADE, blank=True, null=True, db_index=True)

    """ The `SubAssembly` added. """
    child_subassembly = models.ForeignKey(
        to=SubAssembly,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name='child_subassembly',
        db_index=True
    )

    """ The number of `Part` or `SubAssembly` added. """
    quantity = models.IntegerField(default=1)

    """ Notes on the inclusion of this line item. """
    notes = models.TextField(blank=True)

    def clean(self):
        """Validate that adding this line item won't create a circular reference"""
        super().clean()

        # Check for circular reference only if we're adding a subassembly to another subassembly
        if self.child_subassembly and self.subassembly:
            if self.child_subassembly.would_create_cycle(self.subassembly.id):
                # Create a field-specific error message to match Django's form validation pattern
                # This will display below the field like other validation errors
                raise ValidationError({
                    'child_subassembly': f"Cannot add '{self.child_subassembly.reference}' as it would create a circular reference with '{self.subassembly.reference}'."
                })

    def replace_references(self, old_term, new_term):
        """ Update a reference string with a new term.
        Used to update the text fields when renaming models (e.g. "PART-A" -> "PART-B")
        """
        self.notes = self.notes.replace(old_term, new_term)

    @property
    def item(self):
        if self.child_part:
            return self.child_part
        elif self.child_subassembly:
            return self.child_subassembly
        else:
            return None

    def __str__(self):
        return f'{self.quantity} * {self.item if self.item is not None else "No Item Selected"}'

    def save(self, *args, **kwargs):
        """Override save to ensure validation is called"""
        self.full_clean()  # This calls field validation, then clean()
        super().save(*args, **kwargs)
def upload_attachment_path(instance, filename):
    """ Generate a path on disk for where an `Attachement` file is stored.

    This follows the scheme: `attachments/app_model/primary_key/filename.extension`
    """
    # Get information about the model instance the attachment is associated with (e.g. Part).
    app = instance.content_object._meta.app_label
    model = instance.content_object._meta.object_name.lower()
    pk = instance.content_object.pk

    # NOTE: `filename` is the name of the file uploaded, and not the name of the file as it
    # may later appear on disk if a file with the same name already exists.
    return os.path.join('attachments', f'{app}_{model}', f'{pk}', f'{filename}')


class AttachmentManager(models.Manager):
    """ Extended model manager for `Attachment` class.

    This class is adapted from the one used by `https://pypi.org/project/django-attachments/`.

    Syntax:
        Attachment.objects.attachments_for_object(subassembly)
    """

    def attachments_for_object(self, obj):
        """ Get all attachments for a given model instance. """
        object_type = ContentType.objects.get_for_model(obj)
        return self.filter(content_type__pk=object_type.id, object_id=obj.pk).order_by('pk')


class Attachment(models.Model):
    """ An `Attachment` represents a file that can be stored on the server and associated
    with an instance of a different model (e.g. `Part` or `SubAssembly`).


    This class is adapted from the one used by `https://pypi.org/project/django-attachments/`.
    """

    """ Override default model manager. """
    objects = AttachmentManager()

    """ The Django `ContentType` associated with this `Attachment`. For example: `bom | part` """
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)

    """ Reference to the model instance this is attached to. """
    content_object = GenericForeignKey('content_type', 'object_id')

    """ Reference to the primary key of the model instance this is attached to. """
    object_id = models.CharField(db_index=True, max_length=64)

    """ The file that has been attached. """
    attachment_file = models.FileField(upload_to=upload_attachment_path)

    """ When was this attachment first attached. """
    created = models.DateTimeField(auto_now_add=True, db_index=True)

    """ When was this attachment last updated. """
    updated = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-created']  # Set the default ordering when getting a list of attachments.

    @property
    def delete_link(self):
        """ Get a link that when visited will attempt to delete this attachment. """
        return reverse('bom:attachment_delete', kwargs={'attachment_pk': self.pk})

    @property
    def filename(self):
        """ Get the filename and extension but excluding the path on disk. """
        return os.path.split(self.attachment_file.name)[1]


class Deal(models.Model):
    """ A `Deal` model encapsulates buying multiple different parts as a single deal """

    """ The name of the deal """
    name = models.TextField()

    """ The `Parts` attached to this deal """
    parts = models.ManyToManyField(to=Part, through='DealLineItem')

    """ The price paid for the deal. Prices are ex VAT. """
    rrp = models.FloatField(default=0.0)

    """ The cost of shipping all the parts included in the deal. Prices are ex VAT. """
    shipping = models.FloatField(default=0.0)

    """ The number of business days taken to arrive. """
    lead_time = models.IntegerField(default=1)

    """ Notes for the purchasing manager and important points for the supplier. Markdown. """
    order_notes = models.TextField(blank=True)

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    """ A URL that links directly to the deal supplier. """
    url = models.URLField(blank=True)

    """ The owning team. """
    team = models.ForeignKey(
        to=Team, on_delete=models.CASCADE, verbose_name='Team', related_name='deals', db_index=True)

    """ The top level assembly i.e. the project that this subassembly is associated with"""
    project = models.ForeignKey(
        to=SubAssembly, on_delete=models.SET_DEFAULT, default=None, verbose_name='Project', related_name='deals',
        null=True)

    def __str__(self):
        return self.name

    def size(self):
        """ Returns the total number of parts in this deal """
        return sum(self.deallineitem_set.values_list('quantity', flat=True)) if self.deallineitem_set else 0

    @classmethod
    def all_available_to_user(cls, user):
        teams = user.team_set.values_list('id')
        return Deal.objects.filter(team__in=teams)

    def coalesce(self, part_counter):
        """ Given the PartCounter object used in the export functions, this works out how many times a deal
            can be applied to a collection of parts.
            It returns the number of times the deal can be applied, and a PartCounter object showing left over parts
            which are not covered by the deal.
        """
        intersections = {}
        for lineitem in self.deallineitem_set.all():
            if lineitem.part in part_counter:
                intersections[lineitem.part] = part_counter[lineitem.part] // lineitem.quantity
            else:
                # Deal cannot be applied, bail
                return 0, part_counter

        min_deals = min(intersections.values())
        for lineitem in self.deallineitem_set.all():
            part_counter[lineitem.part] -= (lineitem.quantity * min_deals)

        return min_deals, part_counter


class DealLineItem(models.Model):
    """
    The `DealLineItem` encapsulates the relationship of a Part and a Deal
    It shows which Part is in the deal, the quantity, and any specific notes about that part
    in the deal context.
    """

    """ Part added to Deal """
    part = models.ForeignKey(to=Part, on_delete=models.CASCADE)

    """ Deal """
    deal = models.ForeignKey(to=Deal, on_delete=models.CASCADE)

    """ The number of `Parts` added. """
    quantity = models.IntegerField(default=1)

    """ Notes on the inclusion of this line item. """
    notes = models.TextField(blank=True)


class PCBPart(Part):
    """
    PCB-specific extension of `Part` using Django's multi-table inheritance.

    This model shares the same primary key as `Part` (via the implicit
    one-to-one parent link created by multi-table inheritance) and adds
    an extra field for storing the LCSC part number.
    """

    LCSCPartNo = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'PCB Part'
        verbose_name_plural = 'PCB Parts'


class PCBSubAssembly(SubAssembly):
    """
    PCB-specific extension of `SubAssembly` using Django's multi-table inheritance.

    Shares the same primary key as `SubAssembly` and allows PCB-specific
    metadata to be added in future.
    """

    class Meta:
        verbose_name = 'PCB SubAssembly'
        verbose_name_plural = 'PCB SubAssemblies'
