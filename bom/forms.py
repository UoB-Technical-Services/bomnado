from django import forms
from django.contrib.contenttypes.models import ContentType
from django.forms import HiddenInput, fields
from django.forms.models import ModelChoiceField, inlineformset_factory
from django.utils import timezone

from bom import models
from bom.utils import monotonic_id
from bom.widgets.bomnado import (BootstrapDate, BootstrapMarkdownEditor,
                                 BootstrapModelSelector, BootstrapNumber,
                                 BootstrapPastePicture, BootstrapPrice,
                                 BootstrapSelector, BootstrapText,
                                 BootstrapTinyPicture, BootstrapURL)


class SubAssemblyForm(forms.ModelForm):
    """
    Ensure data type consistency, particularly for date fields.
    This prevents issues where date fields might be sometimes strings, sometimes datetime objects.
    """
    deprecated = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=BootstrapDate(input_group_classes='input-group-sm'),
    )

    def clean_deprecated(self):
        dt = self.cleaned_data.get("deprecated")
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        return dt

    class Meta:
        model = models.SubAssembly
        fields = [
            'reference', 'name', 'sale_code', 'hs_code', 'picture', 'revision',
            'is_toplevel', 'instructions', 'qc_steps', 'deprecated', 'spec',
            'production_phase', 'shared', 'review_notes'
        ]
        widgets = {
            'reference': BootstrapText(
                placeholder='ASSEMBLY-REFERENCE',
                input_group_classes='input-group-sm'
            ),
            'name': BootstrapText(
                placeholder='Assembly Name',
                input_group_classes='input-group-sm'
            ),
            'sale_code': BootstrapText(
                placeholder='e.g. PROD-123',
                input_group_classes='input-group-sm'
            ),
            'hs_code': BootstrapText(
                placeholder='e.g. 7318163190',
                input_group_classes='input-group-sm'
            ),
            'revision': BootstrapText(
                placeholder='e.g. 1.0.0',
                input_group_classes='input-group-sm'
            ),
            'instructions': BootstrapMarkdownEditor(),
            'spec': BootstrapMarkdownEditor(),
            'qc_steps': BootstrapMarkdownEditor(),
            'review_notes': BootstrapMarkdownEditor(),
            'picture': BootstrapPastePicture(accept='image/*'),
            'is_toplevel': forms.HiddenInput(),
            'deprecated': BootstrapDate(input_group_classes='input-group-sm'),
            'production_phase': BootstrapText(placeholder='e.g. prebuild', input_group_classes='input-group-sm'),
            'shared': BootstrapSelector(items=[
                {'value': 'True', 'text': 'Yes'},
                {'value': 'False', 'text': 'No'}
            ], input_group_classes='input-group-sm'),
        }
        labels = {
            'reference': 'Assembly Reference',
            'name': 'Name',
            'sale_code': 'Sales Code',
            'hs_code': 'HS Code',
            'revision': 'Version',
            'spec': 'Specification',
            'instructions': 'Instructions',
            'qc_steps': 'Quality Control',
            'deprecated': 'Deprecated On',
            'production_phase': 'Production Phase',
            'shared': 'Shared Assembly',
            'review_notes': 'Comments and Feedback'
        }
        help_texts = {
            'reference': 'Abbreviated. Be consistent with others.',
            'name': 'Short and specific. For humans.',
            'sale_code': 'If set, the part is marked as "sellable" with this code.',
            'hs_code': 'The commodity export code for this assembly.',
            'picture': 'A clear and clean representation of the assembly.',
            'revision': 'Assembly version. Uses semantic versioning.',
            'spec': 'High level description of this assembly.',
            'instructions': 'Detailed part spec. Accepts markdown.',
            'qc_steps': 'Bullet point steps for carrying a quality check.',
            'deprecated': 'The date this part was deprecated. If not set, then it is not deprecated.',
            'production_phase': 'The phase of production that this assembly is created in. '
                                'Case sensitive. e.g. "prebuild"',
            'shared': 'A shared assembly can be used by multiple different projects within your team. A non-shared '
                      'assembly can only be used by the project that created it.',
            'review_notes': 'Improvement notices and tasks can be written here.'
        }


