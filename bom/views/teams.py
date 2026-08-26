""" Teams and the user's own settings: members, invitations, the naming guide, the HS lookup. """

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.generic.base import TemplateView, RedirectView

from bom.forms import UserAccountForm, UserAISettingsForm
from bom.models import Team, UserAISettings
from bom.ai import client as ai_client
from bom.utils import team_owner_required
from bom.utils.accounts import username_from_email
from bom.views.shared import redirect_back_with_message


class TeamsView(LoginRequiredMixin, TemplateView):
    """Teams view"""

    login_url = "/accounts/login/"
    template_name = "pages/teams.html"

    def get_context_data(self, **kwargs):
        context = super(TeamsView, self).get_context_data(**kwargs)

        # Check for messages in session and add to context
        for key in ("error_message", "success_message", "invite_link"):
            if key in self.request.session:
                context[key] = self.request.session.pop(key)

        from bom.ai.naming import DEFAULT_NAMING_GUIDE
        context['default_naming_guide'] = DEFAULT_NAMING_GUIDE
        return context


class UserSettingsView(LoginRequiredMixin, TemplateView):
    """ Per-user settings: account details and a summary of the user's privileges. """

    login_url = '/accounts/login/'
    template_name = 'pages/user_settings.html'

    def get_context_data(self, **kwargs):
        context = super(UserSettingsView, self).get_context_data(**kwargs)
        context.setdefault('form', UserAccountForm(instance=self.request.user))
        context['teams'] = self.request.user.team_set.select_related('owner').order_by('name')
        context['success_message'] = self.request.session.pop('settings_success_message', None)

        # AI assistant.
        ai_settings = ai_client.settings_for(self.request.user)
        context['ai_settings'] = ai_settings
        context['ai_spend'] = ai_settings.spend_this_month() if ai_settings else 0
        context.setdefault('ai_form', UserAISettingsForm(instance=ai_settings or UserAISettings(user=self.request.user)))
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get('form_name') == 'ai':
            return self._post_ai(request)
        form = UserAccountForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            request.session['settings_success_message'] = 'Account details saved.'
            return HttpResponseRedirect(reverse_lazy('bom:user_settings'))
        return self.render_to_response(self.get_context_data(form=form))

    def _post_ai(self, request):
        ai_settings = ai_client.settings_for(request.user) or UserAISettings(user=request.user)
        if request.POST.get('remove_key'):
            ai_settings.api_key = ''
            ai_settings.save()
            request.session['settings_success_message'] = 'AI API key removed.'
            return HttpResponseRedirect(reverse_lazy('bom:user_settings') + '#ai-settings')
        form = UserAISettingsForm(request.POST, instance=ai_settings)
        if form.is_valid():
            form.save()
            request.session['settings_success_message'] = 'AI settings saved.'
            return HttpResponseRedirect(reverse_lazy('bom:user_settings') + '#ai-settings')
        return self.render_to_response(self.get_context_data(ai_form=form))


class NewTeamView(LoginRequiredMixin, RedirectView):
    login_url = "/accounts/login/"

    def get_redirect_url(self, *args, **kwargs):
        # Get the team name from POST data
        team_name = self.request.POST.get("name", "").strip()

        # Validate that team name is provided
        if not team_name:
            return redirect_back_with_message(
                request=self.request,
                message="Team name is required.",
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        # Check if a team with this name already exists
        if Team.objects.filter(name__iexact=team_name).exists():
            return redirect_back_with_message(
                request=self.request,
                message=f"A team with the name '{team_name}' already exists.",
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        # Create the team if validation passes
        try:
            # Create instance first without saving to database, set owner to current user
            t = Team(name=team_name, owner=self.request.user)
            # Validate before saving
            t.full_clean()
            # Save only after validation passes
            t.save()
            t.users.add(self.request.user)
        except ValidationError as e:
            error_message_dict = getattr(e, "message_dict", {})

            # Handle validation errors
            if "name" in error_message_dict:
                error_msg = error_message_dict["name"][0]
            else:
                error_msg = "Team validation failed: " + ", ".join(
                    [f"{k}: {v[0]}" for k, v in error_message_dict.items()]
                )

            return redirect_back_with_message(
                request=self.request,
                message=error_msg,
                message_key="error_message",
                default_url=reverse_lazy("bom:teams"),
            )

        return reverse_lazy("bom:teams")


def make_set_password_link(request, user):
    """ An absolute URL that lets `user` choose a password, using Django's password-reset machinery.

    Valid for `settings.PASSWORD_RESET_TIMEOUT` and only until it is used.
    """
    return request.build_absolute_uri(reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    }))


