"""
Common subexpression elimination library for simple GF(2) equation sets.
Uses (greedy?) selection of n-wise intersections, and optionally, large neighborhood search.

The main optimization function is `optimize_gates`. The rest of the functions are mostly helpers.

The input should be a list of sets, where each set contains an integer >= 0, where an element `n`
represents `in[n]`, so `assign out[0] = 1 ^ in[7] ^ in[2] ^ in[0];` would become `{None, 7, 2, 0}`.
Constant terms can be anything so long as it is not an integer. `None` works well. A string should
work too, but it is not tested, and probably won't type check if you care about that.

The output is a tuple of two values: `tmp_defs` and `outputs`. `outputs` is the equivalent form of
the input, so `outputs[2]` is just the optimized form of `out[2]` from the input. `tmp_defs` is a
dictionary that maps integers to sets, so `tmp_defs[i]` gives the set for tmp signal `i`. tmp
signals can reference each other, and are topologically sorted, so each signal can only rely on
tmp signals with lower indices than itself. outputs cannot reference each other, but can reference
tmp signals. A negative value in a set means it references a tmp signal instead of an input signal.

sometimes, increasing depth or n max can make the overall solution worse.
if you increase it enough, it should get better again.

`set` in type annotations are implicitly `set[int | None]`

requires Python >=3.10
"""

__version__ = "2026.06.25.0"

__all__ = (
	# somewhat internal
	"optimize_gates_nwise", "brute_force", "cleanup_aliases", "optimize_gates_lns",

	# external
	"tsort", "count_gates", "optimize_gates", "expand_gates", "logic_depth",
	"graph_depth", "max_fanout"
)

from random import Random, SystemRandom

def _eprint(*args, **kwargs) -> None:
	"print to stderr"

	from sys import stderr
	from re import sub as replace

	if not stderr.isatty() and type(args[0]) is str:
		print(
			replace(r'\x1b\[[\d;]*?[mKJ]', '', args[0]),
			*args[1:],
			**kwargs,
			file=stderr
		)
	else:
		print(*args, **kwargs, file=stderr)

def get_rng(seed: int | None):
	# 1. random.Random() uses MT, which has pretty good avalanche (~50% flip) when incrementing the seed
	# 2. given a random seed, the initialized state has a bit average around 0.5.

	# because the goal of having both Random and SystemRandom is to have reproducibility
	# and not security, an extra stage of like sha512 on the seed for avalanche isn't needed,
	# and also an extra source of entropy isn't required either.

	return SystemRandom() if seed is None else Random(seed)

def count_gates(x: list[set] | dict[int, set], y: list[set] | dict[int, set] | None = None) -> int:
	if y is not None:
		return count_gates(x) + count_gates(y)

	if type(x) is list:
		# ignore empty sets since they don't effect the gate count
		return sum(map(len, x)) - sum(1 for e in x if len(e))

	if type(x) is dict:
		return sum(map(len, x.values())) - len(x)

	raise Exception(f"invalid type input to `count_gates: '{type(x)}'")

def add_tmp_list(
	s: list[set],
	extraction: tuple[tuple[int, ...], set],
	tmp_count: int
) -> None:
	"tmp_count is the id of the new tmp value, and the number of tmps there are *about to be* in the list"
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
			expr = tmp_defs[sorted_keys[i]]
		else:
			expr = outputs[i - n_tmps]

		expr -= new_s
		expr.add(-tmp_count)

	tmp_defs[tmp_count] = new_s

