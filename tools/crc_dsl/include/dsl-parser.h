#pragma once
#define DSL_PARSER_H

#include "dsl-lexer.h" // "dsl-vars.h"
#include "dsl-ops.h"

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

static u32 dsl__cat_all_bisect(token_t *array, u32 start, u32 length) {
	// returns the index of the token that holds the result.

	// NOTE: the length can never be 0 since it `dsl_cat_all` disallows 0, this function exits
	//       early on 1, and both x >> 1 and x - (x >> 1) can never return 0 for x != 0.

	if (length == 1)
		return start;

	const u32 mid   = length >> 1;
	const u32 left  = dsl__cat_all_bisect(array, start, mid);
	const u32 right = dsl__cat_all_bisect(array, start + mid, length - mid);
	token_t *lnode  = array + left;

	const var_val_t out = dsl_cat(
		tok_to_var(*lnode),
		tok_to_var(array[right])
	);

	// update `.val` and `.type`, but not `.next`

	// I don't care that this can be UB. It is never going to do anything other than 
	// exactly what I intend for it to do.
	lnode->val.spz = out.spz;

	switch (out.type) {
		case VAR_SPZ: lnode->type = TOKEN_SPZ; break;
		case VAR_MPZ: lnode->type = TOKEN_MPZ; break;
		case VAR_STR:
			// dsl_cat never returns a string
		default:
			unreachable();
	}

	return left;
}

[[maybe_unused]]
static void dsl_cat_all(token_list *ll, u32 start, u32 length) {
	// [start, start + length) is a contiguous block in the arena, so real recursive bisection is possible.
	// the result will always be in `ll->array[start]`.

#if DEBUG
	if unlikely (start == 0)
		fatal(1, "concat region cannot include SOF.");

	if unlikely (length == 0)
		fatal(1, "length cannot be 0.");
#endif

	// point to the node immediately following the range.
	// NOTE: using `array[start + length]` almost works, except for the concat region could theoretically
	//       be at the end of the list (e.g. `%seteval[2 + $x$y$z]`) ends with a concat region.
	// NOTE: this is okay to happen before the bisection process since `dsl__cat_all_bisect` doesn't touch
	//       the `.next` field on any of the elements.
	ll->array[start].next = ll->array[start + length - 1].next;
	ll->count -= length - 1;

	dsl__cat_all_bisect(ll->array, start, length);
}

[[maybe_unused]]
static void resolve_expr(token_list *tokens, u32 *lparens) {
	// lparens should be able to fit at least `tokens.count >> 1` integers, so it should be at least
	// `(tokens.count & ~1) << 1` bytes long. `tokens.count << 1` is probably best.

	(void) tokens;
	(void) lparens;

}