#!/usr/bin/env python
# -*- encoding: utf-8 -*-

"""Compatibility shims for legacy dependencies on modern Python."""

import collections
import collections.abc


for _name in (
    'Callable',
    'Iterable',
    'Mapping',
    'MutableMapping',
    'MutableSequence',
    'MutableSet',
    'Sequence',
):
    if not hasattr(collections, _name):
        setattr(collections, _name, getattr(collections.abc, _name))
