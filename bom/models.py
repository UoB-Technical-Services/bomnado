import datetime
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
from simple_history.models import HistoricalRecords

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
    """ References (and named-piece suffixes): uppercase letters, digits, dashes and dots - a dot
    only between characters (`XB4-BA31.1`, `V1.2-BRACKET`), never `>` which joins a part and a piece. """
    return RegexValidator(r'^(?!\.)(?!.*\.$)[0-9A-Z.-]*$',
                          'Only uppercase letters, numbers, dashes and dots are allowed (a dot only in the middle).')


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


def upload_piece_picture_path(instance, filename):
    """ Generate a path based on the parent part's id and the piece `suffix`.
    (The piece's own id is not yet known when a picture is saved with a new row.)
    """
    name, ext = os.path.splitext(filename)
    return os.path.join('named_pieces', f'{instance.part_id}_{instance.suffix}{ext}')


def get_default_reference():
    return str(uuid.uuid4())[:8].upper()


class Team(models.Model):
    """ Represents a team of users and can own many projects. Has an owner (creator)."""
    name = models.TextField(unique=True, max_length=150)
    users = models.ManyToManyField(to=User)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_teams', null=True, blank=True)

    """ How this team names part references, for the AI to follow (see `bom.ai.naming`). Blank = the default guide. """
    naming_guide = models.TextField(blank=True)

    """ Where an HS / commodity code links out to, with {code} standing for the digits. Blank = the UK Trade Tariff. """
    hs_lookup = models.CharField(max_length=300, blank=True)

    HS_LOOKUP_DEFAULT = 'https://www.trade-tariff.service.gov.uk/commodities/{code}'

    @property
    def hs_lookup_url(self):
        return self.hs_lookup or self.HS_LOOKUP_DEFAULT

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

    """ Manufacturer name for this part. """
    manufacturer = models.CharField(max_length=200, blank=True)

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

    """ Is there unresolved `Feedback` on this part. Kept in step by `Feedback`; not edited directly. """
    has_open_feedback = models.BooleanField(default=False, editable=False)

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

    """ Every save is kept (see `bom.utils.activity`). `inherit` gives `PCBPart` its own history too. """
    history = HistoricalRecords(inherit=True, excluded_fields=['updated', 'has_open_feedback'])

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

    """ The supplier's name, for sources that have no link (a quote, a phone order). """
    supplier = models.CharField(max_length=100, blank=True)

    """ Unique suppliers unique part reference or part model number. """
    partcode = models.CharField(max_length=100, default='', blank=True)

    """ A URL that links directly to the part. """
    url = models.URLField(blank=True)

    """ The recommended retail price (not discounted price) for a single unit of the part. Prices are ex VAT. """
    rrp = models.FloatField(default=0.0)

    """ The cost of shipping the `min-order` number of this part. Prices are ex VAT. """
    shipping = models.FloatField(default=0.0)

    """ The smallest number of units per single order. Eg. A box of 200 bolts. """
    minimum_order = models.IntegerField(default=1)

    """ The number of business days taken to arrive. """
    lead_time = models.IntegerField(default=7)

    """ Notes for the purchasing manager and important points for the supplier. Markdown. """
    order_notes = models.TextField(blank=True)

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(excluded_fields=['updated'])

    @property
    def source(self):
        """
        We don't currently have a unique source, so scrape out the start of the URL to
        allow source based grouping in reports to allow purchaser to purchase multiple items in the same order.
        """
        try:
            domain = urlparse(self.url).netloc.replace('www.', '')
        except (ValueError, AttributeError):
            domain = ''
        return domain or self.supplier or self.url

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

        return sorted(sources, key=_evaluate_buy_cost)


