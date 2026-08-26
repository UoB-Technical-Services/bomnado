from rest_framework import serializers

from bom import models


class PartSerializer(serializers.ModelSerializer):
    picture_url = serializers.SerializerMethodField()

    def get_picture_url(self, obj):
        return obj.picture_url

    class Meta:
        model = models.Part
        fields = (
            'url', 'reference', 'name', 'sale_code', 'hs_code', 'picture',
            'picture_url', 'dimensions', 'nature', 'manufacturer', 'spec', 'qc_steps',
            'created', 'updated', 'id', 'kgs', 'sources', 'end_of_life',
            'deprecated', 'has_open_feedback'
        )


class PartSearchSerializer(serializers.ModelSerializer):
    """ The few fields an autocomplete row needs. Keep this small: it is sent for
    every keystroke. """
    picture_url = serializers.SerializerMethodField()
    named_pieces = serializers.SerializerMethodField()

    def get_picture_url(self, obj):
        return obj.picture_url

    def get_named_pieces(self, obj):
        """ The part's `PARENT>SUFFIX` pieces, so reference completion can offer them.
        Relies on the queryset prefetching `named_pieces`: no query per row. """
        return [{'id': sp.id, 'suffix': sp.suffix, 'reference': f'{obj.reference}{sp.SEPARATOR}{sp.suffix}',
                 'note': sp.note} for sp in obj.named_pieces.all()]

    class Meta:
        model = models.Part
        fields = ('id', 'reference', 'name', 'picture_url', 'deprecated', 'sale_code', 'has_open_feedback',
                  'named_pieces')


class PartSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.PartSource
        fields = '__all__'


class ProjectPKField(serializers.PrimaryKeyRelatedField):
    def get_queryset(self):
        user = self.context['request'].user
        return models.SubAssembly.objects.filter(is_toplevel=True, team__in=user.team_set.all())


class DealSerializer(serializers.ModelSerializer):
    project = ProjectPKField()

    class Meta:
        model = models.Deal
        fields = '__all__'


class DealLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.DealLineItem
        fields = '__all__'


class SubAssemblySerializer(serializers.ModelSerializer):
    picture_url = serializers.SerializerMethodField()

    def get_picture_url(self, obj):
        return obj.picture_url

    class Meta:
        model = models.SubAssembly
        fields = (
            'reference', 'name', 'revision', 'picture', 'picture_url',
            'sale_code', 'hs_code', 'is_toplevel', 'created', 'updated',
            'id', 'url', 'deprecated', 'spec', 'qc_steps', 'instructions',
            'production_phase', 'team', 'has_open_feedback'
        )


class SubAssemblyLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.SubAssemblyLineItem
        fields = ('id', 'subassembly', 'child_part', 'child_subassembly', 'quantity', 'notes')
