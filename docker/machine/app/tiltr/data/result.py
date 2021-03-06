#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018-2019 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from typing import Dict, Any, Callable, Union, Tuple, Iterator

import json
import base64
import re

import decimal
from decimal import *

from enum import Enum
from collections import defaultdict

from .exceptions import ErrorDomain, most_severe
from .settings import Workarounds

from texttable import Texttable


class MaybeDecimal:
	def __init__(self, s: Union[str, Decimal, 'MaybeDecimal'] = None):
		if isinstance(s, MaybeDecimal):
			self._d = s._d
		elif s is not None:
			try:
				self._d = Decimal(s)
			except (decimal.ConversionSyntax, decimal.InvalidOperation):
				self._d = None
		else:
			self._d = None

	def valid(self) -> bool:
		return self._d is not None

	def to_decimal(self) -> Decimal:
		return self._d

	def __str__(self):
		if self._d is None:
			return "not-a-number"
		else:
			return str(self._d)

	def encode(self):
		return (True, str(self._d)) if self._d is not None else (False, )

	@staticmethod
	def decode(s):
		if s[0]:
			return MaybeDecimal(s[1])
		else:
			return MaybeDecimal()


def _dump_properties(properties: Dict[str, str], report: Callable[[str], None]):
	table = Texttable()
	table.set_deco(Texttable.HEADER)
	table.set_cols_dtype(['t', 't'])
	table.set_cols_width([70, 50])
	table.set_header_align(['l', 'l'])

	# this supports tuple-keys (for matching questions); which is why we don't simply use
	# json.dumps(properties) to print this out.
	for k, v in properties.items():
		table.add_row([json.dumps(k), json.dumps(v)])

	for line in table.draw().split('\n'):
		report(line)


def _flat(x: Any) -> Any:
	if isinstance(x, tuple):
		for y in x:
			for yy in _flat(y):
				yield yy
	else:
		yield x


def _normalize_json(s: str) -> str:
	try:
		return json.dumps(json.loads(s))
	except ValueError:
		return '-illegal-json-' + s


class Origin(Enum):
	recorded = 0
	exported = 1


def _round_to_2_digits(x: Union[Decimal, MaybeDecimal], r: str) -> MaybeDecimal:
	x = MaybeDecimal(x)
	if x.valid():
		return MaybeDecimal(x.to_decimal().quantize(Decimal("0.01"), rounding=r))
	else:
		return x