class NamedPiece(models.Model):
    """
    A `NamedPiece` is a piece of a `Part` with a name - for example the `TOP` of `3D-PRINTED-CHASSIS` -
    that instructions need to point at, but that is never bought or counted on its own.

    It is *not* a BOM item: it has no quantity, sources or line items, and plays no part in
    costing, exports or the orphan tools. It exists so that a `PARENT>SUFFIX` reference in
    markdown resolves to something, renders as a link, and follows renames of either half.
    """

    """ Fields subject to find-and-replace when a `reference` is updated on selected models. """
    REFERENCE_REPLACE_FIELDS = ['note']

    """ Joins the parent reference and the suffix: `PARENT>SUFFIX`. Not a legal reference character. """
    SEPARATOR = '>'

    """ The `Part` this is a piece of. """
    part = models.ForeignKey(to=Part, on_delete=models.CASCADE, verbose_name='Part', related_name='named_pieces')

    """ The part of the reference after the dot. For example: `TOP`. """
    suffix = models.CharField(max_length=50, validators=[validate_reference()], blank=False)

    """ A one-line description / note. Accepts references. """
    note = models.CharField(max_length=200, blank=True)

    """ An icon that represents this piece of the part. Falls back to the part's own picture. """
    picture = models.ImageField(upload_to=upload_piece_picture_path, blank=True, storage=OverwriteStorage())

    """ When was this record first created. """
    created = models.DateTimeField(default=now)

    """ When was this record last updated. """
    updated = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(excluded_fields=['updated'])

    class Meta:
        unique_together = [('part', 'suffix')]
        ordering = ['suffix']

    @property
    def reference(self):
        """ The full reference: `PARENT>SUFFIX`. """
        return f'{self.part.reference}{self.SEPARATOR}{self.suffix}'

    @classmethod
    def split_reference(cls, reference):
        """ Split `PARENT>SUFFIX` into `('PARENT', 'SUFFIX')`, or `None` if it is not named-piece syntax. """
        if not reference or cls.SEPARATOR not in reference:
            return None
        parent, suffix = reference.split(cls.SEPARATOR, 1)
        if not parent or not suffix:
            return None
        return parent, suffix

    @classmethod
    def find_by_reference(cls, reference):
        """ Look up a named piece from its full `PARENT>SUFFIX` reference, or `None`. """
        halves = cls.split_reference(reference)
        if halves is None:
            return None
        return cls.objects.filter(part__reference=halves[0], suffix=halves[1]).select_related('part').first()

    def can_access(self, user):
        """ Can the given user access this named piece (i.e. its part). """
        return self.part.can_access(user)

    @property
    def picture_url(self):
        """ The piece's own picture, or its part's picture (or placeholder) if it has none. """
        if self.picture:
            return self.picture.url
        return self.part.picture_url

    def __str__(self):
        return self.reference


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

    """ Is there unresolved `Feedback` on this assembly. Kept in step by `Feedback`; not edited directly. """
    has_open_feedback = models.BooleanField(default=False, editable=False)

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

    """ Every save is kept (see `bom.utils.activity`). `inherit` gives `PCBSubAssembly` its own history too. """
    history = HistoricalRecords(inherit=True, excluded_fields=['updated', 'has_open_feedback'])

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

    def collect_and_count_parts(self, parts, assemblies, multiplier=1):
        """
        Traverse the assembly tree and count the uses of each part and assembly.

        Usage:
            root = SubAssembly.objects.get(is_toplevel=True)
            parts = Counter()
            assemblies = Counter()
            root.collect_and_count_parts(parts, assemblies)

        :param multiplier: How many of *this* assembly are being built. Quantities
            are multiplied down the tree rather than the tree being walked once per
            unit, so the cost is proportional to the number of line items, not the
            number of units.
        """
        for line in self.line_items.select_related('child_part', 'child_subassembly'):
            count = line.quantity * multiplier

            # Count each part.
            if line.child_part:
                parts[line.child_part] += count

            # Count each sub-assembly, then everything inside it that many times over.
            if line.child_subassembly:
                assemblies[line.child_subassembly] += count
                line.child_subassembly.collect_and_count_parts(parts, assemblies, count)

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

    history = HistoricalRecords()

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


