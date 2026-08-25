"""
operator precedence (everything is left-to-right unless otherwise specified)
NOTE: %seteval can't have variables that expand to stuff other than integers.
      perhaps there could be some kind of thing that would switch modes. like
      perhaps if the line ends with a variable, it expands the whole line as
      normal, since in that case, there is no way to properly expand only part
      of it.

the ordering between 1 and 2 doesn't matter

0a. concatenation by juxtaposition (only for literals and variables)
0b. ()
1. ^ (right-to-left)
2. unary +, -, ~, & (right-to-left)
3. .
4. *, /, %
5. binary +, -
6. <<, >>
7. and
8. or, xor

NOTE: '.' is the explicit concatenation operator and '&' is the absolute value operator
"""

__all__ = (
	"TOKEN_NONE",
	"TOKEN_VAR",
	"TOKEN_LITERAL",
	"TOKEN_LPAREN",
	"TOKEN_RPAREN",
	"TOKEN_OP_UNARY",
	"TOKEN_OP_BINARY",
	"TOKEN_TEMPORARY",
	"type_map",
	"Token",
	"lex",
	"strtok",
	"is_valid_variable",
	"concat",
	"concat_implicit",
)

from dataclasses import dataclass, field

TOKEN_NONE      = 0
TOKEN_VAR       = 1
TOKEN_LITERAL   = 2
TOKEN_LPAREN    = 3
TOKEN_RPAREN    = 4
TOKEN_OP_UNARY  = 6
TOKEN_OP_BINARY = 7
TOKEN_TEMPORARY = 8

type_map = {
	TOKEN_NONE      : "NONE",
	TOKEN_VAR       : "VAR",
	TOKEN_LITERAL   : "LITERAL",
	TOKEN_LPAREN    : "LPAREN",
	TOKEN_RPAREN    : "RPAREN",
	TOKEN_OP_UNARY  : "OP_UNARY",
	TOKEN_OP_BINARY : "OP_BINARY",
	TOKEN_TEMPORARY : "TEMPORARY",
}

@dataclass
class Token:
	_expr: str # not in C. the vstring stuff is enough to match this behavior
	type: int  # u8

	# vstring
	ofs: int   # in C, this can probably be `ptr` instead of `ofs` since the line buffer is pre-allocated
	len: int   # u64

	@property
	def value(self) -> str:
		return self._expr[self.ofs: self.ofs + self.len]

	@property
	def order(self) -> int:
		# none of this matters
		if self.type in (TOKEN_LITERAL, TOKEN_VAR):
			return 0

		if self.type in (TOKEN_LPAREN, TOKEN_RPAREN):
			return 1

		if self.type == TOKEN_OP_UNARY:
			return 3

		match self.value:
			case '^'             : return 2
			case '.'             : return 4
			case '*' | '/' | '%' : return 5
			case '+' | '-'       : return 6
			case "<<" | ">>"     : return 7
			case "and"           : return 8
			case "or" | "xor"    : return 9

		raise ValueError(f"`Token.order`: unrecognized token: '{self.value}'")

	def __str__(self) -> str:
		return self.value

	def __repr__(self) -> str:
		return f"Token(ofs={self.ofs:3}, len={self.len:2}, order={self.order}, type={type_map[self.type]:9}, value={self.value!r})"

