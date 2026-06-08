#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Project: entero_test

import re

from pyspider.libs.base_handler import *


class Handler(BaseHandler):
    crawl_config = {
        'itag': 'entero-test-v1',
        'headers': {
            'User-Agent': 'Mozilla/5.0 pyspider-entero-test/1.0',
        },
    }

    test_urls = [
        'https://entero.ru/item/91991',
        'https://entero.ru/item/217400',
        'https://entero.ru/item/97529',
    ]

    @every(minutes=24 * 60)
    def on_start(self):
        for url in self.test_urls:
            self.crawl(url, callback=self.detail_page, save={'kind': 'entero_test'})

    def detail_page(self, response):
        doc = response.doc
        name = doc('h1[itemprop="name"], h1').eq(0).text().strip()
        sku = doc('[itemprop="sku"]').eq(0).text().strip()
        price = doc('[itemprop="price"]').eq(0).attr('content') or ''
        if not price:
            price = self._first_price(doc('.price span, .product-current-price').eq(0).text())

        characteristics = []
        for row in doc('table.ch tr').items():
            key = row('td.name').text().strip()
            value = row('td.value').text().strip()
            key = re.sub(r':$', '', key)
            if key or value:
                characteristics.append({'name': key, 'value': value})

        images = []
        for image in doc('.product-card-gallery-image-container img.image, img[itemprop="image"]').items():
            src = image.attr('src')
            if src:
                if src.startswith('//'):
                    src = 'https:' + src
                images.append(src)

        categories = []
        for link in doc('.p-product > div > a').items():
            text = link.text().strip()
            if text:
                categories.append(text)

        description = doc('.htmlcontent[itemprop="description"], .htmlcontent').eq(0).text().strip()

        return {
            'url': response.url,
            'sku': sku,
            'name': name,
            'price': price,
            'description': description,
            'characteristics': characteristics,
            'images': images,
            'categories': categories,
        }

    def _first_price(self, value):
        value = value.replace('\u2009', ' ')
        match = re.search(r'[\d\s]+(?:[.,]\d+)?', value)
        if not match:
            return ''
        return re.sub(r'\s+', '', match.group(0))
