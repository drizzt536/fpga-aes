from expr_lexer import concat

# Node => token_t
# LinkedList => token_list
# int concat(int l, int r) => var_val_t dsl_cat(var_val_t x, var_val_t y)
# void concat_implicit(LinkedList ll) => ??? dsl_cat_all(token_list list, u64 start, u64 length)
# haven't decided on the C return type of dsl_cat_all. I think void should work

# NOTE: since it is a linked list and not a contiguous array, I don't think it is possible to do a true
#       recursive bisection, since that would require jumping to the middle element, but since the
#       middle element doesn't have a pre-known offset from the start, that would be O(n) per split.

class Node:
	__slots__ = ("value", "next")

	def __init__(self, value, next=0):
		self.value = value
		self.next  = next

LOG = True

class LinkedList:
	"""
	this (mostly) simulates the invariants of `token_list`. `append` doesn't,
	since this is specifically for the concat stage
	"""

	def __init__(self):
		self.array = [Node(None, 0)]
		self.count = 0 # number of live nodes

	def append(self, value):
		"assumes all appends happen before any mutation"

		self.array[-1].next = len(self.array)
		self.array.append(Node(value, 0))
		self.count += 1

	def repr_range(self, start, length):
		if length == 0:
			return "empty"

		values  = []
		current = start
		i = 0

		while current != 0 and i < length:
			node = self.array[current]
			values.append(str(node.value))
			current = node.next
			i += 1

		return " -> ".join(values)

	def __repr__(self):
		return self.repr_range(1, self.count)

def concat_implicit_v1(ll, start, length):
	# this version is simpler, but is kind of bad for if the length isn't near a power of 2

	if start == 0 or length <= 0:
		raise ValueError("start must be nonzero and length must be positive")

	ll.count -= length - 1 # NOTE: because of this, exiting early corrupts state

	arena = ll.array

	while length > 1:
		if LOG:
			print(ll.repr_range(start, length))

		current = start
		merges = 0
		target_merges = length >> 1 # one pass of pairwise merges

		while merges < target_merges:
			node = arena[current]
			next_node  = arena[node.next]
			node.value = concat(node.value, next_node.value)
			node.next  = next_node.next
			current    = node.next
			merges += 1

		length -= merges

	if LOG:
		print(ll.repr_range(start, length))

def concat_implicit_v2(ll, start, length):
	if start == 0 or length <= 0:
		raise ValueError("start must be nonzero and length must be positive")

	ll.count -= length - 1 # NOTE: because of this, exiting early corrupts state

	arena = ll.array

	while length > 1:
		if LOG:
			print(ll.repr_range(start, length))

		current = start
		prev = 0
		merges = 0
		target_merges = length >> 1

		while merges < target_merges:
			node = arena[current]
			next_node = arena[node.next]
			node.value = concat(node.value, next_node.value)
			node.next = next_node.next
			prev = current
			current = node.next
			merges += 1

		# NOTE: in C, this can happen after the branching. `print(ll)` needs the length to be correct, but
		#       that is not required for the C version.
		length -= merges

		# if the range had an odd number of elements, merge the leftover
		# node with the last merged pair.
		if (length + merges & 1) and prev != 0 and current != 0:
			if LOG:
				print(ll.repr_range(start, length))
			prev_node = arena[prev]
			current_node = arena[current]
			prev_node.value = concat(prev_node.value, current_node.value)
			prev_node.next  = current_node.next
			length -= 1

	if LOG:
		print(ll.repr_range(start, length))

def _concat_bisect(arena, start, length):
	if length == 1:
		return start

	mid = length >> 1
	left  = _concat_bisect(arena, start, mid)
	right = _concat_bisect(arena, start + mid, length - mid)

	left_node  = arena[left]
	right_node = arena[right]
	left_node.value = concat(left_node.value, right_node.value)

	return left

def concat_implicit_v3(ll, start, length):
	# [start, start + length) is a contiguous block in the arena, so real recursive bisection is possible.
	# the result will always be in `arena[start]`.

	# logging with this one isn't really possible.

	if start == 0 or length <= 0:
		raise ValueError("start must be nonzero and length must be positive")

	arena  = ll.array
	result = _concat_bisect(arena, start, length)
	ll.count -= length - 1

	# point to the node immediately following the range.
	# NOTE: `arena[start + length]` almost works, except for that the region this cares about could
	#       theoretically be at the end of the list (e.g. `%seteval[2 + $x$y$z]`) ends with a concat region.
	arena[result].next = arena[start + length - 1].next

def demo(concat_implicit=concat_implicit_v2, n=20, bits=32):
	from secrets import randbits
	ll = LinkedList()

	ll.append('?')
	ll.append("<A>")

	for i in range(n):
		ll.append(randbits(bits))

	ll.append('?')
	ll.append("<B>")

	concat_implicit(ll, 3, n)

	if LOG:
		print(ll)
		print(f"ll.count = {ll.count}")
