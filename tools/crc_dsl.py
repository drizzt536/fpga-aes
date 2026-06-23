"""
CRC Assembly Format DSL Parser
Requires Python >=3.10.

the preprocessor is more general than the "runtime".

has global state for variable and macro definitions (not reentrant)

'|' is used for comments.
"""

import re
from os.path import expanduser

__version__ = "1.1.0"

FunctionType = type(lambda x: x) # same as types.FunctionType

DEPTH_CAP = 1024      # %macro + %include + %if/%loop/%foreach depth
ITER_CAP  = 1_000_000 # %loop iteration

def multisub(string: str, replacements: dict[str, str | FunctionType]) -> str:
	"makes multiple replacements in series based on the dictionary insert order"

	for pattern, repl in replacements.items():
		string = re.sub(
			pattern,
			'\n'.join(repl) if type(repl) is tuple else repl,
			string
		)

	return string

re.multisub = multisub
del multisub

__all__ = ["process", "preproc"]

class ExitMacro(BaseException):
	"line should be 1-indexed"

	def __init__(self, line: int):
		self.line = line

class ExitLoop(BaseException):
	"line should be 1-indexed. type should be 'continue' or 'break'"

	def __init__(self, type: str, tag: str, line: int):
		self.tag  = tag
		self.type = type # "continue" | "break"
		self.line = line

class ExitProgram(BaseException):
	"stop parsing more lines exit gracefully."

# preprocessor stuff
default_vars = {"$null": ""}

vars   = default_vars.copy()
macros = {}

def expand_vars_repl(match: re.Match, *, line_num: int) -> str:
	key = match.group()

	if key not in vars:
		raise ValueError(f"ERROR: line {line_num}: undefined variable: '{key}'")

	return vars[key]

def expand_vars(line: str, line_num: int) -> str:
	from functools import partial
	return re.sub(r"\$\w+", partial(expand_vars_repl, line_num=line_num), line)

def strip_line(line: str) -> str:
	return re.sub(r"\|.*$", '', line).strip()

def find_if_bounds(in_prgm: list[str], tag: str, line_idx: int, line_num: int) -> tuple[int | None, int]:
	# line_num is 1-indexed

	else_idx = None

	for i, line in enumerate(in_prgm[line_idx + 1:], line_idx + 1):
		line = strip_line(line)

		if line == f"%endif{tag}":
			return (i if else_idx is None else else_idx), i

		if line == f"%else{tag}":
			else_idx = i

	# ran out of lines in the file
	if else_idx is not None:
		line_idx = else_idx + 1

	keyword = "if" if else_idx is None else "else"
	raise ValueError(f"ERROR: line {line_num}: '%{keyword}{tag}' has no corresponding '%endif{tag}'. There might be nested conditionals with the same tag")

def find_block_end(start: str, end: str, tag: str, in_prgm: list[str], line_idx: int, line_num: int) -> int:
	# line_num is 1-indexed

	for i, line in enumerate(in_prgm[line_idx:], line_idx):
		if strip_line(line) == f"%{end}{tag}":
			return i

	print(in_prgm)
	raise ValueError(f"ERROR: line {line_num}: '%{start}{tag}' has no corresponding '%{end}{tag}'. There might be nested blocks with the same tag")

def parse_condition(cmd: str, op: str, arg1: str, arg2: str, line_num: int) -> bool:
	if not arg1:
		raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 1 cannot be empty")

	if op not in {"streq", "strne"}:
		arg1 = arg1.split(',')

		if op != "def":
			arg2 = arg2.split(',')

	match op:
		# variable operations
		case "def" | "undef":
			if arg2.strip():
				raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 2 must be empty")

			result = True
			for var in arg1:
				if (f"${var}" not in vars) if op == "def" else (f"${var}" in vars):
					result = False
					break

		# list operations
		case "subset" | "notsubset":
			result = frozenset(arg1).issubset( frozenset(arg2) )

			if op == "notsubset":
				result = not result

		# string operations
		case "streq" | "strne":
			result = arg1 == arg2

		# integer operations
		case "inrange" | "notinrange":
			try:
				# inclusive of both bounds
				arg2 = range(int(arg2[0]), int(arg2[1]) + 1)
			except ValueError:
				raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 1 element {i} is not an integer: '{x1}'{end_help}")

			# check if it is true for all
			result = True
			for i, x in enumerate(arg1, 1):
				try:
					x1 = int(x1, 0)
				except ValueError:
					raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 1 element {i} is not an integer: '{x1}'{end_help}")

				if (x1 not in arg2) if op == "inrange" else (x1 in arg2):
					result = False
					break

		case "eq" | "ne" | "lt" | "le" | "gt" | "ge":
			if len(arg1) != len(arg2):
				raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' arguments must be the same length")

			cmp = {
				"eq": int.__eq__, "ne": int.__ne__,
				"lt": int.__lt__, "ge": int.__ge__,
				"le": int.__le__, "gt": int.__gt__,
			}[op]

			# elementwise, they must all be true

			end_help = f". did you mean 'str{op}'?" if op in {"eq", "ne"} else ''
			result = True
			for i, (x1, x2) in enumerate(zip(arg1, arg2), 1):
				try:
					x1 = int(x1, 0)
				except ValueError:
					raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 1 element {i} is not an integer: '{x1}'{end_help}")

				try:
					x2 = int(x2, 0)
				except ValueError:
					raise ValueError(f"ERROR: line {line_num}: `{cmd}` operator '{op}' argument 2 element {i} is not an integer: '{x2}'{end_help}")

				if not cmp(x1, x2):
					result = False
					break

		case _:
			raise ValueError(f"ERROR: line {line_num}: unknown `{cmd}` operator: '{op}'")

	return result

