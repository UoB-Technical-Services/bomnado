# Factories for creating valid instances of objects (including foreign keys) quickly for testing and debug
import datetime
import random
import string
import uuid

from factory import LazyAttribute, SubFactory, Sequence
from factory.django import DjangoModelFactory, ImageField
from factory.fuzzy import FuzzyText, FuzzyDateTime, FuzzyFloat, FuzzyChoice, FuzzyInteger

from bom.models import Part, PartSource, SubAssembly, SubAssemblyLineItem, NamedPiece, Team, User, Deal, DealLineItem

start_dt = datetime.datetime(2008, 1, 1, tzinfo=datetime.timezone.utc)
end_dt = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = Sequence(lambda n: 'username_{}'.format(n))
    password = 'password'


class TeamFactory(DjangoModelFactory):
    class Meta:
        model = Team

    name = Sequence(lambda n: 'team_{}'.format(n))


class PartFactory(DjangoModelFactory):
    class Meta:
        model = Part

    reference = LazyAttribute(lambda a: str(uuid.uuid4())[:8].upper())
    name = FuzzyText(length=200, chars=string.ascii_letters)
    kgs = FuzzyFloat(low=0, high=5000)
    dimensions = LazyAttribute(
        lambda a: f'{random.uniform(1, 10000)} X {random.uniform(1, 10000)} X {random.uniform(1, 10000)}')
    colour = FuzzyText(length=100, chars=string.ascii_letters)
    nature = FuzzyChoice([nature for nature, _ in Part.NATURE])
    spec = FuzzyText(length=1000, chars=string.ascii_letters)
    picture = ImageField(color='blue', width=300, height=300, format='JPEG')
    sale_code = FuzzyText(length=100, chars=string.ascii_letters)
    hs_code = FuzzyText(length=10, chars=string.digits)
    end_of_life = FuzzyDateTime(start_dt=start_dt, end_dt=end_dt)
    team = SubFactory(TeamFactory)


class PartSourceFactory(DjangoModelFactory):
    class Meta:
        model = PartSource

    part = SubFactory(PartFactory)
    partcode = FuzzyText(length=100, chars=string.ascii_letters)
    url = FuzzyText(length=100, chars=string.ascii_letters)
    rrp = FuzzyFloat(low=0, high=5000)
    shipping = FuzzyFloat(low=0, high=5000)
    minimum_order = FuzzyInteger(low=1, high=10000)
    lead_time = FuzzyInteger(low=1, high=365)


class NamedPieceFactory(DjangoModelFactory):
    class Meta:
        model = NamedPiece

    part = SubFactory(PartFactory)
    suffix = Sequence(lambda n: f'SUB{n}')
    note = FuzzyText(length=50, chars=string.ascii_letters)


class SubAssemblyFactory(DjangoModelFactory):
    class Meta:
        model = SubAssembly

    reference = LazyAttribute(lambda a: str(uuid.uuid4())[:8].upper())
    name = FuzzyText(length=200, chars=string.ascii_letters)
    revision = LazyAttribute(lambda a: f'{random.randint(0, 100)}.{random.randint(0, 100)}.{random.randint(0, 100)}')
    picture = ImageField(color='blue', width=300, height=300, format='JPEG')
    is_toplevel = FuzzyChoice([True, False])
    sale_code = FuzzyText(length=100, chars=string.ascii_letters)
    hs_code = FuzzyText(length=10, chars=string.digits)
    instructions = FuzzyText(length=1000, chars=string.ascii_letters)
    team = SubFactory(TeamFactory)


class SubAssemblyLineItemFactory(DjangoModelFactory):
    class Meta:
        model = SubAssemblyLineItem

    subassembly = SubFactory(factory=SubAssemblyFactory)
    child_part = SubFactory(factory=PartFactory)
    child_subassembly = SubFactory(factory=SubAssemblyFactory)
    quantity = FuzzyInteger(low=1, high=10000)
    notes = FuzzyText(length=1000, chars=string.ascii_letters)


class DealFactory(DjangoModelFactory):
    class Meta:
        model = Deal

    name = FuzzyText(length=10000)
    rrp = FuzzyFloat(low=0.0)
    shipping = FuzzyFloat(low=0.0)
    lead_time = FuzzyFloat(low=0.0)
    order_notes = FuzzyText(length=1000)
    team = SubFactory(TeamFactory)


class DealLineItemFactory(DjangoModelFactory):
    class Meta:
        model = DealLineItem

    deal = SubFactory(factory=DealFactory)
    part = SubFactory(factory=PartFactory)
    quantity = FuzzyInteger(low=1, high=1000)
    notes = FuzzyText(length=1000)
