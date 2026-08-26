from django import template

from bom.ai.client import settings_for

register = template.Library()


@register.simple_tag(takes_context=True)
def ai_status(context):
    """ Whether the current user can use the AI: `{% ai_status as ai %}` -> `ai.configured`, `ai.over_budget`, `ai.ready`.

    Syntax::

        {% ai_status as ai %}{% if ai.ready %}...{% endif %}
    """
    user = getattr(context.get('request'), 'user', None)
    config = settings_for(user) if user is not None and user.is_authenticated else None
    configured = bool(config and config.is_configured)
    spend = config.spend_this_month() if configured else 0
    over_budget = bool(configured and config.monthly_budget is not None and spend >= config.monthly_budget)
    return {'configured': configured, 'over_budget': over_budget, 'ready': configured and not over_budget,
            'spend': spend, 'budget': config.monthly_budget if configured else None,
            'percent': config.percent_used() if configured else None,
            'model': config.model if configured else ''}


@register.filter
def ai_person(user):
    """ How a user is named in the window: first name, else email, else username. """
    if user is None:
        return ''
    return user.first_name or user.email or user.username


@register.filter
def ai_web_uses(message):
    """ What an assistant message looked up on the web: "Searched: M8 nut", "Read: https://...". """
    uses = []
    for block in message.content or []:
        if block.get('type') != 'server_tool_use':
            continue
        arguments = block.get('input') or {}
        if block.get('name') == 'web_search':
            uses.append(f'Searched: {arguments.get("query", "")}')
        else:
            uses.append(f'Read: {str(arguments.get("url", ""))[:80]}')
    return uses


@register.filter
def ai_tool_calls(message):
    """ The Bomnado tools a tool-result message reports (see `bom.ai.chat`), with the raw
    "search_parts: M8 nut" summaries turned into readable "Search parts: M8 nut" rows. """
    shown = []
    for call in (message.meta or {}).get('tools', []):
        summary = call.get('summary') or call.get('name', '')
        name, _, value = summary.partition(':')
        pretty = name.replace('_', ' ').strip().capitalize() + (': ' + value.strip() if value.strip() else '')
        shown.append(dict(call, summary=pretty))
    return shown


@register.filter
def ai_new_tab(html):
    """ Links in an answer open in a new tab (a supplier page to check, a part to look at), so the
    conversation stays where it is. """
    import re
    return re.sub(r'<a (?![^>]*target=)', '<a target="_blank" rel="noopener" ', html)
