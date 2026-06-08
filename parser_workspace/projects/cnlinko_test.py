#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Project: cnlinko_test

import datetime
import hashlib
import json
import os
import re
import ssl
import urllib.request
from copy import deepcopy
from html import unescape
from urllib.parse import quote, urljoin, urlparse

from lxml.html.clean import Cleaner
from pyspider.libs.base_handler import *


def env(name, default=''):
    return os.environ.get(name, default)


DONOR = 'cnlinko'
GROUP = 'connectors'
DOWNLOAD_DIR = env('PARSER_DOWNLOAD_DIR', './data/download')
PUBLIC_UPLOAD_DIR = env('PARSER_PUBLIC_UPLOAD_DIR', '/upload/spider')


def absolute_url(base_url, url):
    if not url:
        return ''
    url = url.strip()
    if url.startswith('//'):
        return 'https:' + url
    return urljoin(base_url, url)


def compact_text(value):
    value = unescape(value or '')
    value = re.sub(r'\s+', ' ', value)
    return value.strip()


def clean_name(value):
    value = compact_text(value)
    value = re.sub(r'\s+Copy$', '', value)
    value = re.sub(r'^Part Number\s*:\s*', '', value, flags=re.I)
    return value.strip()


def is_asset_url(url):
    if not url:
        return False
    if url.startswith(('javascript:', 'mailto:', 'tel:', '#')):
        return False
    return True


def download_asset(base_url, url, donor=DONOR, kind='images'):
    url = absolute_url(base_url, url)
    if not is_asset_url(url):
        return ''

    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    ext = ext or '.html'
    digest = hashlib.sha1(url.encode('utf8')).hexdigest()
    filename = digest + ext.lower()

    local_dir = os.path.join(DOWNLOAD_DIR, donor, kind)
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)

    local_path = os.path.join(local_dir, filename)
    if not os.path.exists(local_path):
        request = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 pyspider-cnlinko-test/1.0',
                'Referer': base_url,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30, context=ssl._create_unverified_context()) as response:
                with open(local_path, 'wb') as fp:
                    fp.write(response.read())
        except Exception as exc:
            print('asset download failed: %s (%s)' % (url, exc))
            return ''

    return '/'.join([PUBLIC_UPLOAD_DIR.rstrip('/'), donor, kind, filename])