def eval_expr(expr: str, line_num: int) -> str:
	import ast

	expr = (
		expr
		.replace('^'  , "**")
		.replace('/'  , "//")
		.replace("and", '&')
		.replace("or" , '|')
		.replace("xor", '^')
	)

	allowed_types =           \
		  ast.Add    | ast.Sub \
		| ast.Mod    | ast.Pow  \
		| ast.UAdd   | ast.USub  \
		| ast.BitAnd | ast.BitOr  \
		| ast.Invert | ast.BitXor  \
		| ast.RShift | ast.LShift   \
		| ast.BinOp  | ast.UnaryOp   \
		| ast.Mult   | ast.FloorDiv   \

	try:
		tree = ast.walk(ast.parse(expr, mode="eval"))
	except ValueError, SyntaxError:
		raise ValueError(f"ERROR: line {line_num}: `%seteval` has invalid expression")

	next(tree) # skip the tree base since it is always ast.Expression

	for node in tree:
		if isinstance(node, ast.Constant):
			if type(node.value) is not int:
				raise ValueError(f"ERROR: line {line_num}: `%seteval` expression contains a non-integer constant")
		elif not isinstance(node, allowed_types):
			raise ValueError(f"ERROR: line {line_num}: `%seteval` contains a disallowed operation")

	return str(eval(expr, {}, {}))

