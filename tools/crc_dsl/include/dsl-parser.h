#pragma once
#define DSL_PARSER_H

// parser for `%seteval`

#include "dsl-lexer.h" // "dsl-vars.h"
#include "dsl-ops.h"

typedef struct {
	token_t **array;
	u64 count;
} token_ref_list;

#define tok_advance(IDX) ((tokens).array[IDX].next)

[[gnu::const]]
static var_val_t tok_to_var(token_t x) {
	switch (x.type) {
		case TOKEN_SPZ: return spz_to_var(x.val.spz);
		case TOKEN_MPZ: return mpz_to_var(x.val.mpz);
		case TOKEN_STR: return str_to_var(x.val.str);

		case TOKEN_OP_UNARY:
		case TOKEN_OP_BINARY:
		case TOKEN_SOF:
		case TOKEN_LPAREN:
		case TOKEN_RPAREN:
		case TOKEN_VAR:
		case TOKEN_LITERAL:
		default:
		#if DEBUG
			fatal(1, "invalid token. must be SPZ, MPZ, or STR.");
		#else
			unreachable();
		#endif
	}
}

static u32 dsl_cat_all__bisect(token_t *array, u32 start, u32 length) {
	// returns the index of the token that holds the result.

	// NOTE: the length can never be 0 since it `dsl_cat_all` disallows 0, this function exits
	//       early on 1, and both x >> 1 and x - (x >> 1) can never return 0 for x != 0.

	if (length == 1)
		return start;

	const u32 mid   = length >> 1;
	const u32 left  = dsl_cat_all__bisect(array, start, mid);
	const u32 right = dsl_cat_all__bisect(array, start + mid, length - mid);
	const var_val_t out = dsl_cat(
		tok_to_var(array[left]),
		tok_to_var(array[right])
	);

	// update `.val` and `.type`, but not `.next`

	var_val_cpy(array[left].val, out);

	switch (out.type) {
		case VAR_SPZ: array[left].type = TOKEN_SPZ; break;
		case VAR_MPZ: array[left].type = TOKEN_MPZ; break;
		case VAR_STR:
			// dsl_cat never returns a string
		default:
			unreachable();
	}

	return left;
}

static void dsl_cat_all(token_list *ll, u32 start, u32 length) {
	// [start, start + length) is a contiguous block in the arena, so real recursive bisection is possible.
	// the result will always be in `ll->array[start]`.

#if DEBUG
	if unlikely (start == 0)
		fatal(1, "concat region cannot include SOF.");

	if unlikely (length == 0)
		fatal(1, "length cannot be 0.");
#endif

	if (length == 1)
		return;

	// point to the node immediately following the range.
	// NOTE: using `array[start + length]` almost works, except for the concat region could theoretically
	//       be at the end of the list (e.g. `%seteval[2 + $x$y$z]`) ends with a concat region.
	// NOTE: this is okay to happen before the bisection process since `dsl_cat_all__bisect` doesn't touch
	//       the `.next` field on any of the elements.
	ll->array[start].next = ll->array[start + length - 1].next;
	ll->count -= length - 1;

	dsl_cat_all__bisect(ll->array, start, length);
}

