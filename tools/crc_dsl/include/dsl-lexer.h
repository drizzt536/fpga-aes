#pragma once
#define DSL_LEXER_H

// lexer for `%seteval`

#include <ctype.h>
#include "dsl-except.h" // "dsl-vars.h"

typedef enum : u8 {
	TOKEN_OP_UNARY,
	TOKEN_OP_BINARY,
	TOKEN_OP = TOKEN_OP_BINARY, // use `token.type <= TOKEN_OP` to check VAR | LITERAL
	TOKEN_SOF,
	TOKEN_LPAREN,
	TOKEN_RPAREN,
	// these next ones have to be greater than all the others
	TOKEN_PRIMARY, // use `token.type >= TOKEN_PRIMARY` to check VAR | LITERAL
	TOKEN_VAR = TOKEN_PRIMARY,
	TOKEN_LITERAL,
	// intermediate result tokens
	TOKEN_SPZ,
	TOKEN_MPZ,
	TOKEN_STR, // this one shouldn't come up, I think.
} token_type_t;

#define is_primary(token) (token.type >= TOKEN_PRIMARY)
#define is_op(token)      (token.type <= TOKEN_OP)

typedef enum : u8 {
	/*
	operator precedence:
		between 0a and 0b, order doesn't strictly matter for correctness.
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
	*/

	ORDER_OTHER = 0, // NONE, VAR, LITERAL, LPAREN, RPAREN, SPZ, MPZ, STR
	ORDER_UNARY = 2, // unary +, -, ~, &. right-to-left
	ORDER_SHIFT = 6, // <<, >>
	ORDER_OR    = 8, // or, xor

	// binary operators
	ORDER_EXP = 1, // ^, right-to-left
	ORDER_CAT = 3, // .
	ORDER_MUL = 4, // *
	ORDER_DIV = 4, // /
	ORDER_MOD = 4, // %
	ORDER_ADD = 5, // binary +
	ORDER_SUB = 5, // binary -
	ORDER_SHL = 6, // <<
	ORDER_SHR = 6, // >>
	ORDER_AND = 7, // and
	ORDER_XOR = 8, // xor
	ORDER_IOR = 8, // or (inclusive)
} order_t;

typedef struct __attribute__((packed)) { // size=24, align=1
	union { // size=16, align=16
		// wide pointer for variable, literal, and parens
		vstring atom; // size=16, align=8

		// unary and binary operators
		struct {
			union { // size=8, align=8
				char *ptr;
				u64   ofs;
			};

			u8 len;        // size=1, align=1. operators are at most 3 characters
			order_t order; // size=1, align=1. order is in [0, 8].
			char _pad[6];  // match the size of the value and atom structs
		} op;

		var_val_union_t val; // size=16, align=16 temporary result (SPZ, MPZ)
	};

	u32          next; // size=4, align=4. this doesn't need to be u64 since this covers 96 GiB
	token_type_t type; // size=1, align=1
	char _pad[3];
} token_t;

typedef struct __attribute__((packed)) {
	token_t *array;
	u32 count;
} token_list;

typedef struct {
	token_list;
	u32 cap;
} token_list_builder;

[[maybe_unused]]
static void log_tokens(token_list tokens) {
	const int width = (int) ({
		// max required is 11 bytes
		char widthbuf[16];
		sprintf(widthbuf, "%u", tokens.count - 1);
		strlen(widthbuf);
	});

	printf("tokens: array=%#zx, count=%u\n", (u64) (uintptr_t) tokens.array, tokens.count);

	u32 i = 0;
	do {
		// NOTE: 11 == strlen("  order=x  ");
		token_t *t = tokens.array + i;

		const char *type_name;
		switch (t->type) {
			case TOKEN_OP_UNARY:  type_name = "OP_UNARY";  break;
			case TOKEN_OP_BINARY: type_name = "OP_BINARY"; break;
			case TOKEN_SOF:       type_name = "SOF";       break;
			case TOKEN_LPAREN:    type_name = "LPAREN";    break;
			case TOKEN_RPAREN:    type_name = "RPAREN";    break;
			case TOKEN_VAR:       type_name = "VAR";       break;
			case TOKEN_LITERAL:   type_name = "LITERAL";   break;
			case TOKEN_SPZ:       type_name = "SPZ";       break;
			case TOKEN_MPZ:       type_name = "MPZ";       break;
			case TOKEN_STR:       type_name = "STR";       break;
			default:              unreachable();
		}

		printf("\t[%*u] type=%-10s next=%3u", width, i, type_name, t->next);

		switch (t->type) {
			case TOKEN_SOF:
				printf("%11s(sentinel)", "");
				break;

			case TOKEN_VAR:
				printf("%11s%-5s = ", "", "name");
				printf("\"${%.*s}\"", (int) t->atom.len, t->atom.ptr);
				break;

			case TOKEN_LPAREN:
			case TOKEN_RPAREN:
			case TOKEN_LITERAL:
				printf("%11s%-5s = ", "", "value");
				printf("\"%.*s\"", (int) t->atom.len, t->atom.ptr);
				break;

			case TOKEN_OP_UNARY:
			case TOKEN_OP_BINARY:
				printf("  order=%u  ", t->op.order);
				printf("%11s%-5s = " + 4, "op");
				printf("\"%.*s\"", (int) t->op.len, t->op.ptr);
				break;

			case TOKEN_SPZ:
				printf("%11s%-5s = ", "", "value");
				put_spz(t->val.spz);
				putchar('\n');
				break;
			case TOKEN_MPZ: {
				#pragma GCC diagnostic push
				#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
				char *str = mpz_get_str(nullptr, 10, t->val.mpz);
				#pragma GCC diagnostic pop
				printf("%11s%-5s = ", "", "value");
				printf("%s", str);
				free(str);
				break;
			}
			case TOKEN_STR:
				printf("%11s%-5s = ", "", "value");
				printf("%.*s", (int) t->val.str.len, t->val.str.ptr);
				break;

			default:
				unreachable();
		}

		putchar('\n');

		i = t->next;
	} while (i != 0);
}

