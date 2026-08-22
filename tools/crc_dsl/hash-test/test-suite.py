"""
hash function differential avalanche test suite.
"""

import random
import math

def test_speed(hash_func, /, trials=10_000, input_len=64, seed=None):
	# use this with %time in IPython
	if seed is not None:
		random.seed(seed)

	data = bytearray(random.getrandbits(8) for _ in range(input_len))
	for _ in range(trials):
		hash_func(data)

def test_avalanche(hash_func, /, trials=10_000, min_input_len=1, max_input_len=64, seed=42, hash_size=64):
	# a lot of this function was written by Gemini
	max_detected_bits = 0
	PIPE_WIDTH = 85
	for _ in range(16):
		test_input = bytes(random.getrandbits(8) for _ in range(16))
		h_val = hash_func(test_input)
		max_detected_bits = max(max_detected_bits, h_val.bit_length())

	if seed is not None:
		random.seed(seed)

	detected_hash_size = (max_detected_bits + 7 >> 3) << 3

	if detected_hash_size > hash_size:
		# this is not conclusive.
		raise ValueError(
			f"Configuration Error: hash_size is set to {hash_size} bits, "
			f"but the hash function returned a value up to {detected_hash_size} bits. "
			"Please update the hash_size argument."
		)

	class Stats:
		def __init__(self):
			self.distances = []
			self.bit_flips = [0] * hash_size

	def test_baseline(orig):
		# We return a special flag so the engine knows to compare against 0
		return orig, "BASELINE"

	def test_full_flip(orig):
		mod = bytearray(orig)
		mod[random.randint(0, len(orig) - 1)] ^= (1 << random.randint(0, 7))
		return orig, mod

	def test_left_flip(orig):
		mod = bytearray(orig)
		mod[0] ^= (1 << random.randint(0, 7))
		return orig, mod

	def test_right_flip(orig):
		mod = bytearray(orig)
		mod[-1] ^= (1 << random.randint(0, 7))
		return orig, mod

	def test_increment(orig):
		mod = bytearray(orig)
		for i in range(len(mod) - 1, -1, -1):
			if mod[i] < 255:
				mod[i] += 1
				break
			else:
				mod[i] = 0
		return orig, mod

	def test_rotate_bytes(orig):
		mod = bytearray()
		for b in orig:
			r = random.randint(1, 7)
			rotated = ((b << r) & 0xFF) | (b >> (8 - r))
			mod.append(rotated)
		return orig, mod

	def test_rotate_bytes_same(orig):
		mod = bytearray()
		r = random.randint(1, 7)
		for b in orig:
			rotated = ((b << r) & 0xFF) | (b >> (8 - r))
			mod.append(rotated)
		return orig, mod

	def test_swap(orig):
		if len(orig) < 2: return None
		mod = bytearray(orig)
		idx = random.randint(0, len(orig) - 2)
		if mod[idx] == mod[idx + 1]:
			return None
		mod[idx], mod[idx + 1] = mod[idx + 1], mod[idx]
		return orig, mod

	def test_reverse(orig):
		if len(orig) < 2: return None
		mod = orig[::-1]

		# skip if the random input happened to be a palindrome
		if mod == orig:
			return None 

		return orig, mod

	def test_rotate_input(orig):
		if len(orig) < 2: return None
		r = random.randint(1, len(orig) - 1)
		return orig, orig[r:] + orig[:r]

	def test_shuffle(orig):
		if len(orig) < 2: return None
		mod = bytearray(orig)
		random.shuffle(mod)
		if mod == orig:
			return None
		return orig, mod

	def test_prefix(orig):
		prefix_len = random.randint(min_input_len, max_input_len)
		prefix = bytearray(random.getrandbits(8) for _ in range(prefix_len))
		return orig, prefix + orig

	def test_suffix(orig):
		suffix_len = random.randint(min_input_len, max_input_len)
		suffix = bytearray(random.getrandbits(8) for _ in range(suffix_len))
		return orig, orig + suffix

	def test_prefix_same(orig):
		prefix_len = random.randint(min_input_len, max_input_len)
		prefix_byte = random.getrandbits(8)
		prefix = bytearray(prefix_byte for _ in range(prefix_len))
		return orig, prefix + orig

	def test_suffix_same(orig):
		suffix_len = random.randint(min_input_len, max_input_len)
		suffix_byte = random.getrandbits(8)
		suffix = bytearray(suffix_byte for _ in range(suffix_len))
		return orig, orig + suffix

	def test_prefix_suffix(orig):
		prefix_len = random.randint(min_input_len, max_input_len)
		suffix_len = random.randint(min_input_len, max_input_len)
		prefix = bytearray(random.getrandbits(8) for _ in range(prefix_len))
		suffix = bytearray(random.getrandbits(8) for _ in range(suffix_len))
		return orig, prefix + orig + suffix

	def test_prefix_suffix_equal(orig):
		ext_len = random.randint(min_input_len, max_input_len)
		ext = bytearray(random.getrandbits(8) for _ in range(ext_len))
		return orig, ext + orig + ext

	def test_prefix_suffix_same(orig):
		prefix_len = random.randint(min_input_len, max_input_len)
		suffix_len = random.randint(min_input_len, max_input_len)
		prefix_byte = random.getrandbits(8)
		suffix_byte = random.getrandbits(8)
		prefix = bytearray(prefix_byte for _ in range(prefix_len))
		suffix = bytearray(suffix_byte for _ in range(suffix_len))
		return orig, prefix + orig + suffix

	def test_prefix_suffix_same_equal(orig):
		ext_len = random.randint(min_input_len, max_input_len)
		ext_byte = random.getrandbits(8)
		ext = bytearray(ext_byte for _ in range(ext_len))
		return orig, ext + orig + ext

	def test_adjacent_two_bit_flip(orig):
		if len(orig) < 2: return None
		mod = bytearray(orig)
		idx = random.randint(0, len(orig) - 2)
		bit = random.randint(0, 7)
		# flip the exact same bit in two adjacent bytes
		mod[idx] ^= (1 << bit)
		mod[idx + 1] ^= (1 << bit)
		return orig, mod

	def test_delete(orig):
		if len(orig) < 2: return None
		mod = bytearray(orig)
		# delete one random byte from the array
		del mod[random.randint(0, len(mod) - 1)]
		return orig, mod

	def test_right_delete(orig):
		if len(orig) < 2: return None
		mod = bytearray(orig)
		del mod[-1]
		return orig, mod

	def test_pattern_xor(orig):
		mod = bytearray(orig)
		# randomly choose between alternating patterns or full inversion
		pattern = random.choice([0xAA, 0x55, 0xFF])
		for i in range(len(mod)):
			mod[i] ^= pattern
		return orig, mod

	def test_null_injection(orig):
		mod = bytearray(orig)
		# insert a 0x00 byte at a random index
		mod.insert(random.randint(0, len(mod)), 0x00)
		return orig, mod

	def test_dropout(orig):
		mod = bytearray(orig)
		mod[random.randint(0, len(mod))] = 0x00
		return orig, mod

	def test_independent(orig):
		len2 = random.randint(min_input_len, max_input_len)
		orig2 = bytearray(random.getrandbits(8) for _ in range(len2))
		return orig, orig2

	test_num     = 0
	passed_tests = 0

	test_suite = {
		"Baseline Distribution"         : test_baseline,
		"Full Random Bit Flip"          : test_full_flip,
		"Targeted Leftmost Byte"        : test_left_flip,
		"Targeted Rightmost Byte"       : test_right_flip,
		"Increment by 1"                : test_increment,
		"Rotate Each Byte"              : test_rotate_bytes,
		"Rotate Each Byte Same"         : test_rotate_bytes_same,
		"Adjacent Byte Swap"            : test_swap,
		"Reverse Input"                 : test_reverse,
		"Rotate Whole Input"            : test_rotate_input,
		"Shuffle Bytes"                 : test_shuffle,
		"Prefix Extension"              : test_prefix,
		"Suffix Extension"              : test_suffix,
		"Prefix Extension Same"         : test_prefix_same,
		"Suffix Extension Same"         : test_suffix_same,
		"Prefix+Suffix Extension"       : test_prefix_suffix,
		"Prefix==Suffix Extension"      : test_prefix_suffix_equal,
		"Prefix+Suffix Extension Same"  : test_prefix_suffix_same,
		"Prefix==Suffix Extension Same" : test_prefix_suffix_same_equal,
		"Adjacent 2-bit flip"           : test_adjacent_two_bit_flip,
		"Deletion"                      : test_delete,
		"Targeted Right Deletion"       : test_right_delete,
		"Alternating XOR Pattern"       : test_pattern_xor,
		"Null Injection"                : test_null_injection,
		"Byte Dropout"                  : test_dropout,
		"Independent Random Inputs"     : test_independent
	}

	summary_name_pad = max(map(len, test_suite)) + 2

	if hash_size & 1:
		opt_dev = hash_size * math.comb(hash_size - 1, hash_size - 1 >> 1) / (1 << hash_size)
	else:
		opt_dev = (hash_size >> 1) * math.comb(hash_size, hash_size >> 1) / (1 << hash_size)

	opt_dist_dev = 50 / trials**0.5

	def print_results(name, stats):
		nonlocal test_num, passed_tests

		n = len(stats.distances)
		if n == 0:
			print(f"\nNo valid trials executed for test: {name!r}")
			return

		avg       = sum(stats.distances) / n
		dev       = sum(abs(d - hash_size//2) for d in stats.distances) / n
		probs     = [stats.bit_flips[i] / n * 100 for i in range(hash_size)]
		dist_min  = min(probs)
		dist_max  = max(probs)
		dist_mean = sum(probs) / hash_size
		dist_dev  = (sum((p - dist_mean)**2 for p in probs) / hash_size)**0.5

		c1 = abs(avg - hash_size / 2) <= (0.015 * hash_size) # Distance mean within 1.5% of total bits
		c2 = abs(dev - opt_dev) <= (0.10 * opt_dev)          # Distance MAD within 10% of theoretical
		c3 = abs(dist_mean - 50.0) <= 1.0                    # Distribution mean within 1% of 50/50
		c4 = dist_dev <= 3 * opt_dist_dev                    # Distribution SD within 3x theoretical error

		passed = c1 and c2 and c3 and c4
		status = "\x1b[32mPASS\x1b[m" if passed else "\x1b[31mFAIL\x1b[m"
		passed_tests += passed

		print(f"\n{'='*PIPE_WIDTH}")
		print(f" test {(test_num := test_num + 1)}/{len(test_suite)}: {name}")
		print(f"{'='*PIPE_WIDTH}")
		print(f"result: {status}")
		print(f"Distance Stats:       avg={avg:.2f}, mad={dev:.2f}, min={min(stats.distances)}, max={max(stats.distances)}")
		print(f"Distribution Stats:   avg={dist_mean:.2f}%, mad={dist_dev:.2f}%, min={dist_min:.2f}%, max={dist_max:.2f}%")
		print("\nBit Flip Distribution:")

		pad = len(str(hash_size - 1))
		for row in range(hash_size + 7 >> 3):
			chunk = []
			for col in range(8):
				bit_idx = row * 8 + col
				if bit_idx < hash_size:
					prob = probs[bit_idx]
					chunk.append(f"{prob:4.1f}%")

			end_bit = min(row*8 + 7, hash_size - 1)
			print(f"  Bits {row*8:0{pad}d}-{end_bit:0{pad}d}:  " + "  ".join(chunk))

		return (
			f"[{status}]"
			f" {name:<{summary_name_pad}}"
			f" distance={avg:5.2f}±{dev:5.2f},"
			f" distribution={dist_mean:5.2f}±{dist_dev:5.2f}%"
		)

	summaries = []

	for test_name, mutator_func in test_suite.items():
		stats = Stats()

		trial = 0
		while trial < trials:
			input_len = random.randint(min_input_len, max_input_len)
			orig = bytearray(random.getrandbits(8) for _ in range(input_len))

			result = mutator_func(orig)

			if result is None:
				continue

			trial += 1

			base_val, mod_val = result

			h_base = hash_func(bytes(base_val))
			h_mod  = 0 if mod_val == "BASELINE" else hash_func(bytes(mod_val))
			diff   = h_base ^ h_mod

			stats.distances.append(diff.bit_count())
			for i in range(hash_size):
				if (diff >> i) & 1:
					stats.bit_flips[i] += 1

		summary_string = print_results(test_name, stats)
		if summary_string:
			summaries.append(summary_string)

	opt_dist_dev = 50 / trials**0.5

	print(f"\n{'='*PIPE_WIDTH}")
	print(f"{"FINAL AVALANCHE SUMMARY":^{PIPE_WIDTH}}")
	print(f"{'='*PIPE_WIDTH}")

	print(f"function  : {hash_func.__name__ or "<unknown>"}")
	print(f"trials    : {trials:,}")
	print(f"len range : [{min_input_len}, {max_input_len}]")
	print(f"seed      : {seed}")
	print(f"hash_size : {hash_size}")
	print(f"score     : {passed_tests}/{len(test_suite)} ({passed_tests/len(test_suite) * 100:.2f}%)")

	print(f"{'-'*PIPE_WIDTH}")
	print(f"    {"TARGET":^{summary_name_pad}}    distance={hash_size>>1:5.2f}±{opt_dev:5.2f}, distribution=50.00±{opt_dist_dev:5.2f}%")
	print(f"{'-'*PIPE_WIDTH}")

	for summary in summaries:
		print(summary)

	print(f"{'='*PIPE_WIDTH}")

### helpers

u64_max  = (1 <<  64) - 1
u128_max = (1 << 128) - 1
u256_max = (1 << 256) - 1

def bswap64(x):
	return (
		((x & 0x00000000000000FF) << 56) |
		((x & 0x000000000000FF00) << 40) |
		((x & 0x0000000000FF0000) << 24) |
		((x & 0x00000000FF000000) << 8)  |
		((x & 0x000000FF00000000) >> 8)  |
		((x & 0x0000FF0000000000) >> 24) |
		((x & 0x00FF000000000000) >> 40) |
		((x & 0xFF00000000000000) >> 56)
	)

def bswap128(x):
	return bswap64(x) << 64 | bswap64(x >> 64)

def bswap256(x):
	return bswap128(x) << 128 | bswap128(x >> 128)

def jhash_mulhi64(x: int, y: int) -> int:
	return x * y >> 64

def jhash_mulhi128(x: int, y: int) -> int:
	"""
	static inline u128 jhash_mulhi128(u128 x, u128 y) {
		const u64  xhi = (u64) (x >> 64);
		const u64  yhi = (u64) (y >> 64);

		const u64  lo_hi = jhash_mulhi64((u64) x, yhi);
		const u64  hi_lo = jhash_mulhi64(xhi, (u64) y);
		const u128 hi_hi = (u128) xhi * yhi;

		return hi_hi + lo_hi + hi_lo;
	}
	"""

	xhi = (x >> 64) & u64_max
	yhi = (y >> 64) & u64_max

	lo_hi = jhash_mulhi64(x & u64_max, yhi)
	hi_lo = jhash_mulhi64(xhi, y & u64_max)

	return (xhi*yhi + lo_hi + hi_lo) & u128_max

def jhash_mulhi256(x: int, y: int) -> int:
	"""
	static inline u256 jhash_mulhi256(u256 x, u256 y) {
		const u128 xhi = (u128) (x >> 128);
		const u128 yhi = (u128) (y >> 128);

		const u128 lo_hi = jhash_mulhi128((u128) x, yhi);
		const u128 hi_lo = jhash_mulhi128(xhi, (u128) y);
		const u256 hi_hi = (u256) xhi * yhi;

		return hi_hi + lo_hi + hi_lo;
	}
	"""

	xhi = (x >> 128) & u128_max
	yhi = (y >> 128) & u128_max

	lo_hi = jhash_mulhi128(x & u128_max, yhi)
	hi_lo = jhash_mulhi128(xhi, y)

	return (xhi*yhi + lo_hi + hi_lo) & u256_max

### hash functions

# all the hash functions that have `pow` in them were not made by me (v11+).

def hash_v1(x: bytes) -> int:
	"64-bit FNV-1a"
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max
	return h

def hash_v1_v2(x: bytes) -> int:
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max
	return h * 0xff51afd7ed558ccd & u64_max

def hash_v2(x: bytes) -> int:
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0x9e3779b97f4a7c15 & u64_max
	return h

def hash_v2_v2(x: bytes) -> int:
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0x9e3779b97f4a7c15 & u64_max
	return h * 0xff51afd7ed558ccd & u64_max

def hash_v3(x: bytes) -> int:
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0xff51afd7ed558ccd & u64_max
	return h

def hash_v3_v2(x: bytes) -> int:
	h = 0xcbf29ce484222325
	for byte in x:
		h = (h ^ byte) * 0xff51afd7ed558ccd & u64_max
	return h * 0xff51afd7ed558ccd & u64_max

def hash_v4(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 17
	h  = bswap64(h * 0xff51afd7ed558ccd)
	return h

def hash_v5(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h  = bswap64(h * 0xff51afd7ed558ccd)
	return h

def hash_v6(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max

	h ^= h >> 17
	h  = bswap64(h * 0xff51afd7ed558ccd)
	return h

def hash_v7(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h ^= byte
		h *= 0x100000001b3
		h &= u64_max

	h ^= h >> 17
	h *= 0xff51afd7ed558ccd
	return h

def hash_v8(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max

	h = bswap64(h)
	h ^= h >> 17
	h *= 0xff51afd7ed558ccd
	return h & u64_max

def hash_v9(x: bytes) -> int:
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		h = (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 1]) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		h = (h ^ byte) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h

def hash_v10_v2(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		for i in range(8):
			h = (h ^ byte) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v3(x: bytes) -> int:
	h = 0xcbf29ce484222325

	for byte in x:
		for i in range(16):
			h = (h ^ byte) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v4(x: bytes) -> int:
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		h = (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h = (h ^ x[i + 1]) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v5(x: bytes) -> int:
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		if i > 0: h = (h ^ x[i - 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		if i > 1: h = (h ^ x[i - 2]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 1]) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v6(x: bytes) -> int:
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v7(x: bytes) -> int:
	"this one has good randomness, but it is invertible."
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		if i > 0: h = (h ^ x[i - 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		if i > 1: h = (h ^ x[i - 2]) * 0x100000001b3 & u64_max

	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return h & u64_max

def hash_v10_v7_v2(x: bytes) -> int:
	"this one has good randomness, but it is invertible."
	h = 0xcbf29ce484222325
	x += b'\0'

	for i in range(len(x) - 1):
		if i > 0: h = (h ^ x[i - 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 1]) * 0x100000001b3 & u64_max
		h =           (h ^ x[i + 0]) * 0x100000001b3 & u64_max
		if i > 1: h = (h ^ x[i - 2]) * 0x100000001b3 & u64_max

	h ^= 0xcbf29ce484222325
	h *= 0x100000001b3
	h &= u64_max
	h2 = h
	h  = bswap64(h * 0xff51afd7ed558ccd)
	h ^= h >> 13
	h  = h * 0xff51afd7ed558ccd
	return (h ^ h2) & u64_max

def hash_v10_v8(x: bytes) -> int:
	hash_key = 0x25232284e49cf2cb # FNV-1a start, byte swapped
	x += b'\0' # simulate null byte at the end of C strings

	p1 = 0x6a09e667f3bcc909 # Ceiling[2^64 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15 # Floor  [2^63 (Sqrt[5] - 1)]
	p3 = 0xc4ceb9fe1a85ec53 # from MurmurHash3 fmix64
	mx = 0xff51afd7ed558ccd # from MurmurHash3 fmix64

	hash = bswap64(hash_key) | 1
	rkey = hash_key | 1

	for i in range(len(x) - 1):
		fbkh = hash
		if i > 0: hash = (hash ^ x[i - 1]) * p1 & u64_max
		hash =           (hash ^ x[i + 1]) * p2 & u64_max
		hash =           (hash ^ x[i + 0]) * p1 & u64_max

		if i > 1:
			rkey  = (rkey + p2*2) & u64_max
			hash ^= (fbkh * rkey >> 64) & u64_max
			hash  = (hash ^ x[i - 2]) * p3 & u64_max

	hash ^= (hash * (hash_key | 1) >> 64 + (hash_key & 1)) & u64_max
	hash *= p3
	hash &= u64_max
	fbkh  = hash
	hash  = bswap64(hash * mx)
	hash ^= hash >> 13
	return (hash*mx ^ fbkh) & u64_max

def hash_v10_v8_v2(data: bytes) -> int:
	hash_key = 0x25232284e49cf2cb # FNV-1a start, byte swapped

	p1 = 0x6a09e667f3bcc909 # Ceiling[2^64 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15 # Floor  [2^63 (Sqrt[5] - 1)]
	p3 = 0xc4ceb9fe1a85ec53 # from MurmurHash3 fmix64
	mx = 0xff51afd7ed558ccd # from MurmurHash3 fmix64

	hash = bswap64(hash_key) | 1
	rkey = hash_key | 1

	for i in range(len(data)):
		fbkh  = hash
		hash  = (hash ^ data[i]) * p1 & u64_max
		rkey  = (rkey + p2*2) & u64_max
		hash ^= (fbkh * rkey >> 64) & u64_max

	hash ^= (hash * (hash_key | 1) >> 64 + (hash_key & 1)) & u64_max
	hash *= p3
	hash &= u64_max
	fbkh  = hash
	hash  = bswap64(hash * mx)
	hash ^= hash >> 13
	return (hash*mx ^ fbkh) & u64_max

def hash_v10_v8_v3(data: bytes, key: int = 0) -> int:
	"jhash64"

	p1 = 0x6a09e667f3bcc909 # Ceiling[2^64 (Sqrt[2] - 1)]
	p2 = 0x3c6ef372fe94f82c # Floor  [2^64 (Sqrt[5] - 1)] - 2^64
	p3 = 0xc4ceb9fe1a85ec53 # from MurmurHash3 fmix64
	mx = 0xff51afd7ed558ccd # from MurmurHash3 fmix64
	x1 = 0x736f6d6570736575
	x2 = 0x6c7967656e657261
	x3 = 0x25232284e49cf2cb

	data = memoryview(data)
	n = len(data)

	hash = bswap64(key ^ x1) | 1
	rkey =        (key ^ x2) | 1
	key ^= x3

	while n >= 8:
		fbkh  = hash
		rkey  = (rkey + p2) & u64_max
		chunk = int.from_bytes(data[:8], "little")
		hash  = (hash ^ chunk) * p1 & u64_max
		hash ^= jhash_mulhi64(fbkh, rkey)
		data  = data[8:]
		n    -= 8

	if n > 0:
		fbkh  = hash
		chunk = int.from_bytes(data[:n], "little") | n << 7*8
		rkey  = (rkey + p2)         & u64_max
		hash  = (hash ^ chunk) * p1 & u64_max
		hash ^= jhash_mulhi64(fbkh, rkey)

	hash ^= jhash_mulhi64(hash, key | 1)
	hash  = hash*p3 & u64_max
	fbkh  = hash
	hash  = bswap64(hash * mx)
	hash ^= hash >> 13
	return hash ^ fbkh

def hash_v10_v9(x: bytes) -> int:
	h = 0x6c62272e07bb014262b821756295c58d
	x += b'\0'	

	for i in range(len(x) - 1):
		h2 = h
		if i > 0: h  = (h ^ x[i - 1]) * 0x6a09e667f3bcc908b2fb1366ea957d3f & u128_max
		h            = (h ^ x[i + 1]) * 0x9e3779b97f4a7c15f39cc0605cedc835 & u128_max
		h            = (h ^ x[i + 0]) * 0x6a09e667f3bcc908b2fb1366ea957d3f & u128_max
		if i > 1: h  = (h ^ x[i - 2]) * 0x6a09e667f3bcc908b2fb1366ea957d3f & u128_max
		if i > 1: h ^= h2

	h ^= 0x6c62272e07bb014262b821756295c58d
	h *= 0x9c2d21e4b5bc4be9c4ceb9fe1a85ec53
	h &= u128_max
	h2 = h
	h  = bswap128(h * 0xff3e36acd17d11a63f51afd7ed558ccd)
	h ^= h >> 47
	h  = h * 0xff3e36acd17d11a63f51afd7ed558ccd
	return (h ^ h2) & u128_max

def hash_v10_v9_v2(x: bytes) -> int:
	hash_key = 0x8dc595627521b8624201bb072e27626c
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3f # Floor  [2^128 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15f39cc0605cedc835 # Ceiling[2^127 (Sqrt[5] - 1)]
	p3 = 0x9c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0xff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk

	hash = bswap128(hash_key) | 1
	rkey = hash_key | 1
	x += b'\0' # simulate null byte at the end of C strings

	for i in range(len(x) - 1):
		fbkh = hash
		if i > 0: hash = (hash ^ x[i - 1]) * p1 & u128_max
		hash =           (hash ^ x[i + 1]) * p2 & u128_max
		hash =           (hash ^ x[i + 0]) * p1 & u128_max

		if i > 1:
			rkey  = (rkey + p2*2) & u128_max
			hash ^= (fbkh * rkey >> 128) & u128_max
			hash  = (hash ^ x[i - 2]) * p3 & u128_max

	hash ^= (hash * (hash_key | 1) >> 128 + (hash_key & 1)) & u128_max
	hash *= p3
	hash &= u128_max
	fbkh  = hash
	hash  = bswap128(hash * mx)
	hash ^= hash >> 27
	return (hash*mx ^ fbkh) & u128_max

def hash_v10_v9_v3(x: bytes) -> int:
	hash_key = 0x8dc595627521b8624201bb072e27626c
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3f # Floor  [2^128 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15f39cc0605cedc835 # Ceiling[2^127 (Sqrt[5] - 1)]
	p3 = 0x9c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0xff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk

	hash = bswap128(hash_key) | 1
	rkey = hash_key | 1

	for i in range(len(x)):
		fbkh  = hash
		hash  = (hash ^ x[i]) * p1 & u128_max

		rkey  = (rkey + p2*2) & u128_max
		hash ^= (fbkh * rkey >> 128) & u128_max

	hash ^= (hash * (hash_key | 1) >> 128 + (hash_key & 1)) & u128_max
	hash *= p3
	hash &= u128_max
	fbkh  = hash
	hash  = bswap128(hash * mx)
	hash ^= hash >> 27
	return (hash*mx ^ fbkh) & u128_max

def hash_v10_v9_v4(data: bytes) -> int:
	hash_key = 0x8dc595627521b8624201bb072e27626c
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3f # Floor  [2^128 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15f39cc0605cedc835 # Ceiling[2^127 (Sqrt[5] - 1)]
	p3 = 0x9c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0xff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk

	hash = bswap128(hash_key) | 1
	rkey = hash_key | 1

	for i in range(len(data)):
		fbkh  = hash
		hash  = (hash ^ data[i]) * p1 & u128_max
		rkey  = (rkey + p2*2) & u128_max
		hash ^= jhash_mulhi128(fbkh, rkey)

	hash ^= jhash_mulhi128(hash, hash_key | 1) >> (hash_key & 1)
	hash *= p3
	hash &= u128_max
	fbkh  = hash
	hash  = bswap128(hash * mx)
	hash ^= hash >> 27
	return (hash*mx ^ fbkh) & u128_max

def hash_v10_v9_v5(data: bytes, key: int = 0) -> int:
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3f # Ceiling[2^128 (Sqrt[2] - 1)]
	p2 = 0x3c6ef372fe94f82be73980c0b9db9068 # Floor  [2^128 (Sqrt[5] - 1)] - 2^128
	p3 = 0x9c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0xff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk
	x1 = 0x646f72616e646f6d736f6d6570736575 # from SipHash
	x2 = 0x74656462797465736c7967656e657261 # from SipHash
	x3 = 0x8dc595627521b8624201bb072e27626c # from FNV-1a, byte swapped

	data = memoryview(data)
	n    = len(data)

	hash = bswap128(key ^ x1) | 1
	rkey =         (key ^ x2) | 1
	key ^= x3

	while n >= 16:
		fbkh  = hash
		rkey  = (rkey + p2) & u128_max
		chunk = int.from_bytes(data[:16], "little")
		hash  = ((hash ^ chunk) * p1) & u128_max
		hash ^= jhash_mulhi128(fbkh, rkey)
		data  = data[16:]
		n    -= 16

	if n > 0:
		fbkh  = hash
		chunk = int.from_bytes(data[:n], "little") | n << 15*8
		rkey  = (rkey + p2)           & u128_max
		hash  = (hash ^ chunk) * p1 & u128_max
		hash ^= jhash_mulhi128(fbkh, rkey)

	hash ^= jhash_mulhi128(hash, key | 1)
	hash  = hash * p3 & u128_max
	fbkh  = hash
	hash  = bswap128((hash * mx) & u128_max)
	hash ^= hash >> 27
	return hash ^ fbkh

def hash_v10_v10(data: bytes) -> int:
	hash_key = 0xdd268dbcaac550362d98c384c4e576ccc8b1536847b6bbb31023b4c8caee0535
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3e3adec17512775099da2f590b0667322b # Ceiling[2^256 (Sqrt[2] - 1)]
	p2 = 0x9e3779b97f4a7c15f39cc0605cedc8341082276bf3a27251f86c6a11d0c18e95 # Floor  [2^255 (Sqrt[5] - 1)]
	p3 = 0xd403b506b0d6297b0ef7441435825d309c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0x671c9ff61440e44f65114a2f25d2bd8aff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk

	hash = bswap256(hash_key) | 1
	rkey = hash_key | 1

	for i in range(len(data)):
		fbkh = hash
		hash = (hash ^ data[i]) * p1 & u256_max

		rkey  = (rkey + p2*2) & u256_max
		hash ^= jhash_mulhi256(fbkh, rkey)

	hash ^= jhash_mulhi256(hash, hash_key | 1) >> (hash_key & 1)
	hash *= p3
	hash &= u256_max
	fbkh  = hash
	hash  = bswap256(hash * mx)
	hash ^= hash >> 55
	return (hash*mx ^ fbkh) & u256_max

def hash_v10_v10_v2(data: bytes, key: int = 0) -> int:
	p1 = 0x6a09e667f3bcc908b2fb1366ea957d3e3adec17512775099da2f590b0667322b # Ceiling[2^256 (Sqrt[2] - 1)]
	p2 = 0x3c6ef372fe94f82be73980c0b9db906821044ed7e744e4a3f0d8d423a1831d2a # Floor  [2^256 (Sqrt[5] - 1)] - 2^256
	p3 = 0xd403b506b0d6297b0ef7441435825d309c2d21e4b5bc4be9c4ceb9fe1a85ec53 # from MurmurHash3, plus some junk
	mx = 0x671c9ff61440e44f65114a2f25d2bd8aff3e36acd17d11a63f51afd7ed558ccd # from MurmurHash3, plus some junk
	x1 = 0x7d43e8d3ad421cf485169d699d677166646f72616e646f6d736f6d6570736575 # from SipHash, plus some junk
	x2 = 0x2b357ce6e885ca8d4d95be322af94e1474656462797465736c7967656e657261 # from SipHash, plus some junk
	x3 = 0xdd268dbcaac550362d98c384c4e576ccc8b1536847b6bbb31023b4c8caee0535 # from FNV-1a, byte swapped

	data = memoryview(data)
	n    = len(data)

	hash = bswap256(key ^ x1) | 1
	rkey =         (key ^ x2) | 1
	key ^= x3

	while n >= 32:
		fbkh  = hash
		rkey  = (rkey + p2) & u256_max
		chunk = int.from_bytes(data[:32], "little")
		hash  = ((hash ^ chunk) * p1) & u256_max
		hash ^= jhash_mulhi256(fbkh, rkey)
		data  = data[32:]
		n    -= 32

	if n > 0:
		fbkh  = hash
		chunk = int.from_bytes(data[:n], "little") | n << 31*8
		rkey  = (rkey + p2)         & u256_max
		hash  = (hash ^ chunk) * p1 & u256_max
		hash ^= jhash_mulhi256(fbkh, rkey)

	hash ^= jhash_mulhi256(hash, key | 1)
	hash  = hash * p3 & u256_max
	fbkh  = hash
	hash  = bswap256((hash * mx) & u256_max)
	hash ^= hash >> 55
	return hash ^ fbkh

def hash_v11(x: bytes) -> int:
	h = 0xcbf29ce4882f23e5

	for byte in x:
		h = ~(h & byte)
		h = pow(h, 0xd1c9, 1 << 64)

	h  = bswap64(h * 0xaf51afb7ed958ccf)
	h ^= h << 5
	h *= 0xff51afd5ed558ccd
	h += 1886351216 # int.from_bytes(b'poop', "big")
	return h & u64_max

def hash_v12(x: bytes) -> int:
	h = 0xcbf29ce4882f23e5

	for byte in x:
		h = ~(h ^ byte)
		h += 0x6d722e506f6f7079 # int.from_bytes(b'mr.Poopy', "big")
		h = pow(h, 0xd1c9, 1 << 64)
		h += 0x42757474686f6c65 # int.from_bytes(b'Butthole', "big")
		h &= u64_max

	h  = bswap64(h * 0xaf51afb7ed958ccf)
	h ^= h << 5
	h *= 0xff51afd5ed558ccd
	return h & u64_max

def hash_v13(x: bytes) -> int:
	h = 0xcbf29ce4882f23e5

	for byte in x:
		h = ~(h ^ byte)
		h += 0x6d722e506f6f7079                 # int.from_bytes(b'mr.Poopy', "big")
		h = pow(h, 0xd1c9, 0x1000000000000000d)
		h += u64_max + 1 - 0x42757474686f6c65   # int.from_bytes(b'Butthole', "big")
		h &= u64_max
		h = pow(h | 1, 0x8675309, 1 << 64) * (0x035036503530abcd if (h & 1) else 1)
		h &= u64_max

	h  = bswap64(h * 0x0af51127ed958ccf)
	h ^= h << 5
	h *= 0xff51afd5ed558ccd
	return h & u64_max

def hash_v14_v2(x: bytes) -> int:
	h = 0xcbf29ce4882f23e5

	for byte in x:
		h = ~(h ^ byte)
		h += 0x3141592653589793
		h &= u64_max
		h = pow(h | 1, 0x8675309, 1 << 64) ^ (0x035036503530abcd if (h & 1) else 0)
		h ^= h >> 31
		h &= u64_max

	h *= 0xff51afd7ed558ccd
	return h & u64_max

def hash_v14_v3(x: bytes) -> int:
	h = 0xcbf29ce4882f23e5

	for byte in x:
		h = ~(h ^ byte)
		h += 0x3141592653589793
		h &= u64_max
		h = pow(h | 1, 0x8675309, 1 << 64) ^ (0x035036503530abcd if (h & 1) else 0)
		h ^= h >> 31
		h &= u64_max

	h *= 0xff51afd7ed558ccd
	return h & u64_max

def hash_sha256_64(x: bytes) -> int:
	import hashlib
	return int.from_bytes(hashlib.sha256(x).digest()[:8], "little")

def hash_sha256_128(x: bytes) -> int:
	import hashlib
	return int.from_bytes(hashlib.sha256(x).digest()[:16], "little")

def hash_sha256(x: bytes) -> int:
	import hashlib
	return int.from_bytes(hashlib.sha256(x).digest(), "little")

def rotl64(x: int, r: int) -> int:
	"""Rotate a 64-bit integer left by r bits."""
	return ((x << r) & 0xFFFFFFFFFFFFFFFF) | (x >> (64 - r))

def fmix64(k: int) -> int:
	"""64-bit finalizer mix (fmix) for MurmurHash3."""
	k ^= k >> 33
	k = (k * 0xff51afd7ed558ccd) & 0xFFFFFFFFFFFFFFFF
	k ^= k >> 33
	k = (k * 0xc4ceb9fe1a85ec53) & 0xFFFFFFFFFFFFFFFF
	k ^= k >> 33
	return k

def murmurhash3_x64_128(key: bytes | str, seed: int = 0) -> tuple[int, int]:
	"""
	Computes the canonical 128-bit MurmurHash3 (x64 variant) hash.
	Returns a tuple of two unsigned 64-bit integers: (h1, h2).
	"""
	if isinstance(key, str):
		key = key.encode('utf-8')
	elif not isinstance(key, (bytes, bytearray)):
		raise TypeError("Key must be a string, bytes, or bytearray")

	length = len(key)
	nblocks = length // 16

	h1 = seed
	h2 = seed

	c1 = 0x87c37b91114253d5
	c2 = 0x4cf5ad432745937f

	for block_idx in range(nblocks):
		i = block_idx * 16
		# Read two 64-bit little-endian unsigned integers
		k1 = int.from_bytes(key[i:i+8], byteorder='little')
		k2 = int.from_bytes(key[i+8:i+16], byteorder='little')

		# Mix k1 into h1
		k1 = (k1 * c1) & 0xFFFFFFFFFFFFFFFF
		k1 = rotl64(k1, 31)
		k1 = (k1 * c2) & 0xFFFFFFFFFFFFFFFF
		h1 ^= k1

		h1 = rotl64(h1, 27)
		h1 = (h1 + h2) & 0xFFFFFFFFFFFFFFFF
		h1 = (h1 * 5 + 0x52dce729) & 0xFFFFFFFFFFFFFFFF

		# Mix k2 into h2
		k2 = (k2 * c2) & 0xFFFFFFFFFFFFFFFF
		k2 = rotl64(k2, 33)
		k2 = (k2 * c1) & 0xFFFFFFFFFFFFFFFF
		h2 ^= k2

		h2 = rotl64(h2, 31)
		h2 = (h2 + h1) & 0xFFFFFFFFFFFFFFFF
		h2 = (h2 * 5 + 0x38495ab5) & 0xFFFFFFFFFFFFFFFF

	tail_idx = nblocks * 16
	leftover = length & 15
	tail = key[tail_idx:]

	k1 = 0
	k2 = 0

	if leftover > 8:
		for idx in range(leftover - 1, 7, -1):
			k2 = (k2 << 8) | (tail[idx] & 0xFF)
		k2 = (k2 * c2) & 0xFFFFFFFFFFFFFFFF
		k2 = rotl64(k2, 33)
		k2 = (k2 * c1) & 0xFFFFFFFFFFFFFFFF
		h2 ^= k2

	if leftover > 0:
		limit = min(leftover, 8)
		for idx in range(limit - 1, -1, -1):
			k1 = (k1 << 8) | (tail[idx] & 0xFF)
		k1 = (k1 * c1) & 0xFFFFFFFFFFFFFFFF
		k1 = rotl64(k1, 31)
		k1 = (k1 * c2) & 0xFFFFFFFFFFFFFFFF
		h1 ^= k1

	h1 ^= length
	h2 ^= length

	h1 = (h1 + h2) & 0xFFFFFFFFFFFFFFFF
	h2 = (h2 + h1) & 0xFFFFFFFFFFFFFFFF

	h1 = fmix64(h1)
	h2 = fmix64(h2)

	h1 = (h1 + h2) & 0xFFFFFFFFFFFFFFFF
	h2 = (h2 + h1) & 0xFFFFFFFFFFFFFFFF

	return h1, h2

def murmurhash3_64(key: bytes | str, seed: int = 0) -> int:
	"""
	Returns the lower 64 bits of MurmurHash3_x64_128 as a single integer.
	Matches standard 64-bit implementations.
	"""
	h1, _ = murmurhash3_x64_128(key, seed)
	
	return h1

jhash64  = hash_v10_v8_v3
jhash128 = hash_v10_v9_v5
jhash256 = hash_v10_v10_v2
