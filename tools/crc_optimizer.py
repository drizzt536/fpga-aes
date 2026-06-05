"""
optimizes the CRC HDL code generated in `crc-gen.py` using greedy selecition of n-wise intersections,
and optionally, large neighborhood search.

The main function intended to be called is `optimize_gates`.

The input should be a list of sets, where each set contains an integer >= 0, where an element `n`
represents `in[n]`, so `assign out[0] = in[7] ^ in[2] ^ in[0];` would become `{7, 2, 0}` for the
set. constant terms can be anything so long as it is not an integer. `None` works well. A string
should work well too.

The output is a tuple of two values: `tmp_defs` and `outputs`. `outputs` is the same as the input,
So `outputs[2]` is just the optimized form of `out[2]` from the input. `tmp_defs` is a dictionary
that maps integers to sets, so `tmp_defs[i]` gives the set for tmp signal `i`. tmp signals can
reference each other, and are not topologically sorted. outputs cannot reference each other, but
can reference tmp signals. A negative value in a set means it references a tmp signal instead of
an input signal.

Whenever `set` is in a type annotation for a function, it is implicitly `set[int | None]`

Python 3.10 is probably the minimum that works for this.
"""

from copy   import deepcopy
from random import Random, SystemRandom

def eprint(*args, **kwargs):
	from sys import stderr
	print(*args, **kwargs, file=stderr)

def get_rng(seed: int | None):
	# 1. random.Random() uses MT, which has pretty good avalanche (~50% flip) when incrementing the seed
	# 2. given a random seed, the initialized state has a bit average around 0.5.

	# because the goal of having both Random and SystemRandom is to have reproducibility
	# and not security, an extra stage of like sha512 on the seed for avalanche isn't needed,
	# and also an extra source of entropy isn't required either.

	return SystemRandom() if seed is None else Random(seed)

gate_count = lambda s: sum(len(si) - 1 for si in s if si)

def add_tmp_list(
	s: list[set],
	extraction: tuple[tuple[int, ...], set],
	tmp_count: int
) -> None:
	"tmp_count is the id of the new tmp value, and the number of tmps there are about to be in the list"
	new_i, new_s = extraction

	for i in new_i:
		s[i] -= new_s
		s[i].add(-tmp_count)

	s.insert(0, new_s)

def add_tmp_dict(
	tmp_defs: dict[int, set],
	outputs: list[set],
	extraction: tuple[tuple[int, ...], set],
	tmp_count: int
) -> None:
	"tmp_count is the id of the new tmp value, and the number of tmps there are about to be in the list"
	new_i, new_s = extraction
	n_tmps = tmp_count - 1

	sorted_keys = sorted(tmp_defs.keys(), reverse=True)

	for i in new_i:
		if i < n_tmps:
			expr = tmp_defs[sorted_keys[i]] # this might be off by 1
		else:
			expr = outputs[i - n_tmps]

		expr -= new_s
		expr.add(-tmp_count)

	tmp_defs[tmp_count] = new_s

def _dfs_sets(
	start: int,  # start index
	idxs: tuple[int, ...], # indices
	inter: set,  # current intersection
	s: list[set],
	n_max: int,  # check up to and including n=n_max
	B: int,      # return the top B (or less) results per level
	best_i: dict[int, list[tuple[int, ...]]],
	best_s: dict[int, list[set]],
	prune: bool = True
) -> None:
	n = len(idxs)

	if n >= 2:
		if len(best_s[n]) < B or len(inter) > len(best_s[n][-1]):
			if B == 1:
				best_i[n] = [idxs]
				best_s[n] = [inter]
			else:
				best_i[n].append(idxs)
				best_s[n].append(inter)

				# sort descending by intersection size
				best_i[n], best_s[n] = zip(*sorted(
					zip(best_i[n], best_s[n]),
					key=lambda x: len(x[1]),
					reverse=True
				))

				best_i[n] = list(best_i[n])[:B]
				best_s[n] = list(best_s[n])[:B]

	if n == n_max:
		return

	if prune:
		for i in range(start, len(s)):
			nxt = inter & s[i] if inter is not None else s[i]

			if len(nxt) >= 2 and any(len(nxt) >= len(best_s[j][-1]) if best_s[j] else True for j in range(max(2, n + 1), n_max + 1)):
				_dfs_sets(i + 1, idxs + (i,), nxt, s, n_max, B, best_i, best_s, prune=False)
	else:
		for i in range(start, len(s)):
			nxt = inter & s[i] if inter is not None else s[i]
			if len(nxt) >= 2:
				_dfs_sets(i + 1, idxs + (i,), nxt, s, n_max, B, best_i, best_s)

