// gcc -Ofast -flive-range-shrinkage -frename-registers -fweb -ftracer '-Wl,-s' mm3-cmp.c -o mm3-cmp
// compare speed against MurmurHash3
// usage 1: `mm3-cmp [data size]` => full data
// usage 2: `mm3-cmp [data size] [something else]` => only float output

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>

#include "../int-types.h"

#define FORCE_INLINE inline __attribute__((always_inline, gnu_inline))

static FORCE_INLINE u64 rotl64(u64 x, u32 r) {
	return __builtin_stdc_rotate_left(x, r);
}

static FORCE_INLINE u64 fmix64(u64 k) {
	k ^= k >> 33;
	k *= 0xff51afd7ed558ccdllu;
	k ^= k >> 33;
	k *= 0xc4ceb9fe1a85ec53llu;
	k ^= k >> 33;
	return k;
}

static u64 murmurhash3(const void *_data, u64 len, u64 key) {
	// MurmurHash3_128, but slightly altered to just return 64 bits
	const u8 *data = (const u8 *) _data;
	const u64 nblocks = len >> 4;

	u64 h1 = key;
	u64 h2 = key;

	const u64 c1 = 0x87c37b91114253d5llu;
	const u64 c2 = 0x4cf5ad432745937fllu;

	const u64 *blocks = (const u64 *) data;

	for (u64 i = 0; i < nblocks; i++) {
		u64 k1 = blocks[(i << 1) + 0];
		u64 k2 = blocks[(i << 1) + 1];

		k1 *= c1;
		k1 = rotl64(k1, 31);
		k1 *= c2;
		h1 ^= k1;

		h1 = rotl64(h1, 27);
		h1 += h2;
		h1 = h1*5 + 0x52dce729;

		k2 *= c2;
		k2 = rotl64(k2, 33);
		k2 *= c1;
		h2 ^= k2;

		h2 = rotl64(h2, 31);
		h2 += h1;
		h2 = h2*5 + 0x38495ab5;
	}

	const u8 *tail = data + (nblocks << 4);

	u64 k1 = 0;
	u64 k2 = 0;

	switch (len & 15) {
	case 15: k2 ^= (u64)tail[14] << 48;
	case 14: k2 ^= (u64)tail[13] << 40;
	case 13: k2 ^= (u64)tail[12] << 32;
	case 12: k2 ^= (u64)tail[11] << 24;
	case 11: k2 ^= (u64)tail[10] << 16;
	case 10: k2 ^= (u64)tail[9]  << 8;
	case  9:
		k2 ^= (u64)tail[8];
		k2 *= c2;
		k2 = rotl64(k2, 33);
		k2 *= c1;
		h2 ^= k2;

	case  8: k1 ^= (u64)tail[7] << 56;
	case  7: k1 ^= (u64)tail[6] << 48;
	case  6: k1 ^= (u64)tail[5] << 40;
	case  5: k1 ^= (u64)tail[4] << 32;
	case  4: k1 ^= (u64)tail[3] << 24;
	case  3: k1 ^= (u64)tail[2] << 16;
	case  2: k1 ^= (u64)tail[1] << 8;
	case  1:
		k1 ^= (u64)tail[0];
		k1 *= c1;
		k1 = rotl64(k1, 31);
		k1 *= c2;
		h1 ^= k1;
	}

	h1 ^= len;
	h2 ^= len;

	h1 += h2;
	h2 += h1;

	h1 = fmix64(h1);
	h2 = fmix64(h2);

	h1 += h2;

	return h1;
}

#define jhash_mulhi64(x, y) ( (u64) ((u128) (x) * (y) >> 64) )

