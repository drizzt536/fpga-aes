#pragma once
#define DSL_VARS_H

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wsign-conversion" // `__GMP_ABS` doesn't explicly cast to unsigned.
#pragma GCC diagnostic ignored "-Wconversion"      // Windows (ullong => ulong)
#pragma GCC diagnostic ignored "-Wpadded"          // Linux. `__gmp_randstate_struct` gets padded
#include <gmp.h>
#pragma GCC diagnostic pop

#ifndef MP_BITCNT_MAX
	// GMP doesn't currently define this, but idk if they plan to or not
	#define MP_BITCNT_MAX (~(mp_bitcnt_t) 0)
#endif

#define mp_limbcnt_t typeof(((mpz_t) {0})->_mp_size)
#define MP_MAX_LIMBS ((1llu << (8*sizeof(mp_limbcnt_t) - 1)) - 1)
#define MP_MAX_BITS  (8llu * sizeof(mp_limb_t) * MP_MAX_LIMBS)

#define MAP_H_DEFAULT_OWNED
#define MAP_H_NO_FUN
#define MAP_H_IMPL
#define MAP_H_HASH64
#include "map.h" // <stdlib.h>, <stdint.h>, <string.h>, "va-if.h"

#define ANSI_RED    "\e[31m"
#define ANSI_ORANGE "\e[38;2;180;100;0m"
#define ANSI_RST    "\e[m"

#define eprintf(FMT, ...)  fprintf(stderr, ANSI_RED    FMT ANSI_RST __VA_OPT__(,) __VA_ARGS__)
#define ewprintf(FMT, ...) fprintf(stderr, ANSI_ORANGE FMT ANSI_RST __VA_OPT__(,) __VA_ARGS__)

// p is the chance that it stays in the loop
#define until(x) while (!(x))

// p is the chance that it exits
#define until_likely(x)       while   likely(!(x))
#define until_unlikely(x)     while unlikely(!(x))
#define until_likelyp(x, p)   while   likelyp(!(x), p)
#define until_unlikelyp(x, p) while unlikelyp(!(x), p)

#define _strlen __builtin_strlen

// `volatile` without the reordering restrictions and forced rereads
#define force_mem(var) asm ("" : "+m" (var))

#ifdef THISFILE
	#undef THISFILE
#endif
#define THISFILE "dsl-vars.h"

typedef enum : u8 {
	VAR_SPZ, // spz_t
	VAR_MPZ, // mpz_t
	VAR_STR, // vstring
} var_type_t;

typedef u128 spn_t; // single-precision natural number (because 0 is a natural number)
typedef i128 spz_t; // single precision integer
typedef vstring var_key_t;

#define SPN_MIN U128_MIN
#define SPN_MAX U128_MAX

#define SPZ_MIN I128_MIN
#define SPZ_MAX I128_MAX

typedef union {
	// NOTE: these should all be 16 bytes long
	spz_t   spz; // single-precision integer
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

/// SPZ functions

#define spz_abs2(X, NEG) ({                   \
	const spz_t x_abs2 = (X);                 \
	(NEG) ? -(spn_t) x_abs2 : (spn_t) x_abs2; \
})

#define spz_abs1(X) ({            \
	const spz_t x_abs1 = (X);     \
	spz_abs2(x_abs1, x_abs1 < 0); \
})

#define spz_abs(X, NEG...) VA_IF(spz_abs2(X, NEG), spz_abs1(X), NEG)

// where sign(0) = 1. to compare with 0, compare directly.
#define spz_sgn(X) ((X) >= 0 : 1 : -1)

#define SPZ_MAG_BITS (8*sizeof(spz_t) - 1)

[[gnu::const]]
FORCE_INLINE static u32 spn_size(spn_t x) {
	return (u32) __builtin_stdc_bit_width(x);
}

[[gnu::const]]
FORCE_INLINE static u32 spz_size(spz_t x) {
	return spn_size(spz_abs(x));
}

