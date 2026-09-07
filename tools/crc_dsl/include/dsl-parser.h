#pragma once
#define DSL_PARSER_H

#include "dsl-lexer.h" // "dsl-vars.h"
#include "dsl-ops.h"

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

static u32 dsl__cat_all_bisect(token_t *array, u32 start, u32 length) {
	// returns the index of the token that holds the result.

	// NOTE: the length can never be 0 since it `dsl_cat_all` disallows 0, this function exits
	//       early on 1, and both x >> 1 and x - (x >> 1) can never return 0 for x != 0.

	if (length == 1)
		return start;

	const u32 mid   = length >> 1;
	const u32 left  = dsl__cat_all_bisect(array, start, mid);
	const u32 right = dsl__cat_all_bisect(array, start + mid, length - mid);
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
	// NOTE: this is okay to happen before the bisection process since `dsl__cat_all_bisect` doesn't touch
	//       the `.next` field on any of the elements.
	ll->array[start].next = ll->array[start + length - 1].next;
	ll->count -= length - 1;

	dsl__cat_all_bisect(ll->array, start, length);
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

						// TODO: figure out if this needs to free the original string.
						//       I think it does, but I'm not 100% sure at the moment.
						//       I made it so it does, but it might be wrong.
						//       if it is wrong, it will crash, so no silent bugs.
						var_val_t tmp = dsl_atoi(var->val->str);
						free(var->val->str.ptr);
						*var->val = tmp;
						break;
					}
					default:
						unreachable();
				}

				#pragma GCC diagnostic pop

				val = *var->val;
			}
			else {
			#if DEBUG
				fatal(1, "[BUG] `tok_is_primary` encompasses more than `TOKEN_VAR` and `TOKEN_LITERAL`.");
			#else
				unreachable();
			#endif
			}

			switch (val.type) {
				case VAR_SPZ: tokens->array[j].type = TOKEN_SPZ; break;
				case VAR_MPZ: tokens->array[j].type = TOKEN_MPZ; break;
				case VAR_STR:
				default:
					unreachable();
			}

			var_val_cpy(tokens->array[j].val, val);
		}

		dsl_cat_all(tokens, start, end - start);
		i = end;
	}

	return paren_count;
}

[[maybe_unused]]
static void dsl_parse(token_list *tokens) {
	u32 *lparens;

	const bool heap_alloc = (tokens->count << 1) > 32*1024; // 32 KiB (8 pages)

	if (heap_alloc)
		// (tokens->count >> 1) lparens, (tokens->count >> 1) << 2 ~~ to
		lparens = (u32 *) malloc(tokens->count << 1);
	else {
		lparens = (u32 *) __builtin_alloca(tokens->count << 1);

	#if DEBUG
		// crash immediately on stack overflow
		asm volatile ("or %0, 0" : "+m"(lparens) :: "memory");
	#endif
	}

	u32 paren_count = dsl_resolve_expr(tokens, lparens);

	printf("paren count: %u\nparens:\n", paren_count);
	for (u32 i = 0; i < paren_count; i++)
		printf(" - %u\n", lparens[i]);

	/*
	first = 0

	while lparens:
		left = lparens.pop()
		right = left + 3 # due to error checking in lexing, it can never be less than 3 tokens away
		# () => error. (atom) => atom. (-atom) is the shortest.
		if right >= len(tokens):
			assert False, "should be unreachable."

		while tokens[right].type != TOKEN_RPAREN:
			right += 1

			if right >= len(tokens):
				assert False, "should be unreachable."

		right += 1 # right slice is not inclusive

		tokens = tokens[:left] + [parse_simple(tokens[left:right])] + tokens[right:]

	if len(tokens) > 1:
		# this will trigger in any equation that isn't wrapped in parentheses
		tokens = [parse_simple(tokens)]
	*/

	if (heap_alloc)
		free(lparens);

	/*return tokens[0]*/
}
