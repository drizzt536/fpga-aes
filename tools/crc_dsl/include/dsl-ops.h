#pragma once
#define DSL_OPS_H

#include "dsl-vars.h" // <gmp.h>, "dsl-except.h", "va-if.h"

// look in dsl-lexer.h in the `order_t` declaration for the comment with the full operator list.

// I promise this works. There are no arrays of the variable structures, `mpz_t mpz` is the first field in
// the variable struct, and `malloc` aligns to 16 bytes anyway, so this warning is just noise here.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Waddress-of-packed-member"

#if DEBUG
	#define assert_var_int(x) ({                                     \
		if ((x).type == VAR_STR)                                     \
			fatal(1, "[BUG] arguments should not be type VAR_STR."); \
		(void) 0;                                                    \
	})
#else
	#define assert_var_int(x) ((void) 0)
#endif

////////////////////////////// conversions //////////////////////////////

// spz_to_str
// mpz_to_str
// var_to_str
// spz_to_var
// mpz_to_var
// str_to_var
// mpz_to_var_contrict
// spz_to_mpz
// mpz_to_spz
// trunc_mpz_to_spz
// dsl_atoi

// for the next three, the caller should make sure the out parameter
// is not set to nullptr. if it is, it means the allocation failed
static u64 spz_to_str(spz_t x, char **out) {
	if (x == 0) {
		*out = strdup("0");
		return 1;
	}

	spn_t ux;
	const bool neg = x < 0;
	if (neg)
		// ~x + 1 instead of -x to prevent overflow on `-signed`
		ux = (spn_t) ~x + 1;
	else
		ux = (spn_t) x;

	char buf[1 + spz_sizeinbase10(SPZ_MAX) + 1]; // sign + ux + null

	static_assert(8*sizeof(spz_t) <= 256, "increase `i` to u32");
	u8 i = (u8) (sizeof(buf) - 1);
	buf[i] = '\0';

	do {
		buf[--i] = (char) ('0' + ux % 10);
		ux /= 10;
	} until (ux == 0);

	if (neg)
		buf[--i] = '-';

	*out = strdup(buf + i);
	return sizeof(buf) - i - 1;
}

static u64 mpz_to_str(mpz_t x, char **out) {
	u64 len = mpz_sizeinbase(x, 10) + (mpz_sgn(x) < 0);

	char *ptr = malloc(len + 1);
	*out = nullptr;

	if (ptr == nullptr)
		return 0;

	mpz_get_str(ptr, 10, x);

	if (ptr[len - 1] == '\0')
		len--;

	return len;
}

[[maybe_unused]]
static vstring var_to_str(var_val_t in) {
	if (in.type == VAR_STR)
		return (vstring) {
			.ptr = strdup(in.str.ptr),
			.len = in.str.len,
		};

	vstring str;

	str.len = in.type == VAR_SPZ ?
		spz_to_str(in.spz, &str.ptr) :
		mpz_to_str(in.mpz, &str.ptr);

	return str;
}

#define spz_to_var(z) ((var_val_t) { .spz =  (z)    , .type = VAR_SPZ })
#define mpz_to_var(z) ((var_val_t) { .mpz = {(z)[0]}, .type = VAR_MPZ })
#define str_to_var(s) ((var_val_t) { .str = (s)     , .type = VAR_STR })

// convert to spz if it is small enough and then convert to var
#define mpz_to_var_constrict(Z) ({            \
	mpz_t z = {(Z)[0]};                       \
	var_val_t out_var_;                       \
	if (mpz_fits_spz_p(z)) {                  \
		out_var_ = spz_to_var(mpz_to_spz(z)); \
		mpz_clear(z);                         \
	}                                         \
	else                                      \
		out_var_ = mpz_to_var(z);             \
	out_var_;                                 \
})

static void spz_to_mpz(mpz_t out, spz_t in) {
	mpz_init(out);

	const bool negative = in < 0;
	const spn_t mag = spz_abs(in, negative);

	static_assert(-(spz_t) LONG_MIN >= (spz_t) LONG_MAX);

	if (mag <= LONG_MAX) {
		mpz_set_si(out, (long) in);
		return;
	}

	mpz_import(
		out,
		1,           // count=1
		1,           // order=MSb first
		sizeof(mag), // sizeof(spz_t)
		0,           // native endianness
		0,           // don't skip any bits
		&mag
	);

	if (negative)
		mpz_neg(out, out);
}