static u32 dsl_resolve_expr(token_list *tokens, u32 *lparens) {
	// lparens should be able to fit at least `tokens.count >> 1` integers, so it should be at least
	// `(tokens.count & ~1) << 1` bytes long. `tokens.count << 1` is probably best.

	u32 paren_count = 0;

	const u32 search_count = tokens->count;

	// while i < len(tokens):
	for (u32 i = 0; i < search_count ;) {
		if (!tok_is_primary(tokens->array[i])) {
			if (tokens->array[i].type == TOKEN_LPAREN)
				lparens[paren_count++] = i;

			i++;
			continue;
		}

		const u32 start = i;

		do i++;
		while (i < tokens->count && tok_is_primary(tokens->array[i]));

		const u32 end = i;

		// resolve the values of literals and variables
		for (u32 j = start; j < end; j++) {
			var_val_t val;

			if (tokens->array[j].type == TOKEN_LITERAL)
				val = dsl_atoi(tokens->array[j].atom);
			else if (tokens->array[j].type == TOKEN_VAR) {
				var_t *const var = dsl_get_var(tokens->array[j].atom);

				#pragma GCC diagnostic push

			#if DEBUG
				if unlikely (var == nullptr) {
					eprintf("[BUG] variable '$%.*s' does not exist when it should.",
						(int) tokens->array[j].atom.len, tokens->array[j].atom.ptr
					);
					dsl_panic(EXCEPT_ERR_LEXER);
				}
			#else
				#pragma GCC diagnostic ignored "-Wnull-dereference"
			#endif

				switch (var->val->type) {
					case VAR_SPZ:
					case VAR_MPZ:
						// these are already integers. nothing to convert.
						break;
					case VAR_STR: {
						// NOTE: this updates the actual variable type

						var_val_t tmp = dsl_atoi(var->val->str);
						free(var->val->str.ptr);
						*var->val = tmp;
						break;
					}
					default:
						unreachable();
				}

				#pragma GCC diagnostic pop

				val = var->val[0];

				if (val.type == VAR_MPZ) {
					// deep copy the integer so the variable data is still alive
					mpz_t tmp;

					#pragma GCC diagnostic push
					#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
					mpz_init_set(tmp, val.mpz);
					#pragma GCC diagnostic pop

					val.mpz[0] = tmp[0];
				}
			}
			else {
			#if DEBUG
				fatal(1, "[BUG] `tok_is_primary` encompasses more than `TOKEN_VAR` and `TOKEN_LITERAL`.");
			#else
				unreachable();
			#endif
			}

			tokens->array[j].type = val.type == VAR_SPZ ? TOKEN_SPZ : TOKEN_MPZ;
			var_val_cpy(tokens->array[j].val, val);
		}

		dsl_cat_all(tokens, start, end - start);
		i = end;
	}

	return paren_count;
}

static void dsl_simple_pop_and_eval(token_ref_list *ops, token_ref_list *vals) {
	token_t *op = ops->array[--ops->count];

	if (op->type == TOKEN_OP_UNARY) {
		const u64 vals_last = vals->count - 1;

		// NOTE: I'm pretty sure this is leaking memory currently.
		var_val_t in = tok_to_var(vals->array[vals_last][0]);
		var_val_t res;

		switch (op->op.ptr[0]) {
			case '-': res = dsl_neg(in); break;
			case '~': res = dsl_com(in); break;
			case '&': res = dsl_abs(in); break;
			case '!': res = dsl_not(in); break;
			default:
			#if DEBUG
				fatal(1, "[BUG] unary operator token is not '-', '~', '&', or '!'.");
			#else
				unreachable();
			#endif
		}

		dsl_clear_val(in);

		var_val_cpy(vals->array[vals_last]->val, res);
		vals->array[vals_last]->type = res.type == VAR_SPZ ? TOKEN_SPZ : TOKEN_MPZ;

		return;
	}

	// printf("binary operator: %.*s\n", (int) op->op.len, op->op.ptr);

	token_t *rtok = vals->array[--vals->count]; // top
	token_t *ltok = vals->array[--vals->count]; // below

	var_val_t r = tok_to_var(*rtok);
	var_val_t l = tok_to_var(*ltok);
	var_val_t res;

	switch (op->op.len) {
		case 1:
			switch (op->op.ptr[0]) {
				case '^': res = dsl_pow(l, r); break;
				case '.': res = dsl_cat(l, r); break;
				case '*': res = dsl_mul(l, r); break;
				case '/': res = dsl_div(l, r); break;
				case '%': res = dsl_mod(l, r); break;
				case '+': res = dsl_add(l, r); break;
				case '-': res = dsl_sub(l, r); break;
				default:
				#if DEBUG
					fatal(1, "[BUG] 1-char binary operator token is not '^', '.', '*', '/', '%%', '+', or '-'.");
				#else
					unreachable();
				#endif
			}

			break;
		case 2:
			if      (*(u16 *) op->op.ptr == MC16('<<')) res = dsl_shl(l, r);
			else if (*(u16 *) op->op.ptr == MC16('>>')) res = dsl_shr(l, r);
			else if (*(u16 *) op->op.ptr == MC16('or')) res = dsl_ior(l, r);
			else
			#if DEBUG
				fatal(1, "[BUG] 2-char binary operator token is not '<<', '>>', or 'or'.");
			#else
				unreachable();
			#endif

			break;
		case 3:
			if      (*(u16 *) op->op.ptr == MC16('an') && op->op.ptr[2] == 'd')
				res = dsl_and(l, r);
			else if (*(u16 *) op->op.ptr == MC16('xo') && op->op.ptr[2] == 'r')
				res = dsl_xor(l, r);
			else
			#if DEBUG
				fatal(1, "[BUG] 3-char binary operator is not 'and' or 'xor'.");
			#else
				unreachable();
			#endif

			break;
		default:
		#if DEBUG
			fatal(1, "[BUG] binary operator is not 1, 2, or 3 bytes long.");
		#else
			unreachable();
		#endif
	}

	dsl_clear_val(l);
	dsl_clear_val(r);
	var_val_cpy(ltok->val, res);
	ltok->type = res.type == VAR_SPZ ? TOKEN_SPZ : TOKEN_MPZ;

	vals->array[vals->count++] = ltok;
}

