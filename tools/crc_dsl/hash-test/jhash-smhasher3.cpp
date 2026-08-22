/*
 * jhash
 * Copyright (C) 2026 Daniel Janusch
 *
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use,
 * copy, modify, merge, publish, distribute, sublicense, and/or
 * sell copies of the Software, and to permit persons to whom the
 * Software is furnished to do so, subject to the following
 * conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
 * OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
 * HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
 * WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
 * FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
 * OTHER DEALINGS IN THE SOFTWARE.
 */
#include "Platform.h"
#include "Hashlib.h"
#include "MathMult.h"

/*
tests that fail for jhash64:
Permutations:
	Combination 4-bytes [3 low bits; BE]' - up to 7 blocks from a set of 8
TwoBytes:
	all [2, 20]-byte keys with 1 or 2 non-zero bytes

test that fail for jhash128:
Permutation:
    (partial) Combination 4-bytes [3 low bits; BE]
    (partial) Combination 4-bytes [3 high+low bits; BE]
TwoBytes:
    all [2, 20]-byte keys with 1 or 2 non-zero bytes
*/

//------------------------------------------------------------
static FORCE_INLINE uint64_t jhash_mulhi64(uint64_t x, uint64_t y) {
	uint64_t lo, hi;
	MathMult::mult64_128(lo, hi, x, y);
	return hi;
}

static inline uint128_t jhash_mulhi128(uint128_t x, uint128_t y) {
	// no carry propogation

	const uint64_t  xhi = (uint64_t) (x >> 64);
	const uint64_t  yhi = (uint64_t) (y >> 64);

	const uint64_t  lo_hi = jhash_mulhi64((uint64_t) x, yhi);
	const uint64_t  hi_lo = jhash_mulhi64(xhi, (uint64_t) y);
	const uint128_t hi_hi = (uint128_t) xhi * yhi;

	return hi_hi + lo_hi + hi_lo;
}

#define U128C(hi, lo) ((uint128_t) (0x##hi##llu) << 64 | (uint128_t) (0x##lo##llu))
#define BSWAP128(x) ( (uint128_t) BSWAP64((uint64_t) (x)) << 64 | BSWAP64((uint64_t) ((x) >> 64)) )

template <bool bswap>
static uint64_t jhash64_impl(const void *_data, size_t len, uint64_t key) {
	constexpr uint64_t p1 = 0x6a09e667f3bcc909llu;
	constexpr uint64_t p2 = 0x3c6ef372fe94f82cllu;
	constexpr uint64_t p3 = 0xc4ceb9fe1a85ec53llu;
	constexpr uint64_t mx = 0xff51afd7ed558ccdllu;
	constexpr uint64_t x1 = 0x736f6d6570736575llu;
	constexpr uint64_t x2 = 0x6c7967656e657261llu;
	constexpr uint64_t x3 = 0x25232284e49cf2cbllu;
	const uint64_t *data = (const uint64_t *) _data;

	uint64_t hash = BSWAP64(key ^ x1) | 1;
	uint64_t rkey =        (key ^ x2) | 1;
	uint64_t fbkh;

	key  ^= x3;
	rkey += p2;

	while (len >= 8) {
		uint64_t tmp;
		fbkh  = hash;
		len  -= 8;
		hash ^= GET_U64<bswap>((const uint8_t *) data, 0);
		tmp   = jhash_mulhi64(fbkh, rkey);
		hash *= p1;
		data += 1;
		hash ^= tmp;
		rkey += p2;
	}

	if (len > 0) {
		uint64_t chunk = len << 7*8;
		fbkh = hash;

		switch (len) {
			default: __builtin_unreachable(); break;
			case 7: chunk |= (uint64_t) ((const uint8_t *) data)[6] << 6*8; [[fallthrough]];
			case 6: chunk |= (uint64_t) ((const uint8_t *) data)[5] << 5*8; [[fallthrough]];
			case 5: chunk |= (uint64_t) ((const uint8_t *) data)[4] << 4*8; [[fallthrough]];
			case 4: chunk |= (uint64_t) ((const uint8_t *) data)[3] << 3*8; [[fallthrough]];
			case 3: chunk |= (uint64_t) ((const uint8_t *) data)[2] << 2*8; [[fallthrough]];
			case 2: chunk |= (uint64_t) ((const uint8_t *) data)[1] << 1*8; [[fallthrough]];
			case 1: chunk |= (uint64_t) ((const uint8_t *) data)[0] << 0*8; break;
		}

		hash ^= chunk;
		hash *= p1;
		hash ^= jhash_mulhi64(fbkh, rkey);
	}

	hash ^= jhash_mulhi64(hash, key | 1);
	hash *= p3;
	fbkh  = hash;
	hash  = BSWAP64(hash * mx);
	hash ^= hash >> 13;
	hash ^= fbkh;

	return hash;
}

