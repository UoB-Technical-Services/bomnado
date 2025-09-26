"""
Parse part data from Shop4Fasteners
https://shop4fasteners.co.uk/

Written in 2020
"""

import re
from .base import BaseScrape, currency


def fastener_m_size_from_name(title):
    """ Try to work out the metric size of a part. """
    try:
        return re.findall(r'[m|M]\d+', title)[0]
    except Exception:
        return 'M???'


class Shop4Scrape(BaseScrape):

    def clean_url(self):
        m = re.search(r'http.+\/id\/\w+\/', self.url)
        return m.group(0) if m else ""

    def partcode(self):
        return self.first('.sku span.value')

    def manufacturer_shipping(self):
        return 7.14

    def manufacturer_minimum_order(self):
        pack = self.first('.product-primary-column .pack-price-size')
        numbers = re.findall(r'\d+', pack)
        return int(numbers[0])

    def manufacturer_rrp(self):
        price = currency(self.first('.product-primary-column .price-box span.price'))
        pack_size = self.manufacturer_minimum_order()
        return currency(price / float(pack_size))

    def manufacturer_lead_time(self):
        """ Typical lead time. """
        return 5

    def picture(self):
        img = self.first('#zoom-btn', text_strip=False)
        return img['href']

    def spec(self):
        div = self.first('#product-tabs', text_strip=False)
        return div.text

    def nature(self):
        """ Standard. """
        return 'S'

    def colour(self):
        name = self.name().lower()
        if 'bzp' in name:
            return 'BZP'
        if 'black' in name:
            return 'Black'
        if 'self colour' in name:
            return 'Black'
        return ''

    def dimensions(self):
        return ''

    def kgs(self):
        return 0

    def name(self):
        return self.first('h1.simple-product-name')

    def reference(self):
        name = self.name().lower()
        colour = self.colour()
        if not colour:
            colour = '?COLOUR?'

        # If it is a washer.
        if 'washer' in name:
            m_size = fastener_m_size_from_name(name)
            form = '?FORM?'
            if 'form a' in name:
                form = 'FA'
            if 'form b' in name:
                form = 'FB'
            if 'repair' in name or 'penny' in name:
                form = 'LARGE'
                m_diameter = re.findall(r'x\s(\d+mm)', name)[0]
                if m_diameter:
                    form += f'-{m_diameter}'
            return f'{m_size}-WASHER-{form}-{colour}'.upper()

        # If it is a bolt.
        if 'bolt' in name or 'screw' in name:
            m_size = fastener_m_size_from_name(name)
            m_length = re.findall(r'x\s(\d+mm)', name)[0]
            f_type = '?TYPE?'
            if 'button' in name:
                f_type = 'BTN'
            if 'hex' in name:
                f_type = 'HEX'
            if 'round' in name:
                f_type = 'RND'
            if 'countersunk' in name:
                f_type = 'CSNK'
            return f'{m_size}-{m_length}-BOLT-{f_type}-{colour}'.upper()

        # If it is a NUT
        if 'nut' in name:
            m_size = fastener_m_size_from_name(name)
            return f'{m_size}-NUT-{colour}'.upper()

        # Otherwise, use the manufacturer reference.
        return self.partcode()


if __name__ == '__main__':
    print("TESTING")
    URL = 'https://shop4fasteners.co.uk/catalog/product/view/id/96878/s/socket-head-csk-screws-self-colour-m3-x-12mm/' \
          'category/4789/'

    scrape = Shop4Scrape(URL)
    print("manufacturer_url:", scrape.manufacturer_url())
    print("manufacturer_lead_time:", scrape.manufacturer_lead_time())
    print("manufacturer_minimum_order:", scrape.manufacturer_minimum_order())
    print("manufacturer_shipping:", scrape.manufacturer_shipping())
    print("manufacturer_rrp:", scrape.manufacturer_rrp())
    print("partcode:", scrape.partcode())

    print("picture:", scrape.picture())
    print("nature:", scrape.nature())
    print("colour:", scrape.colour())
    print("dimensions:", scrape.dimensions())
    print("weight_kg:", scrape.kgs())
    print("name:", scrape.name())
    print("reference:", scrape.reference())
