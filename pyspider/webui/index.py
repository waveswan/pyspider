#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# vim: set et sw=4 ts=4 sts=4 ff=unix fenc=utf8:
# Author: Binux<i@binux.me>
#         http://binux.me
# Created on 2014-02-22 23:20:39

import os
import socket
import json as std_json

from six import iteritems, itervalues
from flask import render_template, request, json

try:
    import flask_login as login
except ImportError:
    from flask.ext import login

from .app import app

index_fields = ['name', 'group', 'status', 'comments', 'rate', 'burst', 'updatetime']


def proxy_config_path():
    return os.path.join(app.config.get('data_path', './data'), 'proxy_config.json')


def normalize_proxies(value):
    if isinstance(value, list):
        proxies = value
    else:
        proxies = value.splitlines()
    return [x.strip() for x in proxies if x and x.strip()]


def load_proxy_config():
    try:
        with open(proxy_config_path()) as fp:
            data = std_json.load(fp)
    except Exception:
        data = {}
    proxies = normalize_proxies(data.get('proxies', []))
    data['proxies'] = proxies
    data['enabled'] = bool(proxies)
    data['count'] = len(proxies)
    return data


def save_proxy_config(proxies):
    data = {
        'proxies': normalize_proxies(proxies),
    }
    path = proxy_config_path()
    dirname = os.path.dirname(path)
    if dirname and not os.path.exists(dirname):
        os.makedirs(dirname)
    with open(path, 'w') as fp:
        std_json.dump(data, fp, indent=2)
    data['enabled'] = bool(data['proxies'])
    data['count'] = len(data['proxies'])
    return data


def apply_proxy_config(proxies):
    rpc = app.config.get('fetcher_rpc')
    if rpc is None:
        return None
    return rpc.set_proxy_config(proxies)


@app.route('/')
def index():
    projectdb = app.config['projectdb']
    projects = sorted(projectdb.get_all(fields=index_fields),
                      key=lambda k: (0 if k['group'] else 1, k['group'] or '', k['name']))
    return render_template("index.html", projects=projects,
                           proxy_config=load_proxy_config())


@app.route('/proxy-config', methods=['GET', 'POST'])
def proxy_config():
    if request.method == 'GET':
        config = load_proxy_config()
        try:
            rpc = app.config.get('fetcher_rpc')
            if rpc is not None:
                remote_config = rpc.get_proxy_config()
                if remote_config is not None:
                    config.update(remote_config)
        except Exception as e:
            config['error'] = repr(e)
        return json.dumps(config), 200, {'Content-Type': 'application/json'}

    proxies = request.form.get('proxies', '')
    config = save_proxy_config(proxies)
    try:
        remote_config = apply_proxy_config(config['proxies'])
        if remote_config is not None:
            config.update(remote_config)
    except Exception as e:
        config['error'] = repr(e)
        return json.dumps(config), 502, {'Content-Type': 'application/json'}

    return json.dumps(config), 200, {'Content-Type': 'application/json'}


@app.route('/queues')
def get_queues():
    def try_get_qsize(queue):
        if queue is None:
            return 'None'
        try:
            return queue.qsize()
        except Exception as e:
            return "%r" % e

    result = {}
    queues = app.config.get('queues', {})
    for key in queues:
        result[key] = try_get_qsize(queues[key])
    return json.dumps(result), 200, {'Content-Type': 'application/json'}


@app.route('/update', methods=['POST', ])
def project_update():
    projectdb = app.config['projectdb']
    project = request.form['pk']
    name = request.form['name']
    value = request.form['value']

    project_info = projectdb.get(project, fields=('name', 'group'))
    if not project_info:
        return "no such project.", 404
    if 'lock' in projectdb.split_group(project_info.get('group')) \
            and not login.current_user.is_active():
        return app.login_response

    if name not in ('group', 'status', 'rate'):
        return 'unknown field: %s' % name, 400
    if name == 'rate':
        value = value.split('/')
        if len(value) != 2:
            return 'format error: rate/burst', 400
        rate = float(value[0])
        burst = float(value[1])
        update = {
            'rate': min(rate, app.config.get('max_rate', rate)),
            'burst': min(burst, app.config.get('max_burst', burst)),
        }
    else:
        update = {
            name: value
        }

    ret = projectdb.update(project, update)
    if ret:
        rpc = app.config['scheduler_rpc']
        if rpc is not None:
            try:
                rpc.update_project()
            except socket.error as e:
                app.logger.warning('connect to scheduler rpc error: %r', e)
                return 'rpc error', 200
        return 'ok', 200
    else:
        app.logger.warning("[webui index] projectdb.update() error - res: {}".format(ret))
        return 'update error', 500


@app.route('/counter')
def counter():
    rpc = app.config['scheduler_rpc']
    if rpc is None:
        return json.dumps({})

    result = {}
    try:
        data = rpc.webui_update()
        for type, counters in iteritems(data['counter']):
            for project, counter in iteritems(counters):
                result.setdefault(project, {})[type] = counter
        for project, paused in iteritems(data['pause_status']):
            result.setdefault(project, {})['paused'] = paused
    except socket.error as e:
        app.logger.warning('connect to scheduler rpc error: %r', e)
        return json.dumps({}), 200, {'Content-Type': 'application/json'}

    return json.dumps(result), 200, {'Content-Type': 'application/json'}


@app.route('/run', methods=['POST', ])
def runtask():
    rpc = app.config['scheduler_rpc']
    if rpc is None:
        return json.dumps({})

    projectdb = app.config['projectdb']
    project = request.form['project']
    project_info = projectdb.get(project, fields=('name', 'group'))
    if not project_info:
        return "no such project.", 404
    if 'lock' in projectdb.split_group(project_info.get('group')) \
            and not login.current_user.is_active():
        return app.login_response

    newtask = {
        "project": project,
        "taskid": "on_start",
        "url": "data:,on_start",
        "process": {
            "callback": "on_start",
        },
        "schedule": {
            "age": 0,
            "priority": 9,
            "force_update": True,
        },
    }

    try:
        ret = rpc.newtask(newtask)
    except socket.error as e:
        app.logger.warning('connect to scheduler rpc error: %r', e)
        return json.dumps({"result": False}), 200, {'Content-Type': 'application/json'}
    return json.dumps({"result": ret}), 200, {'Content-Type': 'application/json'}


@app.route('/robots.txt')
def robots():
    return """User-agent: *
Disallow: /
Allow: /$
Allow: /debug
Disallow: /debug/*?taskid=*
""", 200, {'Content-Type': 'text/plain'}
