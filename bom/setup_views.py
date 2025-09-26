"""
Views for first-time setup functionality
"""
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
import json


@method_decorator(ensure_csrf_cookie, name='dispatch')
class FirstTimeSetupView(TemplateView):
    """
    First-time setup view for creating the initial superuser
    """
    template_name = 'pages/first_time_setup.html'

    def dispatch(self, request, *args, **kwargs):
        # If setup is already complete, redirect to dashboard
        # But only if we actually have superusers (not just a database)
        try:
            if User.objects.filter(is_superuser=True).exists():
                return redirect(reverse('bom:start'))
        except Exception:
            # If we can't check, let the view load (probably needs migration)
            pass
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['setup_complete'] = False

        # Check if migrations need to be applied using Django's migration executor
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
            context['needs_migration'] = bool(plan)
        except Exception:
            # If migration system has issues, assume we need migrations
            context['needs_migration'] = True

        return context

    def _is_setup_complete(self):
        """Check if setup is already complete"""
        try:
            # Check if any superusers exist
            return User.objects.filter(is_superuser=True).exists()
        except Exception:
            return False


class FirstTimeSetupAPIView(TemplateView):
    """
    API view for handling first-time setup actions
    """

    def dispatch(self, request, *args, **kwargs):
        # If setup is already complete, return error
        try:
            if User.objects.filter(is_superuser=True).exists():
                return JsonResponse({'success': False, 'error': 'Setup is already complete'})
        except Exception:
            # If we can't check, let the API proceed
            pass
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            action = data.get('action')

            if action == 'migrate':
                return self.handle_migration(request)
            elif action == 'create_superuser':
                return self.handle_create_superuser(request, data)
            else:
                return JsonResponse({'success': False, 'error': 'Invalid action'})

        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    def handle_migration(self, request):
        """Handle database migration"""
        try:
            # Run migrations
            call_command('migrate', verbosity=0, interactive=False)
            return JsonResponse({'success': True, 'message': 'Database migrated successfully'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Migration failed: {str(e)}'})

    def handle_create_superuser(self, request, data):
        """Handle superuser creation"""
        try:
            username = data.get('username', '').strip()
            email = data.get('email', '').strip()
            password = data.get('password', '')
            confirm_password = data.get('confirm_password', '')

            # Validate input
            if not username:
                return JsonResponse({'success': False, 'error': 'Username is required'})

            if not email:
                return JsonResponse({'success': False, 'error': 'Email is required'})

            if not password:
                return JsonResponse({'success': False, 'error': 'Password is required'})

            if password != confirm_password:
                return JsonResponse({'success': False, 'error': 'Passwords do not match'})

            if len(password) < 8:
                return JsonResponse({'success': False, 'error': 'Password must be at least 8 characters long'})

            # Check if username already exists
            if User.objects.filter(username=username).exists():
                return JsonResponse({'success': False, 'error': 'Username already exists'})

            # Check if email already exists
            if User.objects.filter(email=email).exists():
                return JsonResponse({'success': False, 'error': 'Email already exists'})

            # Create superuser
            user = User.objects.create_superuser(
                username=username,
                email=email,
                password=password
            )

            # Log the user in
            login(request, user)

            return JsonResponse({
                'success': True,
                'message': 'Superuser created successfully',
                'redirect_url': reverse('bom:first_time_setup_complete')
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Failed to create superuser: {str(e)}'})

    def _is_setup_complete(self):
        """Check if setup is already complete"""
        try:
            # Check if any superusers exist
            return User.objects.filter(is_superuser=True).exists()
        except Exception:
            return False


class FirstTimeSetupCompleteView(TemplateView):
    """
    Setup completion view
    """
    template_name = 'pages/first_time_setup_complete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dashboard_url'] = reverse('bom:start')
        context['demo_url'] = reverse('bom:first_time_setup_demo')
        return context


class FirstTimeSetupDemoView(TemplateView):
    """
    API view for handling demo creation during setup
    """

    def post(self, request, *args, **kwargs):
        """Handle demo creation request"""
        try:
            # Check if user is authenticated (should be from setup)
            if not request.user.is_authenticated:
                return JsonResponse({'success': False, 'error': 'Authentication required'})
            # Execute the demo creation command with the current user
            call_command('createdemo', user=request.user.username, force=True)
            return JsonResponse({
                'success': True,
                'message': 'Demo bicycle project created successfully!',
                'redirect_url': reverse('bom:start')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Failed to create demo: {str(e)}'})

    def get(self, request, *args, **kwargs):
        """Redirect GET requests to main dashboard"""
        return redirect(reverse('bom:start'))
