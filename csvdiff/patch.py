# -*- coding: utf-8 -*-
#
#  patch.py
#  csvdiff
#

"""
The the patch format.
"""

import sys
import json
import copy
import itertools

import jsonschema

from . import records
from . import error


SCHEMA = {
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'title': 'csvdiff',
    'description': 'The patch format used by csvdiff.',
    'type': 'object',
    'properties': {
        '_index': {
            'type': 'array',
            'minItems': 1,
            'items': {'type': 'string'},
        },
        'added': {
            'type': 'array',
            'items': {'type': 'object',
                      'patternProperties': {
                          '^.*$': {'type': ['string', 'number']},
                      }},
        },
        'removed': {
            'type': 'array',
            'items': {'type': 'object',
                      'patternProperties': {
                          '^.*$': {'type': ['string', 'number']},
                      }},
        },
        'changed': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'key': {'type': 'array',
                            'items': {'type': ['string', 'number']},
                            'minItems': 1},
                    'fields': {
                        'type': 'object',
                        'minProperties': 1,
                        'patternProperties': {
                            '^.*$': {'type': 'object',
                                     'properties': {
                                         'from': {
                                             'type': ['string', 'number']
                                         },
                                         'to': {
                                             'type': ['string', 'number']
                                         },
                                     },
                                     'required': ['from', 'to']},
                        },
                    },
                },
                'required': ['key', 'fields'],
            },
        },
    },
    'required': ['_index', 'added', 'changed', 'removed'],
}


def is_valid(diff):
    "Validate it against the schema."
    try:
        validate(diff)
    except jsonschema.ValidationError:
        return False

    return True


def validate(diff):
    return jsonschema.validate(diff, SCHEMA)


def apply(diff, recs, strict=True):
    """
    Transform the records with the patch. May fail if the records do not
    match those expected in the patch.
    """
    index_columns = diff['_index']
    indexed = records.index(copy.deepcopy(recs), index_columns)
    _add_records(indexed, diff['added'], index_columns, strict=strict)
    _remove_records(indexed, diff['removed'], index_columns, strict=strict)
    _update_records(indexed, diff['changed'], strict=strict)
    return indexed.values()


def _add_records(indexed, recs_to_add, index_columns, strict=True):
    indexed_to_add = records.index(recs_to_add, index_columns)
    for k, r in indexed_to_add.items():
        if strict and k in indexed:
            error.abort(
                'error: key {0} already exists in source document'.format(k)
            )
        indexed[k] = r


def _remove_records(indexed, recs_to_remove, index_columns, strict=True):
    indexed_to_remove = records.index(recs_to_remove, index_columns)
    for k, r in indexed_to_remove.items():
        if strict:
            v = indexed.get(k)
            if v is None:
                error.abort(
                    'ERROR: key {0} does not exist in source '
                    'document'.format(k)
                )
            if v != r:
                error.abort(
                    'ERROR: source document version of {0} has '
                    'changed'.format(k)
                )

        del indexed[k]


def _update_records(indexed, deltas, strict=True):
    for delta in deltas:
        k = tuple(delta['key'])
        field_changes = delta['fields']

        r = indexed.get(k)

        # what happens when the record is missing?
        if r is None:
            if strict:
                error.abort(
                    'ERROR: source document is missing record '
                    'for {0}'.format(k)
                )
            continue

        r = indexed[k]
        for field, from_to in field_changes.items():
            expected = from_to['from']
            if strict and r.get(field) != expected:
                error.abort(
                    'ERROR: source document version of {0} has '
                    'changed {1} field'.format(k, field)
                )
            r[field] = from_to['to']


def load(istream, strict=True):
    "Deserialize a patch object."
    diff = json.load(istream)
    if strict:
        jsonschema.validate(diff, SCHEMA)

    return diff


def save(diff, stream=sys.stdout, compact=False):
    "Serialize a patch object."
    flags = ({}
             if compact
             else {'indent': 2, 'sort_keys': True})
    json.dump(diff, stream, **flags)


def create(from_records, to_records, index_columns):
    """
    Diff two sets of records, using the index columns as the primary key for
    both datasets.
    """
    from_indexed = records.index(from_records, index_columns)
    to_indexed = records.index(to_records, index_columns)

    return create_indexed(from_indexed, to_indexed, index_columns)


def create_indexed(from_indexed, to_indexed, index_columns):
    # examine keys for overlap
    removed, added, shared = _compare_keys(from_indexed, to_indexed)

    # check for changed rows
    changed = _compare_rows(from_indexed, to_indexed, shared)

    diff = _assemble(removed, added, changed, from_indexed, to_indexed,
                     index_columns)

    return diff


def _compare_keys(from_recs, to_recs):
    from_keys = set(from_recs)
    to_keys = set(to_recs)
    removed = from_keys.difference(to_keys)
    shared = from_keys.intersection(to_keys)
    added = to_keys.difference(from_keys)
    return removed, added, shared


def _compare_rows(from_recs, to_recs, keys):
    "Return the set of keys which have changed."
    return set(
        k for k in keys
        if sorted(from_recs[k].items()) != sorted(to_recs[k].items())
    )


def _assemble(removed, added, changed, from_recs, to_recs, index_columns):
    diff = {}
    diff['removed'] = [from_recs[k] for k in removed]
    diff['added'] = [to_recs[k] for k in added]
    diff['changed'] = [{'key': list(k),
                        'fields': record_diff(from_recs[k], to_recs[k])}
                       for k in changed]
    diff['_index'] = index_columns
    return diff


def record_diff(lhs, rhs):
    "Diff an individual row."
    delta = {}
    for k in set(lhs).union(rhs):
        from_ = lhs[k]
        to_ = rhs[k]
        if from_ != to_:
            delta[k] = {'from': from_, 'to': to_}

    return delta


def is_typed(diff):
    "Are any of the values in the diff typed?"
    return any(type(v) != str for v in _iter_fields(diff))


def _iter_fields(diff):
    return itertools.chain(
        _iter_record_fields(diff['added']),
        _iter_record_fields(diff['removed']),
        _iter_change_fields(diff['changed']),
    )


def _iter_change_fields(cs):
    for c in cs:
        for k in c['key']:
            yield k
        for v in c['fields'].values():
            yield v['from']
            yield v['to']


def _iter_record_fields(recs):
    for r in recs:
        for v in r.values():
            yield v