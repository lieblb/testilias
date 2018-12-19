#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2018 Rechenzentrum, Universitaet Regensburg
# GPLv3, see LICENSE
#

from enum import Enum
from decimal import *
from collections import defaultdict
from selenium.common.exceptions import NoSuchElementException

from .question import Question
from ...data.exceptions import *


class ClozeType(Enum):
	text = 0
	select = 1
	numeric = 2


class ClozeComparator(Enum):
	ignore_case = "ci"
	case_sensitive = "cs"


class ClozeQuestionGap():
	_export_names = dict(de="Lücke", en="Gap")

	def __init__(self, question, index):
		self.question = question
		self.index = index

	def get_export_name(self, language):
		return ClozeQuestionGap._export_names[language] + " " + str(self.index + 1)


class ClozeQuestionTextGap(ClozeQuestionGap):
	def __init__(self, question, index, options, comparator, size):
		ClozeQuestionGap.__init__(self, question, index)
		self.options = options
		self.comparator = comparator
		self.size = size

	def initialize_coverage(self, coverage, context):
		for mode in ("verify", "export"):
			for args in coverage.text_cases(self.size, context):
				coverage.add_case(self.question, self.index, mode, *args)
			for solution in self.options.keys():
				coverage.add_case(self.question, self.index, mode, "solution", solution)

	def add_verify_coverage(self, coverage, value):
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(self.question, self.index, "verify", *args)
		if value in self.options:
			coverage.case_occurred(self.question, self.index, "verify", "solution", value)

	def add_export_coverage(self, coverage, value):
		value = str(value)
		for args in coverage.text_cases_occurred(value):
			coverage.case_occurred(self.question, self.index, "export", *args)
		if value in self.options:
			coverage.case_occurred(self.question, self.index, "export", "solution", value)

	def _modify_solution(self, text, score, context):
		mode = context.random.choices(
			("unmodified", "randchar", "randcase"),
			weights=(0.5, 0.25, 0.25))[0]

		if mode == "unmodified":
			# keep exactly as specified.
			return text, score
		else:
			# modify case or content.
			chars = []
			for i in range(len(text)):
				r = context.random.random()
				if mode == "randchar" and r < 0.2:
					chars.append(context.random.choice(context.cloze_random_chars))
				elif mode == "randcase" and r < 0.2:
					chars.append(text[i].swapcase())
				else:
					chars.append(text[i])
			text = "".join(chars)
			return text, self.get_score(text)

	def get_random_choice(self, context):
		if context.random.random() < 0.75 and not context.prefer_text():
			# pick scored answer.
			text, score = context.random.choice(list(self.options.items()))
			return self._modify_solution(text, score, context)
		else:
			# make up something random and probably wrong.
			if context.random.random() < 0.9:
				# produce some random test.
				text = context.produce_text(
					self.size, context.cloze_random_chars)
			else:
				# insert a random number. this is useful to test
				# workarounds.implicit_text_number_conversions.
				num_digits = context.random.randint(0, 2)
				format = (".%d" % num_digits) + "%f"
				text = format % (context.random.random() * 1000)
			return text, self.get_score(text)

	def get_score(self, text):
		if self.comparator == ClozeComparator.case_sensitive:
			return self.options.get(text, Decimal(0))

		assert self.comparator == ClozeComparator.ignore_case
		for option, score in self.options.items():
			if option.casefold() == text.casefold():
				return score

		return Decimal(0)

	def is_valid_answer(self, value):
		return True

	def get_type(self):
		return ClozeType.text


class ClozeQuestionSelectGap(ClozeQuestionGap):
	def __init__(self, question, index, options):
		ClozeQuestionGap.__init__(self, question, index)
		self.options = options

	def initialize_coverage(self, coverage, context):
		for value in self.options.keys():
			for mode in ("verify", "export"):
				coverage.add_case(self.question, self.index, mode, value)

	def add_verify_coverage(self, coverage, value):
		coverage.case_occurred(self.question, self.index, "verify", value)

	def add_export_coverage(self, coverage, value):
		value = str(value)
		coverage.case_occurred(self.question, self.index, "export", value)

	def get_random_choice(self, context):
		return context.random.choice(list(self.options.items()))

	def get_score(self, text):
		return self.options.get(text, Decimal(0))

	def is_valid_answer(self, value):
		return value in self.options

	def get_type(self):
		return ClozeType.select