def find_best_nwise(
	s: list[set],
	tmp_count: int, # number of temporary signals
	depth: int,
	n_max: int,
	B: int,
	skip_min: int = None,
	verbose: bool = True,
	orig_depth: int | None = None,
	idx_data: tuple | None = None
) -> tuple[int, int, tuple[tuple[int, ...], set], bool]:
	"""
	returns (skip_min, score, best, should_continue)
	if should_continue is False, there are no more reductions to make, so the calling code should
	exit the loop it is in.
	best is (best_i, best_s)
	skip_min is an integer and score is an integer
	"""

	if depth < 0:
		depth = 0

	if orig_depth is None:
		orig_depth = depth

	if   skip_min is None: skip_min = 1 + len(s)
	elif skip_min < 3:     skip_min = 3

	if B < 1 or depth == 0:
		B = 1

	if B == 1 and depth > 0:
		depth = 0

	if idx_data is None:
		idx_data = (1, 1)

	n_max = max(2, min(n_max, len(s), skip_min - 1))

	if n_max < 2:
		return skip_min, 0, (None, None), False

	best_i = {n: [] for n in range(2, n_max + 1)}
	best_s = {n: [] for n in range(2, n_max + 1)}

	_dfs_sets(0, (), None, s, n_max, B, best_i, best_s)

	if depth > 0:
		for i in range(2, n_max + 1):
			# foreach `n`

			tmp_best_i     = None
			tmp_best_s     = set()
			tmp_best_score = -1

			for j in range(len(best_i[i])):
				best  = best_i[i][j], best_s[i][j]
				tmp_s = deepcopy(s)

				add_tmp_list(tmp_s, best, tmp_count)

				# immediate score
				tmp_score = (i - 1) * (len(best_s[i][j]) - 1)

				# future score
				tmp_score += find_best_nwise(
					tmp_s,
					tmp_count + 1,
					depth - 1,
					n_max,
					B,
					skip_min,
					verbose,
					orig_depth,
					(i, n_max)
				)[1]

				if tmp_score > tmp_best_score:
					tmp_best_score = tmp_score
					tmp_best_i = best[0]
					tmp_best_s = best[1]

			best_i[i] = tmp_best_i
			best_s[i] = tmp_best_s
	else:
		for i in range(2, n_max + 1):
			best_i[i] = best_i[i][0] if best_i[i] else None
			best_s[i] = best_s[i][0] if best_s[i] else set()

	# Compute scores dynamically up to n_max
	scores = tuple((n - 1) * (len(best_s[n]) - 1) for n in range(2, n_max + 1))

	if verbose:
		eprint(f"#     depth={orig_depth - depth}/{orig_depth}, r={idx_data[0]}/{idx_data[1]}, skip min={skip_min}, scores=", *scores[:skip_min - 2])

	for n in range(3, n_max + 1):
		if scores[n - 2] < 1 and skip_min > n:
			skip_min = n
			break

	if all(score < 1 for score in scores):
		return skip_min, 0, (None, None), False

	max_score = max(scores)

	for n in range(n_max, 1, -1):
		if scores[n - 2] == max_score:
			best = best_i[n], best_s[n]
			break

	return skip_min, max_score, best, True

def optimize_gates_nwise(
	s: list[set],
	depth: int = 0,
	n_max: int = 2,
	B: int = 1,
	verbose: int = 0
) -> tuple[dict[int, set], list[set]]:
	"""
	verbose=0 disables all messages, 1 prints round data, >=2 prints everything
	B is the beam size.
	returns (tmp vars dictionary, new outputs)
	"""

	if n_max < 2:
		n_max = 2

	s = deepcopy(s)

	orig_gate_count = gate_count(s)
	gate_reduction  = 0
	tmp_count       = 0
	skip_min        = n_max + 1
	round           = 0

	while True:
		if verbose >= 1:
			eprint(f"# round {(round := round + 1)}: global reduction = {gate_reduction}, gate count = {gate_count(s)}")

		skip_min, score, best, cont = find_best_nwise(s, tmp_count, depth, n_max, B, skip_min, verbose >= 2)

		if not cont:
			break

		tmp_count += 1

		gate_reduction += score
		add_tmp_list(s, best, tmp_count)

	gate_compression = gate_reduction / orig_gate_count
	tmp_defs = {i: v for i, v in enumerate(reversed(s[0:tmp_count]), 1)}
	outputs  = s[tmp_count:]

	if verbose >= 2:
		eprint(
			f"# old gate count: {orig_gate_count}"
			f"\n# new gate count: {orig_gate_count - gate_reduction}"
			f"\n# gate reduction: {gate_reduction}"
			f"\n# gate compression: {gate_compression}"
			f"\n# number of tmp signals: {tmp_count}"
		)
	elif verbose == 1:
		eprint(f"# optimized gate count = {gate_count(s)}")

	return tmp_defs, outputs