static spz_t mpz_to_spz(mpz_t in) {
	// assume the value fits in a 128-bit signed integer. The checks for that
	// should be performed elsewhere. If it is larger, this will probably crash.

#if DEBUG
	if (!mpz_fits_spz_p(in))
		fatal(1, "[BUG] input value doesn't fit in spz_t.");
#endif

	if (mpz_fits_slong_p(in))
		return (spz_t) mpz_get_si(in);

	// NOTE: no intermediate spn_t is needed because the magnitude of the value should already
	//       have been determined to fit in one less bit than the bit width of the type.
	spz_t out;

	mpz_export(
		&out,
		nullptr,     // discard count
		1,           // order=MSb first
		sizeof(out), // sizeof(spz_t)
		0,           // native endianness
		0,           // don't skip any bits
		in
	);

	return mpz_sgn(in) >= 0 ? out : -out;
}

static spz_t trunc_mpz_to_spz(mpz_t in) {
	mpz_t tmp;
	mpz_init(tmp);
	mpz_fdiv_r_2exp(tmp, in, 128);

	spz_t out;
	mpz_export(&out, nullptr, 1, sizeof(out), 0, 0, tmp);

	mpz_clear(tmp);
	return out;
}

[[maybe_unused]]
static var_val_t dsl_atoi(vstring in) {
	// in.ptr is not assumed to be a C string. It is converted to either SPZ or MPZ
	// the input character array is not touched.

	// NOTE: this should not run until it is guaranteed that the variable's value is valid.
	// constraints:
	//   - no starting or ending whitespace       --  parsing will only work for .len >= 39
	//   - no prefixes (only decimal)             --  parsing will not work
	//   - first and last characters are not '_'  --  parsing will work anyway
	//   - no consecutive '_'                     --  parsing will work anyway
	//   - string is not empty                    --  value is parsed as 0
	//   - no random characters                   --  parsing will only work .len >= 39

#if DEBUG
	if unlikely (in.len == 0)
		fatal(1, "[BUG] argument is empty.");
#endif

	// skip useless stuff at the start
	while unlikely ({char c = *in.ptr; c == '0' || c == '_';}) {
		in.ptr++;
		in.len--;
	}

	if (in.len == 0)
		// all of the digits got skipped
		return spz_to_var(0);

	// NOTE: allocate the same size buffer since the string can never get longer, only shorter.
	vstring tmp;
	tmp.ptr = malloc(in.len + 1);

	if unlikely (tmp.ptr == nullptr)
		dsl_oom();

	// remove underscores
	{
		u64 w = 0;
		for (u64 r = 0; r < in.len; r++) {
			char c = in.ptr[r];

			if (c != '_')
				tmp.ptr[w++] = c;
		}

		tmp.len = w;
	}
	tmp.ptr[tmp.len] = '\0';

	static_assert(8*sizeof(spz_t) == 128, "39 == \\lceil log_{10} 2^{127} \\rceil");

	if (tmp.len < 39) {
		spz_t out = 0;

		for (u64 i = 0; i < tmp.len; i++) {
			out *= 10;
			out += tmp.ptr[i] - '0';
		}

		free(tmp.ptr);
		return spz_to_var(out);
	}

	mpz_t out;
	mpz_init_set_str(out, tmp.ptr, /*base*/ 10); // this should not fail unless it runs out of memory

	free(tmp.ptr);

	// NOTE: a 39-digit number sometimes fits in spz_t, but 40+ never does.
	return tmp.len == 39 ? mpz_to_var_constrict(out) : mpz_to_var(out);
}

///////////////////////////// miscellaneous /////////////////////////////

static void dsl_put_val(var_val_t x) {
#if DEBUG
	switch (x.type) {
		case VAR_SPZ: printf("[SPZ] "); break;
		case VAR_MPZ: printf("[MPZ] "); break;
		case VAR_STR: printf("[STR] "); break;
		default:
			unreachable();
	}
#endif

	switch (x.type) {
		case VAR_SPZ:
			put_spz(x.spz);
			break;

		case VAR_MPZ: {
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			char *str = mpz_get_str(nullptr, 10, x.mpz);
			printf("%s", str);
			free(str);
			#pragma GCC diagnostic pop
			break;
		}

		case VAR_STR:
			// this work because string variable pointers are supposed to be C strings as well as V strings.
			// the do-while is always correct though.
			printf("%s", x.str.ptr);

			/*
			do {
				int chunk = x.str.len >= INT_MAX ? INT_MAX : (int) x.str.len;
				printf("%.*s", chunk, x.str.ptr);

				if (chunk < 0)
					unreachable();

				x.str.ptr +=       chunk;
				x.str.len -= (u64) chunk;
			} while (x.str.len > 0);
			*/
			break;

		default:
			unreachable();
	}
}