static token_t *dsl_parse_simple(token_t *array, u32 left, u32 right, u64 length) {
	// parse the expression assuming all implicit concats were resolved,
	// and there are no parentheses in the input region. It will probably
	// crash or loop infinitely if there are parentheses.

	// printf("parsing range [%u, %u] (length=%zu):\n", left, right, length);

	// more than 64 KiB total between the two stacks
	length *= sizeof(void *);
	const bool heap_alloc = length > 32*1024;

	token_ref_list vals, ops;
	vals.count = 0;
	ops.count  = 0;

#if DEBUG
	if unlikely (length == 0)
		fatal(1, "[BUG] length == 0.");

	if unlikely (right == left)
		fatal(1, "[BUG] left == right.");
#endif

	if unlikely (heap_alloc) {
		// TODO: consider making these allocations static or something.
		vals.array = (token_t **) malloc(length);
		if unlikely (vals.array == nullptr)
			fatal(1, "out of memory.");

		ops.array = (token_t **) malloc(length);
		if unlikely (ops.array == nullptr)
			fatal(1, "out of memory.");
	}
	else {
		vals.array = (token_t **) __builtin_alloca(length);
		ops.array  = (token_t **) __builtin_alloca(length);

	#if DEBUG
		// crash immediately on stack overflow
		asm volatile ("or %0, 0" : "+m"(vals.array) :: "memory");
		asm volatile ("or %0, 0" : "+m"(ops.array) :: "memory");
	#endif
	}

	// NOTE: don't worry about updating anything other than array[left]
	// NOTE: the i != 0 protects from if the last token in the region is also the last token in the list
	//       the `i <= right` is for the normal case.
	for (u32 i = left; likely(i <= right) && unlikely(i != 0); i = array[i].next) {
		token_t *const t = array + i;

		// log_single_token(t, i, /*logical*/ i, /*%3u*/ 3);

		if (tok_is_int(*t)) {
			vals.array[vals.count++] = t;
			continue;
		}

		while (ops.count != 0) {
			// prefix operators always push
			// this is just so `left ^ <unary> right` works.
			if (t->type == TOKEN_OP_UNARY)
				break;

			const order_t top_order = ops.array[ops.count - 1]->op.order;

			// NOTE: lower order binds tighter
			if (top_order > t->op.order || (tok_op_r_assoc(*t) && top_order == t->op.order))
				break;

			// if the new thing binds tighter
			dsl_simple_pop_and_eval(&ops, &vals);
		}

		ops.array[ops.count++] = t;
	}

	// flush any remaining operators
	while (ops.count != 0)
		dsl_simple_pop_and_eval(&ops, &vals);

#if DEBUG
	if unlikely (vals.count != 1)
		fatal(1, "[BUG] stack does not contain exactly one result.");
#endif

	/*if (vals.count != 0) {
		u32 i = (u32) (vals.array[0] - array);
		printf("result (i = %u):\n", i);
		log_single_token(array + i, i, i, 3);
	}*/

	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wmaybe-uninitialized"
	token_t *const res = vals.array[0];
	#pragma GCC diagnostic pop

	if unlikely (heap_alloc) {
		free(vals.array);
		free(ops.array);
	}

	return res;
}