class ClozeQuestionNumericGap(ClozeQuestionGap):
	def __init__(self, question, index, size, driver):
		ClozeQuestionGap.__init__(self, question, index)
		self.size = size

		self.numeric_value = Decimal(driver.find_element_by_name("gap_%d_numeric" % index).get_attribute("value"))
		self.numeric_lower = Decimal(driver.find_element_by_name("gap_%d_numeric_lower" % index).get_attribute("value"))
		self.numeric_upper = Decimal(driver.find_element_by_name("gap_%d_numeric_upper" % index).get_attribute("value"))
		self.score = Decimal(driver.find_element_by_name("gap_%d_numeric_points" % index).get_attribute("value"))

		self.exponent = min(x.as_tuple().exponent for x in (self.numeric_value, self.numeric_lower, self.numeric_upper))

	def initialize_coverage(self, coverage, context):
		for mode in ("verify", "export"):
			coverage.add_case(self.question, self.index, mode, str(self.numeric_value))
			coverage.add_case(self.question, self.index, mode, str(self.numeric_lower))
			coverage.add_case(self.question, self.index, mode, str(self.numeric_upper))

	def add_verify_coverage(self, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(self.question, self.index, "verify", x)

	def add_export_coverage(self, coverage, value):
		x = str(value)
		if x in [str(self.numeric_value), str(self.numeric_lower), str(self.numeric_upper)]:
			coverage.case_occurred(self.question, self.index, "export", x)

	def get_random_choice(self, context):
		if not context.workarounds.disallow_invalid_answers:
			if context.random.random() < 0.25:
				return context.produce_text(20, context.cloze_random_chars), Decimal(0)

		t = context.random.randint(1, 4)
		if t == 1:
			return str(self.numeric_lower), self.score
		elif t == 2:
			return str(self.numeric_upper), self.score
		elif t == 3:
			x = Decimal(context.random.uniform(float(self.numeric_lower), float(self.numeric_upper)))
			return str(round(x, -self.exponent)), self.score
		else:
			eps_exp = self.exponent - context.random.randint(0, 2)  # e.g. enter 5.32 for a numeric range defined as [3, 7]
			eps = 10.0 ** eps_exp
			d = float(self.numeric_upper - self.numeric_lower)
			off = Decimal(str(context.random.uniform(eps, 1000 * d)))
			if context.random.random() < 0.5:
				return str(round(self.numeric_lower - off, -self.exponent)), Decimal(0)
			else:
				return str(round(self.numeric_upper + off, -self.exponent)), Decimal(0)

	def get_score(self, text):
		try:
			value = Decimal(text)
			if self.numeric_lower <= value <= self.numeric_upper:
				return self.score
			else:
				return Decimal(0)
		except InvalidOperation:
			return Decimal(0)

	def is_valid_answer(self, value):
		try:
			Decimal(value)
			return True
		except InvalidOperation:
			return False

	def get_type(self):
		return ClozeType.numeric


def parse_gap_size(driver, gap_index, fallback_length):
	element = driver.find_element_by_name("gap_%d_gapsize" % gap_index)
	text = element.get_attribute("value").strip()
	assert isinstance(text, str)
	if text == '':
		return fallback_length
	else:
		return int(text)


def parse_gap_options(driver, gap_index):
	options = dict()

	while True:
		try:
			answer = driver.find_element_by_id("gap_%d[answer][%d]" % (gap_index, len(options)))
		except NoSuchElementException:
			break
		points = driver.find_element_by_id("gap_%d[points][%d]" % (gap_index, len(options)))
		options[answer.get_attribute("value")] = Decimal(points.get_attribute("value"))

	return options


class ClozeQuestion(Question):
	def __init__(self, driver, title):
		self.title = title
		self.gaps = dict()

		self.identical_scoring = driver.find_element_by_name("identical_scoring").is_selected()

		fallback_length = driver.find_element_by_name("fixedTextLength").get_attribute("value").strip()
		if fallback_length == '':
			fallback_length = 7
		else:
			fallback_length = int(fallback_length)

		self.comparator = ClozeComparator(driver.find_element_by_css_selector(
			"#textgap_rating option[selected]").get_attribute("value"))

		while True:
			gap_index = len(self.gaps)

			try:
				cloze = driver.find_element_by_name("clozetype_%d" % gap_index)
			except NoSuchElementException:
				break

			cloze_type = ClozeType(int(cloze.get_attribute("value")))

			if cloze_type == ClozeType.text or cloze_type == ClozeType.select:
				options = parse_gap_options(driver, gap_index)

				if not options:
					break

				if cloze_type == ClozeType.text:
					gap = ClozeQuestionTextGap(
						self, gap_index, options, self.comparator,
						parse_gap_size(driver, gap_index, fallback_length))
				elif cloze_type == ClozeType.select:
					gap = ClozeQuestionSelectGap(self, gap_index, options)

			elif cloze_type == ClozeType.numeric:
				gap = ClozeQuestionNumericGap(
					self, gap_index,
					parse_gap_size(driver, gap_index, fallback_length),
					driver)

			else:
				raise NotImplementedException("unsupported cloze type " + str(cloze_type))

			self.gaps[gap_index] = gap

	def create_answer(self, driver, *args):
		from ..answers.cloze import ClozeAnswer
		return ClozeAnswer(driver, self, *args)

	def initialize_coverage(self, coverage, context):
		for gap in self.gaps.values():
			gap.initialize_coverage(coverage, context)

	def add_export_coverage(self, coverage, answers, language):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name(language)] = self.gaps[gap.index]
		for gap_name, value in answers.items():
			gaps[gap_name].add_export_coverage(coverage, str(value))

	def get_gap_definition(self, index):
		return self.gap[index]

	def _get_normalized(self, s):
		if self.comparator == ClozeComparator.case_sensitive:
			return s
		else:
			assert self.comparator == ClozeComparator.ignore_case
			return s.casefold()

	def _is_empty_answer(self, answer, context):
		answer = context.strip_whitespace(answer)
		return len(answer) == 0

	def get_random_answer(self, context):
		while True:
			answers = dict()
			valid = dict()

			previous_answers = defaultdict(set)
			previous_answers_prob = 0.1 if self.identical_scoring else 0.25
			all_empty = True

			for gap in self.gaps.values():
				previous = previous_answers[gap.get_type()]

				if len(previous) > 0 and context.random.random() < previous_answers_prob:
					# use some previous answer to explicitly test identical_scoring
					# option, though it's also tested through the case below.
					choice = context.random.choice(list(previous))
				else:
					choice, _ = gap.get_random_choice(context)

				previous.add(choice)
				answers[gap.index] = choice
				valid[gap.index] = gap.is_valid_answer(choice)
				all_empty = all_empty and self._is_empty_answer(choice, context)

			if all_empty and context.workarounds.disallow_empty_answers:
				pass  # retry
			else:
				return answers, valid, self.compute_score_by_indices(answers, context)

	def readjust_scores(self, driver, random, report):
		pass

	def compute_score(self, answers, context):
		gaps = dict()
		for gap in self.gaps.values():
			gaps[gap.get_export_name()] = gap.index

		indexed_answers = dict()
		for name, value in answers.items():
			indexed_answers[gaps[name]] = value
		return self.compute_score_by_indices(indexed_answers, context)

	def compute_score_by_indices(self, answers, context):
		score = Decimal(0)
		given_answers = set()

		for index, text in answers.items():
			if not self.identical_scoring:
				normalized = text

				if not context.workarounds.identical_scoring_ignores_comparator:
					if self.comparator == ClozeComparator.ignore_case:
						normalized = text.casefold()
				if normalized in given_answers:
					continue
				given_answers.add(normalized)

			score += self.gaps[index].get_score(text)

		return score
