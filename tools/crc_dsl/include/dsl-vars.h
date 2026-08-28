#pragma once
#define DSL_VARS_H

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion" // `__GMP_ABS` doesn't explicly cast to unsigned.
#pragma GCC diagnostic ignored "-Wconversion"      // Windows (ullong => ulong)
#pragma GCC diagnostic ignored "-Wpadded"          // Linux. `__gmp_randstate_struct` gets padded
#include <gmp.h>
#pragma GCC diagnostic pop

#define MAP_H_DEFAULT_OWNED
#define MAP_H_NO_FUN
#define MAP_H_IMPL
#define MAP_H_HASH64
#include "map.h" // <stdlib.h>, <stdint.h>, <string.h>, "va-if.h"

#ifdef THISFILE
	#undef THISFILE
#endif
#define THISFILE "dsl-vars.h"

typedef enum : u8 {
	VAR_SPZ, // i128
	VAR_MPZ, // mpz_t
	VAR_STR, // vstring
} var_type_t;

typedef vstring var_key_t;

typedef union {
	// NOTE: these should all be 16 bytes long
	i128    spz; // single-precision integer
	mpz_t   mpz; // multiple-precision integer
	vstring str; // `.ptr` should be a C string.
} var_val_union_t;

typedef struct __attribute__((packed)) {
	var_val_union_t;
	var_type_t type;
} var_val_t;

typedef struct {
	var_key_t *key;
	var_val_t *val;
	u64 next;
} var_t; // same structure as `MapEntry`

static Map dsl_vars;

[[gnu::nonnull]]
static void dsl_free_var(var_t *p2entry) {
	// free the variable entry, but don't remove the entry from the map
	var_key_t *pkey = (var_key_t *) p2entry->key;
	free(pkey->ptr);
	free(pkey);

	var_val_t *pval = (var_val_t *) p2entry->val;

	switch (pval->type) {
		case VAR_SPZ:
			// plain integer has no extra allocation
			break;
		case VAR_MPZ:
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			mpz_clear(pval->mpz);
			#pragma GCC diagnostic pop
			break;
		case VAR_STR:
			free(pval->str.ptr);
			break;
		default:
			unreachable();
	}

	free(pval);
}

FORCE_INLINE static var_t *dsl_get_var2(const var_key_t key, map_hash_t hash) {
	return (var_t *) Map_get_entry_by(dsl_vars, &key, vstring_cmp, hash);
}

FORCE_INLINE static var_t *dsl_get_var1(const var_key_t key) {
	return dsl_get_var2(key, jhash(key.ptr, key.len));
}

#define dsl_get_var(key, hash...) VA_IF(dsl_get_var2(key, hash), dsl_get_var1(key), hash)

[[gnu::nonnull]]
static void dsl_set_var(var_key_t *pkey, var_val_t *pval) {
	const map_hash_t hash = jhash(pkey->ptr, pkey->len);

	var_t *const p2entry = dsl_get_var(*pkey, hash);

	if (p2entry != nullptr) {
		// variable exists. free the old stuff and update in-place
		dsl_free_var(p2entry);
		p2entry->key = pkey;
		p2entry->val = pval;
	}
	else
		dsl_vars = Map_set_by(dsl_vars, pkey, pval, vstring_cmp, hash, vstring_hash, MAP_UNOWNED);
}

[[maybe_unused, gnu::nonnull]]
static void dsl_log_var(var_t *p2entry) {
	// NOTE: the key pointer is a C string as well as a V string.
#if DEBUG
	printf("\"%s\" => { ", p2entry->key->ptr);

	var_val_t *pval = p2entry->val;

	switch (pval->type) {
		case VAR_SPZ: {
			const bool sign = pval->spz >= 0;
			const u128 magn = sign ? (u128) pval->spz : -(u128) pval->spz;

			printf(
				".type = VAR_SPZ, .val = %s%016zx%016zx",
				"-" + !sign,
				(u64)(magn >> 64),
				(u64) magn
			);

			break;
		}
		case VAR_MPZ: {
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			const char *str = mpz_get_str(NULL, 10, pval->mpz);
			#pragma GCC diagnostic pop

			printf(".type = VAR_MPZ, .val = %s", str);

			free((void *) str);
			break;
		}
		case VAR_STR:
			printf(
				".type = VAR_STR, .val = \"%s\", .len = %zu",
				pval->str.ptr,
				pval->str.len
			);

			break;
		default:
			unreachable();
	}

	const map_hash_t hash = jhash(p2entry->key->ptr, p2entry->key->len);
	#ifdef MAP_H_HASH128
		printf(" }; hash = 0x%016zx%016zx; p2entry = 0x%016zx\n",
			(u64) (hash >> 64), (u64) hash,
			(u64) (uintptr_t) p2entry
		);
	#else
		printf(" }; hash = 0x%016zx; p2entry = 0x%016zx\n", hash, (u64) (uintptr_t) p2entry);
	#endif
#else // not debug
	printf("\"%s\" => {\n\t", p2entry->key->ptr);

	var_val_t *pval = p2entry->val;

	switch (pval->type) {
		case VAR_SPZ: {
			const bool sign = pval->spz >= 0;
			const u128 magn = sign ? (u128) pval->spz : -(u128) pval->spz;

			printf(".type = %s\n", "VAR_SPZ");
			printf("\t.val  = %s", "-" + !sign);
			printf("%016zx%016zx", (u64)(magn >> 64), (u64) magn);
			break;
		}
		case VAR_MPZ: {
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			const char *str = mpz_get_str(NULL, 10, pval->mpz);
			#pragma GCC diagnostic pop

			printf(".type = %s\n", "VAR_MPZ");
			printf("\t.val  = %s", str);

			free((void *) str);
			break;
		}
		case VAR_STR:
			printf(".type = %s\n", "VAR_STR");
			printf(
				"\t.val  = \"%s\"\n"
				"\t.len  = %zu",
				pval->str.ptr,
				pval->str.len
			);

			break;
		default:
			unreachable();
	}

	putchar('\n');
	putchar('}');
	putchar('\n');
#endif
}