SubAssemblyItemFormset = inlineformset_factory(
    models.SubAssembly,
    models.SubAssemblyLineItem,
    fk_name='subassembly',
    extra=0,
    # TODO: Set the `queryset` property to limit the options in the select box
    fields=[
        'child_part',
        'child_subassembly',
        'quantity',
        'id',
        'notes'
    ],
    widgets={
        'quantity': BootstrapText(
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator',
            attrs={'min': 1}
        ),
        'notes': BootstrapText(input_group_classes='input-group-sm', placeholder=''),
        'child_part': forms.HiddenInput(),
        'child_subassembly': forms.HiddenInput()
    })


class PartCreationForm(forms.ModelForm):
    """
    Ensure data type consistency, particularly for date fields.
    This prevents issues where date fields might be sometimes strings, sometimes datetime objects.
    """
    deprecated = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=BootstrapDate(input_group_classes='input-group-sm'),
    )
    end_of_life = forms.DateTimeField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=BootstrapDate(input_group_classes='input-group-sm'),
    )

    def clean_deprecated(self):
        dt = self.cleaned_data.get("deprecated")
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        return dt

    def clean_end_of_life(self):
        dt = self.cleaned_data.get("end_of_life")
        if dt and timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.utc)
        return dt

    class Meta:
        model = models.Part
        fields = [
            'reference', 'name', 'manufacturer', 'kgs', 'dimensions', 'colour',
            'nature', 'spec', 'qc_steps', 'picture', 'sale_code', 'hs_code', 'end_of_life',
            'deprecated', 'review_notes'
        ]
        widgets = {
            'reference': BootstrapText(placeholder='PART-REFERENCE', input_group_classes='input-group-sm'),
            'name': BootstrapText(placeholder='Part Name', input_group_classes='input-group-sm'),
            'manufacturer': BootstrapText(placeholder='e.g. Texas Instruments', input_group_classes='input-group-sm'),
            'sale_code': BootstrapText(placeholder='e.g. PROD-123', input_group_classes='input-group-sm'),
            'hs_code': BootstrapText(placeholder='e.g. 7318163190', input_group_classes='input-group-sm'),
            'dimensions': BootstrapText(placeholder='L x W x H', input_group_classes='input-group-sm', append='mm'),
            'kgs': BootstrapText(
                placeholder='e.g. 10.00',
                input_group_classes='input-group-sm',
                input_el_classes='bomnado-calculator',
                append='kg'
            ),
            'colour': BootstrapText(placeholder='e.g. RAL7035', input_group_classes='input-group-sm'),
            'picture': BootstrapPastePicture(accept='image/*'),
            'end_of_life': BootstrapDate(input_group_classes='input-group-sm'),
            'deprecated': BootstrapDate(input_group_classes='input-group-sm'),
            'nature': BootstrapSelector(items=[
                {'value': 'S', 'text': 'Standard'},
                {'value': 'B', 'text': 'Bespoke'}
            ], input_group_classes='input-group-sm'),
            'spec': BootstrapMarkdownEditor(),
            'qc_steps': BootstrapMarkdownEditor(),
            'review_notes': BootstrapMarkdownEditor()
        }
        labels = {
            'reference': 'Part Reference',
            'name': 'Name',
            'manufacturer': 'Manufacturer',
            'dimensions': 'Dimensions',
            'kgs': 'Weight',
            'colour': 'Colour',
            'spec': 'Specification',
            'qc_steps': 'Quality Control',
            'sale_code': 'Sales Code',
            'hs_code': 'HS Code',
            'end_of_life': 'Expected EOL',
            'deprecated': 'Deprecated On',
            'review_notes': 'Comments and Feedback'
        }
        help_texts = {
            'reference': 'Abbreviated. Be consistent with others.',
            'name': 'Short and specific. For humans.',
            'manufacturer': 'Optional manufacturer name (e.g. ST, TI, Murata).',
            'kgs': 'Approximate weight per unit.',
            'dimensions': 'Approximate unpacked size (mm). Length x Width x Height.',
            'colour': 'Short description of physical appearance.',
            'nature': 'Custom made (bespoke) or off-the-shelf (standard).',
            'spec': 'Detailed part spec. Accepts markdown.',
            'qc_steps': 'Bullet point steps for carrying a quality check for incoming goods or when sold directly.',
            'picture': 'A clear and clean representation of the part.',
            'sale_code': 'If set, the part is marked as "sellable" with this code.',
            'hs_code': 'The commodity export code for this part.',
            'end_of_life': 'An optional estimated date that the product line will be retired end of life.',
            'deprecated': 'The date this part was deprecated. If not set, then it is not deprecated.',
            'review_notes': 'Improvement notices and tasks can be written here.'
        }


