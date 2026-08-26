""" Fetching supplier pages on the user's behalf, without letting them point the server at itself.

`fetch_url` refuses anything that is not plain http(s) to a public address, follows redirects
one hop at a time re-checking each, caps size and time. `html_to_text` turns a page into the
compact text Claude reads: title, description, headings, paragraphs, tables and the pictures on it.
"""
import io
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from PIL import Image

MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 15
MAX_TEXT = 60_000  # characters handed to Claude
USER_AGENT = 'Mozilla/5.0 (compatible; Bomnado/1.0; +https://github.com/UoB-Technical-Services/bomnado)'


class UnsafeURL(ValueError):
    """ The URL must not be fetched from the server. """


class FetchError(RuntimeError):
    """ The page could not be fetched. """


def check_url(url):
    """ Raise `UnsafeURL` unless `url` is http(s) to a public host. Returns the parsed URL. """
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise UnsafeURL('Only http and https links can be read.')
    if parsed.username or parsed.password:
        raise UnsafeURL('Links with credentials in them are not read.')
    host = parsed.hostname
    if host == 'localhost' or host.endswith('.localhost') or host.endswith('.local'):
        raise UnsafeURL('That address is not public.')
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, parsed.port or 80, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        raise UnsafeURL('That address could not be found.')
    for address in addresses:
        ip = ipaddress.ip_address(address.split('%')[0])
        if not ip.is_global:
            raise UnsafeURL('That address is not public.')
    return parsed


def fetch_url(url, max_bytes=MAX_BYTES, timeout=TIMEOUT):
    """ GET a public page. Returns `(final_url, content_type, body_bytes)`.

    Each redirect is checked like the original, so a public URL cannot bounce the
    server onto a private one.
    """
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        try:
            response = requests.get(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'},
                                    timeout=timeout, allow_redirects=False, stream=True)
        except requests.RequestException as error:
            raise FetchError(f'Could not fetch the page: {error.__class__.__name__}')
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get('Location')
            response.close()
            if not location:
                raise FetchError('The page redirected nowhere.')
            url = urljoin(url, location)
            continue
        if response.status_code >= 400:
            response.close()
            raise FetchError(f'The page answered {response.status_code}.')
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > max_bytes:
                response.close()
                raise FetchError('The page is too large to read.')
        return url, response.headers.get('Content-Type', ''), bytes(body)
    raise FetchError('Too many redirects.')


def decode_body(body):
    """ Page bytes as text: UTF-8, else Latin-1 (the classic mis-served pound sign). """
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return body.decode('latin-1', errors='replace')


def html_to_text(html, base_url=''):
    """ A compact, readable rendering of a product page for Claude.

    Returns `(text, pictures)`: the page text (title, description, headings, paragraphs,
    list items and tables, in order, capped at `MAX_TEXT`), and the picture URLs found on
    it with their alt text / role (og:image first) so the model can pick the product photo.
    """
    # html.parser: an order of magnitude faster than html5lib on the multi-megabyte pages big retailers serve.
    soup = BeautifulSoup(html, features='html.parser')
    # Forms stay: retailers wrap the whole product view (price, pack size, photos) in the add-to-cart form.
    for tag in soup(['script', 'style', 'noscript', 'svg', 'iframe', 'template', 'nav', 'footer', 'header']):
        tag.decompose()

    lines = []
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    if title:
        lines.append(f'# {title}')
    for meta in soup.find_all('meta'):
        name = (meta.get('name') or meta.get('property') or '').lower()
        content = (meta.get('content') or '').strip()
        if content and name in ('description', 'og:description', 'og:title', 'product:price:amount',
                                'product:price:currency', 'og:site_name'):
            lines.append(f'{name}: {content}')

    pictures = []
    og_image = soup.find('meta', attrs={'property': 'og:image'})
    if og_image and og_image.get('content'):
        pictures.append({'url': urljoin(base_url, og_image['content']), 'alt': 'og:image'})

    body = soup.body or soup
    # The main content first: on menu-heavy shops the product block can sit hundreds of kilobytes in,
    # after a category tree that would otherwise use up the whole text budget.
    main = body.select_one('main, [role="main"], #maincontent, #content, .col-main, .product-view, .page-content')
    regions = [main, body] if main is not None else [body]
    walked = [element for region in regions
              for element in region.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'li', 'table', 'dt', 'dd', 'img', 'div'])]
    for element in walked:
        if element.name == 'div':
            # Only leaf divs: a price or "(Pack of 100)" often sits in a bare div no other walk visits.
            if element.find(['div', 'p', 'li', 'table', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'dl']) is not None:
                continue
        if element.name == 'img':
            src = _best_image_source(element)
            if src and len(pictures) < 40 and not any(p['url'] == urljoin(base_url, src) for p in pictures):
                pictures.append({'url': urljoin(base_url, src), 'alt': (element.get('alt') or '').strip()[:80]})
            continue
        if element.name == 'table':
            for row in element.find_all('tr'):
                cells = [cell.get_text(' ', strip=True) for cell in row.find_all(['th', 'td'])]
                if any(cells):
                    lines.append('| ' + ' | '.join(cells) + ' |')
            continue
        if element.find_parent('table'):
            continue  # already rendered as a row
        text = element.get_text(' ', strip=True)
        if not text:
            continue
        if element.name[0] == 'h':
            lines.append(f'{"#" * int(element.name[1])} {text}')
        elif element.name == 'li':
            lines.append(f'- {text}')
        else:
            lines.append(text)

    # Collapse runs of identical lines (menus repeat) and whitespace.
    seen = set()
    unique = []
    for line in lines:
        line = re.sub(r'\s+', ' ', line).strip()
        if line and line not in seen:
            seen.add(line)
            unique.append(line)
    text = '\n'.join(unique)
    return text[:MAX_TEXT], pictures