def _dfs_sets(
	start: int,            # start index
	idxs: tuple[int, ...], # indices
	inter: set | None,     # current intersection
	s: list[set],          # equation list
	nmax: int,             # check up to and including n=nmax
	B: int,                # return the top B (or less) results per level
	best_i: dict[int, list[tuple[int, ...]]],
	best_s: dict[int, list[set]],
	prune: bool = True
) -> None:
	"always uses constraint pruning, uses domination pruning if `prune` is True."

	n = len(idxs)

	if n >= 2:
		# assert inter is not None
		# this ^^^^ would make mypy shut up about len(None) for inter.

		if len(best_s[n]) < B or len(inter) > len(best_s[n][-1]):
			if B == 1:
				best_i[n] = [idxs]
				best_s[n] = [inter]
			else:
				inter_len = len(inter)
				ins_loc   = len(best_s[n]) - 1

				for i, v in enumerate(best_s[n]):
					if inter_len > len(v):
						ins_loc = i
						break

				best_i[n].insert(ins_loc, idxs)
				best_s[n].insert(ins_loc, inter)

				if len(best_s[n]) > B:
					best_i[n].pop()
					best_s[n].pop()

	if n == nmax:
		return

	if prune:
		# NOTE: these two branches are identical except for the `>` vs `>=` inside `any`.
		#       if B == 1, then it can prune more heavily

		if B == 1:
			for i in range(start, len(s)):
				nxt = inter & s[i] if inter is not None else s[i]
				nxt_len = len(nxt)

				if nxt_len >= 2 and any(
					nxt_len > len(best_s[j][-1]) if best_s[j] else True
					for j in range(max(2, n + 1), nmax + 1)
				):
					_dfs_sets(i + 1, idxs + (i,), nxt, s, nmax, B, best_i, best_s)
		else:
			for i in range(start, len(s)):
				nxt = inter & s[i] if inter is not None else s[i]
				nxt_len = len(nxt)

				if nxt_len >= 2 and any(
					nxt_len >= len(best_s[j][-1]) if best_s[j] else True
					for j in range(max(2, n + 1), nmax + 1)
				):
					_dfs_sets(i + 1, idxs + (i,), nxt, s, nmax, B, best_i, best_s)
	else:
		# for brute force search
		for i in range(start, len(s)):
			nxt = inter & s[i] if inter is not None else s[i]

			if len(nxt) >= 2:
				_dfs_sets(i + 1, idxs + (i,), nxt, s, nmax, B, best_i, best_s, prune=False)

def _resolve_best(
	scores: list[int],
	best_i: dict[int, tuple[int, ...]],
	best_s: dict[int, set],
	prefer: str = "low",
	rng: Random = SystemRandom()
) -> tuple[int, tuple[tuple[int, ...], set]]:
	"""
	The inputs should encode the best reduction for each n value.
	This function resolves those to the best overall reduction,
	breaking ties based on the `prefer` argument.
	"""

	nmax      = 1 + len(best_i)
	max_score = max(scores)

	match prefer:
		case "high":
			for n in range(nmax, 1, -1):
				if scores[n - 2] == max_score:
					best = best_i[n], best_s[n]
					break
		case "low":
			for n in range(2, nmax + 1):
				if scores[n - 2] == max_score:
					best = best_i[n], best_s[n]
					break
		case "mid" | "random":
			ties = [n for n in range(2, nmax + 1) if scores[n - 2] == max_score]

			if   len(ties) == 1:     best_n = ties[0]
			elif prefer == "mid":    best_n = ties[len(ties) >> 1]
			elif prefer == "random": best_n = ties[rng.randint(0, len(ties) - 1)]

			best = best_i[best_n], best_s[best_n]
		case _:
			raise Exception(f"invalid tie break preference: '{prefer}'. valid options are 'high', 'low', 'mid', 'random'")

	return max(0, max_score), best

