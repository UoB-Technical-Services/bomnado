""" The AI client for a user, the models they can pick, and what a call cost. """
from decimal import Decimal

import anthropic

""" Models a user may choose, with list prices in USD per million tokens (input, output). """
MODELS = {
    'claude-opus-5': {'label': 'Claude Opus 5', 'input': Decimal('5.00'), 'output': Decimal('25.00')},
    'claude-sonnet-5': {'label': 'Claude Sonnet 5', 'input': Decimal('3.00'), 'output': Decimal('15.00')},
    'claude-haiku-4-5': {'label': 'Claude Haiku 4.5', 'input': Decimal('1.00'), 'output': Decimal('5.00')},
}
DEFAULT_MODEL = 'claude-opus-5'
MODEL_CHOICES = [(model_id, spec['label']) for model_id, spec in MODELS.items()]

""" Web search is billed per search on top of tokens. """
WEB_SEARCH_COST = Decimal('0.01')


class AINotConfigured(Exception):
    """ The user has no API key stored (or it no longer decrypts). """


def settings_for(user):
    """ The user's `UserAISettings`, or None. """
    return getattr(user, 'ai_settings', None)


def client_for(user):
    """ An Anthropic client using the user's own key. Raises `AINotConfigured`. """
    config = settings_for(user)
    if config is None or not config.api_key:
        raise AINotConfigured('Add an AI API key under Settings to use this.')
    return anthropic.Anthropic(api_key=config.api_key, max_retries=2, timeout=120.0)


def model_for(user):
    config = settings_for(user)
    return config.model if config is not None and config.model in MODELS else DEFAULT_MODEL


def test_connection(user):
    """ Confirm the key works and the chosen model is reachable. Returns the model's display name. """
    client = client_for(user)
    model = client.models.retrieve(model_for(user))
    return model.display_name


def cost_of(model, input_tokens, output_tokens, web_searches=0):
    """ USD for one call, from the list prices above. Unknown models cost as Opus 5. """
    spec = MODELS.get(model, MODELS[DEFAULT_MODEL])
    tokens = (Decimal(input_tokens) * spec['input'] + Decimal(output_tokens) * spec['output']) / Decimal(1_000_000)
    return (tokens + WEB_SEARCH_COST * web_searches).quantize(Decimal('0.0001'))


def usage_of(response):
    """ `(input_tokens, output_tokens, web_searches)` from a Messages API response. Cached and
    cache-written input tokens are counted as input (they are billed, at different rates). """
    usage = response.usage
    input_tokens = (usage.input_tokens or 0) + (getattr(usage, 'cache_read_input_tokens', 0) or 0) \
        + (getattr(usage, 'cache_creation_input_tokens', 0) or 0)
    server_tool_use = getattr(usage, 'server_tool_use', None)
    web_searches = (getattr(server_tool_use, 'web_search_requests', 0) or 0) if server_tool_use else 0
    return input_tokens, usage.output_tokens or 0, web_searches