FORCE_INLINE static void dsl_puts_val(var_val_t x) {
	dsl_put_val(x);
	putchar('\n');
}

FORCE_INLINE static void dsl_clear_val(var_val_t x) {
	// this is intended to be used only for temporary variables, so they should not be VAR_STR.
	// if it is an actual variable in the variable map, use `dsl_free_var`.
	if (x.type == VAR_MPZ)
		mpz_clear(x.mpz);
}

FORCE_INLINE static bool spz__cat_overflows(spz_t z1, spz_t z2) {
	// returns whether or not the result of an `SPZ . SPZ` concat will fit in an SPZ
	// NOTE: this is stricter than necessary, especially if z2 is negative
	return spz_sizeinbase10(z1) + spz_sizeinbase10(z2) >= 39;
}

/////////////////////////////// operators ///////////////////////////////

/*
abs(x)   => &x
sign(x)  => x / &(x or !x)
(x == y) => !(x xor y)
(x != y) => !!(x xor y)
(x >= y) => !(x - y >> 200_000_000_000)
(x <= y) => !(y - x >> 200_000_000_000)
(x > y)  => !!(y - x >> 200_000_000_000)
(x < y)  => !!(x - y >> 200_000_000_000)

// 2^37 also works instead of 200_000_000_000.
// NOTE: 2^37 >= 64(2^31 - 1), which is the max bits in an mpz_t
*/

// NOTE: div and mod are truncating, but shr is floored (twos complement)

static var_val_t dsl_pow(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ && y.type == VAR_SPZ) {
		// 0^-n => 1/0^n => error. n^-k => 0

		if (y.spz < 0) {
			if unlikely (x.spz == 0) {
				eprintf("division by zero.");
				dsl_panic(EXCEPT_ERR_PARSER);
			}

			return spz_to_var(0);
		}

		if (x.spz == 1)
			return x;

		if (x.spz == -1)
			return spz_to_var(y.spz & 1 ? -1 : 1);

		if ((u32) (spn_t) y.spz <= SPZ_MAG_BITS &&
			(u32) (spn_t) y.spz * __builtin_stdc_bit_ceil(spz_abs(x.spz)) < SPZ_MAG_BITS
		) {
			// TODO: see if `<=` is okay in place of `<`. I think it might be due to the
			//       slack from the bit ceiling, but it doesn't follow from the following proof.
			/*
			assume y > 0.
			f(x, y) := x^y < 2^127
			f(x, y) = log2(x^y) < log2(2^127)
			=> y log2(x) < 127 log2(2)
			=> (stricter bound) y ceil(log2(x)) < 127
			*/
			spz_t out = 1;
			static_assert(8*sizeof(spz_t) < 256, "increase `exp` `i` and past u8.");
			u8 exp = (u8) (spn_t) y.spz;

			for (u8 i = (u8) (u32) __builtin_stdc_bit_width(exp); i --> 0 ;) {
				out *= out;

				if ((exp >> i) & 1)
					out *= x.spz;
			}

			return spz_to_var(out);
		}
	}

	bool free_x = false, free_y = false;

	if (x.type == VAR_SPZ) {
		free_x = true;
		spz_to_mpz(x.mpz, x.spz);
	}

	if (y.type == VAR_SPZ) {
		free_y = true;
		spz_to_mpz(y.mpz, y.spz);
	}

	var_val_t res;

	if (mpz_sgn(y.mpz) < 0) {
		if unlikely (mpz_sgn(x.mpz) == 0) {
			eprintf("division by zero.");
			dsl_panic(EXCEPT_ERR_PARSER);
		}

		res = spz_to_var(0);
		goto done;
	}

	if unlikely (mpz_cmp_ui(x.mpz, 1) == 0) {
		res = spz_to_var(1);
		goto done;
	}

	if unlikely (mpz_cmp_si(x.mpz, -1) == 0) {
		res = spz_to_var(mpz_odd_p(y.mpz) ? -1 : 1);
		goto done;
	}

	{
		mpz_t out;
		mpz_init_set_ui(out, 1);

		for (u64 i = mpz_sizeinbase(y.mpz, 2); i --> 0 ;) {
			mpz_mul(out, out, out);

			if (mpz_tstbit(y.mpz, (unsigned long) i))
				mpz_mul(out, out, x.mpz);
		}

		res = mpz_to_var_constrict(out);
	}

done:
	if (free_x) mpz_clear(x.mpz);
	if (free_y) mpz_clear(y.mpz);

	return res;
}

[[maybe_unused]]
static var_val_t dsl_neg(var_val_t x) {
	// -x
	assert_var_int(x);

	if (x.type == VAR_SPZ) {
		x.spz = -x.spz;
		return x;
	}

	mpz_t out;
	mpz_init(out);
	mpz_neg(out, x.mpz);
	return mpz_to_var(out);
}

