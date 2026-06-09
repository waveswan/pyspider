#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import datetime
import hashlib
import os
import re
import urllib.request
from urllib.parse import urljoin, urlparse

from lxml.html.clean import Cleaner
from pymongo import MongoClient
from pyspider.libs.base_handler import *


def env(name, default=''):
    return os.environ.get(name, default)


DOWNLOAD_DIR = env('PARSER_DOWNLOAD_DIR', './data/download')
PUBLIC_UPLOAD_DIR = env('PARSER_PUBLIC_UPLOAD_DIR', '/upload/spider')


def price_to_float(value, default=0.0):
    value = (value or '').replace('\u2009', ' ').replace('\xa0', ' ')
    value = re.sub(r'\.$|[^0-9.,-]', '', value)
    value = value.replace(',', '.')
    if value.count('.') > 1:
        value = value.replace('.', '', value.count('.') - 1)
    try:
        return float(value) if value else default
    except ValueError:
        return default


def absolute_url(base_url, url):
    if not url:
        return ''
    if url.startswith('//'):
        return 'https:' + url
    return urljoin(base_url, url)


def download_asset(base_url, url, donor, kind='images'):
    url = absolute_url(base_url, url)
    if not url:
        return ''

    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    ext = ext or '.bin'
    digest = hashlib.sha1(url.encode('utf8')).hexdigest()
    filename = digest + ext.lower()

    local_dir = os.path.join(DOWNLOAD_DIR, donor, kind)
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)

    local_path = os.path.join(local_dir, filename)
    if not os.path.exists(local_path):
        urllib.request.urlretrieve(url, local_path)

    return '/'.join([PUBLIC_UPLOAD_DIR.rstrip('/'), donor, kind, filename])


