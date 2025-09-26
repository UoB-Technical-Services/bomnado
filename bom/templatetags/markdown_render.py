import re
import os
from django.urls.base import reverse_lazy
from bom.models import Attachment, Part, SubAssembly
from marko.ext.gfm import gfm
from django import template
from bs4 import BeautifulSoup


register = template.Library()


@register.filter
def as_markdown(text, assembly_or_part):
    """ Render a text string using github flavoured markdown.
    https://github.github.com/gfm/

    :param text: The markdown text string.
    :param assembly_or_part: A relevant part/assembly with attachments.

    If `assembly_or_part` is specified then all relative file names are looked up
    and swapped out for file URLs if they match the name of an attachment.
    """
    # Find all `SUB_PARTS` mentioned in the text and try to add them as links.
    pattern = r'(?<!`)`{1,2}\b(?!`)(.*?)\b`+'
    for match in re.findall(pattern, text):
        query = match.strip()
        part = Part.objects.filter(reference=query).first()
        assembly = SubAssembly.objects.filter(reference=query).first()
        if part:
            url = reverse_lazy('bom:part_editor_update', kwargs={'pk': part.id})
            text = text.replace(f'`{match}`', f'<a class="bomlink part" href="{url}">{query}</a>')
        elif assembly:
            url = reverse_lazy('bom:assembly_editor_update', kwargs={'pk': assembly.id})
            text = text.replace(f'`{match}`', f'<a class="bomlink assembly" href="{url}">{query}</a>')

    # Convert the rest to HTML.
    html = gfm(text)

    # If we have no attachment, return the HTML as is.
    if not assembly_or_part:
        return html

    # Otherwise, we start rewriting all the links to files IF we have
    # a matching attachment.

    # Link rewriter helper.
    def _rewrite(address, attachments):
        """ Rewrite links for files that match named attachments. """
        # Hand early exists.
        if not address:
            return address
        if f'{address}'.lower().startswith('http'):
            return address

        # Find matching attachments.
        basename = os.path.basename(address)
        matching_attachents = [a for a in attachments if os.path.basename(a.attachment_file.url) == basename]

        # If we have one, rewrite the link.
        return matching_attachents[0].attachment_file.url if matching_attachents else address

    # Get all possible attachments.
    assy_attachments = [a for a in Attachment.objects.attachments_for_object(assembly_or_part)]

    # Rewrite all relative links to files.
    soup = BeautifulSoup(html, features='html5lib')
    for el in soup.findAll(href=True):
        el['href'] = _rewrite(el['href'], assy_attachments)
    for el in soup.findAll(src=True):
        el['src'] = _rewrite(el['src'], assy_attachments)

    # Remove disabled checkboxes.
    for el in soup.findAll(type='checkbox'):
        del el['disabled']

    return str(soup)