template <bool bswap>
static uint128_t jhash128_impl(const void *_data, size_t len, uint128_t key) {
	constexpr uint128_t p1 = U128C(6a09e667f3bcc908,b2fb1366ea957d3f);
	constexpr uint128_t p2 = U128C(3c6ef372fe94f82b,e73980c0b9db9068);
	constexpr uint128_t p3 = U128C(9c2d21e4b5bc4be9,c4ceb9fe1a85ec53);
	constexpr uint128_t mx = U128C(ff3e36acd17d11a6,3f51afd7ed558ccd);
	constexpr uint128_t x1 = U128C(646f72616e646f6d,736f6d6570736575);
	constexpr uint128_t x2 = U128C(7465646279746573,6c7967656e657261);
	constexpr uint128_t x3 = U128C(8dc595627521b862,4201bb072e27626c);
	const uint128_t *data = (const uint128_t *) _data;

	uint128_t hash = BSWAP128(key ^ x1) | 1;
	uint128_t rkey =         (key ^ x2) | 1;
	uint128_t fbkh;

	key  ^= x3;
	rkey += p2;

	while (len >= 16) {
		uint128_t tmp;
		fbkh  = hash;
		len  -= 16;
		tmp   = jhash_mulhi128(fbkh, rkey);
		hash *= p1;
		data += 1;
		hash ^= tmp;
		rkey += p2;
	}

	if (len > 0) {
		uint128_t chunk = (uint128_t) len << 15*8;
		fbkh = hash;

		switch (len) {
			default: __builtin_unreachable(); break;
			case 15: chunk |= (uint128_t) ((const uint8_t *) data)[14] << 14*8; [[fallthrough]];
			case 14: chunk |= (uint128_t) ((const uint8_t *) data)[13] << 13*8; [[fallthrough]];
			case 13: chunk |= (uint128_t) ((const uint8_t *) data)[12] << 12*8; [[fallthrough]];
			case 12: chunk |= (uint128_t) ((const uint8_t *) data)[11] << 11*8; [[fallthrough]];
			case 11: chunk |= (uint128_t) ((const uint8_t *) data)[10] << 10*8; [[fallthrough]];
			case 10: chunk |= (uint128_t) ((const uint8_t *) data)[ 9] <<  9*8; [[fallthrough]];
			case  9: chunk |= (uint128_t) ((const uint8_t *) data)[ 8] <<  8*8; [[fallthrough]];
			case  8: chunk |= (uint128_t) ((const uint8_t *) data)[ 7] <<  7*8; [[fallthrough]];
			case  7: chunk |= (uint128_t) ((const uint8_t *) data)[ 6] <<  6*8; [[fallthrough]];
			case  6: chunk |= (uint128_t) ((const uint8_t *) data)[ 5] <<  5*8; [[fallthrough]];
			case  5: chunk |= (uint128_t) ((const uint8_t *) data)[ 4] <<  4*8; [[fallthrough]];
			case  4: chunk |= (uint128_t) ((const uint8_t *) data)[ 3] <<  3*8; [[fallthrough]];
			case  3: chunk |= (uint128_t) ((const uint8_t *) data)[ 2] <<  2*8; [[fallthrough]];
			case  2: chunk |= (uint128_t) ((const uint8_t *) data)[ 1] <<  1*8; [[fallthrough]];
			case  1: chunk |= (uint128_t) ((const uint8_t *) data)[ 0] <<  0*8; break;
		}

		hash ^= chunk;
		hash *= p1;
		hash ^= jhash_mulhi128(fbkh, rkey);
	}

	hash ^= jhash_mulhi128(hash, key | 1);
	hash *= p3;
	fbkh  = hash;
	hash  = BSWAP128(hash * mx);
	hash ^= hash >> 27;
	hash ^= fbkh;
	return hash;
}

//------------------------------------------------------------
template <bool bswap>
static void jhash64(const void *in, const size_t len, const seed_t seed, void *out) {
	uint64_t hash = jhash64_impl<bswap>(in, len, (uint64_t) seed);
	PUT_U64<bswap>(hash, (uint8_t *) out, 0);
}

template <bool bswap>
static void jhash128(const void *in, const size_t len, const seed_t seed, void *out) {
	uint128_t hash = jhash128_impl<bswap>(in, len, (uint128_t) seed);

	if (bswap) {
		PUT_U64<bswap>((uint64_t) (hash >> 64), (uint8_t *) out, 0);
		PUT_U64<bswap>((uint64_t) (hash >>  0), (uint8_t *) out, 8);
	}
	else {
		PUT_U64<bswap>((uint64_t) (hash >>  0), (uint8_t *) out, 0);
		PUT_U64<bswap>((uint64_t) (hash >> 64), (uint8_t *) out, 8);
	}
}

//------------------------------------------------------------
REGISTER_FAMILY(jhash,
	$.src_url    = "https://github.com/drizzt536/fpga-aes/tools/crc_dsl/map.h",
	$.src_status = HashFamilyInfo::SRC_ACTIVE
);

REGISTER_HASH(jhash64,
	$.desc            = "jhash64",
	$.hash_flags      = 0,
	$.impl_flags      = 0
		| FLAG_IMPL_LICENSE_MIT
		| FLAG_IMPL_CANONICAL_LE
		| FLAG_IMPL_MULTIPLY_64_64
		| FLAG_IMPL_MULTIPLY_64_128,
	$.bits            = 64,
	$.verification_LE = 0x86080E35,
	$.verification_BE = 0xB46112B9,
	$.hashfn_native   = jhash64<false>,
	$.hashfn_bswap    = jhash64<true>,
	$.badseeds        = { 0x736f6d6570736575llu }
);

REGISTER_HASH(jhash128,
	$.desc            = "jhash128",
	$.hash_flags      = FLAG_HASH_XL_SEED,
	$.impl_flags      = FLAG_IMPL_LICENSE_MIT | FLAG_IMPL_CANONICAL_LE,
	$.bits            = 128,
	$.verification_LE = 0x76022074,
	$.verification_BE = 0x43D3EE18,
	$.hashfn_native   = jhash128<false>,
	$.hashfn_bswap    = jhash128<true>
);