def _best_image_source(img):
    """ The largest real picture an <img> points at. Retailers hide the full-size image in
    `data-old-hires`, `data-a-dynamic-image` (a JSON map of url -> size) or a `srcset`. """
    dynamic = img.get('data-a-dynamic-image')
    if dynamic:
        try:
            sizes = json.loads(dynamic)
            if isinstance(sizes, dict) and sizes:
                return max(sizes, key=lambda url: (sizes[url] or [0])[0] if isinstance(sizes[url], list) else 0)
        except (ValueError, TypeError):
            pass
    hires = img.get('data-old-hires')
    if hires:
        return hires
    srcset = img.get('srcset') or img.get('data-srcset')
    if srcset:
        best, best_width = '', -1
        for candidate in srcset.split(','):
            bits = candidate.strip().split()
            if not bits:
                continue
            width = int(bits[1][:-1]) if len(bits) > 1 and bits[1][:-1].isdigit() else 0
            if width > best_width:
                best, best_width = bits[0], width
        if best:
            return best
    src = img.get('src') or img.get('data-src') or ''
    if not src or src.startswith('data:') or re.search(r'sprite|pixel|1x1|spacer|\.gif($|\?)', src, re.I):
        return ''
    return src


def download_image(url, max_bytes=8 * 1024 * 1024):
    """ Fetch a picture (safely) and hand it back as a PNG `ContentFile`, or None if it is not an image. """
    _, content_type, body = fetch_url(url, max_bytes=max_bytes)
    try:
        with Image.open(io.BytesIO(body)) as image:
            with io.BytesIO() as output:
                image.convert('RGBA').save(output, format='PNG')
                return ContentFile(output.getvalue())
    except (OSError, ValueError):
        return None


""" Currency amounts as they appear in page text: £4.20, $ 1,299.00, €0.042, 4.20 GBP. """
MONEY = re.compile(r'(?:[£$€]\s?\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?\s?(?:GBP|USD|EUR))')


def page_hints(html, text=''):
    """ What a product page says in its structured data, which the visible text often lacks or buries:
    prices (schema.org offers, price meta tags, then currency amounts seen in the text), the seller's
    SKU / part number, and availability. Best-effort: anything unparseable is skipped. """
    prices, skus, availability = [], [], []

    def offer(node):
        if not isinstance(node, dict):
            return
        price = node.get('price') or node.get('lowPrice') or (node.get('priceSpecification') or {}).get('price')
        if price not in (None, ''):
            prices.append(f'{price} {node.get("priceCurrency", "")}'.strip())
        if node.get('availability'):
            availability.append(str(node['availability']).split('/')[-1])

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key in ('sku', 'mpn', 'productID'):
                if node.get(key):
                    skus.append(f'{key}: {node[key]}')
            offers = node.get('offers')
            if isinstance(offers, list):
                for item in offers:
                    offer(item)
            elif offers:
                offer(offers)
            if 'offers' not in node and node.get('price') is not None:
                offer(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)

    for script in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE):
        try:
            walk(json.loads(script.strip()))
        except ValueError:
            continue
    for name in ('product:price:amount', 'og:price:amount', 'twitter:data1'):
        for value in re.findall(r'<meta[^>]+(?:property|name)=["\']' + re.escape(name) + r'["\'][^>]+content=["\']([^"\']+)', html, re.IGNORECASE):
            prices.append(value.strip())
    for value in re.findall(r'itemprop=["\']price["\'][^>]*content=["\']([^"\']+)', html, re.IGNORECASE):
        prices.append(value.strip())
    for value in re.findall(r'itemprop=["\']sku["\'][^>]*content=["\']([^"\']+)', html, re.IGNORECASE):
        skus.append(f'sku: {value.strip()}')
    seen_in_text = MONEY.findall(text or '')
    return {'prices': _unique(prices)[:10], 'prices_in_text': _unique(seen_in_text)[:12], 'part_numbers': _unique(skus)[:6],
            'availability': _unique(availability)[:3]}


def _unique(values):
    out = []
    for value in values:
        value = str(value).strip()
        if value and value not in out:
            out.append(value)
    return out
