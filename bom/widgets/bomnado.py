# bomnado widgets
import datetime

from django.forms.widgets import Input
from django.forms import Select
from django.utils import formats


class BootstrapInput(Input):
    input_type = 'text'
    template_name = 'widgets/inputgroup.html'

    def __init__(self, attrs=None, **kwargs):
        default_attrs = {}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)
        self.custom = kwargs

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['type'] = self.input_type
        context['widget']['custom'] = self.custom
        return context


class BootstrapInputGroup(BootstrapInput):
    input_type = 'text'
    template_name = 'widgets/inputgroup.html'


class BootstrapURL(BootstrapInputGroup):
    input_type = 'url'


class BootstrapText(BootstrapInputGroup):
    input_type = 'text'


class BootstrapNumber(BootstrapInputGroup):
    input_type = 'number'


class BootstrapDate(BootstrapInputGroup):
    format_key = 'DATE_INPUT_FORMATS'
    input_type = 'date'

    def format_value(self, value):
        """
        Format the datetime value to a valid HTML5 date input format (YYYY-MM-DD)
        """
        if value is None:
            return ''

        # If it's a date or datetime, convert it to YYYY-MM-DD string format
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.strftime('%Y-%m-%d')

        # Otherwise use Django's default formatting
        return formats.localize_input(value, formats.get_format(self.format_key)[0])


class BootstrapPrice(BootstrapText):
    def __init__(self, attrs=None, **kwargs):
        if 'prepend' not in kwargs:
            kwargs['prepend'] = '£'
        if 'append' not in kwargs:
            kwargs['append'] = 'ex VAT'
        if 'placeholder' not in kwargs:
            kwargs['placeholder'] = '0.00'
        super().__init__(attrs, **kwargs)


class BootstrapPastePicture(BootstrapInputGroup):
    input_type = 'file'
    needs_multipart_form = True
    template_name = 'widgets/pastepicture.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        # Check if value has a URL attribute
        if value and hasattr(value, 'url'):
            context['widget']['url_value'] = value.url
        elif hasattr(value, 'instance') and hasattr(value.instance, 'picture_url'):
            # Use the picture_url property if it exists
            context['widget']['url_value'] = value.instance.picture_url
        else:
            # Default to part placeholder
            from django.templatetags.static import static
            context['widget']['url_value'] = static('assets/placeholders/part_placeholder.svg')

        return context

    def format_value(self, value):
        """File input never renders a value."""
        return

    def value_from_datadict(self, data, files, name):
        "File widgets take data from FILES, not POST"
        return files.get(name)

    def value_omitted_from_data(self, data, files, name):
        return name not in files

    def use_required_attribute(self, initial):
        return super().use_required_attribute(initial) and not initial


class BootstrapTinyPicture(BootstrapPastePicture):
    """ A compact picture input for table rows: a small thumbnail that is clicked to
    browse (or focused and pasted into). Shows a placeholder glyph rather than an
    inherited picture when the instance has none of its own. """
    template_name = 'widgets/tinypicture.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['widget']['url_value'] = value.url if value and hasattr(value, 'url') else None
        return context


class BootstrapSelector(BootstrapInputGroup):
    input_type = 'select'  # not used
    template_name = 'widgets/selector.html'


class BootstrapMarkdownEditor(BootstrapInputGroup):
    input_type = 'select'  # not used
    template_name = 'widgets/markdown.html'


class BootstrapModelSelector(Select):
    template_name = 'widgets/modelselector.html'