def _preproc(
	in_prgm: list[str],
	out_prgm: list[str] | None = None,
	start_line: int = 1, # only for printouts
	depth: int = 0,
	debug: bool = False
) -> list[line]:
	if depth > DEPTH_CAP:
		# this is a sum of macro depth plus if condition depth
		raise Exception(f"evaluation depth cap ({DEPTH_CAP}) exceeded")

	if out_prgm is None:
		out_prgm = []

	skip_till = 0 # for skipping after regions that have already been parsed (macro, loop, if)

	for line_idx, line in enumerate(in_prgm):
		if line_idx < skip_till:
			continue

		line_num = start_line + line_idx


		if not line:
			continue

		if line.lstrip().startswith("%raw["):
			if not line.rstrip().endswith("]"):
				# raw lines cannot have comments or they won't work.
				raise ValueError(f"ERROR: line {line_num}: '%raw[...' line doesn't end with ']'")

			# no variable expansions inside raw blocks
			# do this before expanding variables
			out_prgm.append(line[5:-1].strip())
			continue

		line = strip_line(line) # remove comments and strip whitespace

		if line[0] != '%':
			out_prgm.append(expand_vars(line, line_num))
			continue

		line = expand_vars(line, line_num)

		if (match := re.fullmatch(r"%if(\d*)\[(\w+)\]\[(.*?)\]\[(.*)\](?:\s*then)?", line)):
			tag, op, arg1, arg2 = match.groups()

			else_idx, endif_idx = find_if_bounds(in_prgm, tag, line_idx, line_num)

			result = parse_condition("if", op, arg1, arg2, line_num)

			# expand out whichever path was correct
			try:
				_preproc(
					in_prgm=(
						in_prgm[line_idx + 1:else_idx]
						if result else
						in_prgm[else_idx + 1:endif_idx]
					),
					out_prgm=out_prgm,
					start_line=line_num if result else start_line + else_idx + 1,
					depth=depth + 1,
					debug=debug
				)
			except ExitLoop as e:
				if e.type == "break" and e.tag == tag:
					pass

				raise e # either the tag doesn't match or it is a %continue

			skip_till = endif_idx + 1
		elif (match := re.fullmatch(r"%loop(\d*)", line)):
			tag = match.group(1)

			endloop_idx = find_block_end("loop", "endloop", tag, in_prgm, line_idx, line_num)

			loopcount = 0

			while True:
				if (loopcount := loopcount + 1) >= ITER_CAP:
					raise Exception(f"ERROR: line {line_num}: %loop iteration count cap ({ITER_CAP}) exceeded")

				try:
					_preproc(
						in_prgm=in_prgm[line_idx + 1:endloop_idx],
						out_prgm=out_prgm,
						start_line=line_num,
						depth=depth + 1,
						debug=debug
					)
				except ExitLoop as e:
					if e.tag != tag:
						raise e # not intended for this loop

					if e.type == "break":
						break

			skip_till = endloop_idx + 1
		elif (match := re.fullmatch(r"%foreach(\d*)\[(\w+)\]\[(.+)\](?:\s*do)?", line)):
			tag, var, expr = match.groups()

			endforeach_idx = find_block_end("foreach", "endfor", tag, in_prgm, line_idx, line_num)

			var = f"${var}"

			old_value = vars.get(var, None)

			for elem in expr.split(','):
				vars[var] = elem

				try:
					_preproc(
						in_prgm=in_prgm[line_idx + 1:endforeach_idx],
						out_prgm=out_prgm,
						start_line=line_num,
						depth=depth + 1,
						debug=debug
					)
				except ExitLoop as e:
					if e.tag != tag:
						raise e # not intended for this loop

					if e.type == "break":
						break

			if old_value is None:
				del vars[var]
			else:
				vars[var] = old_value

			skip_till = endforeach_idx + 1
		elif (match := re.fullmatch(r"%(x?)defmacro\[(\w+)\]\[(\d+)\](?:\s*as)?", line)):
			expand, name, argc = match.groups()
			expand = expand == 'x'

			endmacro_idx = find_block_end("defmacro", "endmacro", '', in_prgm, line_idx, line_num)

			macro_def = [strip_line(line) for line in in_prgm[line_idx + 1:endmacro_idx]]
			if expand:
				macro_def = [
					expand_vars(line, line_num + i)
					for i, line in enumerate(macro_def)
				]

			macros[f"{name}-{argc}"] = line_num, macro_def
			skip_till = endmacro_idx + 1
		elif (match := re.fullmatch(r"%macro\[(\w+)\]\[(.*)\]", line)):
			name, args = match.groups()

			argc = args.count(',') + 1 if args else 0

			macro_line, macro_def = macros.get(f"{name}-{argc}", (None, None, None))

			if macro_def is None:
				raise ValueError(f"ERROR: line {line_num}: macro '{name}' with {argc} arguments does not exist.")

			try:
				args = args.split(',')

				macro_def = [
					re.sub(r"#(\d+)", lambda m: args[int(m.group(1)) - 1], line)
					for line in macro_def
				]
			except IndexError:
				raise ValueError(f"ERROR: line {macro_line}: macro '{name}' contains an invalid argument reference")

			try:
				_preproc(
					in_prgm=macro_def,
					out_prgm=out_prgm,
					start_line=macro_line,
					depth=depth + 1,
					debug=debug
				)
			except ExitMacro:
				pass
		elif (match := re.fullmatch(r"%set\[(\w+)\]\[([^|$]*?)\]", line)):
			# '|' and '$' already shouldn't be there, but explicitly disallow them
			var, val = match.groups()

			vars[f"${var}"] = val
		elif (match := re.fullmatch(r"%unset\[([\w,]+)\]", line)):
			for var in match.group(1).split(','):
				vars.pop(f"${var}", None)
		elif (match := re.fullmatch(r"%(pop|shift)\[(\w*)\]\[(\w+)\]", line)):
			cmd, outvar, invar = match.groups()

			outvar = f"${outvar}"
			invar  = f"${ invar}"

			if invar not in vars:
				raise ValueError(f"ERROR: line {line_num}: '%{cmd}': list variable does not exist")

			# %(pop|shift)[$null][list] just pops and stores it nowhere

			split = getattr(vars[invar], "rsplit" if cmd == "pop" else "split")(',', 1)
			if len(split) == 1:
				vars[invar] = ''

				if outvar != '$':
					vars[outvar] = split[0]
			else:
				vars[invar] = split[0]
				if outvar != '$':
					vars[outvar] = split[1]
		elif (match := re.fullmatch(r"%index\[(\w+)\]\[(\d+)\]\[(.*?)\]", line)):
			outvar, index, expr = match.groups()

			expr = expr.split(',')
			try:
				vars[f"${outvar}"] = expr[int(index)]
			except IndexError:
				raise ValueError(f"ERROR: line {line_num}: '%index': list index '{index}' is outside of list bounds [1,{len(expr)}]")
		elif (match := re.fullmatch(r"%len\[(\w+)\]\[(.*)\]", line)):
			outvar, expr = match.groups()
			vars[f"${outvar}"] = str(expr.count(',') + 1 if expr else 0)
		elif (match := re.fullmatch(r"%repl\[(\w+)\]\[([^|$]*?)\]\[(.*?)\]\[([^$[|]+?)\]", line)):
			var, src, needle, repl = match.groups()
			vars[f"${var}"] = repl.join(src.split(needle))
		elif (match := re.fullmatch(r"%substr\[(\w+)\]\[(\d)(?:,(\d+)(?:,(\d+))?)?\]\[(.*)\]", line)):
			outvar, start, stop, step, expr = match.groups()

			start = int(start) - 1

			if stop is not None:
				stop = int(stop)

			if step is not None:
				step = int(step)

			vars[f"${outvar}"] = expr[start:stop:step]
		elif (match := re.fullmatch(r"%seteval\[(\w+)\]\[(.+)\]", line)):
			var, expr = match.groups()
			vars[f"${var}"] = eval_expr(expr, line_num)
		elif (match := re.fullmatch(r"%log\[(.+)\]", line)):
			print(match.group(1))
		elif (match := re.fullmatch(r"%fatal\[(.+)\]", line)):
			raise Exception(f"ERROR: line {line_num}: `%fatal`: " + match.group(1))
		elif (match := re.fullmatch(r"%(break|continue)(\d*)", line)):
			raise ExitLoop(*match.groups(), line=line_num)
		elif (match := re.fullmatch(r"%exitmacro", line)):
			raise ExitMacro(line=line_num)
		elif (match := re.fullmatch(r"%exit", line)):
			raise ExitProgram()
		elif (match := re.fullmatch(r"%include\[(.+)\]", line)):
			filepath = expanduser(match.group(1))

			try:
				with open(filepath, "r") as f:
					include_lines = f.readlines()
			except FileNotFoundError: raise ValueError(f"ERROR: line {line_num}: '%include': path does not exist")
			except IsADirectoryError: raise ValueError(f"ERROR: line {line_num}: '%include': path is a directory")
			except PermissionError:   raise ValueError(f"ERROR: line {line_num}: '%include': no permissions")
			except OSError:           raise ValueError(f"ERROR: line {line_num}: '%include': path is invalid")

			try:
				_preproc(
					in_prgm=include_lines,
					out_prgm=out_prgm,
					start_line=1,
					depth=depth + 1,
					debug=debug
				)
			except ExitProgram:
				pass

			del include_lines # probably this is large. delete to save memory
		elif debug:
			out_prgm.append(f"| UNKNOWN LINE: {line}")
		else:
			raise ValueError(f"ERROR: line {line_num}: line doesn't match any valid keywords")

	return out_prgm

