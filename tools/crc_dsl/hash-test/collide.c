// compile: gcc -Ofast -flive-range-shrinkage -frename-registers -march=native -fweb '-Wl,-s' collide.c -o collide
// usage:   ./collide [start]

// this finds hash(x) == hash(y) where x != y pretty quickly, where it is not constrained
// to have x already constant. idk how hard it would be to do that.

#include <stdio.h>
#include <stdlib.h>
#include "../int-types.h"

#define FORCE_INLINE inline __attribute__((always_inline, gnu_inline))

#define jhash_mulhi64(x, y) ( (u64) ((u128) (x) * (y) >> 64) )

static FORCE_INLINE u64 jhash64_8_0_step(u64 hash) {
	// simplified jhash64 with fixed len == 8 and key == 0
	u64 fbkh;

	hash ^= 0x75657370656d6f73llu;
	hash *= 0x6a09e667f3bcc909llu;
	hash ^= 0x4d75215b4a944971llu;

	hash ^= jhash_mulhi64(hash, 0x25232284e49cf2cbllu);
	hash *= 0xc4ceb9fe1a85ec53llu;
	fbkh  = hash;
	hash *= 0xff51afd7ed558ccdllu;
	hash  = __builtin_bswap64(hash);
	hash ^= hash >> 13;
	hash ^= fbkh;
	return hash;
}

#define HASH jhash64_8_0_step

int main(int argc, char **argv) {
	argc--; argv++;

	u64 start = 0;

	if (argc > 0) {
		char *str_end;
		start = strtoull(*argv, &str_end, 0);

		if (*str_end != '\0') {
			puts("invalid argument. not an integer");
			return 1;
		}
	}

	for (;; putchar('\n'), start++) {
		printf("starting value:      0x%016llx\n", start);
		u64 hash1 = start;
		u64 hash2 = start;

		u64 n = 0;

		do {
			hash1 = HASH(hash1);
			hash2 = HASH(HASH(hash2));

			n++;

			if ((n & 16777215) == 0)
				printf("\riteration: %llu (0x%016llx, 0x%016llx)", n, hash1, hash2);
		} while (hash1 != hash2);

		printf("\rtotal iterations: %21llu\x1b[K\n", n);
		printf("found meeting point: 0x%016llx\x1b[K\n", hash1);

		u64 mu = 0;
		hash1 = start;

		while (hash1 != hash2) {
			hash1 = HASH(hash1);
			hash2 = HASH(hash2);
			mu++;
		}

		u64 cycle_start = hash1;
		printf("found cycle start:   0x%016llx\n", cycle_start);
		printf("distance to cycle: %20llu\n", mu);

		if (mu == 0) {
			puts("no collision possible (start already inside the cycle)");
			continue; 
		}

		u64 lam = 1;
		hash2 = HASH(hash1);

		while (hash2 != hash1) {
			hash2 = HASH(hash2);
			lam += 1;
		}

		printf("cycle length: %25llu\n", lam);

		u64 a = start;
		for (u64 i = 0; i < mu - 1; i++)
			a = HASH(a);

		printf("predecessor 1:       0x%016llx\n", a);
		u64 b = cycle_start;
		for (u64 i = 0; i < lam - 1; i++)
			b = HASH(b);

		printf("predecessor 2:       0x%016llx\n", b);

		if (a == b)
			puts("false collision, a == b");
		else if (HASH(a) != HASH(b))
			puts("false collision, hashes don't match");
		else
			puts("confirmed collision");
	}
}