class Handler(BaseHandler):
    crawl_config = {
        'itag': 'cnlinko-test-v1',
        'headers': {
            'User-Agent': 'Mozilla/5.0 pyspider-cnlinko-test/1.0',
        },
    }
    if env('PARSER_PROXY'):
        crawl_config['proxy'] = env('PARSER_PROXY')

    cleaner = Cleaner(
        javascript=True,
        comments=True,
        style=True,
        links=True,
        safe_attrs_only=True,
        safe_attrs=frozenset(['src', 'alt', 'title', 'class']),
        remove_tags=['a'],
    )

    test_urls = [
        'https://www.cnlinko.com/products/connectors/lp-20-14-pin-ip68-waterproof-connector-with-snap-ring-shield.html',
    ]
    test_limit = int(env('PARSER_TEST_LIMIT', '5') or '5')

    @every(minutes=24 * 60)
    def on_start(self):
        for url in self.test_urls:
            self.crawl(url, callback=self.series_page, save={'tree': ['Products', 'Connectors']}, validate_cert=False)

    @config(age=0, priority=2)
    def series_page(self, response):
        common = self.parse_common(response)
        products = self.parse_products(response, common)

        for product in products[:self.test_limit]:
            taskid = 'cnlinko:' + product['model']
            url = 'data:,' + quote(product['model'])
            self.crawl(
                url,
                taskid=taskid,
                callback=self.detail_page,
                save={'product': product},
                validate_cert=False,
            )

    @config(age=0, priority=3)
    def detail_page(self, response):
        product = response.save.get('product') or {}
        product['dateUp'] = datetime.datetime.utcnow().isoformat()
        return product

    def parse_common(self, response):
        doc = response.doc
        page_title = compact_text(doc('h1').eq(0).text())
        categories = self.extract_categories(response)

        characteristics = []
        for item in doc('.product-d2-page2 .wrap-left > .list > .item').items():
            if 'display: none' in (item.attr('style') or ''):
                continue
            name = compact_text(item('.title').eq(0).text())
            value = compact_text(item('.text-body').eq(0).text())
            if name and value:
                characteristics.append({'name': name, 'value': value})

        for block in doc('.product-d2-page2 .add-permission-item').items():
            name = compact_text(block('.title').eq(0).text()).rstrip(':')
            values = [compact_text(x.text()) for x in block('.item span').items()]
            values = [x for x in values if x]
            if name and values:
                characteristics.append({'name': name, 'value': values})

        for row in doc('.product-d2-page7 table tr').items():
            cells = [compact_text(x.text()).rstrip(':') for x in row('td').items()]
            for index in range(0, len(cells) - 1, 2):
                name = cells[index]
                value = cells[index + 1]
                if name and value:
                    characteristics.append({'name': name, 'value': value})

        description_html = self.build_description(response)

        common_images = []
        for selector in [
            '.product-d2-page1 img',
            '.product-d2-page3 > .page-img img',
            '.product-d2-page4 img',
            '.product-d2-page6 img',
            '.product-d2-page5 img',
        ]:
            for image in doc(selector).items():
                saved = self.save_image_from_node(response.url, image)
                if saved and saved not in common_images:
                    common_images.append(saved)

        documents = []
        models_3d = []
        files = []
        for link in doc('.product-d2-page3 a.more, .product-d2-page7 a[href]').items():
            href = link.attr('href') or link.attr('data-href')
            text = compact_text(link.text())
            if not href or href.startswith(('javascript:', '#')):
                continue
            kind = self.asset_kind(href, text)
            saved = download_asset(response.url, href, DONOR, kind)
            if not saved:
                continue
            if kind == 'models_3d':
                models_3d.append(saved)
            elif kind == 'documents':
                documents.append({'name': text or os.path.basename(saved), 'url': saved})
            else:
                files.append(saved)

        for model in doc('[data-href]').items():
            href = model.attr('data-href')
            if self.asset_kind(href, '') != 'models_3d':
                continue
            saved = download_asset(response.url, href, DONOR, 'models_3d')
            if saved and saved not in models_3d:
                models_3d.append(saved)

        characteristics = self.dedupe_characteristics(characteristics)
        categories = self.append_series_category(categories, characteristics)

        return {
            'page_title': page_title,
            'categories': categories,
            'characteristics': characteristics,
            'description': description_html,
            'images': common_images,
            'files': files,
            'documents': documents,
            'models_3d': models_3d,
        }

    def parse_products(self, response, common):
        products = []
        slides = list(response.doc('.product-d2-page2 .wrap-right .product-d2-swiper .swiper-slide').items())
        descriptions = [compact_text(x.text()) for x in response.doc('.product-d2-page2 .wrap-right .tab-title .title').items()]

        for index, slide in enumerate(slides):
            model = clean_name(slide('.title').eq(0).text())
            if not model:
                continue
            sku_description = descriptions[index] if index < len(descriptions) else ''
            main_image = self.save_image_from_node(response.url, slide('img').eq(0))
            images = []
            if main_image:
                images.append(main_image)
            for saved in common['images']:
                if saved not in images:
                    images.append(saved)

            characteristics = deepcopy(common['characteristics'])
            characteristics.insert(0, {'name': 'Part Number', 'value': model})
            if sku_description:
                characteristics.insert(1, {'name': 'Specification', 'value': sku_description})

            products.append({
                'name': ' - '.join([x for x in [model, sku_description] if x]),
                'vendor': 'CNLINKO',
                'model': model,
                'typePrefix': common['page_title'],
                'price': 0.0,
                'old_price': None,
                'currency': 'RUB',
                'description': common['description'],
                'characteristics': self.dedupe_characteristics(characteristics),
                'main_image': main_image,
                'images': images,
                'files': list(common['files']),
                'documents': deepcopy(common['documents']),
                'models_3d': list(common['models_3d']),
                'categories': list(common['categories']),
                'donor': DONOR,
                'donor_url': response.url,
                'group': GROUP,
            })

        return products

    def extract_categories(self, response):
        categories = []
        for link in response.doc('.top-head .breadcrumb a').items():
            text = compact_text(link.text())
            if text and text.lower() != 'home' and text != compact_text(response.doc('h1').eq(0).text()):
                categories.append(text)
        if len(categories) < 2 and '/connectors/' in response.url:
            categories = ['Products', 'Connectors']
        return categories or ['Products']

    def append_series_category(self, categories, characteristics):
        categories = list(categories or [])
        for item in characteristics:
            if item.get('name') != 'Product Series':
                continue
            value = item.get('value')
            series = value[0] if isinstance(value, list) and value else value
            series = compact_text(series)
            if series and series not in categories:
                categories.append(series)
            break
        return categories

    def build_description(self, response):
        doc = response.doc
        parts = []
        for selector in [
            '.product-d2-page1 .page-center',
            '.product-d2-page3 .text-body',
            '.product-d2-page4 .float-text-box',
            '.product-d2-page4 .list',
            '.product-d2-page5 .list',
            '.product-d2-page7 .img-box',
        ]:
            html = doc(selector).eq(0).html()
            if html:
                parts.append('<section>%s</section>' % html)
        html = ''.join(parts)
        html = self.localize_description_images(response.url, html)
        return self.cleaner.clean_html(html) if html else ''

    def localize_description_images(self, base_url, html):
        def repl(match):
            attr = match.group(1).lower()
            quote_char = match.group(2)
            url = match.group(3)
            saved = download_asset(base_url, url, DONOR, 'images')
            if attr == 'data-src':
                attr = 'src'
            return '%s=%s%s%s' % (attr, quote_char, saved or url, quote_char)

        html = re.sub(r'(src|data-src)\s*=\s*(")([^"]*)"', repl, html)
        html = re.sub(r"(src|data-src)\s*=\s*(')([^']*)'", repl, html)
        return html

    def save_image_from_node(self, base_url, node):
        src = node.attr('src') or node.attr('data-src') or node.attr('href')
        return download_asset(base_url, src, DONOR, 'images')

    def asset_kind(self, href, name):
        href_value = (href or '').lower()
        text_value = (name or '').lower()
        value = href_value + ' ' + text_value
        if re.search(r'\.(glb|gltf|stl|step|stp|iges|igs|obj)(?:[?#].*)?$', href_value):
            return 'models_3d'
        if re.search(r'\.(pdf|doc|docx|xls|xlsx)(?:[?#].*)?$', value) or 'drawing' in value or 'manual' in value or 'download' in href_value:
            return 'documents'
        return 'files'

    def dedupe_characteristics(self, characteristics):
        result = []
        seen = set()
        for item in characteristics:
            name = compact_text(item.get('name'))
            value = item.get('value')
            if isinstance(value, list):
                value = [compact_text(x) for x in value if compact_text(x)]
                key_value = json.dumps(value, sort_keys=True)
            else:
                value = compact_text(value)
                key_value = value
            if not name or not value:
                continue
            key = (name.lower(), key_value)
            if key in seen:
                continue
            seen.add(key)
            result.append({'name': name, 'value': value})
        return result