[[gnu::const]]
static u32 spz_sizeinbase10(spz_t z) {
	const spn_t n = spz_abs(z);
	// if you ignore that this is O(1), it is kind of like O(log log n)

	// I had to make this a binary search tree myself, because when it
	// was a linear scan, GCC wasn't optimizing it to this.

	if (n < 10000000000000000000llu) {
		if (n < 10000000000llu) {
			if (n < 100000llu) {
				if (n < 1000llu) {
					if (n < 100llu)
						return n < 10llu ? 1 : 2;
					return 3;
				}

				return n < 10000llu ? 4 : 5;
			}

			if (n < 100000000llu) {
				if (n < 10000000llu)
					return n < 1000000llu ? 6 : 7;
				return 8;
			}

			return n < 1000000000llu ? 9 : 10;
		}

		if (n < 1000000000000000llu) {
			if (n < 10000000000000llu) {
				if (n < 1000000000000llu)
					return n < 100000000000llu ? 11 : 12;
				return 13;
			}

			return n < 100000000000000llu ? 14 : 15;
		}

		if (n < 100000000000000000llu)
			return n < 10000000000000000llu ? 16 : 17;

		return n < 1000000000000000000llu ? 18 : 19;
	}

	if (n < (spz_t) 10000000000llu * 10000000000000000000llu) {
		if (n < (spz_t) 100000llu * 10000000000000000000llu) {
			if (n < (spz_t) 1000llu * 10000000000000000000llu) {
				if (n < (spz_t) 100llu * 10000000000000000000llu)
					return n < (spz_t) 10llu * 10000000000000000000llu ? 20 : 21;
				return 22;
			}

			return n < (spz_t) 10000llu * 10000000000000000000llu ? 23 : 24;
		}

		if (n < (spz_t) 100000000llu * 10000000000000000000llu) {
			if (n < (spz_t) 10000000llu * 10000000000000000000llu)
				return n < (spz_t) 1000000llu * 10000000000000000000llu ? 25 : 26;
			return 27;
		}

		return n < (spz_t) 1000000000llu * 10000000000000000000llu ? 28 : 29;
	}

	if (n < (spz_t) 1000000000000000llu * 10000000000000000000llu) {
		if (n < (spz_t) 10000000000000llu * 10000000000000000000llu) {
			if (n < (spz_t) 1000000000000llu * 10000000000000000000llu)
				return n < (spz_t) 100000000000llu * 10000000000000000000llu ? 30 : 31;
			return 32;
		}

		return n < (spz_t) 100000000000000llu * 10000000000000000000llu ? 33 : 34;
	}

	if (n < (spz_t) 100000000000000000llu * 10000000000000000000llu)
		return n < (spz_t) 10000000000000000llu * 10000000000000000000llu ? 35 : 36;

	// I forgot about 39, so this is in a weird place
	if (n >= (spz_t) 10000000000000000000llu * 10000000000000000000llu)
		return 39;

	return n < (spz_t) 1000000000000000000llu * 10000000000000000000llu ? 37 : 38;
}

static void put_spz(spz_t val) {
	if (val == 0) {
		putchar('0');
		return;
	}

	spn_t uval;
	if (val < 0) {
		// ~x + 1 instead of -x to prevent overflow on `-signed`
		putchar('-');
		uval = (spn_t) ~val + 1;
	} else
		uval = (spn_t) val;

	char buf[spz_sizeinbase10(SPZ_MAX) + 1];
	static_assert(8*sizeof(spz_t) < 256, "increase `i` to u32");
	u8 i = (u8) spz_sizeinbase10(SPZ_MAX);
	buf[i] = '\0';

	do {
		buf[--i] = (char) ('0' + uval % 10);
		uval /= 10;
	} until (uval == 0);

	printf("%s", buf + i);
}

[[maybe_unused]]
FORCE_INLINE static void puts_spz(spz_t x) {
	put_spz(x);
	putchar('\n');
}

/// variable functions

[[gnu::const]]
FORCE_INLINE static bool line_isspace(char c) {
	// stuff that can be whitespace inside of a line
	// I don't care about \r, \n, or \f
	return c == ' ' || c == '\t';
}

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
static void dsl_dump_var(var_t *p2entry) {
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
			const char *str = mpz_get_str(nullptr, 10, pval->mpz);
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
			const char *str = mpz_get_str(nullptr, 10, pval->mpz);
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