[[maybe_unused]]
static var_val_t dsl_not(var_val_t x) {
	// !x
	assert_var_int(x);

	if (x.type == VAR_SPZ) {
		x.spz = !x.spz;
		return x;
	}

	return spz_to_var(mpz_sgn(x.mpz) == 0);
}

[[maybe_unused]]
static var_val_t dsl_com(var_val_t x) {
	// ~x
	assert_var_int(x);

	if (x.type == VAR_SPZ) {
		x.spz = ~x.spz;
		return x;
	}

	mpz_t out;
	mpz_init(out);
	mpz_com(out, x.mpz);
	return mpz_to_var(out);
}

[[maybe_unused]]
static var_val_t dsl_abs(var_val_t x) {
	assert_var_int(x);

	if (x.type == VAR_SPZ) {
		if (x.spz < 0)
			x.spz = -x.spz;

		return x;
	}

	mpz_t out;
	mpz_init(out);
	mpz_abs(out, x.mpz);
	return mpz_to_var(out);
}

[[maybe_unused]]
static var_val_t dsl_cat(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ && y.type == VAR_SPZ && !spz__cat_overflows(x.spz, y.spz)) {
		// shift = 10^len(str(y))
		spz_t shift = 1;
		for (u32 i = spz_sizeinbase10(y.spz); i --> 0 ;)
			shift *= 10;

		// x*shift + y*sign(x)
		return spz_to_var( x.spz * shift + (x.spz >= 0 ? y.spz : -y.spz) );
	}

	bool free_x = false, free_y = false;

	if (x.type == VAR_SPZ) {
		free_x = true;
		spz_to_mpz(x.mpz, x.spz);
	}

	if (y.type == VAR_SPZ) {
		free_y = true;
		spz_to_mpz(y.mpz, y.spz);
	}

	mpz_t out;
	mpz_init(out);

	const bool y_negative = mpz_sgn(y.mpz) < 0;
	mpz_abs(y.mpz, y.mpz);

	if unlikely (mpz_sgn(y.mpz) == 0)
		// 0 has exactly 1 digit, so the out is 10
		mpz_set_ui(out, 10);
	else {
		// true size of `y.mpz` is either `size` or `size + 1`.
		u64 size = mpz_sizeinbase(y.mpz, 10) - 1;

	#ifdef _WIN32
		mpz_set_ui(out, 1);
		mpz_t tmp;
		mpz_init(tmp);

		while (size > 0) { // <= 10 iterations
			// unsigned long is 32-bits on Windows
			u32 chunk = size >= UINT32_MAX ? UINT32_MAX : (u32) size;

			mpz_ui_pow_ui(tmp, 10, chunk);
			mpz_mul(out, out, tmp);

			size -= chunk;
		}

		mpz_clear(tmp);
	#else
		mpz_ui_pow_ui(out, 10, size);
	#endif

		if (mpz_cmp(out, y.mpz) <= 0)
			mpz_mul_ui(out, out, 10);
	}

	if (y_negative)
		// restore the sign of y.
		mpz_neg(y.mpz, y.mpz);

	// `out` is currently 10^len(|y|).

	mpz_mul(out, out, x.mpz);

	if (mpz_sgn(x.mpz) < 0)
		mpz_sub(out, out, y.mpz);
	else
		mpz_add(out, out, y.mpz);

	if (free_x) mpz_clear(x.mpz);
	if (free_y) mpz_clear(y.mpz);

	// the constrict is required here.
	return mpz_to_var_constrict(out);
}

[[maybe_unused]]
static var_val_t dsl_mul(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ) {
			// SPZ * SPZ
			spz_t z;

			if (!__builtin_mul_overflow(x.spz, y.spz, &z))
				return spz_to_var(z);

			// SPZ * SPZ with overflow
			mpz_t out, tmp;
			spz_to_mpz(out, x.spz);
			spz_to_mpz(tmp, y.spz);

			mpz_mul(out, out, tmp);
			mpz_clear(tmp);

			return mpz_to_var(out);
		}

		// SPZ * MPZ => MPZ * SPZ
		// NOTE: this works because addition is commutative
		var_val_t t;
		t = x;
		x = y;
		y = t;
	}

	if (y.type == VAR_SPZ) {
		// MPZ * SPZ
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_mul(out, x.mpz, out);

		return mpz_to_var(out);
	}

	// MPZ * MPZ
	mpz_t out;
	mpz_init_set(out, x.mpz);
	mpz_mul(out, out, y.mpz);

	return mpz_to_var(out);
}

