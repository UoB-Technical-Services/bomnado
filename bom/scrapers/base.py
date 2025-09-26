import locale
import random

import requests
from bs4 import BeautifulSoup

HEADERS = [
    {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36'},
]


def get_html(url):
    headers = random.choice(HEADERS)
    response = requests.get(url, headers=headers)
    return response.text


def currency(s):
    val = locale.atof(str(s).strip().replace('£', ''))
    return float(val)


class BaseScrape:

    def __init__(self, url):
        self.url = url

        # Load cached scraper.
        self.src = get_html(url)

        # Debug scraper.
        with open("scrape.html", "w", encoding='utf8') as text_file:
            text_file.write(self.src)
        self.html = BeautifulSoup(self.src, features='html5lib')

    def first(self, selector, text_strip=True, allow_null=True, allow_multi=False):
        options = self.html.select(selector)
        if len(options) == 0 and allow_null:
            return ''

        if len(options) >= 1 and allow_multi:
            if text_strip:
                return options[0].text.strip()
            return options[0]

        if len(options) == 1:
            if text_strip:
                return options[0].text.strip()
            return options[0]

        print(f"!! {len(options)} options !!")
        print(options)
        raise ValueError

    def clean_url(self):
        return self.url

    def reference(self):
        return ''

    def name(self):
        return ''

    def kgs(self):
        return 0

    def dimensions(self):
        return ''

    def colour(self):
        return ''

    def nature(self):
        return ''

    def spec(self):
        return ''

    def picture(self):
        return ''

    def partcode(self):
        return ''

    def manufacturer_rrp(self):
        return 0

    def manufacturer_shipping(self):
        return 0

    def manufacturer_minimum_order(self):
        return 1

    def manufacturer_lead_time(self):
        return 5

    def manufacturer_url(self):
        return self.clean_url()


def find_colours_in_string(input_string):
    colours = [
        'RAL7035', 'RAL7037', 'RAL9011', 'bzp', 'zinc', 'black', 'white', 'nylon', 'aqua', 'blue', 'fuchsia',
        'green', 'gray', 'self colour', 'lime', 'maroon', 'navy', 'olive', 'purple', 'red', 'silver', 'teal', 'white',
        'yellow'
    ]
    colours = [colour for colour in colours if colour.casefold() in input_string.casefold()]

    def _tx(colour):
        if colour == 'bzp':
            return 'BZP'
        if colour.startswith('RAL'):
            return colour.capitalize()
        if 'self colour' == colour:
            return 'Self Colour'
        return colour.capitalize()

    colours = [_tx(colour) for colour in colours]
    return ', '.join(colours)
