""" The dashboard: the team's projects. """
import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, When, BooleanField
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic.base import TemplateView

from bom.models import SubAssembly


class DashboardView(LoginRequiredMixin, TemplateView):
    """ Index view, after a successful login, show all top level assemblies """
    login_url = '/accounts/login/'
    template_name = 'pages/dashboard.html'

    def dispatch(self, request, *args, **kwargs):
        # Ensure user is a member of a team before getting to the dashboard
        # However, allow superusers to access the dashboard even without teams
        if (not request.user.is_anonymous
                and request.user.team_set.count() == 0
                and not request.user.is_superuser):
            return redirect(reverse_lazy('bom:teams'))
        return super(DashboardView, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(DashboardView, self).get_context_data(**kwargs)
        teams = self.request.user.team_set.values_list('id')

        # Use annotate to create a custom field based on the deprecation date.
        products = SubAssembly.objects.filter(team__in=teams, is_toplevel=True).annotate(
            is_deprecated=Case(
                When(deprecated__lte=datetime.date.today(), then=True),
                default=False,
                output_field=BooleanField()
            )
        ).order_by('is_deprecated', 'reference')
        context['products'] = products

        # Check for error messages in session and add to context
        if 'error_message' in self.request.session:
            context['error_message'] = self.request.session.pop('error_message')

        # Also check for part-specific error messages
        if 'part_error_message' in self.request.session:
            context['error_message'] = self.request.session.pop('part_error_message')

        return context