[[maybe_unused]]
static var_val_t dsl_div(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ) {
			if unlikely (y.spz == 0) {
				eprintf("division by zero.");
				dsl_panic(EXCEPT_ERR_PARSER);
			}

			// SPZ / SPZ
			return spz_to_var(x.spz / y.spz);
		}

		// SPZ / MPZ
		if likelyp (mpz_sizeinbase(y.mpz, 2) > spz_size(x.spz), 0.9999d)
			// this should always be true
			// |y| > |x| => x / y == 0
			return spz_to_var(0);

		// in case the MPZ value was SPZ-sized for some reason.
		mpz_t out;
		spz_to_mpz(out, x.spz);
		mpz_tdiv_q(out, out, y.mpz);
		return mpz_to_var_constrict(out);
	}

	// MPZ / ?PZ

	if (y.type == VAR_SPZ) {
		// MPZ / SPZ
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_tdiv_q(out, x.mpz, out);
		return mpz_to_var_constrict(out);
	}

	// MPZ / MPZ
	mpz_t out;
	mpz_init(out);
	mpz_tdiv_q(out, x.mpz, y.mpz);
	return mpz_to_var_constrict(out);
}

[[maybe_unused]]
static var_val_t dsl_mod(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ) {
			if unlikely (y.spz == 0) {
				eprintf("division by zero.");
				dsl_panic(EXCEPT_ERR_PARSER);
			}

			// SPZ % SPZ
			return spz_to_var(x.spz % y.spz);
		}

		// SPZ % MPZ
		if likelyp (mpz_sizeinbase(y.mpz, 2) > spz_size(x.spz), 0.9999d)
			// this should always be true
			// |y| > |x| => x % y == x
			return spz_to_var(x.spz);

		// in case the MPZ value was SPZ-sized for some reason.
		mpz_t out;
		spz_to_mpz(out, x.spz);
		mpz_tdiv_r(out, out, y.mpz);
		return mpz_to_var_constrict(out);
	}

	// MPZ % ?PZ

	if (y.type == VAR_SPZ) {
		// MPZ % SPZ
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_tdiv_r(out, x.mpz, out);
		return mpz_to_var_constrict(out);
	}

	// MPZ % MPZ
	mpz_t out;
	mpz_init(out);
	mpz_tdiv_r(out, x.mpz, y.mpz);
	return mpz_to_var_constrict(out);
}

[[maybe_unused]]
static var_val_t dsl_add(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ) {
			// SPZ + SPZ
			spz_t z;

			if (!__builtin_add_overflow(x.spz, y.spz, &z))
				return spz_to_var(z);

			// SPZ + SPZ with overflow
			mpz_t out, tmp;
			spz_to_mpz(out, x.spz);
			spz_to_mpz(tmp, y.spz);

			mpz_add(out, out, tmp);
			mpz_clear(tmp);

			return mpz_to_var(out);
		}

		// SPZ + MPZ => MPZ + SPZ
		var_val_t t;
		t = x;
		x = y;
		y = t;
	}

	if (y.type == VAR_SPZ) {
		// MPZ + SPZ
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_add(out, x.mpz, out);

		return mpz_to_var_constrict(out);
	}

	// MPZ + MPZ
	mpz_t out;
	mpz_init_set(out, x.mpz);
	mpz_add(out, out, y.mpz);

	return mpz_to_var_constrict(out);
}

[[maybe_unused]]
static var_val_t dsl_sub(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);
	// assume neither argument is VAR_STR.

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ) {
			// SPZ - SPZ
			spz_t z;

			if (!__builtin_sub_overflow(x.spz, y.spz, &z))
				return spz_to_var(z);

			// SPZ - SPZ with overflow
			mpz_t out, tmp;
			spz_to_mpz(out, x.spz);
			spz_to_mpz(tmp, y.spz);

			mpz_sub(out, out, tmp);
			mpz_clear(tmp);

			return mpz_to_var(out);
		}

		// SPZ - MPZ
		mpz_t out;
		spz_to_mpz(out, x.spz);
		mpz_sub(out, out, y.mpz);

		return mpz_to_var_constrict(out);
	}

	if (y.type == VAR_SPZ) {
		// MPZ - SPZ
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_sub(out, x.mpz, out);

		return mpz_to_var_constrict(out);
	}

	// MPZ - MPZ
	mpz_t out;
	mpz_init_set(out, x.mpz);
	mpz_sub(out, out, y.mpz);

	return mpz_to_var_constrict(out);
}

static var_val_t dsl_shr(var_val_t x, var_val_t y); // resolve circular reference

