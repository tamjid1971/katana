from unit import BaseUnit
from units import PrintableDataUnit, NotApplicable
from collections import Counter
import sys
from io import StringIO
import argparse
import os
from units.esoteric.brainfuck import evaluate_brainfuck
from pwn import *
import traceback

'''
JOHN:
	From what I have found, there are "two" renditions of the Pikalang...
	One of which is a straight mapping to Brainfuck, the other is not.
	For the latter, I have shamelessly stolen code from
	   https://github.com/joelsmithjohnson/pikachu-interpreter
	The Katana code attempts that first. If it fails, it tries to
	remap it Brainfuck, and then it just passes it to Brainfuck unit.

	It is, quote Caleb, a "quite a hacky hack".
'''

class SyntaxError(Exception):
	pass

def syntax_error(lineNo):
	"""Display information about syntax errors in the pikachu program and exit

	Arguments:
	lineNo -- the line where the syntax error was found.
	"""
	# log.failure("Pikalang Syntax Error on line: {}".format(lineNo))

	raise SyntaxError # This must not be proper Pikalang for this rendition.

class PikaStack():
	"""
	Encapsulate Stack specific data & methods defined in the pikachu language.

	PikaStack()
	ADD() -> void
	SUB() -> void
	MULT() -> void
	DIV() -> void
	POP() -> int, 'NaN', or None
	PUSH() -> void
	PEEK() -> int, 'NaN', or None
	EMPTY() -> bool
	"""

	def __init__(self):
		"""Construct a PikaStack object.
		"""
		self.elements = []

	def ADD(self):
		""" Add the top two elements on the stack.

		Adds the top two elements on the stack and pushes the result back onto 
		the stack.
		
		Error handling:
		If the stack is empty, nothing happens.
		If the stack only has a single element, the result pushed to the top 
		of the stack is float("NaN").
		"""
		if self.__check_binary_op():
			a = self.POP()
			b = self.POP()
			self.PUSH(a+b)
	
	def SUB(self):
		"""Subtracts the top two elements.
		
		Subtracts the first element on the stack from the second element and
		pushes the result back onto the stack.

		Error Handling:
		If the stack is empty, nothing happens.
		If the stack only has a single element, the result pushed to the top 
		of the stack is float("NaN")
		"""
		if self.__check_binary_op():
			a = self.POP()
			b = self.POP()
			self.PUSH(b-a)
	
	def MULT(self):
		"""Multiplies the top two elements on the stack.

		Multiplies the top two elements on the stack and pushes the result 
		back onto the stack.

		Error handling:
		If the stack is empty, nothing happens.
		If the stack only has a single element, the result pushed to the top 
		of 	the stack is float("NaN")
		"""
		if self.__check_binary_op():
			a = self.POP()
			b = self.POP()
			self.PUSH(a*b)

	def DIV(self):
		"""Divides the top two elements on the stack

		Divides the second element on the stack by the first element on the 
		stack, and pushes the result back on top of the stack.
		
		Error Handling:
		If the stack is empty, nothing happens.
		If the stack only has a single element, the result pushed to the top 
		of the stack is float("NaN")
		If the divisor is '0', the result pushed to the top of the stack is 
		float("NaN")
		"""
		if self.__check_binary_op():
			a = self.POP()
			b = self.POP()
			if a == 0:
				self.PUSH(float('NaN'))
			else:
				self.PUSH(b//a)

	def POP(self):
		"""Pops and returns the top element from the stack.

		Error Handling:
		If the stack is empty None is returned.
		"""
		if len(self.elements):
			return self.elements.pop()
		else:
			return None

	def PUSH(self, element):
		"""Pushes an element to the top of the stack.

		Arguments:
		element -> The element to push on the top of the stack.
		"""
		self.elements.append(element)

	def PEEK(self):
		"""Returns the top element from the stack without removing it.

		Error Handling:
		If the stack is empty None is returned.
		"""
		if len(self.elements):
			return self.elements[-1]
		else:
			return None

	def EMPTY(self):
		"""Returns True if the stack is empty, false otherwise.
		"""
		return len(self.elements) == 0


	def __check_binary_op(self):
		"""Returns True if it is safe to perform a binary op, False otherwise.

		Verifies a binary operation can take place. If the stack is empty, 
		nothing happens. If the stack has a single element, it is replaced 
		with float("NaN").

		Returns True if there are at least 2 elements on the stack.
		Returns False if there is 0 or 1 elements on the stack.
		""" 
		if not len(self.elements):
			return False
		if len(self.elements) == 1:
			self.elements[0] = float('NaN')
			return False
		return True
	
	def __str__(self):
		"""Defines the string representation of the PikaStack object."""
		return str(self.elements)


class PikaReader():
	"""Provide a basic pikachu assembler and command parser.
	
	Methods:
	PikaReader(fileName) -> PikaReader
	goto(lineNo) -> void
	"""
	def __init__(self, fileName):
		"""Construct a PikaReader Object.

		Arguments:
		fileName -> the path to a pika file.
		"""
		l = fileName.split('\n')
		self.lines = {x:l[x].strip() for x in range(len(l))}
		self.lineNo = -1


	def __next__(self):
		"""Provide support for the next() function.

		next(this) is used to loop through the pikachu code a line at a time.
		
		Exceptions:
		StopIteration -- when the end of the file has been reached.
		"""
		self.lineNo += 1
		if self.lineNo >= len(self.lines):
			raise StopIteration
		line = self.lines[self.lineNo]
		line = line.split("//")[0]
		if not line:
			return self.__next__()
		
		#check for invalid repetition of pi, pika, pikachu
		target = None
		reps = 0
		for term in line.split():
			if term == target:
				reps += 1
				if reps >= 3:
					syntax_error(self.lineNo)
			else:
				target = term
				reps = 1

		return line

	def goto(self, lineNo):
		"""Directs the reader to a specific line of code.

		Arguments:
		lineNo -- the line of code (1 based) to set the reader to.
		
		Error Handling:
		If lineNo is greater than the number of lines in the code. The reader 
		will be set at the end of the code.
		"""
		if lineNo >= len(self.lines):
			lineNo = len(self.lines)
		self.lineNo = lineNo - 2


def run(fileName, args):
	"""Run a specified Pikachu file in a virtual environment.

	Arguments:
	fileName -- the name and path of a file containing a pikachu program.
	args -- the command line arguments specified when the pikachu interpreter
	was run.
	"""
	piStack = PikaStack()
	pikaStack = PikaStack()

	output = []

	stackDict = {
		"pi pikachu": piStack,
		"pika pikachu": pikaStack
		}

	for a in args:
		piStack.PUSH(a)

	reader = PikaReader(fileName)
	while True:
		try:
			command = next(reader)
		except StopIteration:
			break
		terms = command.split()
		if len(terms) < 2:
			syntax_error(reader.lineNo)
		elif len(terms) < 3:
			command = " ".join(terms)
			if command == "pi pikachu":
				piStack.POP()
			elif command == "pika pikachu":
				pikaStack.POP()
			elif command == "pi pika":
				if not piStack.EMPTY():
					pikaStack.PUSH(piStack.PEEK())
			elif command == "pika pi":
				if not pikaStack.EMPTY():
					piStack.PUSH(pikaStack.PEEK())
			elif command == "pikachu pikachu":
				try:
					lineNo = len(next(reader).split())
				except StopIteration:
					syntax_error(reader.lineNo - 1)
				if piStack.PEEK() != pikaStack.PEEK():
					continue
				reader.goto(lineNo)
			elif command == "pika pika":
				try:
					lineNo = len(next(reader).split())
				except StopIteration:
					syntax_error(reader.lineNo - 1)
				if piStack.PEEK() == pikaStack.PEEK():
					continue
				reader.goto(lineNo)
			else:
				syntax_error(reader.lineNo)
		elif len(terms) < 4:
			try:
				tStack = stackDict[" ".join(terms[-2:])]
			except KeyError:
				syntax_error(reader.lineNo)
			command = terms[0]
			if command == "pikachu":
				tStack.DIV()
			else:
				tStack.PUSH(1)
		elif len(terms) < 5:
			try:
				tStack = stackDict[" ".join(terms[-2:])]
			except KeyError:
				syntax_error(reader.lineNo)
			command = " ".join(terms[:-2])
			if command == "pi pika":
				tStack.ADD()
			elif command == "pika pi":
				tStack.SUB()
			elif command == "pi pikachu":
				tStack.MULT()
			elif command == "pika pikachu":
				if not tStack.EMPTY():
					output.append(tStack.POP())
				else:
					pass
			elif command == "pikachu pikachu":
				n = tStack.POP()
				if n != None and type(n) == int:
					output.append(chr(n))
				else:
					pass
			else:
				tStack.PUSH(2)
		else:
			try:
				tStack = stackDict[" ".join(terms[-2:])]
			except KeyError:
				syntax_error(reader.lineNo)
			tStack.PUSH(len(terms)-2)

	return ''.join(output)


class Unit(PrintableDataUnit):

	PRIORITY = 40
	ARGUMENTS = [
		{ 'name': 		'pikalang_args', 
		  'type': 		list, 
		  'default': 	[], 
		  'required': 	False,
		  'help': 		'arguments to be passed to pikalang program'
		},
	]

	def __init__(self, katana, target, keywords=[]):
		super(Unit, self).__init__(katana, target)

		self.raw_target = self.target.stream.read().decode('utf-8')
		if ( self.raw_target.count('pi') < 10 ):
			raise NotApplicable("less than 10 occurences of 'pi'")

	# JOHN: This SHOULD be removed following the new unit argument restructure
	@classmethod
	def add_arguments(cls, katana, parser):
		parser.add_argument('--pikalang-args',  action='store_true', default=[], help='arguments to be passed to pikalang program')


	def evaluate(self, katana, case ):

		output = None
		try:
			output = run(self.raw_target, katana.config['pikalang_args'])
			katana.locate_flags(self, output)


		except SyntaxError:
			p_mappings = \
			["pikachu", "pikapi", 'pichu', 'pika', 'pipi', 'chu', 'ka', 'pi']
			r_mappings = [".", ",", '<', '[', '>', ']',  '-',  '+']

			for i in range(len(p_mappings)):
				self.raw_target = self.raw_target.replace(p_mappings[i], 
														  r_mappings[i])
			
			self.raw_target = self.raw_target.replace(' ' ,'')
			try:
				output = evaluate_brainfuck(self.raw_target, None)
			except (ValueError, TypeError):
				return

		if output:
			katana.locate_flags(self,output)
			katana.add_results(self,output)