def lex(expr: str, vars: dict) -> list[Token]:
	tokens = [Token(_expr=expr, type=TOKEN_NONE, ofs=0, len=0)]
	# TODO: consider removing the L/R paren tokens, and instead just storing depth.

	# NOTE: the errors handled here are exhaustive. the parser still needs to handle errors.
	#       this will just catch the obvious ones. firstly, it doesn't check variable contents

	depth = 0 # u64

	# `for (u64 i = 0; i < expr.len; i++)`
	i = -1
	while (i := i + 1) < len(expr):
		c = expr[i]

		# 9
		# 32, 33, 34, 35, 36, 37, 38, 39
		# 40, 41, 42, 43, 44, 45, 46, 47, 48, 49
		# 50, 51, 52, 53, 54, 55, 56, 57, 58, 59
		# 60, 61, 62
		# 92, 94, 97
		# 111, 120, 126
		# default, 33, 34, 35, 39, 44, 58, 59, and 61 => default

		match c:
			case str() as s if s.isspace(): # ' ', '\t'
				continue

			case '(':
				if tokens[-1].type in (TOKEN_LITERAL, TOKEN_VAR):
					raise ValueError("literal or variable cannot immediately be followed by a parentheses")
				depth += 1
				tokens.append(Token(_expr=expr, type=TOKEN_LPAREN, ofs=i, len=1))

			case ')':
				if depth == 0:
					raise ValueError("there cannot be more ')' than '(' at any point in the string")

				if tokens[-1].type == TOKEN_LPAREN:
					raise ValueError("parentheses group cannot be empty")

				if tokens[-1].type in (TOKEN_OP_BINARY, TOKEN_OP_UNARY):
					raise ValueError("right parentheses immediately after an operator is not valid")

				depth -= 1

				if tokens[-2].type == TOKEN_LPAREN:
					# (x) => x
					token = tokens.pop()
					tokens[-1] = token # replace LPAREN with the thing in the parentheses
				else:
					tokens.append(Token(_expr=expr, type=TOKEN_RPAREN, ofs=i, len=1))

			case '^' | '.' | '*' | '/' | '%':
				tokens.append(Token(_expr=expr, type=TOKEN_OP_BINARY, ofs=i, len=1))

			case '~':
				if tokens[-1].type == TOKEN_OP_UNARY and tokens[-1].value == '~':
					# an odd amount of these cancel out
					tokens.pop()
				else:
					tokens.append(Token(_expr=expr, type=TOKEN_OP_UNARY, ofs=i, len=1))

			case '&':
				# multiple consecutive absolute values do nothing after the first one.
				if tokens[-1].type != TOKEN_OP_UNARY or tokens[-1].value != '&':
					tokens.append(Token(_expr=expr, type=TOKEN_OP_UNARY, ofs=i, len=1))

			case '<' | '>': # <<, >>
				i += 1

				if i == len(expr):
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

				if expr[i] != c:
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

				tokens.append(Token(_expr=expr, type=TOKEN_OP_BINARY, ofs=i - 1, len=2))

			case 'a': # and
				i += 1

				if i == len(expr):
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

				if expr[i] != 'n':
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

				i += 1

				if i == len(expr):
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 2}.")

				if expr[i] != 'd':
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 2}.")

				tokens.append(Token(_expr=expr, type=TOKEN_OP_BINARY, ofs=i - 2, len=3))

			case 'x' | 'o': # xor, or
				if c == 'x':
					i += 1

					if i == len(expr):
						raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

					if expr[i] != 'o':
						raise ValueError(f"unknown or invalid character or token '{c}' at index {i - 1}.")

					# fallthrough

				# case 'o':
				i  += 1
				ofs = 1 + (c == 'x')

				if i == len(expr):
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - ofs}.")

				if expr[i] != 'r':
					raise ValueError(f"unknown or invalid character or token '{c}' at index {i - ofs}.")

				tokens.append(Token(_expr=expr, type=TOKEN_OP_BINARY, ofs=i - ofs, len=1 + ofs))

			case str() as s if s.isdigit(): # 0123456789
				if i > 0 and expr[i - 1].isspace() and tokens[-1].type in (TOKEN_LITERAL, TOKEN_VAR):
					raise ValueError("concatenation by juxtaposition cannot have whitespace separation.")

				# TODO: implement `0b`, `0o`, and `0x`?
				j = i

				while True:
					j += 1

					if j == len(expr):
						break

					if expr[j] == '_':
						if expr[j - 1] == '_':
							# no j > 0 check because at least one increment is guaranteed before this point
							raise ValueError("integer literal cannot have consecutive underscores")
					elif not expr[j].isdigit():
						break

				j -= 1

				if expr[j] == '_':
					raise ValueError("integer literal cannot end with an underscore")

				t = Token(_expr=expr, type=TOKEN_LITERAL, ofs=i, len=j - i + 1)

				if tokens[-1].type == TOKEN_OP_UNARY and tokens[-1].value == '&':
					# literals are already positive, so forcing it positive again is useless
					tokens[-1] = t
				else:
					tokens.append(t)
				i = j

			case '$':
				if i > 0 and expr[i - 1].isspace() and tokens[-1].type in (TOKEN_LITERAL, TOKEN_VAR):
					raise ValueError("concatenation by juxtaposition cannot have whitespace separation.")

				i += 1 # exclude the '$'
				j = i

				if i == len(expr):
					raise ValueError("`$` is not a valid variable name.")

				if expr[i] == '{':
					# this can probably be a `memchr` in C, though since variable names are probably
					# short, the call time might outweight the time of just doing it in a loop.
					i += 1

					while True:
						j += 1

						if j == len(expr):
							raise ValueError("unclosed bracket variable")

						# NOTE: this doesn't need to check for \w since the variable won't
						#       exist if it doesn't match, so an error will be thrown later
						#       when the variable name gets checked for existence.

						if expr[j] == '}':
							break

					length = j - i
				else:
					while True:
						if j == len(expr):
							break

						if not (expr[j].isalnum() or expr[j] == '_'):
							break

						j += 1

					length = j - i
					j -= 1

				t = Token(_expr=expr, type=TOKEN_VAR, ofs=i, len=length)
				if t.value not in vars:
					raise ValueError(f"variable does not exist: '{t.value}'")

				tokens.append(t)
				i = j

			case '+' | '-':
				t = Token(_expr=expr, type=TOKEN_NONE, ofs=i, len=1)

				# since these keys are contiguous, this can be a dispatch table in C,
				# rather than a switch/case or if-else.
				ttype = tokens[-1].type
				if   ttype == TOKEN_NONE:      t.type = TOKEN_OP_UNARY  # "-1"
				elif ttype == TOKEN_VAR:       t.type = TOKEN_OP_BINARY # "$x - 1"
				elif ttype == TOKEN_LITERAL:   t.type = TOKEN_OP_BINARY # "2 - 1"
				elif ttype == TOKEN_LPAREN:    t.type = TOKEN_OP_UNARY  # "(-1"
				elif ttype == TOKEN_RPAREN:    t.type = TOKEN_OP_BINARY # "(2) - 1"
				elif ttype == TOKEN_OP_UNARY:  t.type = TOKEN_OP_UNARY  # "- -1"
				elif ttype == TOKEN_OP_BINARY: t.type = TOKEN_OP_UNARY  # "2 - -1"
				else:
					raise ValueError(f"previous token has an unknown type: {ttype}")

				if t.type == TOKEN_OP_UNARY:
					if c == '+':
						continue

					if tokens[-1].type == TOKEN_OP_UNARY:
						if tokens[-1].value == '-':
							# an odd amount of these cancel out
							tokens.pop()
							continue

						if tokens[-1].value == '&':
							# &-x => &x
							continue
					elif tokens[-1].type == TOKEN_OP_BINARY:
						if tokens[-1].value == '+':
							# x + -y => `x - y`
							t.type = TOKEN_OP_BINARY
							tokens[-1] = t
							continue



				tokens.append(t)

			case '\\':
				# \$var can never be valid in %seteval
				raise ValueError("equation cannot contain backslashes")

			case _:
				raise ValueError(f"unknown or invalid character or token '{c}' at index {i}.")

	if depth != 0:
		raise ValueError(f"expression contains {depth} unclosed parentheses")

	for i in range(1, len(tokens)):
		cur  = tokens[i].type
		prev = tokens[i - 1].type

		if cur in (TOKEN_LITERAL, TOKEN_VAR):
			if prev == TOKEN_RPAREN:
				raise ValueError("right parentheses cannot immediately precede a variable or literal")
		elif cur == TOKEN_OP_UNARY:
			if prev in (TOKEN_LITERAL, TOKEN_VAR, TOKEN_RPAREN):
				raise ValueError("unary operator immediately after a variable, literal, or right parentheses is not valid")
		elif cur == TOKEN_OP_BINARY:
			if prev == TOKEN_OP_BINARY:
				raise ValueError(f"a binary operator immediately after a binary operator is not valid")
			elif prev == TOKEN_OP_UNARY:
				raise ValueError(f"a binary operator immediately after a unary operator is not valid")
			elif prev == TOKEN_LPAREN:
				raise ValueError(f"a binary operator immediately after left parentheses is not valid")

	if tokens[-1].type == TOKEN_NONE:
		raise ValueError("expression can't be empty")

	if tokens[-1].type in (TOKEN_OP_BINARY, TOKEN_OP_UNARY):
		raise ValueError("expression can't end with an operator")

	return tokens[1:]

# I am aware this is not what `strtok` actually is. I do not care.
strtok = lambda tokens: ' '.join(str(t.value) for t in tokens)

def is_valid_variable(var: str | int) -> bool:
	if type(var) is int:
		return True

	if var[0] == '_' or var[-1] == '_':
		return False

	for i in range(1, len(var)):
		if var[i] == '_':
			if var[i - 1] == '_':
				return False
		elif not var[i].isdigit():
			return False

	return True

def concat(l: int, r: int) -> int:
	return l * 10**len(str(abs(r))) + r*((l >= 0) - (l < 0))

def concat_implicit(tokens: list[Token], vars: dict) -> TmpToken:
	# The C code will have to do this way different.
	# this simulates the result without all the hard work.
	# probably C will do a binary search type thing
	# the list argument will probably be a pointer and a length
	out = 0

	for token in tokens:
		if token.type == TOKEN_LITERAL:
			out = concat(out, int(token.value))
		elif token.type == TOKEN_VAR:
			# NOTE: this assumes the variable is actually valid
			#       the C code would need to explicitly check before casting
			out = concat(out, int(vars[token.value]))
		else:
			assert False, "unreachable"

	return out