[[maybe_unused]]
static void log_tokens_expr(token_list tokens) {
	for (u32 i = 1; i != 0; i = tokens.array[i].next) {
		token_t *t = tokens.array + i;

		if (!( t[-1].type == TOKEN_OP_UNARY || ( is_primary(t[0]) && is_primary(t[-1]) ) ))
			putchar(' ');

		switch (t->type) {
			case TOKEN_SOF:
				break;
			case TOKEN_VAR:
				printf("${%.*s}", (int) t->atom.len, t->atom.ptr);
				break;
			case TOKEN_LITERAL:
			case TOKEN_LPAREN:
			case TOKEN_RPAREN:
				printf("%.*s", (int) t->atom.len, t->atom.ptr);
				break;

			case TOKEN_OP_UNARY:
			case TOKEN_OP_BINARY:
				printf("%.*s", (int) t->op.len, t->op.ptr);
				break;

			case TOKEN_SPZ:
				put_spz(t->val.spz);
				break;
			case TOKEN_MPZ: {
				#pragma GCC diagnostic push
				#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
				char *str = mpz_get_str(nullptr, 10, t->val.mpz);
				#pragma GCC diagnostic pop
				fputs(str, stdout);
				free(str);
				break;
			}
			case TOKEN_STR:
				printf("%.*s", (int) t->val.str.len, t->val.str.ptr);
				break;

			default:
				unreachable();
		}
	} // for

	putchar('\n');
}

#define lexer_oom() ({                                           \
	eprintf("ran out of memory lexing `%%seteval` expression."); \
	dsl_panic(EXCEPT_ERR_OOM);                                   \
	(void) 0;                                                    \
})                                                               \

static void push_token(token_list_builder *p2tokens, token_t token) {
	if unlikely (p2tokens->count == UINT32_MAX)
		// if it hasn't hit OOM yet, lie and pretend it has.
		// this is 96 GiB, which is absurd. There should not be 2^32 tokens.
		goto oom;

	if unlikely (p2tokens->count == p2tokens->cap) {
		token_t *const new_array = realloc(p2tokens->array, (p2tokens->cap * 3 >> 1) * sizeof(token_t));

		if unlikely (new_array == nullptr)
			goto oom;

		p2tokens->array = new_array;
	}

	p2tokens->array[p2tokens->count - 1].next = p2tokens->count;
	p2tokens->array[p2tokens->count] = token;
	p2tokens->count++;
	return;
oom:
	free(p2tokens->array);
	lexer_oom();
}

static bool is_int_var(var_t *var) {
	// returns true if the variable is an integer or coercible to an integer.

	if likely (var->val->type != VAR_STR)
		// most of the time, variables used in `%seteval` will continue to be used as such.
		return true;

	vstring val = var->val->str;
	if unlikely (val.len == 0)
		return false;

	if unlikely (!isdigit(val.ptr[0]) && !isdigit(val.ptr[val.len - 1]))
		// can't start or end with an underscore
		return false;

	val.len--; // already checked the last digit

	while (val.len --> 1) {
		char c = val.ptr[val.len];

		if (c == '_') {
			if (val.ptr[val.len - 1] == '_')
				return false;
		}
		else if (!isdigit(c))
			return false;
	}

	return true;
}

