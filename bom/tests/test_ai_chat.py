""" The in-app chat: a turn runs the tool loop as the user, and the window shows it as it goes. """
import io
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from bom.ai import chat
from bom.models import AIJob, AIMessage, AIThread, Attachment, Feedback, Part, UserAISettings
from bom.tests.factories import PartFactory, TeamFactory

KEY = 'sk-ant-api03-' + 'x' * 40 + 'wxyz'


def text_block(text):
    return mock.Mock(type='text', text=text)


def tool_block(name, arguments, id='toolu_1'):
    block = mock.Mock(type='tool_use', id=id, input=arguments)
    block.name = name
    return block


def response(blocks, stop_reason='end_turn'):
    r = mock.Mock()
    r.content = blocks
    r.stop_reason = stop_reason
    r.usage = mock.Mock(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0,
                        server_tool_use=None)
    return r


class ChatTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='pw', first_name='Alice')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)
        config = UserAISettings(user=self.user)
        config.api_key = KEY
        config.save()
        self.user.refresh_from_db()
        self.nut = PartFactory(team=self.team, reference='M8-NUT-BZP', name='M8 nut', picture=None)

    def mock_claude(self, *responses):
        patcher = mock.patch('bom.ai.client.anthropic.Anthropic')
        anthropic_cls = patcher.start()
        self.addCleanup(patcher.stop)
        anthropic_cls.return_value.messages.create.side_effect = list(responses)
        return anthropic_cls.return_value.messages.create

    def send(self, text, thread=None, **extra):
        data = {'text': text, 'thread': thread.id if thread else '', **extra}
        return self.client.post(reverse('bom:ai_chat_send'), data)