static void dsl_parse(token_list tokens) {
	u32 *lparens;

	const bool heap_alloc = tokens.count > 16*1024; // 32 KiB (8 pages)

	if unlikely (heap_alloc) {
		// (tokens.count >> 1) lparens, (tokens.count >> 1) << 2 ~~ tokens.count << 1 bytes
		lparens = (u32 *) malloc(tokens.count << 1);

		if unlikely (lparens == nullptr)
			fatal(1, "out of memory.");
	}
	else {
		lparens = (u32 *) __builtin_alloca(tokens.count << 1);

	#if DEBUG
		// crash immediately on stack overflow
		asm volatile ("or %0, 0" : "+m"(lparens) :: "memory");
	#endif
	}

	for (u32 paren_count = dsl_resolve_expr(&tokens, lparens); paren_count --> 0 ;) {
	#if DEBUG
		printf("tmp expr: "); log_tokens_expr(tokens);
	#endif
		const u32 lparen  = lparens[paren_count];
		const u32 left    = tok_advance(lparen); // lparen + 1
		u32 rparen, right = tok_advance(left);   // lparen + 2
		u32 length = 2;
		// due to error checking in lexing, the right paren can never be less than 3 tokens away
		// () => error. (atom) => atom. (unary_op atom) or (atom atom) is the shortest.

		while (tokens.array[rparen = tok_advance(right)].type != TOKEN_RPAREN) {
		#if DEBUG
			if (rparen == 0)
				fatal(1, "[BUG] unclosed '(' uncaught by the lexer");
		#endif
			right = rparen;
			length++;
		}

		// don't include the parentheses in the region given to `dsl_parse_simple`.

		// result is in tokens.array[left] unless tokens.array[left] was a unary operator,
		// in which case it will be somewhere else, which is why `dsl_parse_simple` has to
		// return where the value is.

		// array[left:right + 1]. the length is only for heuristics. it is required because
		// length = right - left + 1 is not guaranteed for linked lists
		tokens.array[lparen] = *dsl_parse_simple(tokens.array, left, right, length);
		tokens.array[lparen].next = tok_advance(rparen); // the token after the right parentheses
	}

#if DEBUG
	printf("tmp expr: "); log_tokens_expr(tokens);
#endif

	if unlikely (heap_alloc)
		free(lparens);

	{
		const u32 left = 1;
		u32 length = 1;
		u32 right = left;
		while (tok_advance(right) != 0) {
			right = tok_advance(right);
			length++;
		}

		// this will trigger in any equation that isn't wrapped in parentheses
		if (left != right)
			tokens.array[1] = *dsl_parse_simple(tokens.array, left, right, length);
	}

	// result is always in array[1]
	tokens.array[1].next = 0;
}

[[maybe_unused]]
static var_val_t dsl_eval(vstring expr) {
	const token_list tokens = dsl_lex(expr);

#if DEBUG
	printf("input expr: %.*s\n", (int) expr.len, expr.ptr);
	printf("lexed expr: "); log_tokens_expr(tokens);
#endif

	dsl_parse(tokens);

	const var_val_t res = tok_to_var(tokens.array[1]);

#if DEBUG
	printf("result: "); dsl_puts_val(result);
#endif

	free(tokens.array);

	return res;
}

#undef tok_advance
