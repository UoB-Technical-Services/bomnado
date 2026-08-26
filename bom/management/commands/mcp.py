""" `manage.py mcp --user alice`: serve Bomnado to an MCP client (Claude Desktop, Claude Code) over stdio,
acting as that user. Configure the client to run this command; for Claude Code:

    claude mcp add bomnado -- pdm run python manage.py mcp --user alice

Logging goes to stderr so stdout stays clean for the protocol.
"""
import logging
import sys

import anyio
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from bom.ai.mcp_server import context_for, serve_stdio
from bom.models import Team


class Command(BaseCommand):
    help = 'Serve Bomnado as an MCP server over stdio, acting as a user.'

    def add_arguments(self, parser):
        parser.add_argument('--user', required=True, help='Username (or email) to act as.')
        parser.add_argument('--team', help='Team name for new records (default: the first team the user is in).')

    def handle(self, *args, **options):
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        user = User.objects.filter(username=options['user']).first() or User.objects.filter(email=options['user']).first()
        if user is None:
            raise CommandError(f'No user {options["user"]!r}.')
        team = None
        if options.get('team'):
            team = Team.objects.filter(name=options['team']).first()
            if team is None or not team.can_access(user):
                raise CommandError(f'{user.username} is not in a team called {options["team"]!r}.')
        ctx = context_for(user, team)
        if ctx.team is None:
            raise CommandError(f'{user.username} is not in any team.')
        anyio.run(serve_stdio, ctx)