class TurnTests(ChatTestCase):

    def test_a_turn_searches_creates_and_answers(self):
        create = self.mock_claude(
            response([text_block('Let me check.'), tool_block('search_parts', {'query': 'M8'})], 'tool_use'),
            response([tool_block('create_part', {'reference': 'M8-20MM-BOLT-BTN-BZP', 'name': 'M8 x 20 button bolt',
                                                 'dimensions': '20 x 13 x 8'}, id='toolu_2')], 'tool_use'),
            response([text_block('Created `M8-20MM-BOLT-BTN-BZP` with no supplier yet.')]))
        with mock.patch('bom.ai.actions.download_image', return_value=None):
            html = self.send('Make an M8 x 20 button bolt').content.decode()

        thread = AIThread.objects.get()
        self.assertEqual(thread.title, 'Make an M8 x 20 button bolt')
        self.assertEqual([m.role for m in thread.messages.all()], ['user', 'assistant', 'user', 'assistant', 'user', 'assistant'])
        part = Part.objects.get(reference='M8-20MM-BOLT-BTN-BZP')
        self.assertEqual(part.history.first().history_change_reason, 'Chat: Make an M8 x 20 button bolt - Bomnado AI')
        self.assertTrue(Feedback.objects.open_for(part).exists())
        job = thread.latest_job
        self.assertEqual((job.status, job.kind, job.outcome['touched'][0]['reference']), ('done', 'chat', 'M8-20MM-BOLT-BTN-BZP'))
        self.assertEqual(job.input_tokens, 3000)

        # The window: the chips for what was called, the answer with the reference linked, the cost.
        self.assertIn('search_parts: M8', html)
        self.assertIn('is-write" title="create_part">create_part: M8-20MM-BOLT-BTN-BZP', html)
        self.assertIn(f'<a target="_blank" rel="noopener" class="bomlink part" href="/part/{part.id}">M8-20MM-BOLT-BTN-BZP</a> '
                      'with no supplier yet', html)
        self.assertIn(f'data-touched="part:{part.id} "', html)
        self.assertNotIn('hx-trigger="every 1s"', html)

        # What the model was told and given.
        first = create.call_args_list[0].kwargs
        self.assertIn('Bomnado conventions', first['system'][0]['text'])
        self.assertIn('Naming guide', first['system'][0]['text'])
        self.assertIn('M8-NUT-BZP', first['system'][0]['text'])  # an existing reference to copy
        self.assertEqual([t['name'] for t in first['tools']][-2:], ['web_search', 'web_fetch'])
        self.assertIn('create_part', [t['name'] for t in first['tools']])
        self.assertEqual(first['messages'][0]['content'][-1],
                         {'type': 'text', 'text': 'Make an M8 x 20 button bolt', 'cache_control': {'type': 'ephemeral'}})
        second = create.call_args_list[1].kwargs['messages']
        self.assertEqual(second[1]['role'], 'assistant')
        self.assertEqual(second[2]['content'][0]['type'], 'tool_result')
        self.assertIn('M8-NUT-BZP', second[2]['content'][0]['content'])  # search result text

    def test_the_page_is_context_and_this_means_it(self):
        create = self.mock_claude(response([text_block('Done.')]))
        self.send('Make it black', context=f'part:{self.nut.id}')
        thread = AIThread.objects.get()
        self.assertEqual(thread.context, {'kind': 'part', 'id': self.nut.id, 'reference': 'M8-NUT-BZP'})
        self.assertEqual(thread.team, self.team)
        system = create.call_args.kwargs['system']
        self.assertIn('The page the person is looking at', system[1]['text'])
        self.assertIn('"reference": "M8-NUT-BZP"', system[1]['text'])
        # The message itself says where it was sent from, so later turns still know.
        sent = create.call_args.kwargs['messages'][0]['content']
        self.assertEqual(sent[0]['text'], f'(Sent from the page of part `M8-NUT-BZP` - /part/{self.nut.id}. "This" means that record.)')
        self.assertEqual(sent[1]['text'], 'Make it black')
        self.assertEqual(sent[-1]['cache_control'], {'type': 'ephemeral'})
        html = self.client.get(reverse('bom:ai_chat') + f'?context=part:{self.nut.id}').content.decode()
        self.assertIn('&#8627; M8-NUT-BZP', html)  # the composer shows what "this" means
        # Someone else's record is not context; and a page with no record clears it.
        other = PartFactory(team=TeamFactory(), picture=None)
        create = self.mock_claude(response([text_block('Done.')]))
        self.send('And this?', thread=thread, context=f'part:{other.id}')
        self.assertEqual(AIThread.objects.get().context, {})
        self.assertIn('Not a particular part or assembly right now', create.call_args.kwargs['system'][1]['text'])
        self.assertIn('not about a particular record', create.call_args.kwargs['messages'][-1]['content'][0]['text'])

    def test_files_are_kept_on_the_thread_and_sent_as_blocks(self):
        create = self.mock_claude(response([text_block('A red square.')]))
        with io.BytesIO() as buffer:
            Image.new('RGB', (4, 4), 'red').save(buffer, format='PNG')
            png = buffer.getvalue()
        html = self.send('What is this?', files=SimpleUploadedFile('square.png', png, content_type='image/png')).content.decode()
        thread = AIThread.objects.get()
        attachment = Attachment.objects.attachments_for_object(thread).get()
        self.assertEqual(thread.messages.first().content[1], chat.file_placeholder(attachment))
        sent = create.call_args.kwargs['messages'][0]['content']
        self.assertEqual([b['type'] for b in sent], ['text', 'text', 'image', 'text'])
        self.assertIn('# Files in this conversation', create.call_args.kwargs['system'][-1]['text'])
        self.assertIn('&#128206; square.png', html)

    def test_failures_show_with_try_again_and_retry_replaces_the_failed_turn(self):
        import anthropic
        create = self.mock_claude(anthropic.APIConnectionError(request=mock.Mock()))
        html = self.send('Hello').content.decode()
        self.assertIn('Could not reach the AI provider', html)
        self.assertIn('Try again', html)
        thread = AIThread.objects.get()
        self.assertEqual(thread.messages.count(), 2)  # the question and the empty answer
        create.side_effect = [response([text_block('Hi.')])]
        html = self.client.post(reverse('bom:ai_chat_retry', kwargs={'thread_id': thread.id})).content.decode()
        self.assertIn('Hi.', html)
        self.assertEqual([m.role for m in thread.messages.all()], ['user', 'assistant'])
        self.assertEqual(AIJob.objects.filter(status='failed').count(), 1)

    def test_a_refusal_and_a_runaway_loop_end_the_turn(self):
        self.mock_claude(response([text_block('No.')], 'refusal'))
        html = self.send('Do something bad').content.decode()
        self.assertIn('declined', html)
        self.mock_claude(*[response([tool_block('search_parts', {'query': 'x'})], 'tool_use')] * (chat.MAX_ROUNDS + 1))
        html = self.send('Loop forever').content.decode()
        self.assertIn('kept working without finishing', html)

    def test_budget_and_key_gate_the_composer(self):
        config = self.user.ai_settings
        config.monthly_budget = 1
        config.save()
        AIJob.objects.create(user=self.user, cost=2)
        html = self.client.get(reverse('bom:ai_chat')).content.decode()
        self.assertIn('raise the budget', html)
        self.assertIn('disabled', html)
        html = self.send('Hello').content.decode()
        self.assertIn('budget is used up', html)
        self.assertFalse(AIThread.objects.exists())