static var_val_t dsl_shl(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (y.type == VAR_MPZ) {
		// see dsl_shr for the comments in this section

		if unlikelyp (mpz_fits_spz_p(y.mpz), 0.9999d)
			return dsl_shl(x, spz_to_var( mpz_to_spz(y.mpz) ));

		if unlikely (mpz_sgn(y.mpz) < 0)
			// x << -super large => x >> super large => 0 or -1
			return spz_to_var((x.type == VAR_SPZ ? x.spz < 0 : mpz_sgn(x.mpz) < 0) ? -1 : 0);

		dsl_oom();
	}

	if unlikely (y.spz < 0) {
		if unlikely (y.spz == SPZ_MIN)
			y.spz++;

		y.spz = -y.spz;

		return dsl_shr(x, y);
	}

	// y is positive SPZ

	if (x.type == VAR_SPZ) {
		const bool negative = x.spz < 0;
		spn_t mag = spz_abs(x.spz);

		if (spn_size(mag) + y.spz < SPZ_MAG_BITS) {
			// this is shifting doing sign(x)*(abs(x) << y) because left shifting a negative
			// value is undefined for whatever reason.
			mag <<= y.spz;
			return spz_to_var(negative ? -(spz_t) mag : (spz_t) mag);
		}

		mpz_t tmp;
		spz_to_mpz(tmp, x.spz);
		var_val_t out = dsl_shl(mpz_to_var(tmp), y);
		mpz_clear(tmp);
		return out;
	}

	// x is MPZ

	if unlikely (mpz_sgn(x.mpz) == 0)
		return spz_to_var(0);

	if unlikely (y.spz >= MP_MAX_BITS || mpz_sizeinbase(x.mpz, 2) + y.spz > MP_MAX_BITS)
		dsl_oom();

	mpz_t out;
	mpz_init(out);

#ifdef _WIN32
	spn_t shift = (spn_t) y.spz;
	mpz_ptr src = x.mpz;

	do {
		mp_bitcnt_t chunk = shift > (spn_t) MP_BITCNT_MAX ?
			MP_BITCNT_MAX :
			(mp_bitcnt_t) shift;

		mpz_mul_2exp(out, src, chunk);

		shift -= (spn_t) chunk;
		src = out;
	} while (shift > 0);
#else
	static_assert(8*sizeof(mp_bitcnt_t) >= 8*sizeof(mp_limbcnt_t) + /*log2(64)*/ 6,
		"mp_bitcnt_t isn't exhaustive of the bit space. this should be unreachable");

	mpz_mul_2exp(out, x.mpz, (mp_bitcnt_t) (spn_t) y.spz);
#endif

	return mpz_to_var(out);
}

static var_val_t dsl_shr(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (y.type == VAR_MPZ) {
		if unlikelyp (mpz_fits_spz_p(y.mpz), 0.9999d)
			return dsl_shr(x, spz_to_var( mpz_to_spz(y.mpz) ));

		// the max number of limbs is 2^31 - 1, times 64 bits per limb, so there
		// can never be more than 37 bits worth of stuff. so saturating to spz_t
		// can't lose information. also it will never be 0, because 0 is small.

		if (mpz_sgn(y.mpz) > 0)
			// `x >> massive number` => 0 or -1
			return spz_to_var((x.type == VAR_SPZ ? x.spz < 0 : mpz_sgn(x.mpz) < 0) ? -1 : 0);

		// `x << massive number` is not representable
		dsl_oom();
	}

	// ?PZ >> SPZ

	if unlikely (y.spz < 0) {
		if unlikely (y.spz == SPZ_MIN)
			// avoid UB. just make it negate to SPN_MAX
			y.spz++;

		y.spz = -y.spz;

		return dsl_shl(x, y);
	}

	if (x.type == VAR_MPZ) {
		if (y.spz >= mpz_sizeinbase(x.mpz, 2))
			return spz_to_var(mpz_sgn(x.mpz) < 0 ? -1 : 0);

		mpz_t out;
		mpz_init(out);

	#ifdef _WIN32
		spn_t shift = (spn_t) y.spz;
		mpz_ptr src = x.mpz;

		do {
			mp_bitcnt_t chunk = shift > (spn_t) MP_BITCNT_MAX ?
				MP_BITCNT_MAX :
				(mp_bitcnt_t) shift;

			mpz_fdiv_q_2exp(out, src, chunk);

			shift -= (spn_t) chunk;
			src = out;
		} while (shift > 0);
	#else
		static_assert(8*sizeof(mp_bitcnt_t) >= 8*sizeof(mp_limbcnt_t) + /*log2(64)*/ 6,
			"mp_bitcnt_t isn't exhaustive of the bit space. this should be unreachable");

		mpz_fdiv_q_2exp(out, x.mpz, (mp_bitcnt_t) (spn_t) y.spz);
	#endif

		return mpz_to_var_constrict(out);
	}

	// x is SPZ

	if (y.spz >= 8*sizeof(spz_t))
		return spz_to_var(x.spz < 0 ? -1 : 0);

	return spz_to_var(x.spz >> (spn_t) y.spz);
}