class FeedbackManager(models.Manager):
    """ Syntax::

        Feedback.objects.for_object(part)   # all of it, newest first
        Feedback.objects.open_for(part)     # only what is still unresolved
    """

    @staticmethod
    def _base_model(obj):
        """ Feedback is filed under `Part` / `SubAssembly`, whichever subclass the instance is. """
        return Part if isinstance(obj, Part) else SubAssembly if isinstance(obj, SubAssembly) else type(obj)

    def for_object(self, obj):
        content_type = ContentType.objects.get_for_model(self._base_model(obj))
        return self.filter(content_type=content_type, object_id=str(obj.pk))

    def open_for(self, obj):
        return self.for_object(obj).filter(resolved__isnull=True)


class Feedback(models.Model):
    """ A comment left on a `Part` or `SubAssembly` for the team: something to look at, and why.

    It stays open - and the record shows the 👀 flag - until someone resolves it. Both
    halves are kept, so the activity strip can show what was asked and what was then done.
    """

    objects = FeedbackManager()

    """ The Django `ContentType` of the record this is about: `bom | part` or `bom | subassembly`. """
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)

    """ Primary key of that record (a string, as `Attachment` does it). """
    object_id = models.CharField(db_index=True, max_length=64)

    """ The record this feedback is about. """
    content_object = GenericForeignKey('content_type', 'object_id')

    """ What needs looking at. Markdown; accepts references. """
    text = models.TextField()

    """ Who wrote it. """
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedback_written')

    """ When it was written. """
    created = models.DateTimeField(default=now)

    """ When it was resolved, if it has been. """
    resolved = models.DateTimeField(null=True, blank=True)

    """ Who resolved it. """
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='feedback_resolved')

    class Meta:
        ordering = ['-created']
        verbose_name_plural = 'feedback'

    @property
    def is_open(self):
        return self.resolved is None

    def resolve(self, user):
        self.resolved = now()
        self.resolved_by = user
        self.save()

    def reopen(self):
        self.resolved = None
        self.resolved_by = None
        self.save()

    def can_access(self, user):
        obj = self.content_object
        return obj is not None and obj.can_access(user)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.sync_flag(self.content_object)

    def delete(self, *args, **kwargs):
        obj = self.content_object
        result = super().delete(*args, **kwargs)
        self.sync_flag(obj)
        return result

    @classmethod
    def sync_flag(cls, obj):
        """ Keep `has_open_feedback` on the record in step. A plain `update()`: the flag is not an
        edit of the record, so it is not recorded in its history. """
        if obj is None:
            return
        model = cls.objects._base_model(obj)
        model.objects.filter(pk=obj.pk).update(has_open_feedback=cls.objects.open_for(obj).exists())

    def __str__(self):
        return f'Feedback on {self.content_object}'


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
    lead_time = models.IntegerField(default=7)

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


class UserAISettings(models.Model):
    """ A user's own AI API key and preferences (see `bom.ai`). The key is encrypted at
    rest and never sent to the browser; only its last characters are ever shown. """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='ai_settings')

    """ The API key, encrypted with `bom.ai.crypto`. Use the `api_key` property. """
    encrypted_api_key = models.TextField(blank=True)

    """ The model calls are made with. """
    model = models.CharField(max_length=50, default='claude-opus-5')

    """ Monthly spending cap in USD; AI actions pause once it is reached. Blank = no cap. """
    monthly_budget = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, default=10)

    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'user AI settings'

    @property
    def api_key(self):
        from bom.ai.crypto import decrypt
        return decrypt(self.encrypted_api_key)

    @api_key.setter
    def api_key(self, value):
        from bom.ai.crypto import encrypt
        self.encrypted_api_key = encrypt((value or '').strip())

    @property
    def is_configured(self):
        return bool(self.api_key)

    @property
    def masked_key(self):
        """ `sk-ant-…wxyz`: enough to recognise, never enough to use. """
        key = self.api_key
        return f'{key[:7]}…{key[-4:]}' if len(key) > 12 else ('…' if key else '')

    def spend_this_month(self):
        """ USD spent on AI jobs since the start of the month, from recorded token usage. """
        start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        total = AIJob.objects.filter(user=self.user, created__gte=start).aggregate(models.Sum('cost'))['cost__sum']
        return total or 0

    def percent_used(self):
        """ Spend this month as a percentage of the budget (None without a budget). """
        if not self.monthly_budget:
            return None
        return min(999, int(100 * self.spend_this_month() / self.monthly_budget))

    def over_budget(self):
        return self.monthly_budget is not None and self.spend_this_month() >= self.monthly_budget

    def __str__(self):
        return f'AI settings for {self.user}'