class ConversationTests(ChatTestCase):

    def test_api_messages_merge_roles_and_shorten_old_results(self):
        thread = AIThread.objects.create(user=self.user, team=self.team)
        AIMessage.objects.create(thread=thread, role='user', content=[{'type': 'text', 'text': 'a'}])
        AIMessage.objects.create(thread=thread, role='user', content=[{'type': 'tool_result', 'tool_use_id': 't', 'content': 'x' * 2000}])
        for index in range(chat.FRESH_MESSAGES):
            AIMessage.objects.create(thread=thread, role='assistant' if index % 2 == 0 else 'user',
                                     content=[{'type': 'text', 'text': str(index)}])
        messages = chat.api_messages(thread)
        self.assertEqual(messages[0]['role'], 'user')
        self.assertEqual(len(messages[0]['content']), 2)  # merged: text + shortened tool result
        self.assertTrue(messages[0]['content'][1]['content'].endswith('call the tool again if you need the rest)'))
        last = {'type': 'text', 'text': str(chat.FRESH_MESSAGES - 1), 'cache_control': {'type': 'ephemeral'}}
        self.assertEqual(messages[-1]['content'], [last])

    def test_window_opens_on_the_latest_conversation_or_a_fresh_one(self):
        html = self.client.get(reverse('bom:ai_chat')).content.decode()
        self.assertIn('data-thread-id=""', html)
        self.assertIn('I can look things up', html)
        self.assertIn('data-ai-prompt="Create a part from this link: "', html)
        html = self.client.get(reverse('bom:ai_chat') + f'?context=part:{self.nut.id}').content.decode()
        self.assertIn('Find other suppliers', html)
        self.assertIn('`M8-NUT-BZP`', html)
        thread = AIThread.objects.create(user=self.user, team=self.team, title='Bolts')
        AIMessage.objects.create(thread=thread, role='user', content=[{'type': 'text', 'text': 'hi'}])
        html = self.client.get(reverse('bom:ai_chat')).content.decode()
        self.assertIn(f'data-thread-id="{thread.id}" data-title="Bolts"', html)
        html = self.client.get(reverse('bom:ai_chat') + '?thread=new').content.decode()
        self.assertIn('data-thread-id=""', html)
        html = self.client.get(reverse('bom:ai_chat_threads')).content.decode()
        self.assertIn(f'data-ai-thread="{thread.id}"', html)
        self.client.post(reverse('bom:ai_chat_delete', kwargs={'thread_id': thread.id}))
        self.assertFalse(AIThread.objects.exists())

    def test_conversations_are_private(self):
        thread = AIThread.objects.create(user=User.objects.create_user('bob', 'bob@example.com', 'pw'))
        for name in ('ai_chat_status', 'ai_chat_stop', 'ai_chat_retry', 'ai_chat_delete'):
            url = reverse(f'bom:{name}', kwargs={'thread_id': thread.id})
            method = self.client.get if name == 'ai_chat_status' else self.client.post
            self.assertEqual(method(url).status_code, 403, name)
        self.assertNotIn('data-thread-id="%d"' % thread.id, self.client.get(reverse('bom:ai_chat') + f'?thread={thread.id}').content.decode())

    def test_stop_while_running(self):
        thread = AIThread.objects.create(user=self.user, team=self.team, title='Slow')
        job = AIJob.objects.create(user=self.user, content_object=thread)
        job.mark_running()
        html = self.client.get(reverse('bom:ai_chat_status', kwargs={'thread_id': thread.id})).content.decode()
        self.assertIn('hx-trigger="every 1s"', html)
        self.assertIn('Stop', html)
        # The poll swaps the messages only: the composer must not come back with them (it duplicated).
        self.assertNotIn('aiChatComposer', html)
        self.assertTrue(html.lstrip().startswith('<div id="aiChatMessages"'))
        stopped = self.client.post(reverse('bom:ai_chat_stop', kwargs={'thread_id': thread.id})).content.decode()
        self.assertNotIn('aiChatComposer', stopped)
        self.assertIn('Wait for the current answer', self.send('more', thread=thread).content.decode())
        self.client.post(reverse('bom:ai_chat_stop', kwargs={'thread_id': thread.id}))
        self.assertTrue(AIJob.objects.get(pk=job.pk).cancel_requested)

    def test_helpers(self):
        self.assertEqual(chat.tool_summary('search_parts', {'query': 'M8 nut'}), 'search_parts: M8 nut')
        self.assertEqual(chat.tool_summary('get_history', {'record': 'part:3', 'limit': 5}), 'get_history: part:3')
        self.assertEqual(chat.progress_for(tool_block('get_part', {'part': 'X'})), 'get_part: X')
        search = mock.Mock(type='server_tool_use', input={'query': 'm8 bolt'})
        search.name = 'web_search'
        self.assertEqual(chat.progress_for(search), 'Searching the web for "m8 bolt"')
        self.assertEqual(chat.serialisable([text_block('hi'), tool_block('t', {'a': 1})]),
                         [{'type': 'text', 'text': 'hi'}, {'type': 'tool_use', 'id': 'toolu_1', 'name': 't', 'input': {'a': 1}}])