class Result:
	@staticmethod
	def key(*args) -> Tuple:
		return tuple(_flat(args))

	@staticmethod
	def normalize_question_title(title: str) -> str:
		return re.sub(r'\s+', '', title)

	@staticmethod
	def reached_score_keys(question_title: str) -> Iterator[Tuple]:
		normed_title = Result.normalize_question_title(question_title)
		for channel in ("xls", "pdf"):
			yield (channel, "question", normed_title, "score_reached")

	@staticmethod
	def maximum_score_keys(question_title: str) -> Iterator[Tuple]:
		normed_title = Result.normalize_question_title(question_title)
		for channel in ("pdf", ):
			yield (channel, "question", normed_title, "score_maximum")

	@staticmethod
	def round_up_to_2_digits(x: Union[Decimal, MaybeDecimal]) -> MaybeDecimal:
		return _round_to_2_digits(x, ROUND_CEILING)

	@staticmethod
	def score_percentage(score: MaybeDecimal, maximum: Decimal) -> MaybeDecimal:
		if score.valid():
			return MaybeDecimal((Decimal(100) * score.to_decimal()) / maximum)
		else:
			return score

	@staticmethod
	def format_percentage(p: Union[Decimal, MaybeDecimal], workarounds: Workarounds) -> MaybeDecimal:
		return _round_to_2_digits(p, ROUND_HALF_UP)

	@staticmethod
	def format_score(score: Union[Decimal, MaybeDecimal]) -> str:
		s = str(Result.round_up_to_2_digits(score))
		if '.' in s:
			s = s.rstrip('0')
			if s.endswith('.'):
				s = s.rstrip('.')
		return s

	def scores(self, channel: str = "xls") -> Iterator[MaybeDecimal]:
		for k, v in self.properties.items():
			if len(k) == 4 and k[0] == channel and k[1] == "question" and k[3] == "score_reached":
				yield MaybeDecimal(v)

	def _serialized_properties(self) -> Iterator[Tuple]:
		for k, v in self.properties.items():
			if isinstance(v, MaybeDecimal):
				yield k, ("MaybeDecimal", v.encode())
			else:
				yield k, v

	@staticmethod
	def _deserialized_properties(items) -> Dict:
		properties = dict()

		for k, v in items:
			if isinstance(v, list) and v[0] == "MaybeDecimal":
				properties[k] = MaybeDecimal.decode(v[1])
			else:
				properties[k] = v

		return properties

	def __init__(self, from_json: str = None, **kwargs):
		from ..question.coverage import Coverage

		if from_json:
			data = json.loads(from_json)
			self.origin = Origin[data["origin"]]
			self.properties = self._deserialized_properties((tuple(key), value) for key, value in data["properties"])
			self.types = dict((tuple(key), value) for key, value in data["types"])
			self.protocol = data["protocol"]
			self.files = dict((k, base64.b64decode(v)) for k, v in data["files"].items())
			self.performance = data["performance"]
			self.errors = data["errors"]
			self.coverage = Coverage(from_dict=data["coverage"])
		else:
			self.origin = kwargs.get('origin', 'unknown')
			self.properties = dict()
			self.types = dict()
			self.protocol = []
			self.files = kwargs.get('files', dict())
			self.performance = []
			self.errors = dict()
			self.coverage = Coverage()

	def to_json(self):
		return json.dumps(dict(
			origin=self.origin.name,
			properties=list(self._serialized_properties()),
			types=list(self.types.items()),
			protocol=self.protocol,
			files=dict((k, base64.b64encode(v).decode('utf8')) for k, v in self.files.items()),
			performance=self.performance,
			errors=self.errors,
			coverage=self.coverage.as_dict()))

	def get_origin(self):
		return self.origin

	def add(self, key: Tuple, value: Union[str, Decimal], value_type: str = None):
		assert key not in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value
		if value_type:
			self.types[key] = value_type

	def update(self, key: Tuple, value: Union[str, Decimal]):
		assert key in self.properties
		if isinstance(value, Decimal):
			value = str(value)  # make it safe for JSON
		self.properties[key] = value

	def remove(self, key: Tuple):
		if key in self.properties:
			del self.properties[key]

	def gather(self, key: Tuple):
		answers = dict()
		for k, v in self.properties.items():
			if k[:len(key)] == key:
				answers[k[len(key):]] = v
		return answers

	@staticmethod
	def from_error(origin, domain, err, files=None):
		r = Result(origin=origin, files=files or dict())
		r.errors[domain.name] = err
		return r

	def get_most_severe_error_domain(self):
		return most_severe(ErrorDomain[d] for d in self.errors.keys())

	def get(self, key: str):
		return self.properties.get(key, None)

	def attach_protocol(self, protocol):
		self.protocol = protocol

	def attach_file(self, filename: str, data: bytes):
		self.files[filename] = data

	def attach_performance_measurements(self, performance):
		self.performance = performance

	def attach_coverage(self, coverage: 'Coverage'):
		self.coverage = coverage

	def get_normalized_properties(self) -> Dict[Tuple, Any]:
		return dict((tuple(str(k) for k in key), value) for key, value in self.properties.items())

	def get_answers(self) -> Dict[str, Dict]:
		answers = defaultdict(dict)
		for p, value in self.properties.items():
			if p[0] == "question" and p[2] == "answer":
				question_title = p[1]
				dimension = p[3]
				answers[question_title][dimension] = value
		return answers

	def check_against(self, other: 'Result', report: Callable[[str], None], workarounds: Workarounds) -> bool:
		all_ok = True

		self_properties = self.get_normalized_properties()
		other_properties = other.get_normalized_properties()

		keys = sorted(list(set(
			list(self_properties.keys()) + list(other_properties.keys()))))

		table = Texttable()
		table.set_deco(Texttable.HEADER)
		table.set_cols_dtype(['t', 't', 't', 't'])
		table.header(['OK?', 'KEY', self.get_origin().name.upper(), other.get_origin().name.upper()])
		table.set_cols_width([10, 60, 20, 20])
		table.set_header_align(['l', 'l', 'l', 'l'])

		def ignore_key(k: Tuple) -> bool:
			return k[0] == "results_tab" and workarounds.ignore_wrong_results_in_results_tab

		def make_is_close(eps: Decimal = Decimal("0.01")):
			def is_close(a: Union[str, MaybeDecimal], b: Union[str, MaybeDecimal]) -> bool:
				a = MaybeDecimal(a)
				b = MaybeDecimal(b)

				if not a.valid() or not b.valid():
					return False

				try:
					return abs(a.to_decimal() - b.to_decimal()) <= eps
				except decimal.InvalidOperation:
					print("could not compute is_close for (%s, %s)" % (a, b))
					return False
			return is_close

		def is_exactly_equal(a, b) -> bool:
			return a == b

		comparators = dict()

		if workarounds.inaccurate_percentage_rounding:
			comparators[("statistics_tab", "percentage_reached")] = make_is_close()
			comparators[("results_tab", "percentage_reached")] = make_is_close()

		for k in keys:
			value_self = "%s" % self_properties.get(k, None)
			value_other = "%s" % other_properties.get(k, None)

			type_self = self.types.get(k, None)
			type_other = self.types.get(k, None)
			types = tuple(set(t for t in (type_self, type_other) if t is not None))

			value_self = workarounds.normalize(value_self)
			value_other = workarounds.normalize(value_other)

			if types == ('json',):
				value_self = _normalize_json(value_self)
				value_other = _normalize_json(value_other)
			elif len(types) > 0:
				raise RuntimeError("incompatible property data types")

			is_equal = comparators.get(k, is_exactly_equal)

			if ignore_key(k):
				status = "IGNORED"
			elif is_equal(value_self, value_other):
				status = "OK"
			else:
				status = "FAIL"
				all_ok = False

			table.add_row([
				status,
				" / ".join(k),
				value_self.replace("\n", "\\n"),
				value_other.replace("\n", "\\n")
			])

		for line in table.draw().split("\n"):
			report(line)

		if False:  # enable for further debugging
			if not all_ok:
				report("\n")
				report("full dump of properties of %s:" % self.get_origin().name.upper())
				_dump_properties(self.properties, report)

				report("\n")
				report("full dump of properties of %s:" % other.get_origin().name.upper())
				_dump_properties(other.properties, report)

		if self.errors:
			for type, err in self.errors.items():
				report("error %s:%s in %s" % (type, err, self.origin))
			all_ok = False
		if other.errors:
			for type, err in other.errors.items():
				report("error %s:%s in %s" % (type, err, other.origin))
			all_ok = False

		return all_ok


def open_results():
	from .database import DB

	return DB()
