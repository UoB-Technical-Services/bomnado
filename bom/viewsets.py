from collections import Counter
from urllib.parse import urlparse

from django.shortcuts import get_object_or_404

from django.core.exceptions import ValidationError
from django.db.models import Q

from rest_framework import viewsets, status, serializers as drf_serializers

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from bom import models, serializers
from bom.serializers import SubAssemblySerializer
from bom.permissions import IsTeamMember
from bom.utils import team_member_required


class PartViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PartSerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    """ Most rows an autocomplete query returns. """
    SEARCH_LIMIT = 20

    def get_queryset(self):
        teams = self.request.user.team_set.values_list('id')
        return models.Part.objects.filter(team__in=teams).prefetch_related('sources')

    @action(methods=['get'], detail=False)
    def search(self, request):
        """ Lightweight autocomplete: `?search=TERM` -> at most SEARCH_LIMIT slim rows.

        Matching, in order of preference:
          1. reference starts with the term;
          2. the term is `PARENT>SUFFIX` syntax - reference starts with the part
             before the chevron (so typing `CHASSIS>TOP` offers `CHASSIS`);
          3. reference or name contains the term.
        """
        term = request.query_params.get('search', '').strip()
        parts = models.Part.objects.filter(team__in=request.user.team_set.values_list('id')).only(
            'id', 'reference', 'name', 'picture', 'deprecated', 'sale_code', 'colour', 'has_open_feedback', 'kgs', 'dimensions').order_by(
            'reference').prefetch_related('named_pieces', 'sources')

        def top(queryset):
            return list(queryset[:self.SEARCH_LIMIT])

        if not term:
            results = top(parts)
        else:
            results = top(parts.filter(reference__istartswith=term))
            if not results and models.NamedPiece.SEPARATOR in term:
                results = top(parts.filter(reference__istartswith=term.split(models.NamedPiece.SEPARATOR, 1)[0]))
            if not results:
                results = top(parts.filter(Q(reference__icontains=term) | Q(name__icontains=term)))

        return Response(serializers.PartSearchSerializer(results, many=True, context={'request': request}).data)


class PartSourceViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.PartSourceSerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        teams = self.request.user.team_set.values_list('id')
        return models.PartSource.objects.filter(part__team__in=teams)


class SubAssemblyViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SubAssemblySerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        teams = self.request.user.team_set.values_list('id')
        return models.SubAssembly.objects.filter(team__in=teams)

    @action(methods=['get'], detail=True)
    @team_member_required
    def available(self, request, pk=None):
        """ End point to view subassemblies available to particular project """
        # Get project only if user has access to it
        queryset = self.get_queryset()
        project = get_object_or_404(queryset, pk=pk)

        shared_assemblies = project.team.assemblies.filter(shared=True)
        all_shared = shared_assemblies | project.children.all().exclude(pk=pk)

        return Response(SubAssemblySerializer(all_shared, many=True, context={'request': request}).data)


class SubAssemblyLineItemViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.SubAssemblyLineItemSerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        teams = self.request.user.team_set.values_list('id')
        return models.SubAssemblyLineItem.objects.filter(subassembly__team__in=teams)

    def create(self, request, *args, **kwargs):
        """Override create to handle circular reference validation errors"""
        try:
            return super().create(request, *args, **kwargs)
        except ValidationError as e:
            # Convert Django's ValidationError to DRF's ValidationError for proper API response
            # This will return a 400 Bad Request with the validation messages
            raise drf_serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else str(e))

    def update(self, request, *args, **kwargs):
        """Override update to handle circular reference validation errors"""
        try:
            return super().update(request, *args, **kwargs)
        except ValidationError as e:
            # Convert Django's ValidationError to DRF's ValidationError for proper API response
            # This will return a 400 Bad Request with the validation messages
            raise drf_serializers.ValidationError(e.message_dict if hasattr(e, 'message_dict') else str(e))


class DealLineItemViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.DealLineItemSerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        teams = self.request.user.team_set.values_list('id')
        return models.DealLineItem.objects.filter(part__team__in=teams)


class DealViewSet(viewsets.ModelViewSet):
    serializer_class = serializers.DealSerializer
    permission_classes = [IsAuthenticated, IsTeamMember]

    def get_queryset(self):
        user = self.request.user
        return models.Deal.objects.filter(team__in=user.team_set.all())

    @action(detail=True, methods=['get', 'post'])
    @team_member_required
    def collect(self, request, pk=None):
        """
            Find all parts with the same supplier as `deal_pk` that are
            also in the `pk` (assembly) or a child of it.

            Then remove all items currently in the deal and add the new ones
            and use the quantity as the number of them used.
            """
        try:
            # Get the deal from the authenticated user's queryset
            deal = self.get_queryset().get(id=pk)
        except models.Deal.DoesNotExist:
            return Response({"error": "Deal not found or access denied"}, status=status.HTTP_404_NOT_FOUND)

        project = deal.project

        # Additional security check for the project team
        if not request.user.team_set.filter(id=project.team.id).exists():
            return Response({"error": "You don't have access to this project"}, status=status.HTTP_403_FORBIDDEN)

        # Delete all existing parts in the deal.
        deal.deallineitem_set.all().delete()

        # Find all the parts that share this supplier used in the assembly.
        parts = Counter()
        assemblies = Counter()
        project.collect_and_count_parts(parts, assemblies)
        supplier_domain = f'{urlparse(deal.url).netloc}'.lower()

        # Find matching domains in the part source list.
        for part in parts:
            # Only allow parts from teams the user belongs to
            matching = models.PartSource.objects.filter(
                part=part.id,
                url__icontains=supplier_domain,
                part__team__in=request.user.team_set.all()
            )

            # Create a new deal item.
            if matching:
                quantity = parts[part]
                deal_line = models.DealLineItem(part=part, deal=deal, quantity=quantity)
                deal_line.save()

        # Return a response to say if it worked.
        return Response({"ok": True})
