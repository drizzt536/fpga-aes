import time, sys
sys.set_int_max_str_digits(5_000_000)
sys.setrecursionlimit(1_000_000)

import concat_implicit
concat_implicit.LOG = False

LinkedList         = concat_implicit.LinkedList
concat_implicit_v1 = concat_implicit.concat_implicit_v1
concat_implicit_v2 = concat_implicit.concat_implicit_v2
concat_implicit_v3 = concat_implicit.concat_implicit_v3

def build(n):
	ll = LinkedList()

	for i in range(n):
		ll.append(i & 1023)

	ll.append("SENTINEL")
	return ll

def bench(fn, n, reps):
	times = []

	for _ in range(reps):
		t0, t1 = 0, 0
		ll = build(n)
		t0 = time.perf_counter_ns()
		fn(ll, 1, n)
		t1 = time.perf_counter_ns()
		times.append(t1 - t0)

	times.sort()
	return times[len(times) >> 1] # median, more robust than mean


sizes = [1, 2, 4, 6, 11, 27, 43, 128, 256, 512, 1024, 2027, 4099, 8191, 15511, 30187]
funcs = [("v1", concat_implicit_v1), ("v2", concat_implicit_v2), ("v3", concat_implicit_v3)]

print(f"{'n':>7} " + ' '.join(f"{name:>13}" for name, _ in funcs))

for n in sizes:
	reps = 100 if n < 5000 else 5
	row = []

	for name, fn in funcs:
		t = bench(fn, n, reps)
		row.append(t)

	print(f"{n:>7,} " + ' '.join(f"{t:>11,}ns" for t in row))
