""" One turn of the in-app conversation: the Messages API tool loop over `bom.ai.tools`.

The person's message is already on the thread (`AIMessage`); `run_turn` streams the model's
answer into new assistant messages, runs the tools it calls (as the person, through the
tool registry), feeds the results back, and stops when the model does. Everything is
persisted as it happens, so the chat window - which polls - shows text as it is written
and tool calls as they run, and a turn survives the page being left.
"""
import logging
import time

from django.conf import settings

from bom.ai import prompts, tools
from bom.ai.client import client_for, model_for
from bom.ai.tools import Blocks, ToolContext
from bom.models import AIMessage, Attachment, Part, SubAssembly

log = logging.getLogger(__name__)

""" Tool-use rounds allowed in one turn, and the web the model may read per turn. """
MAX_ROUNDS = 30
WEB_SEARCHES = 6
WEB_FETCHES = 4
FETCH_TOKENS = 8000

""" Messages of the conversation sent back each turn, and how many keep their tool results whole. """
MAX_MESSAGES = 80
FRESH_MESSAGES = 8
OLD_RESULT_CHARS = 800

""" How often a streaming answer is written to the database for the window to show. """
SAVE_EVERY = 0.6


class AIRefused(RuntimeError):
    """ The model declined (`stop_reason == "refusal"`). """


class Cancelled(RuntimeError):
    """ Someone pressed Stop. """


def check_cancel(job):
    if job is not None and job.cancel_wanted():
        raise Cancelled('Stopped.')


def web_search_tool(model, max_uses=WEB_SEARCHES):
    """ The provider's web search; Haiku 4.5 only has the basic variant. """
    return {'type': 'web_search_20250305' if model.startswith('claude-haiku') else 'web_search_20260209',
            'name': 'web_search', 'max_uses': max_uses}


def web_fetch_tool(model, max_uses=WEB_FETCHES, max_content_tokens=FETCH_TOKENS):
    """ The provider's page fetcher, a capped slice of each page (retail pages run to 100k tokens). """
    return {'type': 'web_fetch_20250910' if model.startswith('claude-haiku') else 'web_fetch_20260209',
            'name': 'web_fetch', 'max_uses': max_uses, 'max_content_tokens': max_content_tokens}


def context_record(thread):
    """ The record the person was looking at when they wrote, if they may see it. """
    context = thread.context or {}
    model = {'part': Part, 'assembly': SubAssembly}.get(context.get('kind'))
    record = model.objects.filter(pk=context.get('id')).first() if model and context.get('id') else None
    return record if record is not None and record.can_access(thread.user) else None


def attachments_for(thread):
    return {a.filename: a for a in Attachment.objects.attachments_for_object(thread).order_by('pk')}


def file_placeholder(attachment):
    """ How a file is held in a stored message: by id, expanded to content blocks when sent. """
    return {'type': 'bomnado_file', 'attachment_id': attachment.id, 'filename': attachment.filename}


def context_placeholder(context):
    """ Where a message was written from (`{"kind", "id", "reference"}`), kept on the message so the
    model sees which page each request came from, not only the page of the latest one. """
    return {'type': 'bomnado_context', **{k: context[k] for k in ('kind', 'id', 'reference') if k in context}}


def context_text(block):
    kind = block.get('kind')
    if not kind or not block.get('reference'):
        return '(Sent from a page that is not about a particular record.)'
    name = 'bom:part_editor_update' if kind == 'part' else 'bom:assembly_editor_update'
    from django.urls import reverse
    return (f'(Sent from the page of {kind} `{block["reference"]}` - {reverse(name, kwargs={"pk": block["id"]})}. '
            '"This" means that record.)')


def expand(blocks):
    """ Stored content blocks as the API takes them: file and context placeholders become blocks. """
    out = []
    for block in blocks:
        if block.get('type') == 'bomnado_context':
            out.append({'type': 'text', 'text': context_text(block)})
        elif block.get('type') == 'bomnado_file':
            attachment = Attachment.objects.filter(pk=block['attachment_id']).first()
            if attachment is None:
                out.append({'type': 'text', 'text': f'(file {block.get("filename")} is no longer available)'})
                continue
            with attachment.attachment_file.open('rb') as fh:
                out += tools.file_blocks(attachment.filename, fh.read())
        elif block.get('type') == 'tool_result' and isinstance(block.get('content'), list):
            out.append({**block, 'content': expand(block['content'])})
        else:
            out.append(block)
    return out


