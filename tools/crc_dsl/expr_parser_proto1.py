# parser prototype v1: custom algorithm + Shunting-Yard

from expr_lexer_proto import *

from dataclasses import dataclass, field

# NOTE: in C, the two types (Token and TmpToken) will have the same size, so they will be
#       interchangeable. also, these will probably have a `u64 next;` field so that I can
#       make them a linked list. this is because during parsing, it does a lot of stuff
#       where it replaces >=1 elements with 1 element, and this would either require a lot
#       of slow memcopies, or it could be turned into a linked list (probably still a
#       contiguous array though)

# NOTE: the `order` attribute here will probably end up being a lookup table based on the
#       type so it doesn't have to take up extra space with an extra field that is trivially
#       computable from the others.

@dataclass
class TmpToken:
	"temporary token to store results of previous operations"

	value: int

	@property
	def type(self) -> int:
		# NOTE: in the C version, this will probably have to be more than one
		#       token type depending on if the temporary is `i64` or `mpz_t`.
		return TOKEN_TEMPORARY

	@property
	def order(self) -> int:
		return 0

	def __str__(self) -> str:
		return f"{self.value}"

	def __repr__(self) -> str:
		return f"TmpToken(order=0, type=TEMPORARY, value={self.value})"

def find_next_subexpr(tokens: list[Token | TmpToken], first: int) -> tuple[int, int, int]:
	for i in range(first, len(tokens)):
		if tokens[i].type == TOKEN_LPAREN:
			first = i
			break
	else:
		# no parentheses
		return 0, len(tokens), 0

	region_start = first

	for i in range(first + 1, len(tokens)):
		if tokens[i].type == TOKEN_RPAREN:
			return region_start, i + 1, first
		
		if tokens[i].type == TOKEN_LPAREN:
			region_start = i
			
	return 0, len(tokens), 0
	
def simple_pop_and_eval(ops: list[int], vals: list[int]):
	op = ops.pop()

	if op.type == TOKEN_OP_UNARY:
		match op.value:
			# NOTE: unary '+' never happens
			case '-': vals[-1] = -vals[-1]
			case '~': vals[-1] = ~vals[-1]
			case '&': vals[-1] = abs(vals[-1])
			case _:
				assert False, "unreachable"

		return

	# binary
	r = vals.pop()
	l = vals.pop()

	match op.value:
		case '^': vals.append(1 // (l ** -r) if r < 0 else l ** r)
		case '.': vals.append(concat(l, r))
		case '*': vals.append(l * r)
		case '/': vals.append(l // r)
		case '%': vals.append(l % r)
		case '+': vals.append(l + r)
		case '-': vals.append(l - r)
		case "<<": vals.append(l << r)
		case ">>": vals.append(l >> r)
		case "and": vals.append(l & r)
		case "or": vals.append(l | r)
		case "xor": vals.append(l ^ r)
		case _:
			assert False, "unreachable"

def parse_simple(tokens: list[Token | TmpToken]) -> TmpToken:
	"""
	parse the expression assuming all implicit concats were resolved
	and there are no parentheses (other than potentially wrapping ones).
	"""

	if tokens[0].type == TOKEN_LPAREN:
		# it is safe to assume the two parentheses are paired
		tokens = tokens[1:-1]

	vals = []
	ops  = []

	for t in tokens:
		if t.type == TOKEN_TEMPORARY:
			vals.append(int(t.value))
			continue

		while ops:
			# prefix operators always push
			# this is just so `left ^ <unary> right` works.
			if t.type == TOKEN_OP_UNARY:
				break

			top_order = ops[-1].order
			# NOTE: lower order binds tighter

			if top_order > t.order or (t.order in (2, 3) and top_order == t.order):
				# NOTE: ^ and unary are right associative
				break

			# if the new thing binds tighter
			simple_pop_and_eval(ops, vals)

		ops.append(t)

	# flush any remaining operators
	while ops:
		simple_pop_and_eval(ops, vals)

	if len(vals) != 1:
		raise ValueError("Evaluation failed: stack does not contain exactly one result.")

	return TmpToken(value=vals[0])


_concat_implicit = concat_implicit

def concat_implicit(tokens: list[Token], vars: dict) -> TmpToken:
	return TmpToken(value=_concat_implicit(tokens, vars))

def resolve_variables(tokens: list[Token], vars: dict) -> list[Token | TmpToken]:
	"resolve variables, implicit concatenation, and check variable values"
	i = 0

	while i < len(tokens):
		if tokens[i].type not in (TOKEN_LITERAL, TOKEN_VAR):
			i += 1
			continue

		start = i

		while True:
			i += 1

			if i == len(tokens):
				break

			if tokens[i].type not in (TOKEN_LITERAL, TOKEN_VAR):
				break

		end = i

		for t in tokens[start:end]:
			if t.type == TOKEN_LITERAL:
				continue

			if not is_valid_variable(vars[t.value]):
				raise ValueError(f"invalid variable: '${t.value}'")

		if end == 1 + start:
			if tokens[start].type == TOKEN_LITERAL:
				tokens[start] = TmpToken(value=int(tokens[start].value))
			elif tokens[start].type == TOKEN_VAR:
				tokens[start] = TmpToken(value=int(vars[tokens[start].value]))

			continue

		tokens = tokens[:start] + [concat_implicit(tokens[start:end], vars)] + tokens[end:]
		i = start + 1

	return tokens

def parse(tokens: list[Token], vars: dict) -> TmpToken:
	tokens = resolve_variables(tokens, vars)

	first = 0

	while len(tokens) > 1:
		start, end, first = find_next_subexpr(tokens, first)
		tokens = tokens[:start] + [parse_simple(tokens[start:end])] + tokens[end:]

	return tokens[0]

def eval(expr: str, vars: dict) -> int:
	return parse(lex(expr, vars), vars).value

# examples

"""
vars = {"w": 1, "x": 2, "y": 3, "z": 4, "a": "5", "b": "6", "c": "-7"}

expr = "-(($x / 4) % ${y}31_42$y$y) - ($y << (5 . ($x$y$x + 3))) and +3 or (- ~$x >> &$c) xor +12_345_678^--2"
print(eval(expr, vars))

expr = "-4^4 * 2 - ~5 . &-21 % +3 << 6 + 7 >> --7/2 and 255 or 3 xor --7"
print(eval(expr, vars))
"""