def preproc(
	in_prgm: list[str],
	start_vars: dict[str, str] | None = None,
	debug: bool = False,
	depth_cap: int | None = DEPTH_CAP,
	iter_cap: int | None = ITER_CAP,
) -> list[str]:
	"takes in the program as a list of lines, preprocesses and outputs as a list of lines"
	global vars, macros, DEPTH_CAP, ITER_CAP

	if start_vars is not None:
		vars = {**default_vars, **start_vars}

	out_prgm = []

	old_depth_cap = DEPTH_CAP
	old_iter_cap  = ITER_CAP

	DEPTH_CAP = float('inf') if depth_cap is None else depth_cap
	ITER_CAP  = float('inf') if  iter_cap is None else  iter_cap

	try:
		return _preproc(
			in_prgm,
			out_prgm=out_prgm,
			start_line=1,
			depth=0,
			debug=debug
		)
	except ExitLoop as e:
		raise ValueError(f"ERROR: line {e.line}: `%{e.type}{e.tag}` used outside of a loop.")
	except ExitMacro as e:
		raise ValueError(f"ERROR: line {e.line}: `%exitmacro{e.tag}` used outside of a loop.")
	except ExitProgram:
		return out_prgm
	finally:
		vars = default_vars.copy()
		macros.clear()
		DEPTH_CAP = old_depth_cap
		ITER_CAP = old_iter_cap

def process(
	program: list[str],
	grammar: dict[str, str | FunctionType],
	pp_vars: dict[str, str] | None = None,
	*,
	pp_debug: bool = False,
	strict: bool = True
) -> list[str]:
	grammar = {
		r"@sh[lr] @regb?\[\d+\], @imm\[0\]$": '',
		**grammar,
		r"@raw\[(.+)\]": lambda m: m.group(1)
	}

	program = [
		re.multisub(line, grammar)
		for line in
		preproc(program, pp_vars, pp_debug)
	]

	program = [line for line in program if line]

	if not strict:
		return program

	for line in program:
		if (errors := re.findall(r"@\w+(?:\[.+?\])?", line)):
			raise Exception(f"ERROR: grammar is not exhaustive: '{"', '".join(errors)}'")

	return program

if __name__ == "__main__":
	print("crc_dsl.py should not be used as a top-level program")
	exit(1)