def trim_old(blocks):
    """ An older message's tool results, shortened: the model has read them already. """
    out = []
    for block in blocks:
        if block.get('type') == 'tool_result':
            content = block.get('content')
            if isinstance(content, list):
                text = ' '.join(b.get('text', '') for b in content if b.get('type') == 'text') or '(file content)'
            else:
                text = str(content or '')
            if len(text) > OLD_RESULT_CHARS:
                text = text[:OLD_RESULT_CHARS] + ' ... (shortened; call the tool again if you need the rest)'
            out.append({**block, 'content': text})
        else:
            out.append(block)
    return out


def api_messages(thread):
    """ The conversation as the API takes it: the last `MAX_MESSAGES`, files expanded, old tool
    results shortened, consecutive same-role messages merged. """
    stored = list(thread.messages.order_by('pk', 'id'))[-MAX_MESSAGES:]
    out = []
    for index, message in enumerate(stored):
        blocks = list(message.content or [])
        if not blocks:
            continue
        blocks = expand(blocks) if index >= len(stored) - FRESH_MESSAGES else trim_old(expand(
            [b for b in blocks if b.get('type') != 'bomnado_file'] or [{'type': 'text', 'text': '(a file was sent)'}]))
        if out and out[-1]['role'] == message.role:
            out[-1]['content'] = out[-1]['content'] + blocks
        else:
            out.append({'role': message.role, 'content': blocks})
    if out:
        # A cache breakpoint at the end: the whole conversation so far is reused by the next round and
        # the next turn, instead of being billed again in full each time.
        last = dict(out[-1]['content'][-1])
        if last.get('type') in ('text', 'tool_result', 'image', 'document'):
            last['cache_control'] = {'type': 'ephemeral'}
            out[-1]['content'] = out[-1]['content'][:-1] + [last]
    return out


def serialisable(content):
    """ Response content blocks as plain dicts, for storing and for sending back. """
    out = []
    for block in content:
        dump = getattr(block, 'model_dump', None)
        dumped = dump(exclude_none=True) if callable(dump) else None
        if isinstance(dumped, dict):
            out.append(dumped)
        elif isinstance(block, dict):
            out.append(block)
        else:  # a test double
            item = {'type': getattr(block, 'type', 'text')}
            if item['type'] == 'text':
                item['text'] = getattr(block, 'text', '')
            elif item['type'] == 'tool_use':
                item.update({'id': block.id, 'name': block.name, 'input': dict(block.input)})
            out.append(item)
    return out


def progress_for(block):
    """ What a content block means the model is doing, for the progress line. """
    kind = getattr(block, 'type', '')
    if kind == 'server_tool_use':
        query = (getattr(block, 'input', None) or {}).get('query') or (getattr(block, 'input', None) or {}).get('url')
        return f'Searching the web for "{query}"' if block.name == 'web_search' else f'Reading {query}'
    if kind == 'tool_use':
        return tool_summary(block.name, dict(block.input or {}))
    if kind == 'text':
        return 'Writing'
    return ''


def tool_summary(name, arguments):
    """ "search_parts: M8 nut" - how a tool call is shown. """
    for key in ('query', 'part', 'assembly', 'record', 'url', 'reference', 'filename', 'supplier_id', 'attachment_id'):
        if arguments.get(key) not in (None, ''):
            return f'{name}: {str(arguments[key])[:60]}'
    return name


def last_request(thread):
    """ The person's most recent message, as text. """
    for message in thread.messages.filter(role='user').order_by('-pk'):
        text = ' '.join(b.get('text', '') for b in message.content if b.get('type') == 'text').strip()
        if text:
            return text
    return ''


