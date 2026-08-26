from django.contrib.auth.models import User
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from bom.forms import SubAssemblyForm
from bom.models import SubAssembly
from bom.tests.factories import PartFactory, SubAssemblyFactory, TeamFactory
from bom.widgets.bomnado import BootstrapMarkdownEditor


class MarkdownWidgetRenderingTests(TestCase):

    def test_renders_hidden_textarea_with_value_and_editor_root(self):
        html = BootstrapMarkdownEditor().render('spec', 'Fit the `M8-NUT` **tight**.\n\n- step', attrs={'id': 'id_spec'})

        self.assertIn('<textarea', html)
        self.assertIn('name="spec"', html)
        self.assertIn('Fit the `M8-NUT` **tight**.', html)
        self.assertIn('class="bomnado-markdown-widget-editor', html)
        self.assertIn('new MarkdownField(', html)
        self.assertNotIn('ace', html.lower())

    def test_value_is_escaped_in_textarea(self):
        html = BootstrapMarkdownEditor().render('spec', '<script>alert(1)</script> & `A<B`', attrs={'id': 'id_spec'})
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt; &amp; `A&lt;B`', html)

    def test_vendored_assets_are_present(self):
        for asset in ('lib/toastui-editor-3.2.2/toastui-editor-all.min.js', 'lib/toastui-editor-3.2.2/toastui-editor.min.css',
                      'lib/expr-eval-2.0.2/expr-eval.min.js', 'app/markdown_widget.js', 'app/markdown_widget.css'):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset), asset)
        self.assertIsNone(finders.find('lib/ace-1.4.5/ace.js'))

    def test_widget_script_does_not_use_ace_or_eval(self):
        with open(finders.find('app/markdown_widget.js'), encoding='utf-8') as fh:
            widget_js = fh.read()
        with open(finders.find('app/inputgroup_widget.js'), encoding='utf-8') as fh:
            calculator_js = fh.read()
        self.assertNotIn('ace.edit', widget_js)
        self.assertIn('toastui.Editor', widget_js)
        self.assertIn('getMarkdown()', widget_js)
        self.assertNotIn('eval(', calculator_js.replace('evaluate(', ''))
        self.assertIn('exprEval.Parser', calculator_js)


class MarkdownEditorPageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='alice', email='alice@example.com', password='password123')
        self.team = TeamFactory(owner=self.user)
        self.team.users.add(self.user)
        self.client.force_login(self.user)

    def test_pages_load_toast_ui_and_expr_eval_instead_of_ace(self):
        assembly = SubAssemblyFactory(team=self.team, picture=None, is_toplevel=True)
        html = self.client.get(reverse('bom:assembly_editor_update', kwargs={'pk': assembly.id})).content.decode()

        # Counted rather than assertIn/NotIn so a failure does not dump the whole page.
        self.assertEqual(html.count('lib/toastui-editor-3.2.2/toastui-editor-all.min.js'), 1)
        self.assertEqual(html.count('lib/toastui-editor-3.2.2/toastui-editor.min.css'), 1)
        self.assertEqual(html.count('lib/expr-eval-2.0.2/expr-eval.min.js'), 1)
        self.assertEqual(html.count('ace.js'), 0)
        self.assertEqual(html.count('ace.edit('), 0)
        self.assertEqual(html.count("MarkdownField.forTextarea('instructions')"), 2)

    def test_part_editor_renders_markdown_widgets(self):
        part = PartFactory(team=self.team, picture=None, spec='Spec for `OTHER-PART`')
        html = self.client.get(reverse('bom:part_editor_update', kwargs={'pk': part.id})).content.decode()
        self.assertEqual(html.count('Spec for `OTHER-PART`'), 1)
        self.assertGreaterEqual(html.count('new MarkdownField('), 2)  # spec, qc_steps


class MarkdownRoundTripTests(TestCase):
    """ The form stores exactly the markdown the textarea submits, so reference renames
    (which rewrite the stored text) round-trip through the editor untouched. """

    def test_form_saves_submitted_markdown_verbatim(self):
        team = TeamFactory()
        assembly = SubAssemblyFactory(team=team, picture=None, is_toplevel=True, revision='1.0.0')
        # (No trailing newline: Django's CharField strips surrounding whitespace, as it always has.)
        markdown = "# Fit\n\n1. Take `M8-NUT` and *turn*\n   - sub `CHASSIS.TOP`\n\n```\ncode `not a ref`\n```"

        form = SubAssemblyForm({
            'reference': assembly.reference, 'name': assembly.name, 'revision': '1.0.0', 'is_toplevel': 'on',
            'instructions': markdown, 'qc_steps': '', 'spec': '', 'production_phase': '', 'review_notes': '',
            'sale_code': '', 'hs_code': '', 'deprecated': '',
        }, instance=assembly)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.assertEqual(SubAssembly.objects.get(pk=assembly.pk).instructions, markdown)

    def test_rename_rewrites_references_in_stored_markdown(self):
        team = TeamFactory()
        part = PartFactory(team=team, picture=None, reference='M8-NUT')
        assembly = SubAssemblyFactory(team=team, picture=None, is_toplevel=True,
                                      instructions='Fit `M8-NUT` twice: `M8-NUT`. Not `M8-NUT-LONG`.')

        part.reference = 'M8-NYLOC'
        part.save()

        assembly.refresh_from_db()
        self.assertEqual(assembly.instructions, 'Fit `M8-NYLOC` twice: `M8-NYLOC`. Not `M8-NUT-LONG`.')
