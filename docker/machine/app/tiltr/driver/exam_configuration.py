from enum import Enum
from decimal import *


class CountSystem(Enum):
	PARTIAL = 0
	COMPLETE = 1


class MCScoring(Enum):
	DO_NOT_SAVE_EMPTY = 0
	SAVE_EMPTY = 1


class ScoreCutting(Enum):
	QUESTION = 0
	TEST = 1


class PassScoring(Enum):
	LAST = 0
	BEST = 1


class ExamConfiguration:
	count_system: CountSystem
	mc_scoring: MCScoring
	score_cutting: ScoreCutting
	pass_scoring: PassScoring

	def __init__(self):
		self.count_system = None
		self.mc_scoring = None
		self.score_cutting = None
		self.pass_scoring = None
		self.marks = None

	def set_count_system(self, value):
		self.count_system = CountSystem(value)

	def set_mc_scoring(self, value):
		self.mc_scoring = MCScoring(value)

	def set_score_cutting(self, value):
		self.score_cutting = ScoreCutting(value)

	def set_pass_scoring(self, value):
		self.pass_scoring = PassScoring(value)

	def clip_answer_score(self, score: Decimal) -> Decimal:
		if self.score_cutting == ScoreCutting.QUESTION:
			return max(score, Decimal(0))
		else:
			return score  # do not clip on question level