PartSourceFormset = inlineformset_factory(
    models.Part,
    models.PartSource,
    fields=[
        'partcode',
        'url',
        'rrp',
        'minimum_order',
        'shipping',
        'lead_time',
        'order_notes',
    ],
    widgets={
        'partcode': BootstrapText(
            placeholder='ABC-123',
            input_group_classes='input-group-sm'
        ),
        'rrp': BootstrapText(
            placeholder='0.00',
            prepend='£',
            append='ex VAT',
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator'
        ),
        'url': BootstrapURL(
            placeholder='https://....',
            input_group_classes='input-group-sm'
        ),
        'shipping': BootstrapPrice(
            placeholder='0.00',
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator'
        ),
        'lead_time': BootstrapNumber(
            append='days',
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator',
            attrs={'min': 1}
        ),
        'minimum_order': BootstrapNumber(
            append='units',
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator',
            attrs={'min': 1}
        ),
        'order_notes': BootstrapMarkdownEditor()
    },
    labels={
        'partcode': 'Part Code',
        'rrp': 'Unit Cost',
        'url': 'Supplier URL',
        'lead_time': 'Lead Time',
        'shipping': 'Shipping Cost',
        'minimum_order': 'Minimum Order Quantity',
        'order_notes': 'Order Notes'
    },
    help_texts={
        'partcode': 'The suppliers unique part code or reference.',
        'rrp': 'Typical selling price. Excludes VAT.',
        'url': 'Link to the supplier\'s part specification.',
        'shipping': 'Typical shipping cost. Excludes VAT.',
        'lead_time': 'Number of business days taken to arrive.',
        'minimum_order': 'The smallest number of units per single order. Eg. A box of 200 bolts.',
        'order_notes': 'Notes for the purchasing manager and important points for the supplier.'
    },
    extra=1
)


class BaseNamedPieceFormset(forms.models.BaseInlineFormSet):
    """ Django's cross-row uniqueness check only flags the *later* duplicates; flag the
    first one too so every offending row is highlighted on the page. """

    def validate_unique(self):
        try:
            super().validate_unique()  # raises when there are duplicates, having flagged the later rows
        finally:
            seen = {}
            for form in self.forms:
                if not hasattr(form, 'cleaned_data') or form.cleaned_data.get('DELETE'):
                    continue
                # Django strips the duplicated value from the later row's cleaned_data, hence the raw fallback.
                suffix = form.cleaned_data.get('suffix') or form.data.get(form.add_prefix('suffix'))
                if not suffix:
                    continue
                if suffix in seen and not seen[suffix].non_field_errors():
                    seen[suffix].add_error(None, self.get_form_error())
                seen.setdefault(suffix, form)


NamedPieceFormset = inlineformset_factory(
    models.Part,
    models.NamedPiece,
    formset=BaseNamedPieceFormset,
    fields=['suffix', 'note', 'picture'],
    widgets={
        # Rendered as `PARENT.` + suffix in one box (the view sets the prepend); the page
        # uppercases and strips illegal characters as the user types, the pattern backs that up.
        'suffix': BootstrapText(placeholder='SUFFIX', input_group_classes='input-group-sm bomnado-piece-reference',
                                attrs={'pattern': '[0-9A-Z-]*', 'autocapitalize': 'characters', 'spellcheck': 'false',
                                       'title': 'Uppercase letters, numbers and dashes only'}),
        'note': BootstrapText(placeholder='What this piece is (optional)', input_group_classes='input-group-sm'),
        'picture': BootstrapTinyPicture(accept='image/*'),
    },
    labels={
        'suffix': 'Suffix',
        'note': 'Note',
        'picture': 'Picture',
    },
    help_texts={
        'suffix': 'Referenced as PARENT.SUFFIX. Uppercase letters, numbers and dashes.',
        'note': 'A one-line description. Accepts references.',
        'picture': 'Optional. Falls back to the part picture.',
    },
    extra=1,
    can_delete=True,
)