static u64 jhash64(const void *_data, u64 len, u64 key) {
	constexpr u64 p1 = 0x6a09e667f3bcc909llu;
	constexpr u64 p2 = 0x3c6ef372fe94f82cllu;
	constexpr u64 p3 = 0xc4ceb9fe1a85ec53llu;
	constexpr u64 mx = 0xff51afd7ed558ccdllu;
	constexpr u64 x1 = 0x736f6d6570736575llu;
	constexpr u64 x2 = 0x6c7967656e657261llu;
	constexpr u64 x3 = 0x25232284e49cf2cbllu;

	const u64 *data = (const u64 *) _data;

	u64 hash = __builtin_bswap64(key ^ x1) | 1;
	u64 rkey =                  (key ^ x2) | 1;
	u64 fbkh;

	key  ^= x3; // for finalization
	rkey += p2;

	while (len >= 8) {
		u64 tmp;
		fbkh  = hash;
		len  -= 8;
		hash ^= *data;
		tmp   = jhash_mulhi64(fbkh, rkey);
		hash *= p1;
		data += 1;
		hash ^= tmp;
		rkey += p2;
	}

	if (len > 0) {
		u64 chunk = len << 7*8;
		fbkh = hash;

		switch (len) {
			default: __builtin_unreachable(); break;
			case 7: chunk |= (u64) ((const u8 *) data)[6] << 6*8; __attribute__((fallthrough));
			case 6: chunk |= (u64) ((const u8 *) data)[5] << 5*8; __attribute__((fallthrough));
			case 5: chunk |= (u64) ((const u8 *) data)[4] << 4*8; __attribute__((fallthrough));
			case 4: chunk |= (u64) ((const u8 *) data)[3] << 3*8; __attribute__((fallthrough));
			case 3: chunk |= (u64) ((const u8 *) data)[2] << 2*8; __attribute__((fallthrough));
			case 2: chunk |= (u64) ((const u8 *) data)[1] << 1*8; __attribute__((fallthrough));
			case 1: chunk |= (u64) ((const u8 *) data)[0] << 0*8; break;
		}

		hash ^= chunk;
		hash *= p1;
		hash ^= jhash_mulhi64(fbkh, rkey);
	}

	hash ^= jhash_mulhi64(hash, key | 1);
	hash *= p3;
	fbkh  = hash;
	hash *= mx;
	hash  = __builtin_bswap64(hash);
	hash ^= hash >> 13;
	hash ^= fbkh;
	return hash;
}

#define ITERATIONS 50'000'000ull

int main(int argc, const char **argv) {
	argc--; argv++;

	u64 data_size = 64;

	if (argc != 0) {
		char *str_end;

		data_size = strtoull(*argv, &str_end, 10);

		if (*str_end != '\0') {
			printf("first argument is not valid: not an integer");
			return 1;
		}
	}

	printf("asdf => 0x%016llx\n", jhash64("asdf", 4, 0));
	printf("qwer => 0x%016llx\n", jhash64("qwer", 4, 0));
	printf("1234 => 0x%016llx\n", jhash64("1234", 4, 0));

	u8 data[data_size];
	for (int i = 0; i < data_size; i++)
		data[i] = (u8)(i ^ 0x5A);

	// Volatile sink to force evaluation of the accumulator and prevent dead-code removal
	volatile u64 sink = 0;
	u64 accumulator   = 0;

	u64 start_cycles, end_cycles;
	u64 cycles_mm3, cycles_jhash64;

	if (argc < 2)
		printf("Benchmarking %llu iterations using CPU Time-Stamp Counter...\n\n", (u64) ITERATIONS);

	for (volatile u32 warmup = 10000; warmup --> 0 ;);

	accumulator = 0;

	start_cycles = __builtin_ia32_rdtsc();

	for (u64 i = 0; i < ITERATIONS; i++)
		accumulator += murmurhash3(data, data_size, 0x123456789ABCDEF0llu + i);

	sink = accumulator; // Force compiler to complete calculations
	end_cycles = __builtin_ia32_rdtsc();
	cycles_mm3 = end_cycles - start_cycles;

	accumulator = 0;

	start_cycles = __builtin_ia32_rdtsc();

	for (u64 i = 0; i < ITERATIONS; i++)
		accumulator += jhash64(data, data_size, 0x123456789ABCDEF0llu + i);

	sink = accumulator; // Force compiler to complete calculations
	end_cycles = __builtin_ia32_rdtsc();
	cycles_jhash64 = end_cycles - start_cycles;

	if (argc < 2) {
		printf("Results (Raw CPU Cycles):\n");
		printf("-----------------------------------------------------------------\n");
		printf("MurmurHash3: %15llu total cycles | ~%.2f cycles/hash\n", cycles_mm3, (double)cycles_mm3 / ITERATIONS);
		printf("jhash64: %15llu total cycles | ~%.2f cycles/hash\n", cycles_jhash64, (double)cycles_jhash64 / ITERATIONS);
		printf("-----------------------------------------------------------------\n");
		printf("mmh3/jhash time: \e[32m%.3f\e[m\n", (double) cycles_mm3 / cycles_jhash64);
	}
	else
		printf("%lf\n", (double) cycles_mm3 / cycles_jhash64);

	return 0;
}
