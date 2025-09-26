"""
Parse part data from RS Online
https://uk.rs-online.com/

Written in 2020
"""

import re

from .base import BaseScrape, currency


class RSScrape(BaseScrape):

    def clean_url(self):
        return self.url

    def partcode(self):
        return self.first('ul > li:nth-child(1) span.keyValue')

    def manufacturer_shipping(self):
        """ Free delivery as standard. """
        return 0

    def manufacturer_minimum_order(self):
        return 1

    def manufacturer_rrp(self):
        price = self.first('.price.txt-vat')
        if price:
            return currency(price)

        price = self.first('.price', allow_multi=True)
        if price:
            return currency(price)
        return 0

    def manufacturer_lead_time(self):
        """ Typical next working day. """
        return 3

    def picture(self):
        # Try to pull it out of some injected JS.
        script = self.first('div#image-carousel')
        regex = r"largeImageURL:\s\"(.+)\""
        url = re.search(regex, script)
        if url:
            url = url.group(1)

        # Otherwise see if we have a mainImage
        else:
            url = self.first('img#mainImage', text_strip=False)['src']

        # Sort out strange formatting.
        url = url.replace("//", 'https://')
        return url

    def spec(self):
        div = self.first('.prodDetailsContainer', text_strip=False)
        return div.text

    def nature(self):
        """ Standard. """
        return 'S'

    def colour(self):
        return ''

    def dimensions(self):
        return ''

    def kgs(self):
        return 0

    def name(self):
        return self.first('h1')

    def reference(self):
        return self.partcode()


if __name__ == '__main__':
    print("TESTING")
    URL = 'https://uk.rs-online.com/web/p/products/1822096/'

    scrape = RSScrape(URL)
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
