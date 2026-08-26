""" Bomnado as an MCP server: the same tools, resources and prompts over the protocol, acting as a user. """
import json

import anyio
from asgiref.sync import async_to_sync
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from bom.ai import mcp_server, tools
from bom.ai.tools import ToolContext
from bom.models import Part
from bom.tests.factories import PartFactory, TeamFactory


class MCPTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw')
        self.team = TeamFactory(owner=self.user, name='Makers')
        self.team.users.add(self.user)
        self.nut = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', picture=None)

    def session(self, coroutine):
        """ Run `coroutine(session)` against an in-memory server acting as alice. """
        ctx = ToolContext(self.user, self.team, origin='Claude (MCP)')
        server = mcp_server.build(ctx)

        async def run():
            async with create_client_server_memory_streams() as (client_streams, server_streams):
                async with anyio.create_task_group() as group:
                    group.start_soon(server.run, server_streams[0], server_streams[1],
                                     server.create_initialization_options(), True)
                    async with ClientSession(client_streams[0], client_streams[1]) as session:
                        await session.initialize()
                        result = await coroutine(session)
                    group.cancel_scope.cancel()
            return result
        return async_to_sync(run)()

    def test_tools_are_the_registry(self):
        async def go(session):
            return await session.list_tools()
        listed = self.session(go)
        self.assertEqual(sorted(t.name for t in listed.tools), sorted(tools.TOOLS))
        by_name = {t.name: t for t in listed.tools}
        self.assertEqual(by_name['get_part'].input_schema, tools.TOOLS['get_part'].schema)

    def test_a_call_acts_as_the_user(self):
        async def go(session):
            found = await session.call_tool('search_parts', {'query': 'm8'})
            made = await session.call_tool('create_part', {'reference': 'M8-WASHER-FA-BZP', 'name': 'M8 washer'})
            bad = await session.call_tool('get_part', {'part': 'NOPE'})
            return found, made, bad
        found, made, bad = self.session(go)
        self.assertEqual(json.loads(found.content[0].text)[0]['reference'], 'M8-NUT-BZP')
        self.assertFalse(found.is_error)
        washer = Part.objects.get(reference='M8-WASHER-FA-BZP')
        self.assertEqual(washer.history.first().history_change_reason, 'Claude (MCP) - Bomnado AI')
        self.assertEqual(washer.history.first().history_user, self.user)
        self.assertTrue(bad.is_error)
        self.assertIn('No part', bad.content[0].text)

    def test_resources_and_prompts(self):
        async def go(session):
            resources = await session.list_resources()
            guide = await session.read_resource('bomnado://naming-guide')
            team = await session.read_resource('bomnado://team')
            prompts = await session.list_prompts()
            prompt = await session.get_prompt('find_suppliers', {'part': 'M8-NUT-BZP'})
            return resources, guide, team, prompts, prompt
        resources, guide, team, prompts, prompt = self.session(go)
        self.assertEqual(sorted(str(r.uri) for r in resources.resources),
                         ['bomnado://conventions', 'bomnado://naming-guide', 'bomnado://team'])
        self.assertIn('M8-NUT-BZP', guide.contents[0].text)  # existing references to copy
        self.assertIn('Team Makers', team.contents[0].text)
        self.assertIn('create_part_from_link', [p.name for p in prompts.prompts])
        self.assertIn('Find other suppliers for `M8-NUT-BZP`', prompt.messages[0].content.text)

    def test_command_checks_the_user_and_team(self):
        with self.assertRaises(CommandError):
            call_command('mcp', user='nobody')
        with self.assertRaises(CommandError):
            call_command('mcp', user='alice', team='Not mine')
        loner = User.objects.create_user(username='loner', email='l@example.com', password='pw')
        with self.assertRaises(CommandError):
            call_command('mcp', user=loner.username)