static var_val_t dsl_ior(var_val_t x, var_val_t y); // out of order reference

static var_val_t dsl_rol(var_val_t x, var_val_t y) {
	/*
	ROL and ROR interpret the left argument integer as a 2-adic integer, then the rotation is applied,
	and then the resulting 2-adic integer is reinterpreted back as a regular integer. Under that model,
	(x <<< n) => (x << n) | (x < 0) & ((1 << n) - 1), and (x >>> n) => (x >> n). The logic behind the
	left shift is simple, since bitwise operations use infinite two's compliment, so a positive number
	has infinite zeros to the left and a negative number has infinite ones to the left, so left shifting
	by n bits will spawn 1s for a negative number of 0s for a positive one.

	For right rotation, there is a simple case and a more complicated case. If all of the bits being
	rotated off the right side are equivalent to the sign bit, then the rotation is fully defined, since
	when those bits are moved to bit infinity, nothing changes, so it is the same as x >> n in that case.
	The other case is a bit more complicated.

	Case A (positive)
	let x = ...01111111 (= 127)

	x >>> 1 is the limit of the following:
	|i=1 =>         10111111
	|i=2 =>        100111111
	|i=3 =>       1000111111
	|                    ...
	|i=9 => 1000000000111111
	|                    ...

	for every bit n for n >= 6, if you go enough iterations out, the value stabilizes as a 0.
	so the value approaches ...00111111, which is 63.

	Case B (negative):
	let x = ...10000000 (= -128)

	x >>> 1 is the limit of the following:
	|i=1 =>         01000000
	|i=2 =>        011000000
	|i=3 =>       0111000000
	|                    ...
	|i=9 => 0111111111000000
	|                    ...

	for every bit n for n >= 6, if you go enough iterations out, the value stabilizes as a 1.
	so the value approaches ...11000000, which is -64.

	in either case, the bits being shifted off are essentially deleted, since they do not matter
	in the limit, which means this is identical to x >> n
	*/
	// (x <<< n) => (x << n) | (x < 0) & ((1 << n) - 1)

	assert_var_int(x);
	assert_var_int(y);

	if (y.type == VAR_MPZ) {
		if unlikelyp (mpz_fits_spz_p(y.mpz), 0.9999d)
			return dsl_rol(x, spz_to_var( mpz_to_spz(y.mpz) ));

		// negative shift ROL is the same as positive ROR, which is the same as SHR. x >> large => 0 or -1
		if unlikely (mpz_sgn(y.mpz) < 0)
			return spz_to_var((x.type == VAR_SPZ ? x.spz < 0 : mpz_sgn(x.mpz) < 0) ? -1 : 0);

		dsl_oom();
	}

	if unlikely (y.spz < 0) {
		if unlikely (y.spz == SPZ_MIN)
			y.spz++;

		y.spz = -y.spz;

		return dsl_shr(x, y);
	}

	// y is positive SPZ

	var_val_t out = dsl_shl(x, y);

	if (x.type == VAR_SPZ) {
		if (x.spz >= 0)
			return out;

		if (out.type == VAR_SPZ) {
			// since x < 0, |x| >= 1, and x << y fits in spz, so 1 << y.spz definitely fits in spz
			out.spz |= ((spz_t) 1 << y.spz) - 1;
			return out;
		}

		// out is MPZ
	}
	else {
		// MPZ <<< SPZ

		if (mpz_sgn(x.mpz) >= 0)
			return out;

		// NOTE: MPZ << +SPZ => MPZ
	}

	// out is MPZ

	if (y.spz < 8*sizeof(spz_t) - 1) {
		mpz_t tmp;
		spz_to_mpz(tmp, ((spz_t) 1 << y.spz) - 1);

		mpz_ior(out.mpz, out.mpz, tmp);
		mpz_clear(tmp);
		return out;
	}

	const var_val_t tmp = dsl_pow(
		spz_to_var(2),
		spz_to_var(y.spz)
	);

#if DEBUG
	if (tmp.type != VAR_MPZ)
		fatal(1, "[BUG] 2^(y >= 127) is not SPZ.");
#endif

	mpz_ior(out.mpz, out.mpz, tmp.mpz);
	dsl_clear_val(tmp);
	return out;
}

