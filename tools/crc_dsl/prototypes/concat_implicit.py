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
	def __init__(self, value):
		self.value = value
		self.next = None

class LinkedList:
	def __init__(self):
		self.head = None
		self.length = 0

	def append(self, value, inside: bool = True):
		new_node = Node(value)
		if not self.head:
			self.head = new_node
		else:
			current = self.head
			i = 0
			while i < self.length - 1:
				current = current.next
				i += 1
			current.next = new_node

		if inside:
			# if inside == False, it simulates this being a sublist of a larger list.
			# in that case, `.next` on the last node may still point to a real node
			self.length += 1

	def __repr__(self):
		values = []
		current = self.head
		i = 0
		while current and i < self.length:
			values.append(current.value)
			current = current.next
			i += 1
		return " -> ".join(str(x) for x in values)

def concat_implicit_v1(ll):
	# this version is simpler, but is kind of bad for if the length isn't near a power of 2

	if not ll.head:
		raise ValueError("head must exist")

	while ll.length > 1:
		print(ll)

		current = ll.head
		merges = 0
		target_merges = ll.length >> 1 # one pass of pairwise merges

		while merges < target_merges:
			current.value = concat(current.value, current.next.value)
			current.next = current.next.next
			current = current.next
			merges += 1

		ll.length -= merges

	print(ll)

def concat_implicit_v2(ll):
	# this version still doesn't get full binary

	if not ll.head:
		raise ValueError("head must exist")

	while ll.length > 1:
		print(ll)

		current = ll.head
		prev = None
		merges = 0
		target_merges = ll.length >> 1

		while merges < target_merges:
			current.value = concat(current.value, current.next.value)
			current.next = current.next.next
			prev = current
			current = current.next
			merges += 1

		# NOTE: in C, this can happen after the branching. `print(ll)` needs the length to be correct, but
		#       that is not required for the C version.
		ll.length -= merges

		# if the list had an odd number of elements, merge the leftover
		# node with the last merged pair.
		if (ll.length + merges & 1) and prev and current:
			print(ll)
			prev.value = concat(prev.value, current.value)
			prev.next  = current.next
			ll.length -= 1

	print(ll)

def demo(concat_implicit=concat_implicit_v2):
	from secrets import randbits
	ll = LinkedList()

	for i in range(0, 29):
		ll.append(randbits(32))

	ll.append('?', inside=False)
	ll.append('<', inside=False)
	ll.append('|', inside=False)
	ll.append('>', inside=False)

	concat_implicit(ll)