class AIThread(models.Model):
    """ One conversation between a user and the AI (see `bom.ai.chat`). It belongs to the
    person, lives on the server (so it follows them across pages, tabs and devices), and
    remembers the record they were looking at when it began. Files they drop in are
    `Attachment`s on the thread. """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_threads')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='ai_threads', null=True, blank=True)

    """ Set from the first message; shown in the window's list of conversations. """
    title = models.CharField(max_length=200, blank=True)

    """ Where it started: `{"kind": "part", "id": 12}` or empty. """
    context = models.JSONField(default=dict, blank=True)

    created = models.DateTimeField(default=now)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated']

    def can_access(self, user):
        return self.user_id == user.id

    @property
    def latest_job(self):
        """ The most recent turn, for its status, progress and cost. """
        return AIJob.objects.filter(content_type=ContentType.objects.get_for_model(AIThread),
                                    object_id=str(self.pk)).first()

    def __str__(self):
        return self.title or f'Conversation {self.pk}'


class AIMessage(models.Model):
    """ One message of an `AIThread`, in Messages API form: a list of content blocks. A person's
    message holds text and file placeholders; the AI's holds text and tool calls; tool results
    are a `user` message too (that is how the API wants them), with `meta` saying what was called
    so the window can show it. """

    thread = models.ForeignKey(AIThread, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=[('user', 'user'), ('assistant', 'assistant')])
    content = models.JSONField(default=list, blank=True)

    """ For the window: tool calls made (`tools`), what they touched (`touched`); never sent to the API. """
    meta = models.JSONField(default=dict, blank=True)

    """ The turn that produced this message, for its progress, cost and error. """
    job = models.ForeignKey('AIJob', on_delete=models.SET_NULL, null=True, blank=True, related_name='messages_made')

    created = models.DateTimeField(default=now)

    class Meta:
        ordering = ['pk']

    @property
    def text(self):
        return ''.join(block.get('text', '') for block in self.content if block.get('type') == 'text')

    @property
    def is_tool_result(self):
        return any(block.get('type') == 'tool_result' for block in self.content)

    @property
    def files(self):
        return [block for block in self.content if block.get('type') == 'bomnado_file']

    def __str__(self):
        return f'{self.role}: {self.text[:40]}'