def find_all_reductions(tmp_defs: dict[int, set], outputs: list[set]) -> tuple[dict[int, tuple], dict[int, set]]:
	sorted_keys = sorted(tmp_defs.keys(), reverse=True)
	s = [tmp_defs[k] for k in sorted_keys] + outputs

	n_max = len(s)
	best_i = {n: [] for n in range(2, n_max + 1)}
	best_s = {n: [] for n in range(2, n_max + 1)}

	_dfs_sets(0, (), None, s, n_max, 1 << 31, best_i, best_s, prune=False)
	return best_i, best_s

def brute_force(
	tmp_defs: dict[int, set],
	outputs: list[set],
	max_depth: int,
	depth: int = 1, # current execution depth
	verbose: int = 0
) -> tuple[dict[int, set], list[set]]:
	if depth > max_depth:
		return tmp_defs, outputs

	best_i, best_s = find_all_reductions(tmp_defs, outputs)

	candidates = []
	for n in best_i:
		for j in range(len(best_i[n])):
			if len(best_s[n][j]) >= 2:
				candidates.append( (best_i[n][j], best_s[n][j]) )

	if not candidates:
		return tmp_defs, outputs

	best_result = None
	best_gates  = gate_count(tmp_defs.values()) + gate_count(outputs)

	for i, candidate in enumerate(candidates):
		if verbose >= 2 and depth == 1:
			eprint(f"\r# {i}/{len(candidates)}\x1b[K", end="", flush=True)

		td  = deepcopy(tmp_defs)
		out = deepcopy(outputs)

		add_tmp_dict(td, out, candidate, len(td) + 1)
		td, out = brute_force(td, out, max_depth, depth + 1)
		g = gate_count(td.values()) + gate_count(out)

		if g < best_gates:
			best_gates  = g
			best_result = (td, out)

	if best_result is None:
		return (tmp_defs, outputs)

	return best_result

def patch_tmp(tmp_defs: dict[int, set], outputs: list[set], deleted_id: int) -> None:
	last_id = len(tmp_defs) + 1

	if deleted_id == last_id:
		# no gap to fix
		return

	tmp_defs[deleted_id] = tmp_defs.pop(last_id)

	# update references
	for expr in list(tmp_defs.values()) + outputs:
		if -last_id in expr:
			expr.discard(-last_id)
			expr.add(-deleted_id)

def delete_tmp(tmp_defs: dict[int, set], outputs: list[set], id: int, *, patch: bool = False):
	"id is the key in tmp_defs"

	defn = tmp_defs.pop(id)
	id = -id # -n signifies tmp[n]

	for e in list(tmp_defs.values()) + outputs:
		if id in e:
			e.discard(id)
			e |= defn

	if patch:
		patch_tmp(tmp_defs, outputs, -id)

def cleanup_tmps(tmp_defs: dict[int, set], outputs: list[set]) -> None:
	"remove tmp signals that just alias another one."
	changed = True

	while changed:
		changed = False

		for tmp_id in tuple(tmp_defs.keys()):
			if len(tmp_defs[tmp_id]) == 1:
				delete_tmp(tmp_defs, outputs, tmp_id, patch=True)
				changed = True
				break