def find_best_nwise(
	s: list[set],
	tmp_count: int, # number of temporary signals
	depth: int,
	nmax: int,
	B: int,
	skip_min: int | None = None,
	n_prefer: str = "low",
	lookahead_weight: float | int = 1,
	rng: Random = SystemRandom(),
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

	if B < 1:
		B = 1

	if idx_data is None:
		idx_data = (1, 1)

	nmax = max(2, min(nmax, len(s), skip_min - 1))

	if nmax < 2:
		return skip_min, 0, (None, None), False

	best_i: dict[int, list[tuple[int, ...]]] = {n: [] for n in range(2, nmax + 1)}
	best_s: dict[int, list[set]]             = {n: [] for n in range(2, nmax + 1)}

	_dfs_sets(0, (), None, s, nmax, B, best_i, best_s)

	if depth > 0:
		# lookahead

		# it is impossible for any score to be lower than -nmax
		scores = [-nmax] * (nmax - 1)

		for i in range(2, nmax + 1):
			# foreach `n`

			tmp_best_i = None
			tmp_best_s: set = set()

			for j in range(len(best_i[i])):
				best  = best_i[i][j], best_s[i][j]
				tmp_s = [s_.copy() for s_ in s]

				add_tmp_list(tmp_s, best, tmp_count)

				# future score
				tmp_score = find_best_nwise(
					tmp_s,
					tmp_count + 1,
					depth - 1,
					nmax,
					B,
					skip_min,
					n_prefer,
					lookahead_weight,
					rng,
					verbose,
					orig_depth,
					(i, nmax)
				)[1]

				if lookahead_weight != 1:
					tmp_score = round(tmp_score * lookahead_weight)

				# immediate score
				tmp_score += (i - 1) * (len(best_s[i][j]) - 1)

				if tmp_score > scores[i - 2]:
					scores[i - 2] = tmp_score
					tmp_best_i, tmp_best_s = best

			best_i[i] = tmp_best_i
			best_s[i] = tmp_best_s

		# this makes regressions better sometimes
		#for i in range(2, nmax + 1):
		#	scores[i - 2] += (i - 1) * (len(best_s[i]) - 1)
	else:
		# evaluate immediate scores
		for i in range(2, nmax + 1):
			best_i[i] = best_i[i][0] if best_i[i] else None
			best_s[i] = best_s[i][0] if best_s[i] else set()

		scores = [(n - 1) * (len(best_s[n]) - 1) for n in range(2, nmax + 1)]

	if verbose:
		# NOTE: `r` isn't really an incredibly helpful metric since it prints the same one multiple times
		_eprint(f"#     depth={orig_depth - depth}/{orig_depth}, r={idx_data[0]}/{idx_data[1]}, skip min={skip_min}, scores=", *scores[:skip_min - 2])

	for n in range(3, min(nmax + 1, skip_min)):
		if scores[n - 2] < 1:
			skip_min = n
			break

	if all(score < 1 for score in scores):
		return skip_min, 0, (None, None), False

	return skip_min, *_resolve_best(scores, best_i, best_s, n_prefer, rng), True

def optimize_gates_nwise(
	s: list[set],
	depth: int = 0,
	nmax: int = 2,
	B: int = 1,
	n_prefer: str = "low",
	lookahead_weight: float | int = 1,
	rng: Random = SystemRandom(), # for n_prefer="random"
	exit_fast: int = 0,
	max_tmps: int | None = None,
	interactive: bool = False,
	verbose: int = 0
) -> tuple[dict[int, set], list[set], bool]:
	"""
	verbose=0 disables all messages, 1 prints round data, >=2 prints everything
	s is the equation list. B is the beam size.

	exits early if it thinks there aren't any reductions greator than `exit_fast`
	anywhere along the lookahead path.

	returns (tmp vars dictionary, new outputs, exited_early)
	"""

	import signal

	if max_tmps is None:
		max_tmps = float("inf")

	if nmax < 2:
		nmax = 2

	sigint_critical = False # don't throw KeyboardInterrupt in critical sections
	sigint_pending  = False # interrupt pending for end of round

	def sigint_stop_now(signum, frame) -> None:
		nonlocal sigint_pending

		if verbose >= 0:
			_eprint("\x1b[33m# stopping optimization as soon as possible\x1b[m")

		if sigint_critical:
			sigint_pending = True
		else:
			raise KeyboardInterrupt

	def sigint_stop_soon(signum, frame) -> None:
		nonlocal sigint_pending

		if verbose >= 0:
			_eprint("\x1b[33m# stopping optimization after the current round\x1b[m")

		sigint_pending = True
		signal.signal(signal.SIGINT, sigint_stop_now)

	if abs(lookahead_weight - 1) < 1e-9:
		# avoid divide by 0
		exit_fast_thresh = depth + 1
	else:
		# NOTE: (w**(depth + 1) - 1) / (w - 1) == \sum_{n=0}^{depth} w^n
		#       the 0.001 term is just a fudge value because I don't feel like making sure it
		#       is always correct. this is the score that will be returned for lookahead depth
		#       1 if all of the reductions only reduce the gate count by 1.
		#       this doesn't account for the `round` calls in `find_best_nwise`
		exit_fast_thresh = (lookahead_weight**(depth + 1) - 1) / (lookahead_weight - 1) + 1e-3

	exit_fast_thresh *= exit_fast

	s = [s_.copy() for s_ in s]

	gate_count      = count_gates(s)
	prev_gate_count = gate_count
	orig_gate_count = gate_count
	gate_reduction  = 0
	tmp_count       = 0
	skip_min        = nmax + 1
	round           = 1
	score           = None
	early           = False

	if interactive:
		sigint_orig_handler = signal.signal(signal.SIGINT, sigint_stop_soon)

	try:
		while True:
			sigint_critical = False

			if round > max_tmps:
				_eprint(f"# max tmps {max_tmps} reached. exiting early")
				early = True
				break

			if verbose >= 1:
				_eprint(f"# round {round}: global reduction = {gate_reduction}, prev round reduction = {prev_gate_count - gate_count}, gate count = {gate_count}")

			if score is not None and score <= exit_fast_thresh:
				# NOTE: this won't actually fire if exit_fast <= 0
				if verbose >= 1:
					_eprint(f"# lookahead only sees reductions of <={exit_fast} gates. exiting early")

				early = True
				break

			# not a critical section since it doesn't alter `s`
			skip_min, score, best, cont = find_best_nwise(
				s, tmp_count, min(depth, max_tmps - round),
				nmax, B, skip_min, n_prefer,
				lookahead_weight, rng, verbose >= 2
			)

			if not cont:
				break

			sigint_critical = True
			tmp_count += 1

			add_tmp_list(s, best, tmp_count)

			prev_gate_count = gate_count
			gate_count      = count_gates(s)
			gate_reduction  = orig_gate_count - gate_count
			round += 1

			if sigint_pending:
				raise KeyboardInterrupt

		# for regular breaks
		sigint_critical = True
	except KeyboardInterrupt:
		if not interactive:
			raise KeyboardInterrupt

		early = True # skip LNS if enabled

	# NOTE: if something else throws an error, then the old sigint handler is lost.
	# TODO: consider fixing this ^^^^^

	gate_compression = 0.0 if orig_gate_count == 0.0 else gate_reduction / orig_gate_count
	tmp_defs = {i: v for i, v in enumerate(reversed(s[0:tmp_count]), 1)}
	outputs  = s[tmp_count:]

	if verbose >= 2:
		_eprint(
			f"# gate reduction: {gate_reduction}"
			f"\n# gate compression: {gate_compression}"
			f"\n# number of tmp signals: {tmp_count}"
		)
	elif verbose == 1:
		_eprint(f"# number of tmp signals: {tmp_count}")

	if interactive:
		signal.signal(signal.SIGINT, sigint_orig_handler)

	return tmp_defs, outputs, early

def find_all_reductions(
	tmp_defs: dict[int, set],
	outputs: list[set]
) -> tuple[dict[int, list[tuple[int, ...]]], dict[int, list[set]]]:
	sorted_keys = sorted(tmp_defs.keys(), reverse=True)
	s = [tmp_defs[key] for key in sorted_keys] + outputs

	nmax = len(s)
	best_i: dict[int, list[tuple[int, ...]]] = {n: [] for n in range(2, nmax + 1)}
	best_s: dict[int, list[set]]             = {n: [] for n in range(2, nmax + 1)}

	_dfs_sets(0, (), None, s, nmax, 1 << 31, best_i, best_s, prune=False)
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
	best_gates  = count_gates(tmp_defs, outputs)

	for i, candidate in enumerate(candidates):
		if verbose >= 2 and depth == 1:
			_eprint(f"\r# {i}/{len(candidates)}\x1b[K", end="", flush=True)

		td  = {key: val.copy() for key, val in tmp_defs.items()}
		out = [s.copy() for s in outputs]

		add_tmp_dict(td, out, candidate, len(td) + 1)
		td, out = brute_force(td, out, max_depth, depth + 1)
		g = count_gates(td, out)

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

def cleanup_aliases(tmp_defs: dict[int, set], outputs: list[set], strict: bool = False) -> None:
	"""
	remove tmp signals that just alias another one. this should be done before topological sorting.
	strict makes it so something like outputs = [{-1}, {-1, 3}] will expand out the {-1} set into
	the value of tmp[-1]. this can increase gate count, so it is disabled by default.

	this is O(V^2) in theory, but probably won't actually be any higher than like O(n^1.5)
	"""

	keys = set(tmp_defs)

	# this two-layer loop is required since `delete_tmp` changes the order of the elements,
	# so it might move one that hasn't been checked into a slot that has been checked.
	while True:
		for tmp_id in tuple(keys):
			if tmp_id not in keys:
				continue

			if len(tmp_defs[tmp_id]) == 1:
				delete_tmp(tmp_defs, outputs, tmp_id, patch=True)
				keys.discard(len(tmp_defs) + 1)
				break

			keys.discard(tmp_id)
		else:
			break

	if strict:
		for eqn in outputs:
			if len(eqn) == 1:
				dep ,= eqn

				if dep < 0:
					delete_tmp(tmp_defs, outputs, -dep, patch=True)

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

	old_gate_count = count_gates(tmp_defs, outputs)

	for round in range(1, 1 + trials):
		if verbose >= 1:
			_eprint(f"# LNS round {round}: gates={count_gates(tmp_defs, outputs)}")

		td  = {key: val.copy() for key, val in tmp_defs.items()}
		out = [s.copy() for s in outputs]

		for i in range(min(window_size, len(td) - 1)):
			delete_tmp(td, out, rng.randint(1, len(td)), patch=True)

		# since brute force gives the true minimum, this is always at least as good as the old solution
		td, out = brute_force(td, out, max_depth, 1, verbose)

		if count_gates(td, out) < old_gate_count:
			tmp_defs, outputs = td, out

		if verbose >= 2:
			_eprint("\r\x1b[K", end="", flush=True)

	if verbose >= 2:
		_eprint(f"# LNS ending gates: {count_gates(tmp_defs, outputs)}")

	return tmp_defs, outputs

def tmp_swap(tmp_defs: dict[int, set], outputs: list[set], i: int, j: int) -> None:
	"swap the IDs of two temporary signals and update all references"

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

def _tsort_map_fast(tmp_defs: dict[int, set]) -> dict[int, int]:
	"topological sort helper to get position map. Kahn's algorithm with a plain FIFO"

	from collections import deque

	graph: dict[int, list[int]] = {node: [] for node in tmp_defs}
	indegree: dict[int, int]    = {node: 0  for node in tmp_defs}

	for node, dependencies in tmp_defs.items():
		for dep in dependencies:
			if type(dep) is int and dep < 0:
				graph[-dep].append(node)
				indegree[node] += 1

	pos_map: dict[int, int] = {}
	queue = deque([node for node in tmp_defs if indegree[node] == 0])
	pos   = 1

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

def _tsort_map_slow(tmp_defs: dict[int, set]) -> dict[int, int]:
	"""
	topological sort helper to get position map. Kahn's algorithm with a heuristic priority queue.
	For nodes of the same indegree, it prioritizes by outdegree. O([V + E] log V)
	"""

	import heapq

	graph: dict[int, list[int]] = {node: [] for node in tmp_defs}
	indegree: dict[int, int]    = {node: 0  for node in tmp_defs}

	for node, dependencies in tmp_defs.items():
		for dep in dependencies:
			if type(dep) is int and dep < 0:
				graph[-dep].append(node)
				indegree[node] += 1

	outdegree: dict[int, int] = {node: len(deps) for node, deps in graph.items()}

	pos_map: dict[int, int] = {}
	heap = [(-outdegree[node], node) for node in tmp_defs if indegree[node] == 0]
	heapq.heapify(heap)
	pos   = 1

	while heap:
		_, u = heapq.heappop(heap)

		pos_map[u] = pos
		pos += 1

		for v in graph[u]:
			indegree[v] -= 1

			if indegree[v] == 0:
				heapq.heappush(heap, (-outdegree[v], v))

	if len(pos_map) != len(tmp_defs):
		raise ValueError("A cyclic dependency was detected")

	return pos_map

def tsort(tmp_defs: dict[int, set], outputs: list[set], *, fast: bool = True) -> None:
	"topological sort using direct remapping"

	pos_map = (_tsort_map_fast if fast else _tsort_map_slow)(tmp_defs)

	id_map = {-old_pos: -new_pos for old_pos, new_pos in pos_map.items()}

	sorted_tmp_defs = {
		pos_map[old_key]: {id_map.get(dep, dep) for dep in deps}
		for old_key, deps in tmp_defs.items()
	}

	tmp_defs.clear()
	tmp_defs.update(sorted_tmp_defs)

	for i, eqn in enumerate(outputs):
		outputs[i] = {id_map.get(dep, dep) for dep in eqn}

def optimize_gates(
	s: list[set],
	depth: int = 0,
	nmax: int = 2,
	beam: int = 1,
	n_prefer: str = "low",
	lookahead_weight: int | float = 1,
	lns_window: int = 0,
	lns_trials: int = 0,
	exit_fast: int = 0,
	max_tmps: int | None = None,
	seed: int | None = None,
	verbose: int = 0,
	*,
	interactive: bool = False,
	sort: str = "slow"
) -> tuple[dict[int, set], list[set], bool]:
	"""
	first stage uses n-wise greedy optimization.
	optional second stage uses brute force LNS
	lns_window = 0 => skip LNS
	lns_trials = 0 => use trials = 1 + ceil( (len(tmp_defs) + len(outputs)) / window_size )
	seed = None means it uses `SystemRandom` instead of `Random`.

	if interactive, ^C requests the optimizer to stop after the current round.
	And a second ^C requests it to stop as soon as possible, which is usually
	immediately unless it is in a critical section.

	sort should be "off", "slow", or "fast".
	technically "slow" can be anything, so long as it is distinct from the other two.

	returns (tmp vars dictionary, new outputs, exited_early)
	"""

	# NOTE: I haven't tested it, but I think nmax is the max tmp signal fanout when LNS is off.

	rng = get_rng(seed)

	tmp_defs, outputs, early = optimize_gates_nwise(
		s, depth, nmax, beam, n_prefer, lookahead_weight,
		rng, exit_fast, max_tmps, interactive, verbose
	)

	if not early and lns_window != 0:
		tmp_defs, outputs = optimize_gates_lns(
			tmp_defs, outputs, lns_window,
			lns_trials, -1, rng, verbose
		)

	# LNS seems to like adding alias tmp signals.
	# always run this in case the nwise optimizer does it too
	cleanup_aliases(tmp_defs, outputs, strict=False)

	if sort != "off":
		tsort(tmp_defs, outputs, fast=sort == "fast")

	return tmp_defs, outputs, early

def expand_gates(tmp_defs: dict[int, set], outputs: list[set]) -> list[set]:
	"""
	this should return the original equation list.
	both arguments are also updated in-place.
	"""

	for tmp in tuple(tmp_defs.keys()):
		delete_tmp(tmp_defs, outputs, tmp)

	return outputs

def _ceil_log(n: int, b: int | None = 4) -> int:
	"""
	returns \\lceil log_b(n) \\rceil.
	slower than math.log, but more accurate.
	if b is None, then it uses base infinity (kind of). (always returns 1)
	kind of like math.ceil(math.log(n, 1e308)), except for if n <= 1.
	"""

	if b is None:
		return 1

	if b <= 1:
		raise ValueError(f"base must be > 1 or None. got {b}")

	if n <= 1:
		return 0

	count = 0
	val   = 1

	while val < n:
		val  *= b
		count += 1

	return count

def logic_depth(
	tmp_defs: dict[int, set] | None,
	outputs: list[set],
	/,
	lut_size: int | None = 4,
	*,
	sorted: bool = False
) -> int | float:
	"""
	calculate an approximate hardware logic depth assuming balanced trees.
	use sorted=False to topologically sort before ranking.
	lut_size=None assumes infinite fanout
	`outputs` should be non empty.

	if `tmp_defs` is None, then `sorted` is ignored.
	the return value is only a float if lut_size <= 1, at which point it returns infinity.
	"""

	if lut_size is not None and lut_size <= 1:
		return float("inf")

	if not sorted and tmp_defs is not None:
		# TODO: consider doing a shallow copy instead of a deep copy.
		tmp_defs = {key: val.copy() for key, val in tmp_defs.items()}
		outputs  = [s.copy() for s in outputs]
		tsort(tmp_defs, outputs, fast=True)

	tmp_depths: dict[int, int] = {}

	# start off assuming it is topologically sorted, and then if it isn't, then topologically sort it and start over
	for i in range(1, 1 if tmp_defs is None else len(tmp_defs) + 1):
		eqn = tmp_defs[i]

		depth = 0
		for v in eqn:
			if type(v) is int and v < 0:
				if -v not in tmp_depths:
					# this only happens if the graph was assumed to be sorted but actually wasn't
					# this won't go indefinitely on cyclic graphs becase tsort._map throws an error for those.
					return logic_depth(tmp_defs, outputs, lut_size=lut_size, sorted=False)

				tmp = tmp_depths[-v]
				if tmp > depth:
					depth = tmp

		tmp_depths[i] = depth + _ceil_log(len(eqn) - (None in eqn), lut_size)

	return max( _ceil_log(len(eqn) - (None in eqn), lut_size) + max(
		(tmp_depths[-v] for v in eqn if type(v) is int and v < 0),
		default=0
	) for eqn in outputs )

def graph_depth(tmp_defs: dict[int, set], outputs: list[set], *, sorted: bool = False) -> int:
	"""
	This assumes LUT\\infty, which is not true for real hardware.
	But for graphviz rank count, this is accurate.
	use sorted=False to topologically sort before ranking.
	returns one less than the number of ranks in the graph
	outputs should be non empty.
	"""

	return logic_depth(tmp_defs, outputs, lut_size=None, sorted=sorted)

def max_fanout(
	tmp_defs: dict[int, set] | None,
	outputs: list[set],
	*,
	nodes: bool = True
) -> int | tuple[int, list[int]]:
	"returns the max fanout, and optionally an unsorted list of the signals with that fanout value"
	from collections import defaultdict

	fanouts = defaultdict(int)

	if tmp_defs is not None:
		for eqn in tmp_defs.values():
			for dep in eqn:
				fanouts[dep] += 1

	for eqn in outputs:
		for dep in eqn:
			fanouts[dep] += 1

	max_fanout = max(fanouts.values(), default=0)

	if nodes:
		return max_fanout, [e for e in fanouts if fanouts[e] == max_fanout]
	else:
		return max_fanout

if __name__ == "__main__":
	_eprint(f"gf2_cse (v{__version__}) is not a top level program")
	exit(1)
