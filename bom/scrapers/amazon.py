"""
Parse part data from Amazon
https://amazon.co.uk/

Written in 2020
"""

import re
from .base import BaseScrape, currency, find_colours_in_string


class AmazonScrape(BaseScrape):

    def asin(self):
        m = re.search(r'(?:dp|o|gp|product|-)\/(B[0-9]{2}[0-9A-Z]{7}|[0-9]{9}(?:X|[0-9]))', self.url)
        return m.group(1) if m else ""

    def clean_url(self):
        return f'https://www.amazon.co.uk/dp/{self.asin()}/'

    def partcode(self):
        return self.asin()

    def manufacturer_shipping(self):
        """ Free delivery as standard. """
        _ = self.first('#ourprice_shippingmessage')
        return 0

    def manufacturer_minimum_order(self):
        pack_dimensions = re.findall(r'(\d+\.?\d*\s?)(pack|pieces|pcs)', self.name().lower())
        for match in pack_dimensions:
            return int(match[0])
        return 1

    def manufacturer_rrp(self):
        price = self.first('#priceblock_ourprice', allow_null=True)
        if price:
            price = currency(price)
            return price

        price = self.first('.priceBlockStrikePriceString', allow_null=True)
        if price:
            price = currency(price)
            return price

        price = self.first('#priceblock_saleprice', allow_null=True)
        if price:
            price = currency(price)
            return price
        return 0

    def manufacturer_lead_time(self):
        """ Typical next working day. """
        return 3

    def picture(self):
        img = self.first('#imgTagWrapperId img', text_strip=False, allow_null=True)
        if not img:
            return ''

        url = img.get('data-old-hires')
        if url and url.startswith('http'):
            return url

        url = img.get('src').strip()
        if url and (url.startswith('http') or url.startswith('data:image')):
            return url
        return ''

    def spec(self):
        div = self.first('#feature-bullets', text_strip=False)
        return div.text.strip() if div else ''

    def nature(self):
        """ Standard. """
        return 'S'

    def colour(self):
        return find_colours_in_string(self.name())

    def dimensions(self):

        # Convert a size from CM to MM.
        def _units(string):
            string = string.strip().lower()
            if string.endswith('cm'):
                string = string.replace('cm', '')
                items = [float(d) for d in string.split('x')]
                items = [str(d * 10) for d in items]
                return ' x '.join(items)
            return string

        # Try to find the .size-weight tr for "Product Dimensions"
        for row in self.html.select('.size-weight'):
            if 'dimensions' not in row.text.lower():
                continue
            for cell in row.select('td.value'):
                return _units(cell.text)
        return ''

    def kgs(self):
        row = self.first('tr.shipping-weight', text_strip=False, allow_null=True)
        if not row:
            return 0

        weight_g = re.findall(r'(\d+\.?\d*\s?)(g|G)', row.text)
        if weight_g:
            return float(weight_g[0][0]) * 0.001

        weight_kg = re.findall(r'(\d+\.?\d*\s?)(kg|kgs|KG|KGS|Kg)', row.text)
        if weight_kg:
            return float(weight_kg[0][0])

        return 0

    def name(self):
        return self.first('span#productTitle')

    def reference(self):
        return self.partcode()


if __name__ == '__main__':
    print("TESTING")
    URL = 'https://www.amazon.co.uk/dp/0904406024'

    scrape = AmazonScrape(URL)
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