def optimize_gates_lns(
	tmp_defs: dict[int, set],
	outputs: list[set],
	window_size: int,
	trials: int = 0,
	max_depth: int = -1,
	rng: Random = SystemRandom(),
	verbose: int = 0
) -> tuple[dict[int, set], list[set]]:
	"large neighborhood search"

	if max_depth == -1:
		max_depth = window_size + 1

	if trials == 0:
		trials = 1 + (len(tmp_defs) + len(outputs) + window_size - 1) // window_size

	old_gate_count = gate_count(tmp_defs.values()) + gate_count(outputs)

	for round in range(1, 1 + trials):
		if verbose >= 1:
			eprint(f"# LNS round {round}: gates={gate_count(tmp_defs.values()) + gate_count(outputs)}")

		td  = deepcopy(tmp_defs)
		out = deepcopy(outputs)

		for i in range(min(window_size, len(td) - 1)):
			delete_tmp(td, out, rng.randint(1, len(td)), patch=True)

		# since brute force gives the true minimum, this is always at least as good as the old solution
		td, out = brute_force(td, out, max_depth, 1, verbose)

		# if gate_count(td.values()) + gate_count(out) < old_gate_count:
		# 	tmp_defs, outputs = td, out

		if verbose >= 2:
			eprint("\r\x1b[K", end="", flush=True)

	if verbose >= 2:
		eprint(f"# LNS ending gates: {gate_count(tmp_defs.values()) + gate_count(outputs)}")

	return tmp_defs, outputs

def tmp_swap(tmp_defs: dict[int, set], outputs: list[set], i: int, j: int) -> None:
	tmp_defs[i], tmp_defs[j] = tmp_defs[j], tmp_defs[i]

	i = -i
	j = -j

	# update references
	for eqn in tmp_defs.values():
		if i in eqn and j not in eqn:
			eqn.discard(i)
			eqn.add(j)
		elif j in eqn and i not in eqn:
			eqn.discard(j)
			eqn.add(i)

	for eqn in outputs:
		if i in eqn and j not in eqn:
			eqn.discard(i)
			eqn.add(j)
		elif j in eqn and i not in eqn:
			eqn.discard(j)
			eqn.add(i)

def _tsort_tmps(tmp_defs: dict[int, set]) -> dict[int, int]:
	"topological sort helper to get position map"

	from collections import deque

	graph    = {node: [] for node in tmp_defs}
	indegree = {node: 0  for node in tmp_defs}

	for node, dependencies in tmp_defs.items():
		for dep in dependencies:
			if isinstance(dep, int) and dep < 0:
				graph[-dep].append(node)
				indegree[node] += 1

	queue   = deque([node for node in tmp_defs if indegree[node] == 0])
	pos_map = {}
	pos     = 1

	while queue:
		u = queue.popleft()
		
		pos_map[u] = pos
		pos += 1

		for v in graph[u]:
			indegree[v] -= 1

			if indegree[v] == 0:
				queue.append(v)

	if len(pos_map) != len(tmp_defs):
		raise ValueError("A cyclic dependency was detected")

	return pos_map

def tsort(tmp_defs: dict[int, set], outputs: list[set]) -> None:
	"topological sort"

	# NOTE: the last remaining element in the map will always be of the form `x: x`
	pos_map = _tsort_tmps(tmp_defs)

	while pos_map:
		key, val = next(iter( pos_map.items() ))

		if key == val:
			del pos_map[key]
			continue

		tmp_swap(tmp_defs, outputs, key, val)
		pos_map[key] = pos_map.pop(val)

def optimize_gates(
	s: list[set],
	depth: int = 0,
	nmax: int = 2,
	beam: int = 1,
	lns_window: int = 0,
	lns_trials: int = 0,
	seed: int | None = None,
	verbose: int = 0,
	sort: bool = True
):
	"""
	first stage uses n-wise greedy optimization.
	optional second stage uses brute force LNS
	lns = (lns window size, lns trials)
	lns[0] = 0 => skip LNS
	lns[1] = 0 => use trials = 1 + ceil( (len(tmp_defs) + len(outputs)) / window_size )
	seed = None means it uses `SystemRandom` instead of `Random`.
	"""

	rng = get_rng(seed)

	tmp_defs, outputs = optimize_gates_nwise(s, depth, nmax, beam, verbose)

	if lns_window != 0 and lns_trials != 0:
		tmp_defs, outputs = optimize_gates_lns(tmp_defs, outputs, lns_window, lns_trials, -1, rng, verbose)

	cleanup_tmps(tmp_defs, outputs)

	if sort:
		tsort(tmp_defs, outputs)

	return tmp_defs, outputs

def expand_gates(tmp_defs: dict[int, set], outputs: list[set]) -> None:
	"""
	this should return the original equation list.
	both arguments are also updated in-place.
	this is not used anywhere
	"""

	for tmp in tuple(tmp_defs.keys()):
		delete_tmp(tmp_defs, outputs, tmp)

	return outputs