[[maybe_unused]]
static var_val_t dsl_ror(var_val_t x, var_val_t y) {
	// see dsl_rol for the explanation of the logic behind ROL and ROR two of these
	// (x >>> n) => (x >> n)

	assert_var_int(x);
	assert_var_int(y);

	if (y.type == VAR_MPZ) {
		if unlikelyp (mpz_fits_spz_p(y.mpz), 0.9999d)
			// rol => shr
			return dsl_shr(x, spz_to_var( mpz_to_spz(y.mpz) ));

		// x >>> y => x >> large => 0 or -1
		if unlikely (mpz_sgn(y.mpz) > 0)
			return spz_to_var((x.type == VAR_SPZ ? x.spz < 0 : mpz_sgn(x.mpz) < 0) ? -1 : 0);

		// x >>> -large => x <<< +large => OOM
		dsl_oom();
	}

	if unlikely (y.spz < 0) {
		if unlikely (y.spz == SPZ_MIN)
			y.spz++;

		y.spz = -y.spz;

		return dsl_rol(x, y);
	}

	// y SPZ >= 0

	return dsl_shr(x, y);
}

[[maybe_unused]]
static var_val_t dsl_and(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ)
			return spz_to_var(x.spz & y.spz);

		// SPZ & MPZ => MPZ & SPZ
		var_val_t t;
		t = x;
		x = y;
		y = t;
	}

	// MPZ & ?PZ

	if (y.type == VAR_SPZ) {
		if (y.spz >= 0)
			return spz_to_var(trunc_mpz_to_spz(x.mpz) & y.spz);

		// since two's compliment means negative values have infinite 1s to the left,
		// MPZ & -SPZ could theoretically return a value outside of the SPZ range.
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_and(out, out, x.mpz);
		return mpz_to_var_constrict(out);
	}

	// MPZ & MPZ

	mpz_t out;
	mpz_init(out);
	mpz_and(out, x.mpz, y.mpz);
	return mpz_to_var_constrict(out);
}

static var_val_t dsl_ior(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ)
			return spz_to_var(x.spz | y.spz);

		// SPZ | MPZ => MPZ | SPZ
		var_val_t t;
		t = x;
		x = y;
		y = t;
	}

	// MPZ | ?PZ

	if (y.type == VAR_SPZ) {
		if (y.spz < 0)
			// the infinite left 1s from the negative sign make the output in spz range
			return spz_to_var(trunc_mpz_to_spz(x.mpz) | y.spz);

		// MPZ | +SPZ could theoretically return a value outside of the SPZ range.
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_ior(out, out, x.mpz);
		return mpz_to_var_constrict(out);
	}

	// MPZ | MPZ

	// the constrict can be useful if both values are negative.
	mpz_t out;
	mpz_init(out);
	mpz_ior(out, x.mpz, y.mpz);
	return mpz_to_var_constrict(out);
}

[[maybe_unused]]
static var_val_t dsl_xor(var_val_t x, var_val_t y) {
	assert_var_int(x);
	assert_var_int(y);

	if (x.type == VAR_SPZ) {
		if (y.type == VAR_SPZ)
			return spz_to_var(x.spz ^ y.spz);

		// SPZ ^ MPZ => MPZ ^ SPZ
		var_val_t t;
		t = x;
		x = y;
		y = t;
	}

	// MPZ ^ ?PZ

	if (y.type == VAR_SPZ) {
		// neither +SPZ nor -SPZ destroys the high bits of x.
		mpz_t out;
		spz_to_mpz(out, y.spz);
		mpz_xor(out, out, x.mpz);
		return mpz_to_var_constrict(out);
	}

	// MPZ ^ MPZ

	// the constrict can be useful if both values are negative.
	mpz_t out;
	mpz_init(out);
	mpz_xor(out, x.mpz, y.mpz);
	return mpz_to_var_constrict(out);
}

#undef assert_var_int

// `OUT` must be an actual variable. it should not have side-effects.
#define dsl_unary_repl(OP, OUT, IN1) ({ \
	const var_val_t                     \
		in1_ = (IN1),                   \
		res_ = dsl_##OP(in1_);          \
	dsl_clear_val(OUT);                 \
	OUT = res_;                         \
})

#define dsl_binary_repl(OP, OUT, IN1, IN2) ({ \
	const var_val_t                           \
		in1_ = (IN1),                         \
		in2_ = (IN2),                         \
		res_ = dsl_##OP(in1_, in2_);          \
	dsl_clear_val(OUT);                       \
	OUT = res_;                               \
})

#pragma GCC diagnostic pop // -Waddress-of-packed-member
