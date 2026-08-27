# parser prototype v2: recursive descent

from expr_lexer import *
# recursive descent

# typedef struct { ... } ParserState;
# vars will be a global
class ParserState:
	def __init__(self, tokens: list[Token], vars: dict):
		self.ptr  = tokens
		self.idx  = 0
		self.len  = len(tokens)
		self.vars = vars

	# these will be macros, or inline
	@property
	def current(self) -> Token:
		return self.ptr[self.idx]

	@property
	def done(self) -> Token:
		return self.idx >= self.len

	def consume(self) -> None:
		self.idx += 1

def parse_0(state: ParserState):
	"0. literals and variables"
	start = state.idx
	end = start

	token = state.ptr[start]
	if token.type == TOKEN_VAR and not is_valid_variable(state.vars[token.value]):
		raise ValueError(f"invalid variable: '${token.value}'")

	while True:
		end += 1

		if end == state.len:
			break

		token = state.ptr[end]

		if token.type == TOKEN_VAR:
			if not is_valid_variable(state.vars[token.value]):
				raise ValueError(f"invalid variable: '${token.value}'")
		elif token.type != TOKEN_LITERAL:
			break

	state.idx = end

	if start + 1 == end:
		# only one. nothing to concat

		token = state.ptr[start]
		return int(state.vars[token.value] if token.type == TOKEN_VAR else token.value)

	return concat_implicit(state.ptr[start:end], state.vars)

def parse_1(state: ParserState) -> int:
	"1. ()"

	if state.done:
		raise ValueError("unexpected end of input")

	token = state.current

	if token.type == TOKEN_LPAREN:
		state.consume()
		value = parse_9(state) # restart

		if state.done or state.current.type != TOKEN_RPAREN:
			raise ValueError("expected ')'")

		state.consume()
		return value

	if token.type in (TOKEN_LITERAL, TOKEN_VAR):
		return parse_0(state)

	raise ValueError(f"unexpected token: {token.value!r}")

def parse_2(state: ParserState) -> int:
	"2. ^ (right-to-left)"
	left = parse_1(state)

	if state.done:
		return left

	token = state.current

	if token.type != TOKEN_OP_BINARY or token.value != '^':
		return left

	state.consume()
	right = parse_3(state)

	return 1 // (left ** -right) if right < 0 else left ** right

def parse_3(state: ParserState) -> int:
	"3. unary -, ~, &"

	if state.done or state.current.type != TOKEN_OP_UNARY:
		return parse_2(state)

	token = state.current
	state.consume()
	right = parse_3(state)

	if token.value == '-':
		return -right
	elif token.value == '~':
		return ~right
	else:
		return abs(right)

def parse_4(state: ParserState) -> int:
	"4. ."
	left = parse_3(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value != '.':
			break

		state.consume()
		right = parse_3(state)

		left = concat(left, right)

	return left

def parse_5(state: ParserState) -> int:
	"5. *, /, %"
	left = parse_4(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value not in ('*', '/', '%'):
			break

		state.consume()
		right = parse_4(state)

		if token.value == '*':
			left = left * right
		elif token.value == '/':
			left = left // right
		else:
			left = left % right

	return left

def parse_6(state: ParserState) -> int:
	"6. binary +, -"
	left = parse_5(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value not in ('+', '-'):
			break

		state.consume()
		right = parse_5(state)

		if token.value == '+':
			left = left + right
		else:
			left = left - right

	return left

def parse_7(state: ParserState) -> int:
	"7. <<, >>"
	left = parse_6(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value not in ("<<", ">>"):
			break

		state.consume()
		right = parse_6(state)

		if token.value == "<<":
			left = left << right
		else:
			left = left >> right

	return left

def parse_8(state: ParserState) -> int:
	"8. and"
	left = parse_7(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value != "and":
			break

		state.consume()
		right = parse_7(state)

		left = left & right

	return left

def parse_9(state: ParserState) -> int:
	"9. or, xor"
	left = parse_8(state)

	while not state.done:
		token = state.current

		if token.type != TOKEN_OP_BINARY:
			break

		if token.value not in ("or", "xor"):
			break

		state.consume()
		right = parse_8(state)

		if token.value == "or":
			left = left | right
		else:
			left = left ^ right

	return left

parse = parse_9

def eval(expr: str, vars: dict) -> int:
	tokens = lex(expr, vars)
	return parse(ParserState(tokens, vars))