class AddToTeamView(LoginRequiredMixin, RedirectView):
    """ Add a user to a team (owner only).

    The owner enters a username or email address. An existing account is added
    straight away. An unknown *email address* creates a new account for that
    person, adds it to the team, and gives the owner a "set your password" link
    to pass on - so new users can be onboarded even when outgoing email is not
    configured. The same link is also emailed, best-effort.
    """
    login_url = '/accounts/login/'

    @team_owner_required
    def get_redirect_url(self, *args, **kwargs):
        request = self.request
        team = request.user.team_set.get(id=kwargs.get('pk'))
        identifier = (request.POST.get('username') or '').strip()
        teams_url = reverse_lazy('bom:teams')

        def _error(message):
            return redirect_back_with_message(request=request, message=message, default_url=teams_url)

        if not identifier:
            return _error('Enter a username or email address to add to the team.')

        # Existing account, by username or email (either way, case-insensitive).
        user = User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)).order_by('pk').first()
        if user:
            if team.users.filter(pk=user.pk).exists():
                return _error(f'{user.email or user.username} is already a member of {team.name}.')
            team.users.add(user)
            request.session['success_message'] = f'{user.email or user.username} has been added to {team.name}.'
            return teams_url

        # Nobody by that name. Only an email address can be used to invite someone new.
        try:
            validate_email(identifier)
        except ValidationError:
            return _error(f'No user called "{identifier}" was found. '
                          'Enter an email address to invite someone new.')

        user = User(username=username_from_email(identifier), email=identifier)
        user.set_unusable_password()
        try:
            user.full_clean()
        except ValidationError as e:
            return _error('Could not create that user: ' + '; '.join(
                f'{field}: {errors[0]}' for field, errors in e.message_dict.items()))
        user.save()
        team.users.add(user)

        link = make_set_password_link(request, user)
        try:
            send_mail(
                subject=f'You have been added to {team.name} on Bomnado',
                message=(f'{request.user.email or request.user.username} has added you to the team '
                         f'"{team.name}" on Bomnado.\n\n'
                         f'Choose a password to get started:\n\n{link}\n'),
                from_email=None,
                recipient_list=[user.email],
                fail_silently=True,
            )
        except Exception:
            # Email is optional here - the owner is shown the link regardless.
            pass

        request.session['success_message'] = (
            f'Created an account for {user.email} and added it to {team.name}. '
            'Send them the link below so they can choose a password (it can only be used once).')
        request.session['invite_link'] = link
        return teams_url


class RemoveFromTeamView(LoginRequiredMixin, RedirectView):
    login_url = '/accounts/login/'

    @team_owner_required
    def get_redirect_url(self, *args, **kwargs):
        request = self.request
        username = request.POST.get('username')
        t = request.user.team_set.get(id=kwargs.get('pk'))
        users = User.objects.filter(username=username)
        if users:
            t.users.remove(users.first())
            t.save()
        return reverse_lazy('bom:teams')


class TeamHsLookupView(LoginRequiredMixin, RedirectView):
    """ Where the team's HS codes link out to ({code} stands for the digits). POST only. """
    login_url = '/accounts/login/'

    def post(self, request, *args, **kwargs):
        team = get_object_or_404(Team, pk=kwargs['pk'])
        if not team.is_owner(request.user):
            raise PermissionDenied('Only the team owner can change the HS code lookup.')
        team.hs_lookup = (request.POST.get('hs_lookup') or '').strip()[:300]
        team.save()
        request.session['success_message'] = f'HS code lookup for {team.name} saved.'
        return redirect(reverse_lazy('bom:teams'))


class TeamNamingGuideView(LoginRequiredMixin, RedirectView):
    """ The team owner's reference naming guide (see `bom.ai.naming`). POST only. """
    login_url = '/accounts/login/'

    def post(self, request, *args, **kwargs):
        team = get_object_or_404(Team, pk=kwargs['pk'])
        if not team.is_owner(request.user):
            raise PermissionDenied('Only the team owner can change the naming guide.')
        team.naming_guide = (request.POST.get('naming_guide') or '').strip()[:20000]
        team.save()
        request.session['success_message'] = f'Naming guide for {team.name} saved.'
        return redirect(reverse_lazy('bom:teams'))