class AIJob(models.Model):
    """ One piece of work the AI did for a user - a turn of a conversation (`AIThread`) - with
    its progress while it runs, what it cost, and how it ended. """

    KIND_CHAT = 'chat'
    KINDS = [
        (KIND_CHAT, 'Chat'),
        # Earlier kinds, kept so old rows still read.
        ('scrape_url', 'Create a part from a link (old)'),
        ('scrape_file', 'Create a part from a datasheet (old)'),
        ('alternatives', 'Find alternative suppliers (old)'),
        ('ingest', 'Turn notes and files into parts (old)'),
    ]

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_EXECUTED = 'executed'  # old jobs whose plan was carried out
    STATUS_FAILED = 'failed'
    STATUSES = [(s, s) for s in (STATUS_QUEUED, STATUS_RUNNING, STATUS_DONE, STATUS_EXECUTED, STATUS_FAILED)]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_jobs')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='ai_jobs', null=True, blank=True)
    kind = models.CharField(max_length=20, choices=KINDS, default=KIND_CHAT)
    status = models.CharField(max_length=10, choices=STATUSES, default=STATUS_QUEUED)
    model = models.CharField(max_length=50, blank=True)

    """ What was asked, where a job is not a conversation turn. """
    input = models.JSONField(default=dict, blank=True)

    """ What the turn did: `{"touched": [{"model", "id", "reference", "what"}]}`. """
    outcome = models.JSONField(null=True, blank=True)

    error = models.TextField(blank=True)

    """ What the job is doing right now, for the person watching it ("Reading the page..."). """
    progress = models.CharField(max_length=200, blank=True)

    """ When `progress` was last written: a running job that goes quiet for too long is presumed dead. """
    progress_at = models.DateTimeField(null=True, blank=True)

    """ Set by the Stop button; the runner checks it between steps and gives up. """
    cancel_requested = models.BooleanField(default=False)

    """ Cleared from the activity page (the job still counts towards the month's spend). """
    cleared = models.BooleanField(default=False)

    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    web_searches = models.IntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=4, default=0)

    """ The thread this turn belongs to (for old jobs: the record they were about). """
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    created = models.DateTimeField(default=now)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created']

    @property
    def is_finished(self):
        return self.status in (self.STATUS_DONE, self.STATUS_EXECUTED, self.STATUS_FAILED)

    """ A running job that has not reported progress for this long is presumed dead (a restarted server). """
    STALE_AFTER = datetime.timedelta(minutes=10)

    def mark_running(self):
        self.status, self.started, self.finished, self.error = self.STATUS_RUNNING, now(), None, ''
        self.progress, self.progress_at, self.cancel_requested = 'Starting', now(), False
        self.save(update_fields=['status', 'started', 'finished', 'error', 'progress', 'progress_at', 'cancel_requested'])

    def note_progress(self, text):
        """ Say what is happening now (shown on the job's banner while it runs). """
        self.progress, self.progress_at = text[:200], now()
        self.save(update_fields=['progress', 'progress_at'])

    @property
    def is_running(self):
        return self.status in (self.STATUS_QUEUED, self.STATUS_RUNNING)

    @property
    def is_stale(self):
        """ Running, but quiet for longer than `STALE_AFTER`. """
        return self.is_running and (now() - (self.progress_at or self.started or self.created)) > self.STALE_AFTER

    def reap_if_stale(self):
        """ Turn a presumed-dead job into a failed one, so it can be retried instead of spinning forever. """
        if self.is_stale:
            self.mark_failed('It stopped without finishing (the server probably restarted). Try again.')
        return self

    @property
    def seconds_running(self):
        """ How long the job has been (or was) running, in whole seconds. """
        if self.started is None:
            return 0
        end = self.finished if (self.is_finished and self.finished) else now()
        return max(0, int((end - self.started).total_seconds()))

    def cancel_wanted(self):
        """ Has someone pressed Stop since this job started? Reads the database, not this instance. """
        return bool(AIJob.objects.filter(pk=self.pk, cancel_requested=True).exists())

    @property
    def percent_of_budget(self):
        """ This job's cost as a share of its user's monthly budget, or None without one. """
        config = getattr(self.user, 'ai_settings', None)
        if config is None or not config.monthly_budget:
            return None
        return int(100 * self.cost / config.monthly_budget)

    def mark_done(self, result=None):
        self.status, self.finished = self.STATUS_DONE, now()
        self.save(update_fields=['status', 'finished'])

    def mark_failed(self, error):
        self.status, self.error, self.finished = self.STATUS_FAILED, str(error)[:2000], now()
        self.save(update_fields=['status', 'error', 'finished'])

    def add_usage(self, response):
        """ Record a Messages API response's tokens and cost against this job. """
        from bom.ai.client import cost_of, usage_of
        input_tokens, output_tokens, web_searches = usage_of(response)
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.web_searches += web_searches
        self.cost += cost_of(self.model, input_tokens, output_tokens, web_searches)
        self.save(update_fields=['input_tokens', 'output_tokens', 'web_searches', 'cost'])

    def can_access(self, user):
        return self.user_id == user.id

    def __str__(self):
        return f'{self.get_kind_display()} ({self.status})'


class PCBPart(Part):
    """
    PCB-specific extension of `Part` using Django's multi-table inheritance.

    This model shares the same primary key as `Part` (via the implicit
    one-to-one parent link created by multi-table inheritance) and adds
    PCB-specific metadata.
    """

    LCSCPartNo = models.CharField(max_length=100, blank=True)
    Footprint = models.CharField(max_length=200, blank=True)
    Value = models.CharField(max_length=200, blank=True)
    Category = models.CharField(max_length=200, blank=True)
    DatasheetLink = models.URLField(blank=True)

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