class HandlerDima(BaseHandler):
    crawl_config = {
        'itag': 'v1',
    }
    if env('PARSER_PROXY'):
        crawl_config['proxy'] = env('PARSER_PROXY')

    cleaner = Cleaner(
        javascript=True,
        comments=True,
        style=True,
        links=True,
        safe_attrs_only=True,
        remove_tags=['a'],
    )

    i = {
        # Marketlab database group. Keep separate from pyspider project.group.
        'group': env('PARSER_MARKET_GROUP', 'electronik'),
        'name': 'example.ru',
        'url': 'https://example.ru/catalog/',

        'catalog_search': [''],
        'p_search': '',
        'p_next': '',

        'p_name': 'h1',
        'p_price': '',
        'p_old_price': '',
        'p_available': '',
        'p_vendor': '',
        'p_description': '',
        'p_characteristics': '',
        'p_c_name': '',
        'p_c_value': '',
        'p_c_array': '',
        'p_images': '',
        'p_main_image': '',
        'p_files': '',
        'p_documents': '',
        'p_document_name': '',
        'p_models_3d': '',
        'p_category': '',
    }

    test_urls = []
    test_limit = int(env('PARSER_TEST_LIMIT', '0') or '0')

    @property
    def db(self):
        kwargs = {}
        if env('PARSER_MONGO_USER'):
            kwargs.update({
                'username': env('PARSER_MONGO_USER'),
                'password': env('PARSER_MONGO_PASSWORD'),
                'authSource': env('PARSER_MONGO_AUTH_SOURCE', 'admin'),
            })
        client = MongoClient(
            env('PARSER_MONGO_HOST', 'localhost'),
            int(env('PARSER_MONGO_PORT', '27017')),
            **kwargs
        )
        return client[env('PARSER_MONGO_DB', 'pyspider')]

    @every(minutes=24 * 60)
    def on_start(self):
        if self.test_urls:
            for url in self.test_urls[:self.test_limit or len(self.test_urls)]:
                self.crawl(url, callback=self.detail_page, save={'tree': []}, validate_cert=False)
            return
        self.crawl(self.i['url'], callback=self.catalog_page, save={'tree': []}, validate_cert=False)

    @config(age=7 * 24 * 60 * 60)
    def catalog_page(self, response):
        found_subcategory = False
        for query in self.i['catalog_search']:
            if not query:
                continue
            for each in response.doc(query).items():
                href = each.attr.href
                title = each.text().strip()
                if not href:
                    continue
                found_subcategory = True
                tree = list(response.save.get('tree') or [])
                if title:
                    tree.append(title)
                self.crawl(href, callback=self.catalog_page, save={'tree': tree}, validate_cert=False)

        if found_subcategory:
            return

        self.parse_listing(response)

    @config(age=7 * 24 * 60 * 60, priority=2)
    def listing_page(self, response):
        self.parse_listing(response)

    def parse_listing(self, response):
        for each in response.doc(self.i['p_search']).items():
            href = each.attr.href
            if not href:
                continue
            listing = {
                'name': each.text().strip(),
            }
            self.crawl(
                href,
                callback=self.detail_page,
                save={'tree': response.save.get('tree') or [], 'listing': listing},
                validate_cert=False,
            )

        next_page = response.doc(self.i['p_next']).attr.href if self.i['p_next'] else ''
        if next_page:
            self.crawl(next_page, callback=self.listing_page, save=response.save, validate_cert=False)

    @config(age=7 * 24 * 60 * 60, priority=2)
    def detail_page(self, response):
        ret = {
            'name': response.doc(self.i['p_name']).text().strip(),
            'vendor': None,
            'model': None,
            'typePrefix': None,
            'price': 0.0,
            'currency': 'RUB',
            'description': '',
            'characteristics': [],
            'main_image': None,
            'images': [],
            'files': [],
            'documents': [],
            'models_3d': [],
            'categories': response.save.get('tree') or [],
            'donor': self.i['name'],
            'donor_url': response.url,
            'group': self.i['group'],
            'dateUp': datetime.datetime.utcnow(),
        }

        if self.i['p_price']:
            ret['price'] = price_to_float(response.doc(self.i['p_price']).text())

        if self.i['p_old_price']:
            old_price = price_to_float(response.doc(self.i['p_old_price']).text())
            if old_price:
                ret['old_price'] = old_price

        if self.i['p_description']:
            ret['description'] = response.doc(self.i['p_description']).html() or ''

        if self.i['p_vendor']:
            vendor = response.doc(self.i['p_vendor']).text().strip()
            if vendor:
                ret['vendor'] = vendor

        for each in response.doc(self.i['p_characteristics']).items():
            cc_name = each(self.i['p_c_name']).text().strip()
            cc_value = each(self.i['p_c_value']).text().strip()
            cc_name = re.sub(':$', '', cc_name)
            if not cc_name and not cc_value:
                continue
            if cc_name == 'Производитель':
                ret['vendor'] = cc_value
                continue
            if cc_name == 'Модель':
                ret['model'] = cc_value
                continue
            if self.i['p_c_array'] and self.i['p_c_array'] in cc_value:
                cc_value = [x.strip() for x in cc_value.split(self.i['p_c_array']) if x.strip()]
            ret['characteristics'].append({'name': cc_name, 'value': cc_value})

        main_image_selector = self.i['p_main_image'] or self.i['p_images']
        if main_image_selector:
            main_src = response.doc(main_image_selector).eq(0).attr('src') or response.doc(main_image_selector).eq(0).attr('href')
            ret['main_image'] = download_asset(response.url, main_src, self.i['name'], 'images')

        for image in response.doc(self.i['p_images']).items():
            src = image.attr('src') or image.attr('href')
            saved = download_asset(response.url, src, self.i['name'], 'images')
            if saved and saved not in ret['images']:
                ret['images'].append(saved)

        for file_link in response.doc(self.i['p_files']).items():
            href = file_link.attr.href
            saved = download_asset(response.url, href, self.i['name'], 'files')
            if saved:
                ret['files'].append(saved)

        for document in response.doc(self.i['p_documents']).items():
            href = document.attr.href
            name = document(self.i['p_document_name']).text().strip() if self.i['p_document_name'] else document.text().strip()
            saved = download_asset(response.url, href, self.i['name'], 'documents')
            if saved:
                ret['documents'].append({'name': name or os.path.basename(saved), 'url': saved})

        for model in response.doc(self.i['p_models_3d']).items():
            href = model.attr.href or model.attr('src') or model.attr('data-src')
            saved = download_asset(response.url, href, self.i['name'], 'models_3d')
            if saved:
                ret['models_3d'].append(saved)

        if not ret['categories'] and self.i['p_category']:
            ret['categories'] = [x.text().strip() for x in response.doc(self.i['p_category']).items() if x.text().strip()]

        return ret

    def on_result(self, result):
        if not result:
            return
        if result.get('description'):
            result['description'] = self.cleaner.clean_html(result['description'])
        if result.get('vendor'):
            self.fill_name_parts(result)
        self.save_to_mongo(result)

    def fill_name_parts(self, result):
        vendor = result.get('vendor', '').strip()
        name = result.get('name', '').strip()
        pos = name.lower().find(vendor.lower())
        if pos > 0:
            result['typePrefix'] = name[:pos].strip()
            result['model'] = name[pos + len(vendor):].strip()

    def save_to_mongo(self, result):
        self.db[self.i['group']].update(
            {'name': result['name'], 'donor': self.i['name']},
            {'$set': result},
            upsert=True,
        )
        print('saved to mongodb ' + result['name'])
