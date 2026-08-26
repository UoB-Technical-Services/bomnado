""" Bomnado as an MCP server, so Claude Desktop / Claude Code can talk to it directly.

The same registry the in-app chat uses (`bom.ai.tools`) is served as MCP tools, the team's
conventions and naming guide as resources, and the jumping-off prompts as prompts. Every
call acts as the user the server was started for (`manage.py mcp --user`), so history and
review comments look exactly as they do from the app. Over stdio for now; the Django ORM is
synchronous, so each handler hops to a thread.
"""
import mcp.types as types
from asgiref.sync import sync_to_async
from mcp.server.lowlevel.server import Server
from mcp.server.stdio import stdio_server

from bom.ai import prompts, tools
from bom.ai.tools import Blocks, ToolContext

INSTRUCTIONS = ('Bomnado is a bill-of-materials tool: parts, their suppliers and prices, and assemblies made of '
                'them. Read the conventions and naming-guide resources before creating anything; search before '
                'you create; every change is attributed to you and flagged for human review.')


def build(ctx):
    """ An MCP `Server` acting as `ctx` (a `ToolContext`). """
    run = sync_to_async(_call, thread_sensitive=True)
    read = sync_to_async(prompts.read_resource, thread_sensitive=True)

    async def on_list_tools(_rctx, _params):
        return types.ListToolsResult(tools=[types.Tool(name=t.name, description=t.description, input_schema=t.schema)
                                            for t in tools.TOOLS.values()])

    async def on_call_tool(_rctx, params):
        content, is_error = await run(ctx, params.name, params.arguments or {})
        return types.CallToolResult(content=content, is_error=is_error)

    async def on_list_resources(_rctx, _params):
        return types.ListResourcesResult(resources=[
            types.Resource(uri=uri, name=name, description=description, mime_type='text/markdown')
            for uri, name, description, _ in prompts.resources(ctx)])

    async def on_read_resource(_rctx, params):
        text = await read(ctx, str(params.uri))
        return types.ReadResourceResult(contents=[
            types.TextResourceContents(uri=params.uri, mime_type='text/markdown', text=text)])

    async def on_list_prompts(_rctx, _params):
        return types.ListPromptsResult(prompts=[
            types.Prompt(name=p['name'], description=p['description'],
                         arguments=[types.PromptArgument(name=a['name'], required=a['required'])
                                    for a in p['arguments']]) for p in prompts.PROMPTS])

    async def on_get_prompt(_rctx, params):
        text = prompts.prompt_text(params.name, params.arguments or {})
        return types.GetPromptResult(messages=[
            types.PromptMessage(role='user', content=types.TextContent(type='text', text=text))])

    return Server('bomnado', version='1.0', instructions=INSTRUCTIONS, on_list_tools=on_list_tools,
                  on_call_tool=on_call_tool, on_list_resources=on_list_resources, on_read_resource=on_read_resource,
                  on_list_prompts=on_list_prompts, on_get_prompt=on_get_prompt)


def _call(ctx, name, arguments):
    """ A tool call as MCP content: JSON text, or the blocks of a file. """
    outcome = tools.call(ctx, name, arguments)
    if isinstance(outcome, Blocks):
        return [_content(block) for block in outcome.blocks], False
    is_error = isinstance(outcome, dict) and 'error' in outcome
    return [types.TextContent(type='text', text=tools.to_text(outcome))], is_error


def _content(block):
    kind = block.get('type')
    if kind == 'image':
        return types.ImageContent(type='image', data=block['source']['data'], mime_type=block['source']['media_type'])
    if kind == 'document':
        return types.EmbeddedResource(type='resource', resource=types.BlobResourceContents(
            uri='bomnado://file', mime_type=block['source']['media_type'], blob=block['source']['data']))
    return types.TextContent(type='text', text=block.get('text', ''))


def context_for(user, team=None):
    """ Who the server acts as. """
    return ToolContext(user=user, team=team or user.team_set.first(), origin='Claude (MCP)')


async def serve_stdio(ctx):
    server = build(ctx)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