def run_turn(job):
    """ Answer the thread's latest message. Raises on failure (`bom.ai.jobs.run` records it). """
    thread = job.content_object
    client = client_for(thread.user)
    model = model_for(thread.user)
    job.model = model
    job.save(update_fields=['model'])

    asked = last_request(thread)
    ctx = ToolContext(thread.user, thread.team, origin=f'Chat: {asked[:60]}' if asked else 'AI chat',
                      attachments=attachments_for(thread))
    record = context_record(thread)
    system = [{'type': 'text', 'text': prompts.system_prompt(ctx, hint=asked), 'cache_control': {'type': 'ephemeral'}}]
    system.append({'type': 'text', 'text': prompts.page_context(record)})
    if ctx.attachments:
        system.append({'type': 'text', 'text': '# Files in this conversation\n\n'
                       + '\n'.join(f'- {name} (attachment id {a.id})' for name, a in ctx.attachments.items())})
    request = {'model': model, 'max_tokens': 8000, 'system': system,
               'tools': tools.anthropic_tools() + [web_search_tool(model), web_fetch_tool(model)]}
    if not model.startswith('claude-haiku'):
        request['output_config'] = {'effort': 'medium'}

    if not thread.title and asked:
        thread.title = asked[:80]
        thread.save(update_fields=['title'])

    job.note_progress('Thinking')
    for _ in range(MAX_ROUNDS):
        check_cancel(job)
        answer = AIMessage.objects.create(thread=thread, role='assistant', content=[], job=job)
        response = _ask(client, request, api_messages(thread), job, answer)
        job.add_usage(response)
        answer.content = serialisable(response.content)
        answer.save(update_fields=['content'])
        check_cancel(job)

        if response.stop_reason == 'refusal':
            raise AIRefused('The AI declined to do this.')
        if response.stop_reason == 'pause_turn':
            continue
        if response.stop_reason != 'tool_use':
            break

        results, shown = [], []
        for block in response.content:
            if getattr(block, 'type', '') != 'tool_use':
                continue
            arguments = dict(block.input or {})
            summary = tool_summary(block.name, arguments)
            job.note_progress(summary)
            outcome = tools.call(ctx, block.name, arguments)
            error = outcome.get('error') if isinstance(outcome, dict) else None
            results.append({'type': 'tool_result', 'tool_use_id': block.id, 'content': _store(thread, outcome),
                            **({'is_error': True} if error else {})})
            shown.append({'name': block.name, 'summary': summary, 'error': error,
                          'writes': tools.TOOLS[block.name].writes if block.name in tools.TOOLS else False})
        AIMessage.objects.create(thread=thread, role='user', content=results, job=job,
                                 meta={'tools': shown, 'touched': list(ctx.touched)})
        job.note_progress('Thinking')
    else:
        raise RuntimeError('The AI kept working without finishing an answer.')

    thread.save(update_fields=['updated'])
    return {'touched': ctx.touched}


def _store(thread, outcome):
    """ A tool result as stored: JSON text, or blocks with any file kept as an attachment on the thread. """
    if not isinstance(outcome, Blocks):
        return tools.to_text(outcome)
    stored = []
    for block in outcome.blocks:
        if block.get('type') in ('document', 'image') and block.get('source', {}).get('type') == 'base64':
            import base64
            from django.core.files.base import ContentFile
            name = f'tool-result.{"pdf" if block["type"] == "document" else block["source"]["media_type"].split("/")[-1]}'
            attachment = Attachment(content_object=thread)
            attachment.attachment_file.save(name, ContentFile(base64.standard_b64decode(block['source']['data'])))
            stored.append(file_placeholder(attachment))
        else:
            stored.append(block)
    return stored


def _ask(client, request, messages, job, answer):
    """ One API call. Streamed (so the window can show the answer as it is written) unless
    `BOMNADO_AI_STREAM` is off, as it is in tests. """
    if not getattr(settings, 'BOMNADO_AI_STREAM', True):
        return client.messages.create(messages=messages, **request)
    saved_at = 0
    with client.messages.stream(messages=messages, **request) as stream:
        for event in stream:
            kind = getattr(event, 'type', '')
            snapshot = stream.current_message_snapshot
            if kind == 'content_block_stop' and snapshot is not None and event.index < len(snapshot.content):
                progress = progress_for(snapshot.content[event.index])
                if progress:
                    job.note_progress(progress)
                check_cancel(job)  # a Stop lands between blocks; the stream is closed on exit
            if snapshot is not None and time.monotonic() - saved_at > SAVE_EVERY:
                answer.content = serialisable(snapshot.content)
                answer.save(update_fields=['content'])
                saved_at = time.monotonic()
        return stream.get_final_message()
