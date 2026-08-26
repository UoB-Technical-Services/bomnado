""" The per-project tools: production phases, orphans, reviews, sales items, supplier deals. """
from collections import defaultdict, Counter

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic.base import TemplateView, RedirectView

from bom.forms import DealPartFormset, DealForm
from bom.models import Part, SubAssembly, Deal, Feedback
from bom import library


def _project_crumb(project):
    """ What a tool page's header needs: the project it belongs to, and the way back to it. """
    return {'project': project, 'project_url': reverse_lazy('bom:assembly_editor_update', kwargs={'pk': project.id})}


class ToolProductionPhases(LoginRequiredMixin, TemplateView):
    """ Production phases view to show what assemblies are allocated to what phases. """
    template_name = 'pages/tool_production_phases.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Sort assemblies by production phase
        product_id = self.kwargs.get('pk')
        root = get_object_or_404(SubAssembly, id=product_id)

        # Check team access
        if not root.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        assemblies = root.children.all().order_by('production_phase')
        phases = defaultdict(list)
        for assy in assemblies:
            phases[assy.production_phase].append(assy)

        # Count the uses.
        counted_parts = Counter()
        counted_assemblies = Counter()
        root.collect_and_count_parts(counted_parts, counted_assemblies)

        # Add to the context.
        context = super(ToolProductionPhases, self).get_context_data(**kwargs)
        context['phases'] = dict(phases)
        context['assemblies'] = assemblies
        context['counted_assemblies'] = counted_assemblies
        context.update(_project_crumb(root))
        return context


class ToolOrphanFinder(LoginRequiredMixin, TemplateView):
    """ Find orphan assemblies and parts. """
    template_name = 'pages/tool_orphan_finder.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Find orphans.
        project = get_object_or_404(SubAssembly, id=self.kwargs.get('pk'))

        # Check team access
        if not project.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        orphan_parts = [p for p in Part.all_available_to_user(self.request.user) if p.is_orphan]
        orphan_assemblies = [a for a in project.children.all() if a.is_orphan]

        # Add to the context.
        context = super(ToolOrphanFinder, self).get_context_data(**kwargs)
        context['orphan_parts'] = orphan_parts
        context['orphan_assemblies'] = orphan_assemblies
        context.update(_project_crumb(project))
        return context


class ToolReviews(LoginRequiredMixin, TemplateView):
    """ What needs a look in a project: open feedback on its assemblies and parts, and parts missing data. """
    template_name = 'pages/tool_reviews.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        project = get_object_or_404(SubAssembly, id=self.kwargs.get('pk'))
        if not project.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        assemblies, parts = library.project_contents(project)
        for assembly in assemblies:
            assembly.is_assembly = True
        attention = [(record, list(Feedback.objects.open_for(record)))
                     for record in assemblies + parts if record.has_open_feedback]
        missing = [(part, status) for part in parts for status in [library.part_status(part)] if status.is_missing]
        context = super().get_context_data(**kwargs)
        context.update({'attention': attention, 'missing': missing}, **_project_crumb(project))
        return context


class ToolSalesCodes(LoginRequiredMixin, TemplateView):
    """ Show all parts and subassemblies with sales codes """

    template_name = 'pages/tool_sales_codes.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Get all the items with sales codes to display
        project = get_object_or_404(SubAssembly, id=self.kwargs.get('pk'))

        # Check team access
        if not project.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        parts = [p for p in Part.all_available_to_user(self.request.user) if p.sale_code]
        assemblies = [a for a in project.children.all() if a.sale_code]
        # Filter further and fetch ones with sales codes but no HS codes
        # since we can't filter in the template
        parts_without_hs = [p for p in parts if not p.hs_code]
        assemblies_without_hs = [a for a in assemblies if not a.hs_code]

        # Add to the context.
        context = super(ToolSalesCodes, self).get_context_data(**kwargs)
        context['parts'] = parts
        context['assemblies'] = assemblies
        context['parts_without_hs'] = parts_without_hs
        context['assemblies_without_hs'] = assemblies_without_hs
        context.update(_project_crumb(project))
        return context


class ToolDeals(LoginRequiredMixin, TemplateView):
    """ View for a page that displays all `Deals` for a `Project` so that they can be edited. """
    template_name = 'pages/tool_deals.html'
    login_url = '/accounts/login/'

    def get_context_data(self, **kwargs):
        # Sort assemblies by production phase
        product_id = self.kwargs.get('pk')
        root = get_object_or_404(SubAssembly, id=product_id)

        # Check team access
        if not root.can_access(self.request.user):
            raise PermissionDenied("You don't have access to this project")
        team = root.team

        dealparts = {}
        deals = {}
        for deal in team.deals.all():
            d_formset = DealPartFormset(instance=deal)
            for f in d_formset.forms:
                f.fields['part'].queryset = Part.all_available_to_user(self.request.user)
            dealparts[deal] = d_formset
            deals[deal] = DealForm(instance=deal)
            deals[deal]['team'].queryset = self.request.user.team_set.all()

        # Add to the context.
        context = super(ToolDeals, self).get_context_data(**kwargs)
        context['dealparts'] = dealparts
        context['deals'] = deals
        context['new_dform'] = DealForm()
        context['pk'] = product_id
        context['product'] = root
        context.update(_project_crumb(root))
        return context


class ToolDealLineItemUpdateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        deal_id = self.kwargs.get('deal_id')
        deal = get_object_or_404(Deal, pk=deal_id)

        # Check if user has access to this deal's team
        if not deal.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this deal")

        formset = DealPartFormset(self.request.POST, instance=deal)
        if formset.is_valid():
            formset.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})


class ToolDealUpdateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        deal_id = self.kwargs.get('deal_id')
        deal = get_object_or_404(Deal, pk=deal_id)

        # Check if user has access to this deal's team
        if not deal.team.can_access(request.user):
            raise PermissionDenied("You don't have access to this deal")

        form = DealForm(self.request.POST, instance=deal)
        if form.is_valid():
            form.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})


class ToolDealCreateView(LoginRequiredMixin, RedirectView):

    def post(self, request, *args, **kwargs):
        form = DealForm(self.request.POST)
        if form.is_valid():
            # A deal belongs to a team, so only members of that team may create one for it.
            if not form.cleaned_data['team'].can_access(request.user):
                raise PermissionDenied("You don't have access to this team")
            form.save()
        return redirect(self.get_redirect_url())

    def get_redirect_url(self, *args, **kwargs):
        pk = self.kwargs.get('pk')
        return reverse_lazy('bom:tools_deals', kwargs={'pk': pk})
