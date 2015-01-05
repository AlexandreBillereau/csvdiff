#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, print_function, division

import os
from os import path
import unittest
import json
import tempfile
from io import StringIO
from collections import namedtuple
import csv

import csvdiff
from csvdiff import patch

from click.testing import CliRunner


class TestCsvdiff(unittest.TestCase):
    def setUp(self):
        csvdiff.DEBUG = True
        self.examples = path.join(path.dirname(__file__), 'examples')
        self.a_file = path.join(self.examples, 'a.csv')
        self.b_file = path.join(self.examples, 'b.csv')
        self.diff_file = path.join(self.examples, 'diff.json')
        self.runner = CliRunner()

    def csvdiff_cmd(self, *args):
        RunResult = namedtuple('RunResult', 'exit_code diff')
        t = tempfile.NamedTemporaryFile(delete=True)
        result = self.runner.invoke(csvdiff.csvdiff_cmd,
                                    ('--output', t.name) + args)
        diff = None
        if path.exists(t.name) and os.stat(t.name).st_size:
            with open(t.name) as istream:
                diff = json.load(istream)

        return RunResult(result.exit_code, diff)

    def patch_cmd(self, *args):
        RunResult = namedtuple('RunResult', 'exit_code records')
        t = tempfile.NamedTemporaryFile(delete=True)
        result = self.runner.invoke(csvdiff.csvpatch_cmd,
                                    ('--output', t.name) + args)
        recs = None
        if path.exists(t.name) and os.stat(t.name).st_size:
            with open(t.name) as istream:
                recs = list(csv.DictReader(istream))

        return RunResult(result.exit_code, recs)

    def test_summarize(self):
        lhs = [
            {'name': 'a', 'sheep': '7'},
            {'name': 'b', 'sheep': '12'},
            {'name': 'c', 'sheep': '0'},
        ]
        rhs = [
            {'name': 'a', 'sheep': '7'},
            {'name': 'c', 'sheep': '2'},
            {'name': 'd', 'sheep': '8'},
        ]
        diff = csvdiff.diff_records(lhs, rhs, ['name'])
        assert patch.is_valid(diff)
        assert not patch.is_typed(diff)
        o = StringIO()
        csvdiff._summarize_diff(diff, len(lhs), stream=o)
        self.assertEqual(
            o.getvalue(),
            "1 rows removed (33.3%)\n"
            "1 rows added (33.3%)\n"
            "1 rows changed (33.3%)\n"
        )

    def test_needs_args(self):
        result = self.csvdiff_cmd()
        assert result.exit_code != 0

    def test_needs_enough_arguments(self):
        result = self.csvdiff_cmd(self.a_file, self.b_file)
        assert result.exit_code != 0

    def test_needs_valid_key(self):
        result = self.csvdiff_cmd('abcd', self.a_file, self.b_file)
        assert result.exit_code != 0

    def test_diff_command_valid_usage(self):
        result = self.csvdiff_cmd('id', self.a_file, self.b_file)
        self.assertEqual(result.exit_code, 0)
        diff = result.diff
        patch.validate(diff)
        assert patch.is_valid(diff)

        expected = {
            'added': [{'id': '5', 'name': 'mira', 'amount': '81'}],
            'removed': [{'id': '2', 'name': 'eva', 'amount': '63'}],
            'changed': [
                {'key': ['1'],
                 'fields': {'amount': {'from': '20', 'to': '23'}}},
                {'key': ['6'],
                 'fields': {'amount': {'from': '10', 'to': '13'}}},
            ],
        }

        self.assertEqual(diff['added'],
                         expected['added'])
        self.assertEqual(diff['removed'],
                         expected['removed'])
        self.assertEqual(sorted(diff['changed'], key=lambda r: r['key']),
                         sorted(expected['changed'], key=lambda r: r['key']))

    def test_diff_records_str_values(self):
        lhs = [
            {'name': 'a', 'sheep': '7'},
            {'name': 'b', 'sheep': '12'},
            {'name': 'c', 'sheep': '0'},
        ]
        rhs = [
            {'name': 'a', 'sheep': '7'},
            {'name': 'c', 'sheep': '2'},
            {'name': 'd', 'sheep': '8'},
        ]

        diff = csvdiff.diff_records(lhs, rhs, ['name'])
        assert patch.is_valid(diff)
        assert not patch.is_typed(diff)

        # check the contents of the diff
        self.assertEqual(diff['added'], [
            {'name': 'd', 'sheep': '8'}
        ])
        self.assertEqual(diff['removed'], [
            {'name': 'b', 'sheep': '12'}
        ])
        self.assertEqual(diff['changed'], [
            {'key': ['c'],
             'fields': {'sheep': {'from': '0', 'to': '2'}}}
        ])

        # check that we can apply the diff
        patched = csvdiff.patch_records(diff, lhs)
        self.assertRecordsEqual(rhs, patched)

    def test_diff_records_nonstr_values(self):
        lhs = [
            {'name': 'a', 'sheep': 7},
            {'name': 'b', 'sheep': 12},
            {'name': 'c', 'sheep': 0},
        ]
        rhs = [
            {'name': 'a', 'sheep': 7},
            {'name': 'c', 'sheep': 2},
            {'name': 'd', 'sheep': 8},
        ]

        diff = csvdiff.diff_records(lhs, rhs, ['name'])
        assert patch.is_valid(diff)
        assert patch.is_typed(diff)

        self.assertEqual(diff['added'], [
            {'name': 'd', 'sheep': 8}
        ])
        self.assertEqual(diff['removed'], [
            {'name': 'b', 'sheep': 12}
        ])
        self.assertEqual(diff['changed'], [
            {'key': ['c'],
             'fields': {'sheep': {'from': 0, 'to': 2}}}
        ])

        # check that we can apply the diff
        patched = csvdiff.patch_records(diff, lhs)
        self.assertRecordsEqual(rhs, patched)

    def test_diff_records_multikey(self):
        lhs = [
            {'name': 'a', 'type': 1, 'sheep': 7},
            {'name': 'b', 'type': 1, 'sheep': 12},
            {'name': 'c', 'type': 1, 'sheep': 0},
        ]
        rhs = [
            {'name': 'a', 'type': 1, 'sheep': 7},
            {'name': 'c', 'type': 1, 'sheep': 2},
            {'name': 'd', 'type': 1, 'sheep': 8},
        ]

        diff = csvdiff.diff_records(lhs, rhs, ['name', 'type'])
        assert patch.is_valid(diff)
        assert patch.is_typed(diff)

        self.assertEqual(diff['added'], [
            {'name': 'd', 'sheep': 8, 'type': 1}
        ])
        self.assertEqual(diff['removed'], [
            {'name': 'b', 'sheep': 12, 'type': 1}
        ])
        self.assertEqual(diff['changed'], [
            {'key': ['c', 1],
             'fields': {'sheep': {'from': 0, 'to': 2}}}
        ])

        # check that we can apply the diff
        patched = csvdiff.patch_records(diff, lhs)
        self.assertRecordsEqual(rhs, patched)

    def assertRecordsEqual(self, lhs, rhs):
        lhs_sorted = sorted(lhs, key=lambda r: tuple(r.items()))
        rhs_sorted = sorted(rhs, key=lambda r: tuple(r.items()))
        self.assertEqual(lhs_sorted, rhs_sorted)

    def test_patch_schema_is_valid(self):
        assert not patch.is_valid({})

    def test_patch_cmd_valid_args(self):
        result = self.patch_cmd('-i', self.diff_file, self.a_file)
        self.assertEqual(result.exit_code, 0)

        with open(self.b_file) as istream:
            expected = list(csv.DictReader(istream))

        self.assertRecordsEqual(result.records, expected)

    def test_patch_add(self):
        orig = [
            {'name': 'a', 'type': '1', 'sheep': '7'},
        ]
        diff = {
            '_index': ['name'],
            'added': [{'name': 'b', 'type': '1', 'sheep': '9'}],
            'changed': [],
            'removed': [],
        }
        expected = [
            {'name': 'a', 'type': '1', 'sheep': '7'},
            {'name': 'b', 'type': '1', 'sheep': '9'},
        ]
        self.assertRecordsEqual(patch.apply(diff, orig), expected)

    def test_patch_remove(self):
        orig = [
            {'name': 'a', 'type': '1', 'sheep': '7'},
        ]
        diff = {
            '_index': ['name'],
            'added': [],
            'changed': [],
            'removed': [{'name': 'a', 'type': '1', 'sheep': '7'}],
        }
        expected = []
        self.assertRecordsEqual(patch.apply(diff, orig), expected)

    def test_patch_change(self):
        orig = [
            {'name': 'a', 'type': '1', 'sheep': '7'},
        ]
        diff = {
            '_index': ['name'],
            'added': [],
            'changed': [{'key': ['a'], 'fields': {'sheep': {'from': '7',
                                                            'to': '8'}}}],
            'removed': [],
        }
        expected = [
            {'name': 'a', 'type': '1', 'sheep': '8'},
        ]
        self.assertRecordsEqual(patch.apply(diff, orig), expected)

    def tearDown(self):
        pass


if __name__ == '__main__':
    unittest.main()