class DealForm(forms.ModelForm):
    name = fields.CharField(widget=BootstrapText(placeholder='Deal Name', input_group_classes='input-group-sm'),
                            label='Name')
    rrp = fields.FloatField(
        widget=BootstrapText(placeholder='0.00', prepend='£', append='ex VAT', input_group_classes='input-group-sm',
                             input_el_classes='bomnado-calculator'), label='Unit Cost')
    url = fields.URLField(widget=BootstrapURL(placeholder='https://....', input_group_classes='input-group-sm'),
                          label='Supplier URL')
    shipping = fields.FloatField(widget=BootstrapPrice(placeholder='0.00', input_group_classes='input-group-sm',
                                                       input_el_classes='bomnado-calculator'), label='Shipping Cost')
    lead_time = fields.IntegerField(widget=BootstrapNumber(append='days', input_group_classes='input-group-sm',
                                                           input_el_classes='bomnado-calculator', attrs={'min': 1}),
                                    label='Lead Time')
    team = ModelChoiceField(widget=BootstrapModelSelector(), label='Team', queryset=models.Team.objects.all())
    project = ModelChoiceField(widget=BootstrapModelSelector(), label='Project',
                               queryset=models.SubAssembly.objects.filter(is_toplevel=True))
    order_notes = fields.CharField(widget=BootstrapMarkdownEditor(monotonic_id=monotonic_id), label='Order Notes')

    class Meta:
        model = models.Deal
        fields = ['id', 'name', 'rrp', 'shipping', 'lead_time', 'url', 'team', 'order_notes']


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = models.Attachment
        fields = ['attachment_file']

    def save(self, request, obj, *args, **kwargs):
        self.instance.content_type = ContentType.objects.get_for_model(obj)
        self.instance.object_id = obj.pk
        super(AttachmentForm, self).save(*args, **kwargs)


DealFormset = inlineformset_factory(
    models.Part,
    models.DealLineItem,
    fields=[
        'deal',
        'quantity',
        'notes',
    ],
    widgets={
        'deal': BootstrapModelSelector(),
        'quantity': BootstrapText(
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator',
            attrs={'min': 1}
        ),
        'notes': BootstrapMarkdownEditor()
    },
    labels={
        'deal': 'Part of Deal',
        'quantity': 'Quantity',
        'notes': 'Order Notes'
    },
    help_texts={
        'deal': 'The deal name.',
        'quantity': 'Number of parts in this deal.',
        'order_notes': 'Notes for the purchasing manager and important points for the supplier.'
    },
    extra=1
)

DealPartFormset = inlineformset_factory(
    models.Deal,
    models.DealLineItem,
    fields=[
        'id',
        'part',
        'quantity',
        'notes',
        'deal'
    ],
    widgets={
        'part': BootstrapModelSelector(),
        'quantity': BootstrapText(
            input_group_classes='input-group-sm',
            input_el_classes='bomnado-calculator',
            attrs={'min': 1}
        ),
        'notes': BootstrapText(),
        'deal': HiddenInput()
    },
    labels={
        'part': 'Part in Deal',
        'quantity': 'Quantity',
        'notes': 'Order Notes'
    },
    help_texts={
        'deal': 'The deal name.',
        'quantity': 'Number of parts in this deal.',
        'order_notes': 'Notes for the purchasing manager and important points for the supplier.'
    },
    extra=1
)


class UserAccountForm(forms.ModelForm):
    """ The details a user may change about their own account.

    Email is required and must be unique (ignoring case) because it is the
    login identifier - see `bom.auth.backends.EmailBackend`. The username is a
    display handle (team lists, menus) and must also be unique ignoring case.
    """
    username = fields.CharField(required=True, max_length=150, label='Username',
                                widget=forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
                                help_text='Internal short handle used by the admin site and command-line tools - '
                                          'other users see your email address. Letters, digits and @/./+/-/_ only.')
    first_name = fields.CharField(required=False, max_length=150, label='First name',
                                  widget=forms.TextInput(attrs={'class': 'form-control'}))
    last_name = fields.CharField(required=False, max_length=150, label='Last name',
                                 widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = fields.EmailField(required=True, label='Email address',
                              widget=forms.EmailInput(attrs={'class': 'form-control'}),
                              help_text='You sign in with this address.')

    class Meta:
        model = models.User
        fields = ['username', 'first_name', 'last_name', 'email']

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        others = models.User.objects.filter(username__iexact=username)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError('That username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email'].strip()
        others = models.User.objects.filter(email__iexact=email)
        if self.instance.pk:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise forms.ValidationError('That email address is already in use by another account.')
        return email