#define pop_token() ({                   \
	tokens.array[tokens.count].next = 0; \
	tokens.count--;                      \
	(void) 0;                            \
})

#define prev_token_n(TOKENS, N) ((TOKENS).array[(TOKENS).count - (N)])
#define prev_token  prev_token_n(tokens, 1)
#define prev2_token prev_token_n(tokens, 2)

[[maybe_unused]]
static token_list lex(vstring expr) {
	u64 depth = 0;
	(void) depth;

	// guess a new token starts every other character.
	// if the input has a lot of variables with long names, this could wildly over-allocate.
	// in case this is way too big, fall back to a one-page allocation.
	token_list_builder tokens = {
		.array = malloc((expr.len >> 1) * sizeof(token_t)),
		.count = 1,
		.cap   = (u32) (expr.len >> 1),
	};

	if unlikely (tokens.array == nullptr) {
		tokens.cap   = PAGE_SIZE / sizeof(token_t);
		tokens.array = malloc(tokens.cap*sizeof(token_t));

		if unlikely (tokens.array == nullptr)
			lexer_oom();
	}

	*tokens.array = (token_t) {
		.type = TOKEN_SOF,
		.next = 0,
	}; // circular reference

	for (u64 i = 0; i < expr.len; i++) {
		char c = expr.ptr[i];

		switch (c) {
			case '\t':
			case ' ':
				// skip whitespace
				break;
			case '(':
				if unlikely (is_primary(prev_token)) {
					eprintf("%s followed immediately by %s is invalid.", "LITERAL or VAR", "'('");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				depth++;
				push_token(&tokens, (token_t) {
					.atom = {
						.ptr = expr.ptr + i,
						.len = 1,
					},
					.next = 0,
					.type = TOKEN_LPAREN,
				});
				break;
			case ')':
				if unlikely (depth == 0) {
					eprintf("')' with no corresponding '(' is invalid.");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				if unlikely (prev_token.type == TOKEN_LPAREN) {
					eprintf("%s followed immediately by %s is invalid.", "'('", "')'");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				if unlikely (is_op(prev_token)) {
					eprintf("%s followed immediately by %s is invalid.", "OPERATOR", "')'");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				depth--;
				if (prev2_token.type == TOKEN_LPAREN) {
					// (x) => x
					// [LPAREN, atom] => [atom]
					prev2_token = prev_token;
					tokens.count--;
				}
				else
					push_token(&tokens, (token_t) {
						.atom = {
							.ptr = expr.ptr + i,
							.len = 1,
						},
						.next = 0,
						.type = TOKEN_RPAREN,
					});

				break;

			// single-character binary operators
			{
				order_t order;
			case '^':
				order = ORDER_EXP;
				goto case_binary1;
			case '.':
				order = ORDER_CAT;
				goto case_binary1;
			case '*':
				// NOTE: this assumes order('*') == order('/') == order('%')
			case '/':
			case '%':
				order = ORDER_MUL;
			case_binary1:
				push_token(&tokens, (token_t) {
					.op = {
						.ptr = expr.ptr + i,
						.len = 1,
						.order = order,
					},
					.next = 0,
					.type = TOKEN_OP_BINARY,
				});
				break;
			}

			case '~':
				if likely (prev_token.type != TOKEN_OP_UNARY || *prev_token.op.ptr != '~')
					push_token(&tokens, (token_t) {
						.op = {
							.ptr = expr.ptr + i,
							.len = 1,
							.order = ORDER_UNARY,
						},
						.next = 0,
						.type = TOKEN_OP_UNARY,
					});
				else
					// NOTE: all unary operators are exactly one character long,
					//       so don't bother checking the length of the operator string.
					pop_token();
				break;
			case '&':
				// NOTE: && => &
				if likely (prev_token.type != TOKEN_OP_UNARY || *prev_token.op.ptr != '&')
					push_token(&tokens, (token_t) {
						.op = {
							.ptr = expr.ptr + i,
							.len = 1,
							.order = ORDER_UNARY,
						},
						.next = 0,
						.type = TOKEN_OP_UNARY,
					});
				break;
			case '<': // <<, >>
			case '>':
				if unlikely (i + 1 == expr.len)
					goto case_unknown;

				if unlikely (expr.ptr[i + 1] != c)
					goto case_unknown;

				// Token(_expr=expr, type=TOKEN_OP_BINARY, ofs=i - 1, len=2)
				push_token(&tokens, (token_t) {
					.op = {
						.ptr = expr.ptr + i,
						.len = 2,
						.order = ORDER_SHIFT,
					},
					.next = 0,
					.type = TOKEN_OP_BINARY,
				});

				i++;
				break;
			case 'a':
				if unlikely (i + 2 >= expr.len)
					goto case_unknown;

				if unlikely (*(u16 *)(expr.ptr + i) != MC16('nd'))
					goto case_unknown;

				push_token(&tokens, (token_t) {
					.op = {
						.ptr = expr.ptr + i,
						.len = 3,
						.order = ORDER_AND,
					},
					.next = 0,
					.type = TOKEN_OP_BINARY,
				});
				i += 2;
				break;

			// or, xor
			{
				u8 ofs;
			case 'x': // xor
			case 'o':
				ofs = c == 'x';

				if unlikely (i + 1 + ofs >= expr.len)
					goto case_unknown;

				if unlikely (*(u16 *)(expr.ptr + i + ofs) != MC16('or'))
					goto case_unknown;

				push_token(&tokens, (token_t) {
					.op = {
						.ptr = expr.ptr + i,
						.len = (u8) (2 + ofs),
						.order = ORDER_OR,
					},
					.next = 0,
					.type = TOKEN_OP_BINARY,
				});

				i += 1u + ofs;
				break;
			}

			// literals
			{
			case '0' ... '9':
				if unlikely (i > 0 && line_isspace(expr.ptr[i - 1]) && is_primary(prev_token)) {
					eprintf("concatenation by juxtaposition with whitespace separation is invalid.");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				u64 j = i;

				while (true) {
					j++;

					if (j == expr.len)
						break;

					if (expr.ptr[j] == '_') {
						if unlikely (expr.ptr[j - 1] == '_') {
							// no j > 0 check because at least one increment is guaranteed before this point
							eprintf("integer literal cannot %s.", "have consecutive underscores");
							dsl_panic(EXCEPT_ERR_LEXER);
						}
						// else ignore it
					}
					else if (!isdigit( expr.ptr[j] ))
						break;
				} // while

				j -= 1;

				if unlikely (expr.ptr[j] == '_') {
					eprintf("integer literal cannot %s.", "end with an underscore");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				const token_t token = {
					.atom = {
						.ptr = expr.ptr + i,
						.len = j - i + 1,
					},
					.next = 0,
					.type = TOKEN_LITERAL,
				};

				if (prev_token.type == TOKEN_OP_UNARY && *prev_token.op.ptr == '&')
					// literals are already positive. `&` is useless here.
					prev_token = token;
				else
					push_token(&tokens, token);

				i = j;

				break;
			} // literal

			case '$': {
				if unlikely (i > 0 && line_isspace(expr.ptr[i - 1]) && is_primary(prev_token)) {
					eprintf("concatenation by juxtaposition with whitespace separation is invalid.");
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				i++; // exclude the '$'
				u64 j = i;
				u64 len;

				if unlikely (i == expr.len)
					// NOTE: normally, this would be just a plain dollar sign, but since that is not valid
					//       in this context, it is an error instead.
					goto case_unknown;

				if (expr.ptr[i] == '{') {
					i++;
					char *const end = memchr(expr.ptr + i, '}', expr.len - i);

					if unlikely (end == nullptr) {
						eprintf("unclosed bracketed variable.");
						dsl_panic(EXCEPT_ERR_LEXER);
					}

					j = (u64) (end - expr.ptr);
					len = j - i;
				}
				else {
					for (; j < expr.len; j++)
						if (!isalnum(expr.ptr[j]) && expr.ptr[j] != '_')
							break;

					len = j - i;
					j--;
				}

				token_t token = {
					.atom = {
						.ptr = expr.ptr + i,
						.len = len,
					},
					.next = 0,
					.type = TOKEN_VAR,
				};

				var_t *const var = dsl_get_var(token.atom);

				if unlikely (var == nullptr) {
					eprintf("variable '$%.*s' does not exist.", (int) token.atom.len, token.atom.ptr);
					dsl_panic(EXCEPT_ERR_LEXER);
				}

				if (!is_int_var(var))
					// expand out the whole line and try again
					dsl_throw(EXCEPT_EVAL_EXPAND);

				push_token(&tokens, token);
				i = j;
				break;
			}

			// unary/binary +/-
			{
			case '+':
			case '-':
				token_t token = {
					.op = {
						.ptr = expr.ptr + i,
						.len = 1,
						.order = 0
					},
					.next = 0,
					.type = 0,
				};

				switch (prev_token.type) {
					case TOKEN_VAR     : // "$x - 1"
					case TOKEN_LITERAL : // "2 - 1"
					case TOKEN_RPAREN  : // "(2) - 1"
						token.type     = TOKEN_OP_BINARY;
						token.op.order = ORDER_ADD;
						break;
					case TOKEN_SOF       : // "-1"
					case TOKEN_LPAREN    : // "(-1"
					case TOKEN_OP_UNARY  : // "- -1"
					case TOKEN_OP_BINARY : // "2 - -1"
						token.type     = TOKEN_OP_UNARY;
						token.op.order = ORDER_UNARY;
						break;
					case TOKEN_SPZ:
					case TOKEN_MPZ:
					case TOKEN_STR:
						// there are no intermediate values at this point.
					default:
					#if DEBUG
						eprintf("+/- previous token has an unknown type: %u.", prev_token.type);
						dsl_panic(EXCEPT_ERR_LEXER);
					#else
						unreachable();
					#endif
				}

				if (token.type == TOKEN_OP_UNARY) {
					if (c == '+')
						continue;

					if (prev_token.type == TOKEN_OP_UNARY) {
						if (*prev_token.op.ptr == '-') {
							// -- => nothing
							pop_token();
							continue;
						}

						if (*prev_token.op.ptr == '&')
							// &- => &
							continue;
					}
					else if (prev_token.type == TOKEN_OP_BINARY) {
						// NOTE: prev_token.op.len is at least 1, and the only
						//       token starting with '+' is the '+' itself.
						if (*prev_token.op.ptr == '+') {
							// x + -y => x - y
							token.type = TOKEN_OP_BINARY;
							prev_token = token;
							continue;
						}
					}
				}

				push_token(&tokens, token);
				break;
			}

			// explicitly mention these 8 so 32-62 is a fully used region.
			case '!': case '"': case '#': case '\'': // 33, 34, 35, 39
			case ',': case ':': case ';': case  '=': // 44, 58, 59, 61
			default:
			case_unknown:
				eprintf("unknown or invalid character or token '%c' at index %zu.", c, i);
				dsl_panic(EXCEPT_ERR_LEXER);
		} // switch
	} // for

	if unlikely (depth != 0) {
		eprintf("expression contains %zu unclosed parentheses.", depth);
		dsl_panic(EXCEPT_ERR_LEXER);
	}

	{
		token_type_t prev, cur = tokens.array[0].type;

		for (u64 i = 1; i < tokens.count; i++) {
			prev = cur;
			cur  = tokens.array[i].type;

			if (cur == TOKEN_LITERAL || cur == TOKEN_VAR) {
				if unlikely (prev == TOKEN_RPAREN) {
					eprintf("%s followed immediately by %s is invalid.", "')'", "LITERAL or VAR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
			}
			else if (cur == TOKEN_OP_UNARY) {
				if unlikely (prev == TOKEN_LITERAL || prev == TOKEN_VAR || prev == TOKEN_RPAREN) {
					eprintf("%s followed immediately by %s is invalid.",
						"LITERAL, VAR, or ')'", "UNARY OPERATOR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
			}
			else if (cur == TOKEN_OP_BINARY) {
				if unlikely (prev == TOKEN_OP_BINARY) {
					eprintf("%s followed immediately by %s is invalid.", "BINARY OPERATOR", "BINARY OPERATOR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
				else if unlikely (prev == TOKEN_OP_UNARY) {
					eprintf("%s followed immediately by %s is invalid.", "UNARY OPERATOR", "BINARY OPERATOR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
				else if unlikely (prev == TOKEN_LPAREN) {
					eprintf("%s followed immediately by %s is invalid.", "'('", "BINARY OPERATOR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
				else if unlikely (prev == TOKEN_SOF) {
					eprintf("%s followed immediately by %s is invalid.", "SOF", "BINARY OPERATOR");
					dsl_panic(EXCEPT_ERR_LEXER);
				}
			} // if-else
		} // for
	} // bare block

	if unlikely (prev_token.type == TOKEN_SOF) {
		eprintf("%s followed immediately by %s is invalid.", "SOF", "EOF");
		dsl_panic(EXCEPT_ERR_LEXER);
	}

	if unlikely (is_op(prev_token)) {
		eprintf("%s followed immediately by %s is invalid.", "OPERATOR", "EOF");
		dsl_panic(EXCEPT_ERR_LEXER);
	}

	// this will never fail (shrink)
	if likely (tokens.count < tokens.cap)
		tokens.array = realloc(tokens.array, tokens.count * sizeof(token_t));

	return (token_list) {
		.array = tokens.array,
		.count = tokens.count
	};
} // lex

#undef is_primary
#undef is_op

#undef prev_token_n
#undef prev_token
#undef prev2_token
#undef lexer_oom
