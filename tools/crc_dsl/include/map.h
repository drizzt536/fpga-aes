// SPDX-License-Identifier: MIT

/*
	map.h v0.9.6
	Copyright (c) 2026 Daniel Janusch

	Permission is hereby granted, free of charge, to any person obtaining a copy
	of this software and associated documentation files (the "Software"), to deal
	in the Software without restriction, including without limitation the rights
	to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	copies of the Software, and to permit persons to whom the Software is
	furnished to do so, subject to the following conditions:

	The above copyright notice and this permission notice shall be included in all
	copies or substantial portions of the Software.

	THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
	SOFTWARE.

	//////////////////////////////////////////////////////////////////////////////////////

	resizable and cache-friendly GNU C23 single-header hashmap API.
	primarily for C-string => C-string, but supports arbitrary types.
	relies on int-types.h and va-if.h (both can be copy/pasted here though)

	to compile separately:
		gcc -c -x c -DMAP_H_BUILD map.h -o map.o

		#define MAP_H_SEPARATE
		#include "map.h"

	to include directly:
		#define MAP_H_IMPL
		#include "map.h"

	NOTES:
	1. function naming convention:
		- map_x     : "static method", no live Map instance involved
		- Map_x     : "instance method", takes `Map this` as first argument.
		              Map_create is the only exception (the constructor).
		- Map__x    : probably unsafe to call directly; internal use only.
		- Map_x_ref : same as Map_x, but takes `Map *pthis` and doesn't return the new `this`.
		- Map_xN    : an arity-dispatch variant (i.e. Map_delete4, Map_set3).
		              not recommended for use, but still technically part of the public API.
	2. the following types exist for public use:
		- u8/i8, u16/i16, u32/i32, u64/i64, u128/i128
		- vstring: wide string pointer (string view, typically non-owning)
		- vstring_list: wide pointer to vstring. not used internally
		- map_hash_t: either u64 or u128, depending on the hash mode
		- map_cmp_t: a function that takes two `const void` pointers and returns `i32`
		- map_hashfn_t: a function that takes a `const void` pointer and returns `map_hash_t`
		- MapEntry
		- Map / ConstMap
		- MapEntryVView / MapEntryCView: key/val pair of either vstring or char *
		- MapEntryVList / MapEntryCList: wide pointer to the corresponding view type.
		- MapIter: map iterator object. use this if Map_foreach generates too much code
		- AF_Map / AF_ViewMap: auto-freeing variants of `Map`.
	3. The following helper macros exist for public use:
		- VA_IF: for arity-based dispatch: #define f(x, y...) VA_IF(f2(x, y), f1(x), y)
		- MAP_VMAJOR, MAP_VMINOR, MAP_VMICRO, MAP_VERSION: all `llu` integers
		- MAP_JSON_MODE_PACK, MAP_JSON_MODE_LINE, MAP_JSON_MODE_FULL
		- STR/STR_E: stringify, and expanded stringify
		- EXPAND: returns all the arguments identically
		- FORCE_INLINE: C23 attribute to force function inlining
		- nullstr: "(null)"
		- MAP_OWNED / MAP_UNOWNED: true/false, for `bool owned` arguments in some functions
		- AF_char: auto-freeing character array, e.g. `AF_char *x = malloc(32);`
		- Map_count(map) -> u64: returns the number of entries in the map
		- Map_foreach(map[, bucket], block) -> Map: execute the block for each entry in the map.
		  probably don't mutate the map too heavily such that iteration stops working.
		  the extra variables and labels available in the block are as follows:
			- prev_next: a pointer to the next field in the previous entry
			- p2entry: a pointer to the current entry
			- entry: a value copy of the current entry
			- bucket_done: a local label to exit bucket iteration
			- foreach_done: local label to exit iteration (only for 2-argument form)
			- bucket: the index of the current bucket (only for the 2-argument form)
		- Map_bucket(map, key) -> u64: hash the key and return it modulo the number of buckets.
		- Map_bucket_from_hash(map, hash) -> u64: return the hash modulo the number of buckets.
		- Map_normalize(map) -> Map: must be called when switching from Map_set_raw to Map_set.
		- Map_fit(map) -> nodiscard Map: resize the map to better fit the current live entries.
		- Map_has(map, key[, hash]): return a bool for if the map contains the key or not.
		- Map_has_by(map, key, cmp, hash): return a bool for if the map contains the key or not.
		- map_with(count, owned, pairs...) -> Map: create a new map with a constant set of keys.
		  e.g `AF_ViewMap = map_with(2, views, ("a", "b"), ("c", "d"));`. the second argument can
		  be view/views, or copy/copies. the rest of the arguments must be given as tuples.
		- Map_dump(map[, mode[, format]]) -> Map: log out the map. if format == 0, use JSON,
		  otherwise use basic formatting.
		- Map_transfer(dst, src[, owned]): transfer key-value pairs from the src map to the dst
		  map. If owned, the old map is cleared to prevent potential double frees.
		- jhash(in, len[, key]): the underlying hash function below `map_hash`, usable for types
		  other than C strings. The key defaults to `map_key()`
		- map_key([val]): with an argument given, it sets the map key and returns nothing. with
		  no argument given, it returns the map key.
		- map_init_key(): randomize the map key. requires RDRAND (-mrdrnd)
	4. the following functions exist for public use:
		- Map_create([m_cap[, o_cap]]): creates and returns a new map object. `m_cap` defaults to
		  `MAP_SIZE_SMALLEST`, and `o_cap` default to `MAP_H_MIN_OCAP`. Ignoring the return value
		  leaks memory.
		- Map_destroy_ref(pthis[, owned]): defaults to owning. NOTE: don't use this if the keys or
		  values are not C-strings unless nothing past potentially the struct containers is owned.
		  Iterate the map and free each entry yourself, and then call `Map_destroy_shallow_ref`.
		- Map_destroy_shallow_ref(pthis): free the map itself but none of the entries.
		- Map_gc(this): compact and sort overflow by bucket index.
		- Map_delete(this, key[, h[, owned]]): delete a given entry from the map. This assumes the
		  key is a C-string. If it puts it under the threshold, it may resize the overflow, but it
		  won't resize the map itself. If you want to shrink the map, call `Map_mresize`
		  explicitly.
		- Map_delete_by(this, key, cmp, hash, owned): the same as Map_delete, except it assumes
		  the keys are structs. It still only frees the containers, so if the struct has nested
		  objects that need to be freed, use `Map_get_entry_by`, free the subentries, and then
		  call `Map_delete_by`.
		- Map_clear(this[, owned]): delete all the entries from the map, and free them depending
		  on the mode. This assumes all the entries are C-strings, so don't call it if keys or
		  values are structs and need freeing beyond the struct containers.
		- Map_get_entry(this, key[, hash]): returns a pointer to the entry, or null if not found
		- Map_get_entry_by(this, key, cmp, hash): the same as `Map_get_entry` except it is used
		  for struct keys instead of C-string keys, hence the comparison function argument.
		- Map_get(this, key[, hash]): returns the corresponding value from the matching entry,
		  or null if it isn't present. Assumes the keys are C strings.
		- Map_get_by(this, key, cmp, hash): the same as `Map_get`, but assumes a struct key.
		- Map_cgetall(this, keys, count): this function assumes the keys and values are all
		  C-strings. It updates the `keys` array in-place with the corresponding value strings.
		  Any key that isn't in the map will be replaced with null. returns nothing.
		- Map_vgetall(this, keys, count): the same as `Map_cgetall`, except the keys array is typed
		  as `vstring keys[]` instead of `char *keys[]`, and the map is assumed to have V-strings
		  for all keys and values.
		- Map_set_raw(this, key, val[, owned]): add an entry to the map. Never resizes the map, and
		  will only ever resize the overflow. When switching from `Map_set_raw` to `Map_set` you
		  must call `Map_normalize` due to when each function applies resizes.
		- Map_set_raw_ref(pthis, key, val[, owned]): the same as `Map_set_raw` except it takes a
		  pointer to the map, modifies it in-place, and returns nothing.
		- Map_set_raw_by(this, key, val, cmp, hash[, owned]): the same as `Map_set_raw`, except it
		  is intended for struct keys, so a comparison function is required.
		- Map_set_raw_by_ref(pthis, key, val, cmp, hash, owned): the same as `Map_set_raw_by`
		  except it takes a pointer to the map, modifies it in-place, and returns nothing.
		- Map_set(this, key[, val[, owned]]): val defaults to null. Similar to `Map_set_raw` except
		  it has much more sophisticated growth heuristics, and it will grow the map itself. It
		  returns the map; ignoring the return value causes undefined behavior if the map grew.
		- Map_set_ref(pthis, key[, val[, owned]]): the same as `Map_set` except it takes a pointer
		  to the map, modifies it in-place, and returns nothing.
		- Map_vset(this, key[, val[, owned]]): the same as `Map_set`, except it assumes the key is
		  `vstring *` instead of `char *`.
		- Map_vset_ref(pthis, key[, val[, owned]]): the same as `Map_vset` except it takes a
		  pointer to the map, modifies it in-place, and returns nothing.
		- Map_set_by(this, key, val, cmp, hash, hashfn[, owned]): the same as `Map_set` except for
		  it assumes the key is a generic struct type, so it needs the comparison function, and the
		  hash function. It returns the map; ignoring the return value causes UB on resize.
		- Map_set_by_ref(pthis, key, val, cmp, hash, hashfn[, owned]): the same as `Map_set_by`
		  except it takes a pointer to the map, modifies it in-place, and returns nothing.
		- Map_csetall(this, entries[, owned]): takes a list of C-strings and adds each of them to
		  the map. It returns the map; ignoring the return value causes UB on resize.
		- Map_csetall_ref(pthis, entries[, owned]): the same as `Map_csetall` except it takes a
		  pointer to the map, modifies it in-place, and returns nothing.
		- Map_vsetall(this, entries): takes a list of `vstring` and adds each of them to the map
		  as owned containers. It returns the map; ignoring the return value causes UB on resize.
		- Map_vsetall_ref(pthis, entries): the same as `Map_vsetall` except it takes a pointer to
		  the map, modifies it in-place, and returns nothing.
		- Map_oresize(this[, o_cap]): resizes the overflow to the given cap. if o_cap is not
		  given, it will resize the overflow to the exact size needed to hold the current entries.
		- Map_mresize(this, m_cap): creates a new map with the new size, shallowly transfers the
		  entries to the new map, and returns it. If the new size is the same as the old size, it
		  does nothing. Ignoring the return value causes UB.
		- Map_mresize_ref(pthis, m_cap): the same as `Map_mresize` except it takes a pointer to
		  the map, modifies it in-place, and returns nothing.
		- Map_mresize_by(this, m_cap, cmp, hashfn): the same as `Map_mresize` except it assumes the
		  keys are arbitrary struct objects, so it needs the hash and comparison functions.
		- Map_mresize_by_ref(pthis, m_cap, cmp, hashfn): the same as `Map_mresize_by` except it
		  takes a pointer to the map, modifies it in-place, and returns nothing.
		- Map_rehash(this): the same as `Map_mresize` except it keeps m_cap the same, and
		  unconditionally performs the rehash. Useful if the hash key changed, since the old
		  entries will only be reachable via iteration.
		- Map_rehash_ref(pthis): the same as `Map_rehash` except it takes a pointer to the map,
		  modifies it in-place, and returns nothing.
		- Map_rehash_by(this, cmp, hashfn): the same as `Map_rehash`, except it assumes the keys
		  are arbitrary structs, so it needs the comparison and hash functions.
		- Map_rehash_by_ref(pthis, cmp, hashfn): the same as `Map_rehash_by` except it takes a
		  pointer to the map, modifies it in-place, and returns nothing.
		- Map_copy(this[, owned]): create and return a copy of the map. if owned is true, it
		  assumes the map keys and values are C-strings and duplicates the strings. if owned is
		  false, it makes no assumptions about the data and just memcopies to the new map.
		- Map_merge(this, other, owned1, owned2): merge `other` into `this`, where `other` wins
		  when a value is present in both maps. This assumes all keys and values are C-strings.
		  See the function comment for more information.
		- Map_merge_ref(pthis, other, owned1, owned2): the same as `Map_merge` except it takes a
		  pointer to the map, modifies it in-place, and returns nothing.
		- Map_iter(this): returns an iterator for the map containing the first entry. If the map is
		  empty, it gives a null pointer for the entry pointer.
		- Map_next(this, iterator): advances to the next entry, or gives a null pointer.
		- Map_tojson(this, mode): returns a dynamically-allocated JSON C-string. `mode` can be
		  '\0' for minified JSON, ' ' for spaces in-between stuff, and '\t' for pretty-printing.
		  This function assumes the map only contains C-string keys and values.
		- Map_tovstring_owned(this): in-place convert a C-string => C-string to a V-string =>
		  V-string map. Each V-string is put in its own separately-allocated struct container.
		  it always returns null for consistency with the unowned variant.
		- Map_tovstring_unowned(this): the same as `Map_tovstring_owned`, except all the V-strings
		  are put in the same memory allocation, so they can't be freed separately.
		- Map_tovstring(this[, owned]): picks between `Map_tovstring_owned` and
		  `Map_tovstring_unowned` depending on the ownership mode.
		- map_dedup_shuffle_det(strings, count): shuffle a list of C-strings using a map.
		  Deterministic so long as the map key doesn't change between calls. not reentrant.
		- map_dedup_shuffle(strings, count): the same as `map_dedup_shuffle_det`, except it
		  randomizes the hash key between calls to remove the strict determinism.
		- map_size(size): returns the closest usable map size to the input value. rounds up on tie.
		- map_hash(str): C-string hash function.
		- vstring_cmp(a, b): similar to `strcmp` but for `vstring *` instead of `char *`
		- vstring_hash(vstr): V-string (`vstring *`) hash function.
	5. Before including, define `MAP_H_IMPL` to pull in the actual implementation. To compile this
	   separately as an object or DLL and link later, define `MAP_H_SEPARATE`; this will remove
	   `static` from all function declarations and definitions. `MAP_H_BUILD` defines both
	   `MAP_H_IMPL` and `MAP_H_SEPARATE`. define `MAP_H_NO_FUN` if you hate fun so it will not
	   include the extra fun stuff like `map_dedup_shuffle`. define `MAP_H_DEFAULT_OWNED` or
	   `MAP_H_DEFAULT_UNOWNED` to specify the default ownership model (owned is the default
	   default). define `MAP_H_HASH128` or `MAP_H_HASH64` to select `jhash128` or `jhash64`.
	   `jhash64` is the default. define `MAP_H_MIN_OCAP` to set the minimum overflow arena size
	   (default is 4). Define `MAP_H_CHAR_ENTRIES` to define `MapEntry` with keys and values of
	   `char *`, or define `MAP_H_VOID_ENTRIES` to explicitly keep them as `void *. instead of
	   `void *`. It is `void *` by default to accommodate non C-string keys and values.
	6. the `setall` functions are really only for when creating a map from nothing *and*
	   it is easier to create a list and call one function instead of doing some kind of iterator
	   and calling `Map_set` for each entry object.
	7. the keys and values in the map should either all be owned by the map, or all non-owning
	   views. If they aren't all the same, you have to figure out which is which and call
	   `Map_set`/`Map_set_by` with the correct `owning` value for each one; it will cause heap
	   corruption if you get it wrong, so probably just don't do that.
	8. `Map` allocations are aligned to 64 bytes. freeing the map without `Map_destroy_ref` /
	   `Map_destroy_shallow_ref` can cause issues. On Linux, it is fine, though still not
	   recommended. On Windows, it will not work.
	9. most functions will automatically compile-time dispatch the correct variant based on the
	   argument count. e.g. `Map_set(map, key, val)` is the same as `Map_set3(map, key, val)`, but
	   `Map_set(map, key, val, owned)` is the same as `Map_set4(map, key, val, owned)`.
	10. on allocation failure, functions never crash or corrupt state, but they may silently do
	   less than requested (or nothing). This library assumes you are not allocating so much that
	   malloc/realloc/strdup realistically fails. If you need to verify an operation fully
	   completed, diff `Map_count(map)`, `map->m_cap`, or `map->o_cap` before and after, depending
	   on what you expect to have changed. If you plan on seeing OOM frequently, then probably you
	   should either A) use a library that handles OOM first-class, B) rethink and/or optimize
	   your design, or C) write wrapper functions that do handle allocation failures.
	11. For < 2^32 buckets, there is a fixed set of 48 map sizes that are allowed. If the requested
	   size is greater than 2^32 - 5, then it will return the size you requested, or perhaps one
	   greater if it was even. For reasonable input values, it will pick the size that is closest
	   smallest sizes increase faster, so the real average is closer to exactly 50%. all the fixed
	   bucket size values are prime. To manually increase the number of buckets to the next value,
	   use `map = Map_mresize(map, map->m_cap*3 >> 1);`.
	12. `Map` is not a thread-safe type. You should not touch a map object from one thread while
	    another thread maybe be mutating it. This also applies to non-owning maps that hold
	    references into non-readonly memory that is used across threads. mutating independent `Map`
	    objects from different threads is okay though since the functions are all reentrant.
	13. Most of the functions will crash if you pass them nullptr. They all assume the input is a
	    valid map, so they dereference without checking. The only exceptions are `Map_destroy_ref`
	    and `Map_destroy_shallow_ref`, where you can pass a pointer to nullptr, but still cannot
	    pass `nullptr` itself. All the other references assume that `pthis != nullptr` and
	    `*pthis != nullptr`. For this reason, all functions are marked with `[[gnu::nonnull]]`,
	    but macros can't be marked as that, so just note that the arguments should all point to
	    valid stuff.
	14. `Map` and `ConstMap` are pointers. If you are using `struct MapImpl` directly, you are
	    almost certainly doing something wrong, and it will probably cause heap corruption. Always
	    build maps using `Map_create`, and never put them on the stack or in BSS. `ConstMap` is a
	    promise about how a function will use a map; it should not be used for map declarations.
	    `AF_Map` and `AF_ViewMap` provide RAII, using a full destructor and a shallow destructor,
	    respectively.
	15. never set an entry's key to NULL/nullptr. That is used as a sentinel value to indicate
	    that the entry is not live. you can, however, values can be set to NULL/nullptr since
	    they are never dereferenced from inside the map implementation. Also, never reuse pointers
	    for keys and/or values in an owned map. it will cause multi frees.
	16. when using `_by` deletion functions, note that when they free the key and value, they only
	    free the struct container, since they don't have a way to know where the memory is that
	    would need to be freed anyway.
	17. see each specific function for comments on its specific API (only for some functions)

	this library will work with all GCC warning flags, except for the following:
		-Wcast-qual    (disallow explicitly casting away `const`)
		-Wuseless-cast (casting away const in macros is sometimes useless)
		-Wc++-compat
		-Wpedantic
		-Wtraditional
		-Wtraditional-conversion
		-Wsystem-headers (probably this one depends)

		most of these are stupid anyway

	Cache lines are assumed to be 64 bytes long.

	With `MAP_H_HASH128`, if using -nostdlib and linking manually, it requires -lgcc.
*/

#ifndef MAP_H_PROTO
#define MAP_H_PROTO

#include <stdlib.h>
#include <string.h>
#include <stdio.h> // for Map_dump

#include "int-types.h" // u8, u32, u64, u128
#include "va-if.h"     // VA_IF

#if defined(__AVX2__) || defined(__SSE2__)
	#include <immintrin.h>
#endif

// GCC's multichars are always big-endian regardless of target endianness for whatever
// reason, so I have to byte swap on little-endian systems. bypassing `-Wmultichar` is
// okay because it only exists because the feature is non-intuitive and error prone,
// but I am using it correctly, so that isn't an issue.

#define _MC_IMPL(x) ({                                \
	_Pragma("GCC diagnostic push")                    \
	_Pragma("GCC diagnostic ignored \"-Wmultichar\"") \
	x;                                                \
	_Pragma("GCC diagnostic pop")                     \
})

#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
	#define MC8(x)  ((u8)  _MC_IMPL(x))
	#define MC16(x) ((u16) _MC_IMPL(__builtin_bswap16(x)))
	#define MC32(x) ((u32) _MC_IMPL(__builtin_bswap32(x)))
	#define MC64(x) ((u64) _MC_IMPL(__builtin_bswap64(x)))
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	#define MC8(x)  ((u8)  _MC_IMPL(x))
	#define MC16(x) ((u16) _MC_IMPL(x))
	#define MC32(x) ((u32) _MC_IMPL(x))
	#define MC64(x) ((u64) _MC_IMPL(x))
#else
	#error "target has unknown byte order. define __BYTE_ORDER__ manually."
#endif

#define   likely(x)     (__builtin_expect(!!(x), 1))
#define unlikely(x)     (__builtin_expect(!!(x), 0))

#define   likelyp(x, p) (__builtin_expect_with_probability(!!(x), 1, p))
#define unlikelyp(x, p) (__builtin_expect_with_probability(!!(x), 0, p))

#define MAP_VMAJOR  ((u64) 0)
#define MAP_VMINOR  ((u64) 9)
#define MAP_VMICRO  ((u64) 3)
#define MAP_VERSION ((MAP_VMAJOR << 16) | (MAP_VMINOR << 8) | MAP_VMICRO)

#define MAP_JSON_MODE_PACK u8'\0' // single-line without padding
#define MAP_JSON_MODE_LINE u8' '  // single-line with padding
#define MAP_JSON_MODE_FULL u8'\t' // multiline

#ifndef FORCE_INLINE
	#define FORCE_INLINE [[gnu::always_inline, gnu::gnu_inline]] inline
#endif

#if defined(MAP_H_DEFAULT_OWNED) && defined(MAP_H_DEFAULT_UNOWNED)
	#error "`MAP_H_DEFAULT_OWNED` and `MAP_H_DEFAULT_UNOWNED` cannot both be defined"
#endif

// if these get switched, the code will not work
#define MAP_OWNED   true
#define MAP_UNOWNED false

#ifdef MAP_H_DEFAULT_UNOWNED
	#define MAP_DEF_OWNED MAP_UNOWNED

	#undef MAP_H_DEFAULT_UNOWNED
#else
	#define MAP_DEF_OWNED MAP_OWNED

	#ifdef MAP_H_DEFAULT_OWNED
		#undef MAP_H_DEFAULT_OWNED
	#endif
#endif

#ifdef MAP_STATIC
	// idk why this would be defined already
	#undef MAP_STATIC
#endif

#ifdef MAP_INLINE
	#undef MAP_INLINE
#endif

#ifdef MAP_H_BUILD
	#ifndef MAP_H_IMPL
		#define MAP_H_IMPL
	#endif

	#ifndef MAP_H_SEPARATE
		#define MAP_H_SEPARATE
	#endif
#endif

#ifdef MAP_H_SEPARATE
	#define MAP_STATIC
	#define MAP_INLINE
#else
	#define MAP_STATIC              static
	#define MAP_INLINE FORCE_INLINE static
#endif

#ifndef MAP_H_MIN_OCAP
	#define MAP_H_MIN_OCAP 4
#endif

#ifndef nullstr
	// so you can do `printf("%s\n", Map_get(map, key) ?: nullstr);` if you use `-Wall`
	#define nullstr "(null)"
#endif

#if defined(MAP_H_HASH128) && defined(MAP_H_HASH64)
	#error "`MAP_H_HASH128` and `MAP_H_HASH64` cannot both be defined."
#endif

#ifdef MAP_H_HASH128
	typedef u128 map_hash_t;
	#define _jhash jhash128
#else
	typedef u64 map_hash_t;
	#define _jhash jhash64

	#ifndef MAP_H_HASH64
		#define MAP_H_HASH64
	#endif
#endif

typedef struct {
	union {
		char *ptr; // memory ownership is tied to the object
		u64 ofs;   // memory ownership is independent of the object
		//            (i.e. index into dynamically allocated buffer)
	};

	u64 len;
} vstring;

typedef struct {
	vstring *array;
	u64 count;
} vstring_list;

typedef i32 (*map_cmp_t)(const void *, const void *);
typedef map_hash_t (*map_hashfn_t)(const void *);

#define _jhash3(in, len, key) _jhash(in, len, key)
#define _jhash2(in, len)      _jhash(in, len, map_key())

#define jhash(in, len, key...) VA_IF(_jhash3(in, len, key), _jhash2(in, len), key)

// NOTE: index 0 will be invalid, indicating there is no next entry.

#if defined(MAP_H_CHAR_ENTRIES) && defined(MAP_H_VOID_ENTRIES)
	#error "MAP_H_CHAR_ENTRIES and MAP_H_VOID_ENTRIES cannot both be defined."
#endif

typedef struct {
#ifdef MAP_H_CHAR_ENTRIES
	const char *key, *val;
#else
	const void *key, *val;
#endif
	u64 next; // index into arena
} MapEntry;

// MAPIMPL_NON_VA_BUCKETS must solve: (48 + 24*n) % 64 = 0 where n <= 11
//  - 48 == offsetof(struct MapImpl, buckets)
//  - 24 == sizeof(MapEntry)
//  - 64 == alignof(struct MapImpl)
//  - 11 == MAP_SIZE_SMALLEST
#define MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS 6

// if I use [[gnu::aligned(64)]] like normal, then the compiler will add 16 extra padding bytes, so
// I have to inline some of the buckets to make it work. It has to inline the exact amount to where
// sizeof(struct MapImpl) % 64 == 0, but it also has to be less than MAP_SIZE_SMALLEST + 1, because
// if you inline more buckets than the minimum amount of buckets, you waste memory.
struct [[gnu::aligned(64)]] MapImpl {
	// NOTE: o_size includes tombstones
	u64 m_size, o_size; // number of buckets used, number of overflow slots used
	u64 o_tcnt;         // number of tombstones in the overflow arena
	u64 m_cap, o_cap;   // number of buckets, total number of overflow slots
	MapEntry *overflow; // arena

	// first layer of entries is directly embedded.
	// don't worry about buffer overflows on this. I promise it works.
	MapEntry buckets[MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS];
	MapEntry _magic_field_with_more_buckets__dont_touch[];
};

typedef       struct MapImpl      *Map;
typedef const struct MapImpl *ConstMap;

typedef struct {
	vstring key, val;
} MapEntryVView;

typedef struct {
	MapEntryVView *array;
	u64 count;
} MapEntryVList;

typedef struct {
	char *key, *val;
} MapEntryCView;

typedef struct {
	MapEntryCView *array;
	u64 count;
} MapEntryCList;

typedef struct {
	// this has to be a pointer to the entry to prevent use after frees
	// in a case where you call Map_delete in the middle of execution.
	// you can still get undefined behavior if an insert triggers a resize
	// mid iteration. probably just don't do that unless you really need to.
	// Or I guess you could manually check the map attributes and make sure
	// an insert can't trigger a full resize.
	MapEntry *item;
	u64 bucket;
} MapIter;

// We have RAII at home
#define AF_Map     [[gnu::cleanup(Map_destroy_ref1)]]        Map
#define AF_ViewMap [[gnu::cleanup(Map_destroy_shallow_ref)]] Map
#define AF_ConstMap comptime_error("RAII for a const map makes no sense"); Map

#ifdef AF_char
	#define MAP_NODEFINE_CLEANUP_ARRAY
#else
	#define AF_char [[gnu::cleanup(cleanup_array)]] char
	[[gnu::nonnull]] MAP_INLINE void cleanup_array(const void *p);
#endif

// I considered making `t->count` or `t->size` an attribute instead of requiring a macro for it,
// but for the cases this will be used for, the speedup from accessing one field instead of three
// does not pay for the slowdown of having to update that field every time any mutation happens.
#define Map_count(this) ({       \
	const ConstMap t_ = this;     \
	_Pragma("GCC diagnostic push") \
	_Pragma("GCC diagnostic ignored \"-Wnull-dereference\"") \
	if (t_->o_tcnt > t_->o_size)     \
		unreachable();                \
	if (t_->m_size > t_->m_cap)        \
		unreachable();                  \
	_Pragma("GCC diagnostic pop")        \
	t_->m_size + t_->o_size - t_->o_tcnt; \
})

// NOTE: `this` should be an expression that is okay to be re-evaluated, so probably
//       it should not have any side-effects. also `this` should not be null or this
//       will crash. basically pretend it has `[[gnu:nonnull]]`
// this probably does not work if you nest loops.
// The `__label__`s are so you can do multiple `Map_foreach`s in the same function.
#define Map_foreach3(THIS, BUCKET, BLOCK) ({                 \
	__label__ bucket_done;                                   \
	[[maybe_unused]] u64 *prev_next = nullptr;               \
	MapEntry entry, *p2entry;                                \
	_Pragma("GCC diagnostic push")                           \
	_Pragma("GCC diagnostic ignored \"-Wnull-dereference\"") \
	p2entry = (MapEntry *) (THIS)->buckets + (BUCKET);       \
	_Pragma("GCC diagnostic pop")                            \
	entry   = *p2entry;                                      \
	/* NOTE 1: overflow[0].key == nullptr      */            \
	/* NOTE 2: entry.next == 0 for final entry */            \
	for (; entry.key != nullptr;                             \
		prev_next = &p2entry->next,                          \
		p2entry   = (THIS)->overflow + entry.next,           \
		entry     = *p2entry                                 \
	) {                                                      \
		BLOCK;                                               \
	}                                                        \
[[maybe_unused]] bucket_done:                                \
	THIS;                                                    \
})

#define Map_foreach2(THIS, BLOCK) ({                         \
	__label__ foreach_done;                                  \
	/* roughly: for (MapEntry entry : this) {block} */       \
	_Pragma("GCC diagnostic push")                           \
	_Pragma("GCC diagnostic ignored \"-Wnull-dereference\"") \
	for (u64 bucket = 0; bucket < (THIS)->m_cap; bucket++)   \
		Map_foreach3(THIS, bucket, BLOCK);                   \
	_Pragma("GCC diagnostic pop")                            \
[[maybe_unused]] foreach_done:                               \
	THIS;                                                    \
})

#define Map_foreach(this, x1, x2...) \
	VA_IF(Map_foreach3(this, x1, x2), Map_foreach2(this, x1), x2)

// do the extra variable just so it will get type-checked.
#define Map_bucket_from_hash(this, hash) ({ \
	const ConstMap t_ = this;                \
	(u64) (hash % (map_hash_t) t_->m_cap);    \
})
#define Map_bucket(this, key) Map_bucket_from_hash(this, map_hash(key))

// call this if you switch from `Map_set_raw` to `Map_set`.
// you don't need to normalize on the other way though.
// this should only ever need `==`, but use `>=` anyway.
#define Map_normalize(this) ({                               \
	const Map t_ = this;                                     \
	_Pragma("GCC diagnostic push")                           \
	_Pragma("GCC diagnostic ignored \"-Wnull-dereference\"") \
	if unlikely (t_->o_size + 1 >= t_->o_cap)                \
		Map_oresize(t_, t_->o_cap*3 >> 1);                   \
	_Pragma("GCC diagnostic pop")                            \
	t_;                                                      \
})

// resize the map buckets to fit the size
#define Map_fit(this) ({                \
	const Map t_ = this;                 \
	Map_oresize(t_);                      \
	Map_mresize(t_, Map_count(t_)*3 >> 1); \
})

#define Map_transfer3(dst, src, owned) Map_merge(dst, src, MAP_UNOWNED, owned)
#define Map_transfer2(dst, src)        Map_transfer3(dst, src, MAP_DEF_OWNED)
#define Map_transfer(dst, src, owned...) \
	VA_IF(Map_transfer3(dst, src, owned), Map_transfer2(dst, src), owned)

#ifdef copies
	#warning "macro `copies` is defined, which will make `map_with` not work."
#endif
#ifdef views
	#warning "macro `views` is defined, which will make `map_with` not work."
#endif
#ifdef copy
	#warning "macro `copies` is defined, which will make `map_with` not work."
#endif
#ifdef view
	#warning "macro `views` is defined, which will make `map_with` not work."
#endif

// the compiler counts the number of arguments in the preprocessor before
// it actually expands out the arguments, so it can, and does, count wrong.

// NOTE: these can use `Map_set_raw` because `map_with` creates it with roughly 50% extra
//       buckets than the number of things it is inserting.
#define Map__set_copy_impl(m,k,v) Map_set_raw(m, strdup(k), strdup(v), MAP_OWNED)
#define Map__set_copy(m,kv,_)      Map__set_copy_impl(m, kv)
#define Map__set_copies(m,kv,_)    Map__set_copy_impl(m, kv)

#define Map__set_view_impl(m,k,v,_) Map_set_raw(m, k, v, MAP_UNOWNED)
#define Map__set_views(m,kv,_)       Map__set_view_impl(m, kv, _)
#define Map__set_view(m,kv,_)        Map__set_view_impl(m, kv, _)

#ifndef STR
	// this stuff isn't used internally
	#define STR(x) #x

	#ifdef STR_E
		#undef STR_E
	#endif

	// stringify expanded
	#define STR_E(x) STR(x)
#endif

#ifdef EXPAND
	// idk, this seems like something that would be defined by other 3rd-party libraries.
	// they may or may not have defined it with var args though.
	#undef EXPAND
#endif

#define EXPAND(x...) x

// these pass the extra `0`s to get around a compiler bug. GCC counts macro arguments
// before actually expanding the arguments, so in the case where one of the arguments
// expands to more than one argument, the preprocessor uses the wrong number.
// I seriously doubt this will ever be fixed, since probably a lot of code relies on this,
// e.g. this code.
// I have no clue if Clang or MSVC have the same issue. Clang probably does.
#define Map__with16(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with15(m,o,x)
#define Map__with15(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with14(m,o,x)
#define Map__with14(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with13(m,o,x)
#define Map__with13(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with12(m,o,x)
#define Map__with12(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with11(m,o,x)
#define Map__with11(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with10(m,o,x)
#define Map__with10(m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with9 (m,o,x)
#define Map__with9( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with8 (m,o,x)
#define Map__with8( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with7 (m,o,x)
#define Map__with7( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with6 (m,o,x)
#define Map__with6( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with5 (m,o,x)
#define Map__with5( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with4 (m,o,x)
#define Map__with4( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with3 (m,o,x)
#define Map__with3( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with2 (m,o,x)
#define Map__with2( m,o,kv,x...) Map__set_##o(m, EXPAND kv, 0); Map__with1 (m,o,x)
#define Map__with1( m,o,kv)      Map__set_##o(m, EXPAND kv, 0)
#define Map__with0( m,o)

// basically `Map_vsetall`, but where the inputs are either constants or separate variables.
// NOTE: if you get weird errors about the number of arguments, probably you have a mismatch
//       between `count`, and the number of variable arguments.
#define map_with(count, owned, x...) ({   \
	Map map_ = Map_create(count*3 >> 1);  \
	if likely (map_ != nullptr) {         \
		Map__with##count(map_, owned, x); \
	}                                     \
	Map_normalize(map_);                  \
	map_;                                 \
})

#define Map_dump3(this, mode, format) ({            \
	const typeof(this) t_ = this;                   \
	if (format == 0) {                              \
		char *const json = Map_tojson(t_, mode);    \
		puts(json);                                 \
		free(json);                                 \
	}                                               \
	else /* basically just pass anything else */    \
		Map_foreach(t_, printf("\"%s\" = \"%s\"\n", \
			entry.key, entry.val                    \
		)); /* `mode` does nothing here */          \
	t_;                                             \
})

#define Map_dump2(this, mode) Map_dump3(this, mode, 0)
#define Map_dump1(this) Map_dump2(this, MAP_JSON_MODE_FULL)

#define Map_dump2_3(this, mode, format...) \
	VA_IF(Map_dump3(this, mode, format), Map_dump2(this, mode), format)
#define Map_dump(this, mode...) VA_IF(Map_dump2_3(this, mode), Map_dump1(this), mode)

#define Map_has(...)    (Map_get_entry(__VA_ARGS__) != nullptr)
#define Map_has_by(...) (Map_get_entry_by(__VA_ARGS__) != nullptr)

[[gnu::error("comptime error")]]
void comptime_error(...);

[[gnu::error("use `Map_destroy_ref(&map)`.")]]
Map Map_destroy(Map this);

#define map_key0() map_h_jhash_key
#define map_key(key...) VA_IF(map_key1(key), map_key0(), key)

#ifdef map__rng_type
	#undef map__rng_type
#endif

#ifdef map__rng_func
	#undef map__rng_func
#endif

#ifdef __RDRND__
	#define map__rng_type unsigned long long
	#define map__rng_func __builtin_ia32_rdrand64_step
#elifdef __RDSEED__
	#define map__rng_type unsigned long long
	#define map__rng_func __builtin_ia32_rdseed64_step
#elifdef __ARM_FEATURE_RNG
	#include <arm_acle.h>
	#define map__rng_type u64
	#define map__rng_func __rndr
#elifdef _WIN32
	// try using the operating system's provided functions.

	// this exists past like 2003
	// RtlGenRandom (CRYPTBASE.dll or Advapi32.dll)

	// this isn't declared by `#include <windows.h>`, so it is safe to declare it here.
	[[gnu::dllimport]]
	bool SystemFunction036(void *buf, u32 len);

	#define map_init_key() ({                                     \
		map_hash_t key_;                                          \
		while unlikely (!SystemFunction036(&key_, sizeof(key_))); \
		map_key(key_);                                            \
	})
#elifdef __linux__
	#if defined(__GLIBC__) && !(__GLIBC__ > 2 || (__GLIBC__ == 2 && __GLIBC_MINOR__ >= 25))
		// glibc, but not new enough.
		[[gnu::error("map_init_key requires RDRAND or RDSEED (x86), RNDR (arm), or getrandom, but none are available.")]]
		void map_init_key(...);
	#else
		// musl, or a sufficient version of glibc.
		// Doesn't check ENOSYS because I don't care. Update your kernel, Dawg. ts from 2014
		#include <sys/random.h>

		#define map_init_key() ({              \
			map_hash_t key_;                   \
			getrandom(&key_, sizeof(key_), 0); \
			map_key(key_);                     \
		})
	#endif
#else
	// no RDRAND, no RDSEED, ARM __rndr, and unknown system
	[[gnu::error("map_init_key requires RDRAND or RDSEED, but neither is available.")]]
	void map_init_key(...);
#endif // map_init_key

#if defined(map__rng_type) && defined(map__rng_func)
	#ifdef MAP_H_HASH128
		#define map_init_key() ({                        \
			map__rng_type ukey_;                         \
			map__rng_type lkey_;                         \
			while unlikely (map__rng_func(&ukey_) == 0); \
			while unlikely (map__rng_func(&lkey_) == 0); \
			map_key((map_hash_t)ukey_ << 64 | lkey_);    \
		})
	#else // HASH64
		#define map_init_key() ({                       \
			map__rng_type key_;                         \
			while unlikely (map__rng_func(&key_) == 0); \
			map_key((map_hash_t) key_);                 \
		})
	#endif
#endif

#define Map_create1(m_cap) Map_create2(m_cap, 0)
#define Map_create0() Map_create1(0)
#define Map_create1_2(m_cap, o_cap...) VA_IF(Map_create2(m_cap, o_cap), Map_create1(m_cap), o_cap)
#define Map_create(m_cap...) VA_IF(Map_create1_2(m_cap), Map_create0(), m_cap)

#define Map_destroy_ref2(pthis, owned) ({    \
	if (owned) Map_destroy_ref1(pthis);       \
	else       Map_destroy_shallow_ref(pthis); \
	(void) 0;                                   \
})

#define Map_destroy_ref(pthis, owned...) \
	VA_IF(Map_destroy_ref2(pthis, owned), Map_destroy_ref1(pthis), owned)

[[gnu::error("use `Map_destroy_shallow_ref(&map)`.")]]
Map Map_destroy_shallow(Map this);

// one empty slot after, and then the zero slot before
#define Map_oresize1(this) ({         \
	const Map t_ = this;              \
	Map_oresize2(t_, t_->o_size + 2); \
})
#define Map_oresize(this, o_cap...) VA_IF(Map_oresize2(this, o_cap), Map_oresize1(this), o_cap)

#define Map_get_entry2(this, key) Map_get_entry3(this, key, map_hash(key))
#define Map_get_entry(this, key, h...) VA_IF(Map_get_entry3(this, key, h), Map_get_entry2(this, key), h)

#define Map_get2(this, key) Map_get3(this, key, map_hash(key))
#define Map_get(this, key, h...) VA_IF(Map_get3(this, key, h), Map_get2(this, key), h)

#define Map_set_raw3(this, key, val) Map_set_raw4(this, key, val, MAP_DEF_OWNED)
#define Map_set_raw(this, key, val, owned...) \
	VA_IF(Map_set_raw4(this, key, val, owned), Map_set_raw3(this, key, val), owned)

#define Map_set_raw_ref4(pthis, key, val, owned) ({ \
	Map *const p = pthis;                           \
	*p = Map_set_raw(*p, key, val, owned);          \
	(void) 0;                                       \
})
#define Map_set_raw_ref3(pthis, key, val) Map_set_raw_ref4(pthis, key, val, MAP_DEF_OWNED)
#define Map_set_raw_ref(pthis, key, val, owned...) \
	VA_IF(Map_set_raw_ref4(pthis, key, val, owned), Map_set_raw_ref3(pthis, key, val), owned)

#define Map_set_raw_by5(this, key, val, cmp, hash) Map_set_raw_by6(this, key, val, cmp, hash, MAP_DEF_OWNED)
#define Map_set_raw_by(this, key, val, cmp, hash, owned...) VA_IF( \
	Map_set_raw_by6(this, key, val, cmp, hash, owned),             \
	Map_set_raw_by5(this, key, val, cmp, hash),                    \
	owned                                                          \
)

#define Map_set_raw_by_ref6(pthis, key, val, cmp, hash, owned) ({ \
	Map *const p = pthis;                                         \
	*p = Map_set_raw_by(*p, key, val, cmp, hash, owned);          \
	(void) 0;                                                     \
})
#define Map_set_raw_by_ref5(pthis, key, val, cmp, hash) \
	Map_set_raw_by_ref6(pthis, key, val, cmp, hash, MAP_DEF_OWNED)

#define Map_set_raw_by_ref(pthis, key, val, cmp, owned...) VA_IF( \
	Map_set_raw_by_ref6(pthis, key, val, cmp, hash, owned),       \
	Map_set_raw_by_ref5(pthis, key, val, cmp, hash),              \
	owned                                                         \
)

#define Map_set3(this, key, val) Map_set4(this, key, val, MAP_DEF_OWNED)
#define Map_set2(this, key) Map_set3(this, key, nullptr)
#define Map_set3_4(this, key, val, owned...) \
	VA_IF(Map_set4(this, key, val, owned), Map_set3(this, key, val), owned)
#define Map_set(this, key, val...) \
	VA_IF(Map_set3_4(this, key, val), Map_set2(this, key), val)

#define Map_set_ref4(pthis, key, val, owned) ({ \
	Map *const p = pthis;                       \
	*p = Map_set(*p, key, val, owned);          \
	(void) 0;                                   \
})
#define Map_set_ref3(pthis, key, val) Map_set_ref4(pthis, key, val, MAP_DEF_OWNED)
#define Map_set_ref2(pthis, key) Map_set_ref3(pthis, key, nullptr)
#define Map_set_ref3_4(pthis, key, val, owned...) \
	VA_IF(Map_set_ref4(pthis, key, val, owned), Map_set_ref3(pthis, key, val, owned), owned)
#define Map_set_ref(pthis, key, val...) \
	VA_IF(Map_set_ref3_4(pthis, key, val), Map_set_ref2(pthis, key), val)

#define Map_vset3(this, key, val) Map_vset4(this, key, val, MAP_DEF_OWNED)
#define Map_vset2(this, key) Map_vset3(this, key, nullptr)
#define Map_vset3_4(this, key, val, owned...) \
	VA_IF(Map_vset4(this, key, val, owned), Map_vset3(this, key, val), owned)
#define Map_vset(this, key, val...) \
	VA_IF(Map_vset3_4(this, key, val), Map_vset2(this, key), val)

#define Map_vset_ref4(pthis, key, val, owned) ({ \
	Map *const p = pthis;                        \
	*p = Map_vset(*p, key, val, owned);          \
	(void) 0;                                    \
})
#define Map_vset_ref3(pthis, key, val) Map_vset_ref4(pthis, key, val, MAP_DEF_OWNED)
#define Map_vset_ref2(pthis, key) Map_vset_ref3(pthis, key, nullptr)
#define Map_vset_ref3_4(pthis, key, val, owned...) \
	VA_IF(Map_vset_ref4(pthis, key, val, owned), Map_vset_ref3(pthis, key, val, owned), owned)
#define Map_vset_ref(pthis, key, val...) \
	VA_IF(Map_vset_ref3_4(pthis, key, val), Map_vset_ref2(pthis, key), val)

#define Map_set_by6(this, key, val, cmp, hash, hashfn) \
	Map_set_by7(this, key, val, cmp, hash, hashfn, MAP_DEF_OWNED)
#define Map_set_by(this, key, val, cmp, hash, hashfn, owned...) VA_IF( \
	Map_set_by7(this, key, val, cmp, hash, hashfn, owned),             \
	Map_set_by6(this, key, val, cmp, hash, hashfn),                    \
	owned                                                              \
)

#define Map_set_by_ref7(pthis, key, val, cmp, hash, hashfn, owned) ({ \
	Map *const p = pthis;                                             \
	*p = Map_set_by(*p, key, val, cmp, hash, hashfn, owned);          \
	(void) 0;                                                         \
})
#define Map_set_by_ref6(pthis, key, val, cmp, hash, hashfn) \
	Map_set_by_ref7(pthis, key, val, cmp, hash, hashfn, MAP_DEF_OWNED)
#define Map_set_by_ref(pthis, key, val, cmp, hash, hashfn, owned...) VA_IF( \
	Map_set_by_ref7(pthis, key, val, cmp, hash, hashfn, owned),             \
	Map_set_by_ref6(pthis, key, val, cmp, hash, hashfn),                    \
	owned                                                                   \
)

#define Map_vsetall_ref(pthis, entries) ({ \
	Map *const p = pthis;                  \
	*p = Map_vsetall(*p, entries);         \
	(void) 0;                              \
})

#define Map_csetall2(this, entries) Map_csetall3(this, entries, MAP_DEF_OWNED)
#define Map_csetall(this, entries, owned...) \
	VA_IF(Map_csetall3(this, entries, owned), Map_csetall2(this, entries), owned)

#define Map_csetall_ref3(pthis, entries, owned) ({ \
	Map *const p = pthis;                          \
	*p = Map_csetall(*p, entries, owned);          \
	(void) 0;                                      \
})
#define Map_csetall_ref2(pthis, entries) Map_csetall_ref3(pthis, entries, MAP_DEF_OWNED)
#define Map_csetall_ref(this, entries, owned...) \
	VA_IF(Map_csetall_ref3(this, entries, owned), Map_csetall_ref2(this, entries), owned)

#define Map_mresize_ref(pthis, m_cap) ({ \
	Map *const p = pthis;                \
	*p = Map_mresize(*p, m_cap);         \
	(void) 0;                            \
})

#define Map_mresize_by_ref(pthis, m_cap, cmp, hashfn) ({ \
	Map *const p = pthis;                                \
	*p = Map_mresize_by(*p, m_cap, cmp, hashfn);         \
	(void) 0;                                            \
})

#define Map_rehash_ref(pthis) ({ \
	Map *const p = pthis;        \
	*p = Map_rehash(*p);         \
	(void) 0;                    \
})

#define Map_rehash_by_ref(pthis, cmp, hashfn) ({ \
	Map *const p = pthis;                        \
	*p = Map_rehash_by(*p, cmp, hashfn);         \
	(void) 0;                                    \
})

#define Map_delete3(this, key, h) Map_delete4(this, key, h, MAP_DEF_OWNED)
#define Map_delete3_4(this, key, h, owned...) \
	VA_IF(Map_delete4(this, key, h, owned), Map_delete3(this, key, h), owned)
#define Map_delete2(this, key) Map_delete3(this, key, map_hash(key))
#define Map_delete(this, key, h...) VA_IF(Map_delete3_4(this, key, h), Map_delete2(this, key), h)

#define Map_delete_by4(this, key, cmp, hash) Map_delete_by5(this, key, cmp, hash, MAP_DEF_OWNED)
#define Map_delete_by(this, key, cmp, hash, owned...) VA_IF( \
	Map_delete_by5(this, key, cmp, hash, owned),             \
	Map_delete_by4(this, key, cmp, hash),                    \
	owned                                                    \
)

#define Map_clear1(this) Map_clear2(this, MAP_DEF_OWNED)
#define Map_clear(this, owned...) VA_IF(Map_clear2(this, owned), Map_clear1(this), owned)

#define Map_copy1(this) Map_copy2(this, MAP_DEF_OWNED)
#define Map_copy(this, owned...) \
	VA_IF(Map_copy2(this, owned), Map_copy1(this), owned)

#define Map_merge3(this, other, owned) Map_merge4(this, other, owned, owned)
#define Map_merge3_4(this, other, owned1, owned2...) \
	VA_IF(Map_merge4(this, other, owned1, owned2), Map_merge3(this, other, owned1), owned2)
#define Map_merge2(this, other) Map_merge3(this, other, MAP_DEF_OWNED)
#define Map_merge(this, other, owned...) \
	VA_IF(Map_merge3_4(this, other, owned), Map_merge2(this, other), owned)

#define Map_merge_ref3(pthis, other, owned) ({ \
	Map *const p = pthis;                      \
	*p = Map_merge(*p, other, owned);          \
	(void) 0;                                  \
})
#define Map_merge_ref2(pthis, other) Map_merge_ref3(pthis, other, MAP_DEF_OWNED)
#define Map_merge_ref(pthis, other, owned...) \
	VA_IF(Map_merge_ref3(pthis, other, owned), Map_merge_ref2(pthis, other), owned)

#define Map_tovstring2(this, owned) ((owned) ? Map_tovstring_owned : Map_tovstring_unowned)(this)
#define Map_tovstring1(this) Map_tovstring2(this, MAP_DEF_OWNED)
#define Map_tovstring(this, owned...) VA_IF(Map_tovstring2(this, owned), Map_tovstring1(this), owned)

[[gnu::pure]] MAP_STATIC u64 map_size(u64 size);
[[gnu::nonnull, gnu::pure]] MAP_INLINE map_hash_t map_hash(const void *in);
[[gnu::nonnull, gnu::pure]] MAP_STATIC i32 vstring_cmp(const void *a, const void *b);
[[gnu::nonnull, gnu::pure]] MAP_STATIC map_hash_t vstring_hash(const void *in);
MAP_INLINE void map_key1(map_hash_t key);
[[nodiscard, gnu::malloc]] MAP_STATIC Map Map_create2(u64 m_cap, u64 o_cap);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_destroy_ref1(Map *pthis);
[[maybe_unused, gnu::nonnull]] MAP_INLINE void Map_destroy_shallow_ref(const Map *pthis);
[[gnu::nonnull]] MAP_STATIC bool Map_gc(Map this);
[[gnu::nonnull]] MAP_STATIC bool Map_oresize2(Map this, u64 o_cap);
[[gnu::nonnull, gnu::pure]] MAP_STATIC MapEntry *Map_get_entry3(ConstMap this, const char *key, map_hash_t hash);
[[gnu::nonnull, gnu::pure]] MAP_STATIC MapEntry *Map_get_entry_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash);
[[gnu::nonnull, gnu::pure]] MAP_INLINE char *Map_get3(ConstMap this, const char *key, map_hash_t hash);
[[gnu::nonnull, gnu::pure]] MAP_INLINE void *Map_get_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash);
[[maybe_unused, gnu::nonnull]] MAP_STATIC bool Map_delete4(Map this, const char *key, map_hash_t hash, bool owned);
[[maybe_unused, gnu::nonnull]] MAP_STATIC bool Map_delete_by5(Map this, const void *key, map_cmp_t cmp, map_hash_t hash, bool owned);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_STATIC Map Map_mresize(Map this, u64 m_cap);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_STATIC Map Map_mresize_by(Map this, u64 m_cap, map_cmp_t cmp, map_hashfn_t hashfn);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_INLINE Map Map_rehash(Map this);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_INLINE Map Map_rehash_by(Map this, map_cmp_t cmp, map_hashfn_t hashfn);
[[gnu::nonnull(1,2)]] MAP_STATIC bool Map_set_raw4(Map this, const char *restrict key, const char *restrict val, bool owned);
[[gnu::nonnull(1,2,4)]] MAP_STATIC bool Map_set_raw_by6(Map this, const void *restrict key, const void *restrict val, map_cmp_t cmp, map_hash_t hash, bool owned);
[[nodiscard, gnu::nonnull(1,2)]] MAP_STATIC Map Map_set4(Map this, const char *restrict key, const char *restrict val, bool owned);
[[nodiscard, gnu::nonnull(1,2)]] MAP_STATIC Map Map_vset4(Map this, const vstring *restrict key, const void *restrict val, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull(1,2,4,6)]] MAP_STATIC Map Map_set_by7(Map this, const void *restrict key, const void *restrict val, map_cmp_t cmp, map_hash_t hash, map_hashfn_t hashfn, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_vsetall(Map this, MapEntryVList entries);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_csetall3(Map this, MapEntryCList entries, bool owned);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_cgetall(ConstMap this, const char *keys[], u64 count);
[[maybe_unused, gnu::nonnull]]MAP_STATIC void Map_vgetall(ConstMap this, vstring_list keys);
[[maybe_unused, gnu::nonnull]] MAP_STATIC MapIter Map_iter(ConstMap this);
[[maybe_unused, gnu::nonnull]] MAP_STATIC MapIter Map_next(ConstMap this, MapIter iter);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_clear2(Map this, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_copy2(ConstMap this, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull(1)]] MAP_STATIC Map Map_merge4(Map this, Map other, bool owned1, bool owned2);
[[nodiscard, maybe_unused, gnu::nonnull, gnu::malloc]] MAP_STATIC char *Map_tojson(ConstMap this, u8 mode);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void *Map_tovstring_owned(Map this);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC void *Map_tovstring_unowned(Map this);
#ifndef MAP_H_NO_FUN
	[[gnu::nonnull]] MAP_STATIC u64 map_dedup_shuffle_det(const char *strings[], u64 len);
	[[maybe_unused, gnu::nonnull]] MAP_STATIC u64 map_dedup_shuffle(const char *strings[], u64 len);
#endif

#endif // MAP_H

#if defined(MAP_H_IMPL) && !defined(MAP_H_IMPL_CONFIRM)
#define MAP_H_IMPL_CONFIRM

// basically a copy of Map_destroy_shallow_ref, except it crashes if you pass null, and it is not by reference.
#define Map__destroy_shallow(this) ({ \
	const Map t_ = this;              \
	free((void *) t_->overflow);      \
	map__free((void *) t_);           \
	(void) 0;                         \
})

#define map__free_kv(k, v) ({ \
	free((void *) (k));       \
	free((void *) (v));       \
})

#define map__free_entry(entry) map__free_kv((entry).key, (entry).val)

#ifdef _WIN32
	#define map__alloc(size) _aligned_malloc(size, 64)
	#define map__free(map)   _aligned_free(map)
#else
	// perhaps this should use posix_memalign or whatever it is called,
	// since that one doesn't require the size to be aligned
	#define map__alloc(size) aligned_alloc(64, (size + 63) & ~63llu)
	#define map__free(map)   free(map)
#endif

#define MAP_SIZE_SMALLEST 11
static constexpr u32 map_small_sizes[48] = {
	MAP_SIZE_SMALLEST, 19, 31, 59, 101, 173, 257, 389, 587, 877, 1319, 1973, 2957,
	4441, 6653, 9973, 14969, 22447, 33679, 50503, 75743, 113623, 170447, 255667,
	383489, 575251, 862879, 1294309, 1941479, 2912213, 4368323, 6552503, 9828733,
	14743129, 22114667, 33171997, 49758001, 74637007, 111955483, 167933239, 251899849,
	377849753, 566774657, 850162007, 1275242989, 1912864493, 2869296739, 4294967291
};

[[gnu::pure]]
MAP_STATIC u64 map_size(u64 size) {
	// returns the actual size of the map. not all map sizes are valid.
	// it picks the nearest valid size to the value given.

	// prime nearest to 2 * 1.5^(i + 6), except the first one is 11 and not 17, and the last
	// one is 2^32 - 5. also the first 6 are slightly faster so it could take 6 elements
	// instead of 7 to get to 173. (173/11)^(1/5) ~~ 1.735 instead of 1.5

	if unlikely (size > (1llu << 32) - 5)
		// these values will not be in the table
		// with that many elements, the length being prime doesn't really matter.
		// just make sure it is at least odd.
		return size + !(size & 1);

	static_assert(sizeof(map_small_sizes) == sizeof(*map_small_sizes)*48);

	// one binary search step
	const u32 *const arr = map_small_sizes + (size > map_small_sizes[23] ? 24 : 0);
	u8 i;

	for (i = 0; i < 24; i++)
		if (arr[i] >= size)
			break;

	if (i == 0 && map_small_sizes == arr)
		return MAP_SIZE_SMALLEST;

	const u64
		prev = arr[i - 1],
		next = arr[i];

	// return size - prev < next - size ? prev : next;
	return size << 1 < prev + next ? prev : next;
}

#define jhash_mulhi64(x, y) ( (u64) ((u128) (x) * (y) >> 64) )
#define jhash_bswap64(x) __builtin_bswap64((u64) (x))
#define map__u128c(hi, lo) ((u128) (0x##hi##llu) << 64 | (u128) (0x##lo##llu))

#ifdef MAP_H_HASH128
// 128-bit variant

#define jhash_bswap128(x) __builtin_bswap128(x)

// this is an approximation. multiplication with `unsigned _BitInt(256)` is super slow,
// and I also don't need the entire result, so I will just not do that.
#define jhash_mulhi128(_x, _y) ({             \
	const u128 x = _x;                         \
	const u128 y = _y;                          \
	const u64 xhi = (u64) (x >> 64);             \
	const u64 yhi = (u64) (y >> 64);              \
	const u64 lo_hi = jhash_mulhi64((u64) x, yhi); \
	const u64 hi_lo = jhash_mulhi64(xhi, (u64) y);  \
	const u128 hi_hi = (u128) xhi * yhi;             \
	hi_hi + lo_hi + hi_lo;                            \
})

static map_hash_t map_h_jhash_key = 0;

[[gnu::nonnull, gnu::pure]]
MAP_STATIC u128 jhash128(const void *in, u64 len, u128 key) {
	// look at the 64-bit variant for explanatory comments.
	// probably don't bother using this over the 64-bit one since it is like 12 times slower I think.

	const u128 *data = (const u128 *) in;

	constexpr u128 p1 = map__u128c(6a09e667f3bcc908,b2fb1366ea957d3f); // Ceiling[2^128 (Sqrt[2] - 1)]
	constexpr u128 p2 = map__u128c(3c6ef372fe94f82b,e73980c0b9db9068); // Floor  [2^128 (Sqrt[5] - 1)] - 2^128
	constexpr u128 p3 = map__u128c(9c2d21e4b5bc4be9,c4ceb9fe1a85ec53); // from MurmurHash3, plus some junk
	constexpr u128 mx = map__u128c(ff3e36acd17d11a6,3f51afd7ed558ccd); // from MurmurHash3, plus some junk
	constexpr u128 x1 = map__u128c(646f72616e646f6d,736f6d6570736575); // from SipHash
	constexpr u128 x2 = map__u128c(7465646279746573,6c7967656e657261); // from SipHash
	constexpr u128 x3 = map__u128c(8dc595627521b862,4201bb072e27626c); // from FNV-1a, kind of

	u128 hash = jhash_bswap128(key ^ x1) | 1;
	u128 rkey =               (key ^ x2) | 1; // round key
	u128 fbkh;                                // feedback hash

	key  ^= x3;
	rkey += p2;

	while (len >= 16) {
		u128 tmp;
		fbkh  = hash;
		len  -= 16;
	#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
		hash ^= data[0];
	#else
		hash ^= jhash_bswap128(data[0]);
	#endif
		tmp   = jhash_mulhi128(fbkh, rkey);
		hash *= p1;
		data += 1;
		hash ^= tmp;
		rkey += p2;
	}

	if (len > 0) {
		u128 block = (u128) len << 15*8;
		fbkh = hash;

		switch (len) {
			default: unreachable(); break;
			case 15: block |= (u128) ((const u8 *) data)[14] << 14*8; [[fallthrough]];
			case 14: block |= (u128) ((const u8 *) data)[13] << 13*8; [[fallthrough]];
			case 13: block |= (u128) ((const u8 *) data)[12] << 12*8; [[fallthrough]];
			case 12: block |= (u128) ((const u8 *) data)[11] << 11*8; [[fallthrough]];
			case 11: block |= (u128) ((const u8 *) data)[10] << 10*8; [[fallthrough]];
			case 10: block |= (u128) ((const u8 *) data)[ 9] <<  9*8; [[fallthrough]];
			case  9: block |= (u128) ((const u8 *) data)[ 8] <<  8*8; [[fallthrough]];
			case  8: block |= (u128) ((const u8 *) data)[ 7] <<  7*8; [[fallthrough]];
			case  7: block |= (u128) ((const u8 *) data)[ 6] <<  6*8; [[fallthrough]];
			case  6: block |= (u128) ((const u8 *) data)[ 5] <<  5*8; [[fallthrough]];
			case  5: block |= (u128) ((const u8 *) data)[ 4] <<  4*8; [[fallthrough]];
			case  4: block |= (u128) ((const u8 *) data)[ 3] <<  3*8; [[fallthrough]];
			case  3: block |= (u128) ((const u8 *) data)[ 2] <<  2*8; [[fallthrough]];
			case  2: block |= (u128) ((const u8 *) data)[ 1] <<  1*8; [[fallthrough]];
			case  1: block |= (u128) ((const u8 *) data)[ 0] <<  0*8; break;
		}

		hash ^= block;
		hash *= p1;
		hash ^= jhash_mulhi128(fbkh, rkey);
	}

	hash ^= jhash_mulhi128(hash, key | 1);
	hash *= p3;
	fbkh  = hash;
	hash  = jhash_bswap128(hash * mx);
	hash ^= hash >> 27;
	hash ^= fbkh;
	return hash;
}

#undef jhash_bswap128
#undef jhash_mulhi128

#else ////////////////////////////////////////////////////////////////////////////////////////////////
// 64-bit variant

static map_hash_t map_h_jhash_key = 0;

[[gnu::nonnull, gnu::pure]]
MAP_STATIC u64 jhash64(const void *in, u64 len, u64 key) {
	// this is non-cryptographic. collision attacks are possible in a reasonable amount of time (<=minutes).
	// The outputs look like a random oracle though in most cases.

	const u64 *data = (const u64 *) in;

	// p2 must be even
	constexpr u64 p1 = 0x6a09e667f3bcc909llu; // Ceiling[2^64 (Sqrt[2] - 1)]
	constexpr u64 p2 = 0x3c6ef372fe94f82cllu; // Ceiling[2^64 (Sqrt[5] - 1)] - 2^64
	constexpr u64 p3 = 0xc4ceb9fe1a85ec53llu; // from MurmurHash3 fmix64
	constexpr u64 mx = 0xff51afd7ed558ccdllu; // from MurmurHash3 fmix64
	constexpr u64 x1 = 0x736f6d6570736575llu; // from SipHash
	constexpr u64 x2 = 0x6c7967656e657261llu; // from SipHash
	constexpr u64 x3 = 0x25232284e49cf2cbllu; // from FNV-1a, byte swapped

	u64 hash = jhash_bswap64(key ^ x1) | 1; // starting hash
	u64 rkey =              (key ^ x2) | 1; // round key
	u64 fbkh;                               // feedback hash

	key  ^= x3; // for finalization
	rkey += p2;

	while (len >= 8) {
		u64 tmp;
		fbkh  = hash;
		len  -= 8;
	#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
		hash ^= *data;
	#else
		hash ^= jhash_bswap64(*data);
	#endif
		tmp   = jhash_mulhi64(fbkh, rkey);
		hash *= p1;
		data += 1;
		hash ^= tmp;
		rkey += p2;
	}

	if (len > 0) {
		u64 block = len << 7*8;
		fbkh = hash;

		switch (len) {
			default: unreachable(); break;
			case 7: block |= (u64) ((const u8 *) data)[6] << 6*8; [[fallthrough]];
			case 6: block |= (u64) ((const u8 *) data)[5] << 5*8; [[fallthrough]];
			case 5: block |= (u64) ((const u8 *) data)[4] << 4*8; [[fallthrough]];
			case 4: block |= (u64) ((const u8 *) data)[3] << 3*8; [[fallthrough]];
			case 3: block |= (u64) ((const u8 *) data)[2] << 2*8; [[fallthrough]];
			case 2: block |= (u64) ((const u8 *) data)[1] << 1*8; [[fallthrough]];
			case 1: block |= (u64) ((const u8 *) data)[0] << 0*8; break;
		}

		hash ^= block;
		hash *= p1;
		hash ^= jhash_mulhi64(fbkh, rkey);
	}

	hash ^= jhash_mulhi64(hash, key | 1);
	hash *= p3;
	fbkh  = hash;
	hash *= mx;
	hash  = jhash_bswap64(hash);
	hash ^= hash >> 13;
	hash ^= fbkh;
	return hash;
}
#endif

[[gnu::nonnull, gnu::pure]]
MAP_INLINE map_hash_t map_hash(const void *in) {
	const char *cstr = (const char *) in;
	return jhash(cstr, strlen(cstr), map_key());
}

[[gnu::nonnull, gnu::pure]]
MAP_STATIC i32 vstring_cmp(const void *a, const void *b) {
	vstring *va = (vstring *) a;
	vstring *vb = (vstring *) b;
	return va->len == vb->len ? strncmp(va->ptr, vb->ptr, va->len) : 1;
}

[[gnu::nonnull, gnu::pure]]
MAP_STATIC map_hash_t vstring_hash(const void *in) {
	vstring *const key = (vstring *) in;
	return jhash(key->ptr, key->len);
}

MAP_INLINE void map_key1(map_hash_t key) {
	map_h_jhash_key = key;
}

[[nodiscard, gnu::malloc]]
MAP_STATIC Map Map_create2(u64 m_cap, u64 o_cap) {
	if (o_cap < MAP_H_MIN_OCAP)
		o_cap = MAP_H_MIN_OCAP;

	m_cap = map_size(m_cap);

	static_assert(offsetof(struct MapImpl, buckets) == 48,
		"struct MapImpl should not have automatic padding."
		" also, the header should have six u64/ptr fields."
		" or maybe the number of inlined buckets is wrong.");
	static_assert(sizeof(MapEntry) == 24);
	static_assert(sizeof(struct MapImpl) % 64 == 0);
	static_assert(sizeof(struct MapImpl) == offsetof(struct MapImpl, buckets)
		+ sizeof(MapEntry)*MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS,
		"struct MapImpl should not have any trailing padding."
	);
	static_assert(MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS <= MAP_SIZE_SMALLEST);
	static_assert(sizeof(void *) == 8);

	Map map = map__alloc(
		sizeof(struct MapImpl) + sizeof(MapEntry)*(m_cap - MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS)
	);

	if unlikely (map == nullptr)
		return nullptr;

	// NOTE: these emit `movaps`, which is fine since map is 64-byte aligned.
	#ifdef __AVX2__
		// this also zeros m_cap, but it gets set properly afterwards
		*(__m256i *) map = (__m256i) {0};
	#elifdef __SSE2__
		*(__m128i *) map = (__m128i) {0};
		((u64 *) map)[2] = 0;
	#else
		map->m_size = 0;
		map->o_size = 0;
		map->o_tcnt = 0;
	#endif
	map->m_cap    = m_cap;
	map->o_cap    = o_cap;
	map->overflow = (MapEntry *) malloc(sizeof(MapEntry)*o_cap);

	if unlikely (map->overflow == nullptr) {
		map__free(map);
		return nullptr;
	}
	// zeroing the overflow arena doesn't matter

	static_assert(MAP_H_MIN_OCAP > 1);

	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	// key and next fields are empty for the reserved entry.
	#ifdef __AVX2__
		// this also zeros the key of the next entry, but that is fine.
		_mm256_storeu_si256((__m256i *) map->overflow, (__m256i) {0});
	#else
		map->overflow->key  = nullptr;
		map->overflow->next = 0;
	#endif

	#pragma GCC diagnostic pop

	// make sure all the `next` fields are 0 and `key` fields are null in the inline buckets
	memset(map->buckets, 0, sizeof(MapEntry)*m_cap);

	// the rest of the overflow is cold, so prefetch the first few cache lines.
	// since sizeof(MapEntry) == 24, this is roughly 2.7 inserts per prefetch.
	__builtin_prefetch((char *) map->overflow + 64*1, 1, 3); // rw=write, L1
	__builtin_prefetch((char *) map->overflow + 64*2, 1, 3);
	// __builtin_prefetch((char *) map->overflow + 64*3, 1, 3);
	// __builtin_prefetch((char *) map->overflow + 64*4, 1, 3);

	return map;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_destroy_ref1(Map *pthis) {
	// make the user pass a pointer to their variable to avoid use after frees
	Map this = *pthis;

	if unlikely (this == nullptr)
		// destroy an already-destroyed map => do nothing.
		return;

	Map_foreach(this,
		map__free_entry(entry)
	);

	Map__destroy_shallow(this);
	*pthis = nullptr;
}

[[maybe_unused, gnu::nonnull]]
MAP_INLINE void Map_destroy_shallow_ref(const Map *pthis) {
	const Map this = *pthis;
	if unlikely (this == nullptr)
		return;

	free((void *) this->overflow);
	map__free((void *) this);

	// this is technically undefined behavior if the enclosing scope declares as either
	// `const Map m = ...;` or `AF_ViewMap const m = ...;`, but I don't reall care since the
	// issues from the undefined behavior that arises from this are always at least as good as
	// what happens if it does not do this null write. most compilers will just write anyway,
	// which is the best case scenario. Or they will ignore this, which is fine too. basically,
	// just don't touch the map after it is destroyed, and this doesn't matter at all.
	// (and obviously don't store map pointers in .rdata)
	*(Map *) pthis = nullptr;
}

[[gnu::nonnull]]
MAP_STATIC bool Map_gc(Map this) {
	// tracing tombstone garbage collector
	// preserves linked list ordering per bucket
	// returns true if it succeeded and false if it failed

	// after running this, iterating over the arena is the same as iterating with Map_foreach,
	// except for you skip the first entry in every bucket (the inline entries).
	// it could also be a reasonable name to make this `Map_sort`.

	MapEntry *new_overflow = malloc(sizeof(MapEntry)*this->o_cap);

	if unlikely (new_overflow == nullptr)
		return false;

	// this is the same zeroing block as in Map_create2
	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	#ifdef __AVX2__
		_mm256_storeu_si256((__m256i *) new_overflow, (__m256i) {0});
	#elifdef __SSE2__
		_mm_storeu_si128((__m128i *) new_overflow, (__m128i) {0});
		((u64 *) new_overflow)[2] = 0;
	#else
		new_overflow[0] = (MapEntry) {0};
	#endif

	#pragma GCC diagnostic pop

	u64 new_id = 1; // index 0 is reserved, so start at 1.
	// the two preprocessor branches are logically identical.
	// the Map_foreach way is slightly slower since it checks prev_next == nullptr for every element,
	// but it is way simpler.
#if 0
	u64 *new_prev_next = nullptr;

	Map_foreach(this,
		if (prev_next == nullptr)
			// inline bucket entry. the write location is the same as the read location
			new_prev_next = &p2entry->next;
		else {
			*new_prev_next       = new_id;
			new_overflow[new_id] = entry;
			new_prev_next        = &new_overflow[new_id].next; // advance new chain for writing
			new_id++;
		}
	);
#else
	MapEntry *old_overflow = this->overflow;

	for (u64 bucket = 0; bucket < this->m_cap; bucket++) {
		u64 old_id = this->buckets[bucket].next; // old id of first chain value

		if (old_id == 0)
			continue; // no overflow chain for this bucket

		u64 *prev_next = &this->buckets[bucket].next; // this is the same in both chains

		do {
			*prev_next = new_id;
			new_overflow[new_id] = old_overflow[old_id];

			prev_next = &new_overflow[new_id].next; // advance new chain for writing
			old_id    =  old_overflow[old_id].next; // advance old chain for reading
			new_id++;
		} while unlikely (old_id != 0);
	}
#endif

	// new_id starts at 1 and increments after each write, so new_id is 1 + o_size
	this->o_size = new_id - 1;
	this->o_tcnt = 0;

	free(this->overflow);
	this->overflow = new_overflow;

	// same prefetch strategy as in `Map_create2`.
	__builtin_prefetch((char *) (new_overflow + new_id) + 64*0, 1, 3); // rw=write, L1
	__builtin_prefetch((char *) (new_overflow + new_id) + 64*1, 1, 3);
	// __builtin_prefetch((char *) (new_overflow + new_id) + 64*2, 1, 3);
	// __builtin_prefetch((char *) (new_overflow + new_id) + 64*3, 1, 3);

	return true;
}

[[gnu::nonnull]]
MAP_STATIC bool Map_oresize2(Map this, u64 o_cap) {
	// returns true if it succeeded and false if it failed.
	// shrinking the map is not recommended, especially if you have a MapIter for the map.

	// assert the invariants from the rest of the code in case it helps GCC with optimization.
	if (this->o_cap < MAP_H_MIN_OCAP || this->o_cap < this->o_size + 1)
		unreachable();

	if unlikely (o_cap < MAP_H_MIN_OCAP || o_cap < this->o_size + 2)
		return false; // not allowed

	MapEntry *new_overflow = realloc(this->overflow, sizeof(MapEntry)*o_cap);
	if unlikely (new_overflow == nullptr)
		return false;

	this->o_cap = o_cap;
	this->overflow = new_overflow;
	return true;
}

[[gnu::nonnull, gnu::pure]]
MAP_STATIC MapEntry *Map_get_entry3(ConstMap this, const char *key, map_hash_t hash) {
	// returns a pointer to the matching element
	hash = Map_bucket_from_hash(this, hash);

	Map_foreach(this, hash,
		if (strcmp(entry.key, key) == 0)
			return p2entry;
	);

	return nullptr;
}

[[gnu::nonnull, gnu::pure]]
MAP_STATIC MapEntry *Map_get_entry_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash) {
	// same as Map_get_entry3 but with `cmp` instead of `strcmp`
	hash = Map_bucket_from_hash(this, hash);

	Map_foreach(this, hash,
		if (cmp((void *) entry.key, key) == 0)
			return p2entry;
	);

	return nullptr;
}

[[gnu::nonnull, gnu::pure]]
MAP_INLINE char *Map_get3(ConstMap this, const char *key, map_hash_t hash) {
	// returns the value field from the matching element
	MapEntry *e = Map_get_entry(this, key, hash);
	return e == nullptr ? nullptr : (char *) e->val;
}

[[gnu::nonnull, gnu::pure]]
MAP_INLINE void *Map_get_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash) {
	// returns the value field from the matching element
	MapEntry *e = Map_get_entry_by(this, key, cmp, hash);
	return e == nullptr ? nullptr : (void *) e->val;
}

[[maybe_unused, gnu::nonnull]]
MAP_INLINE bool Map__delete_by(Map this, const void *key, map_cmp_t cmp, map_hash_t hash, bool owned) {
	// returns true if the entry was found, and false if it wasn't

	hash = Map_bucket_from_hash(this, hash);
	u64 idx = 0; // arena index of the found element. 0 => inline entry or not found

	// they keys are set to null to mark it as a tombstone, and the values are set to null
	// just to prevent use after frees if users keep old pointers.
	Map_foreach(this, hash,
		if (cmp(entry.key, key) == 0) {
			// this is safe even if `entry.key` and `key` are the same pointer
			if (owned)
				map__free_entry(entry);

			if (prev_next != nullptr) {
				// overflow entry
				*prev_next = entry.next;

				// mark and count the tombstone
				p2entry->key = nullptr;
				p2entry->val = nullptr;

				idx = (u64) (p2entry - this->overflow); // this should never be negative
				this->o_tcnt++;
			}
			else

			// inline bucket entry
			if (entry.next != 0) {
				p2entry->key  = this->overflow[entry.next].key;
				p2entry->val  = this->overflow[entry.next].val;
				p2entry->next = this->overflow[entry.next].next;

				// mark and count the tombstone
				this->overflow[entry.next].key = nullptr;
				this->overflow[entry.next].val = nullptr;

				idx = entry.next;
				this->o_tcnt++;
			}
			else {
				// the bucket is now empty
				p2entry->key = nullptr;
				p2entry->val = nullptr;
				this->m_size--;

				// no tombstone
			}

			goto found;
		}
	);

	return false; // fallthrough means not found
found:
	if (idx != 0 && idx == this->o_size) {
		// if you deleted the last element, walk backwards and free elements
		// until the first one that isn't a tombstone.

		// the first iteration is definitely on a tombstone.
		do {
			this->o_tcnt--;
			idx--;
		} while (/*idx &&*/ this->overflow[idx].key == nullptr && this->o_tcnt != 0);

		// the "&& o_tcnt != 0" protects against it over-reading the start of the buffer.
		// you can't have more tombstones than you have slots being used.

		this->o_size = idx;
	}

	// if less than 25% of the slots have live entries, potentially GC, and then shrink overflow.
	// never shrink past the minimum though.
	// NOTE: it never needs to be shrunk more than once because the linear reclamation step that
	//       just ran does not effect the live count (`o_size - o_tcnt`).

	if (this->o_cap >= MAP_H_MIN_OCAP << 1 && this->o_size - this->o_tcnt < this->o_cap >> 2) {
		if unlikely (this->o_size + 2 >= this->o_cap >> 1 && !Map_gc(this))
			return true; // can't resize if GC failed

		// this is a shrink, so it will never fail
		Map_oresize(this, this->o_cap >> 1);
	}

	return true;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC bool Map_delete4(Map this, const char *key, map_hash_t hash, bool owned) {
	return Map__delete_by(this, key, (map_cmp_t) strcmp, hash, owned);
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC bool Map_delete_by5(Map this, const void *key, map_cmp_t cmp, map_hash_t hash, bool owned) {
	return Map__delete_by(this, key, cmp, hash, owned);
}

[[gnu::nonnull(1,2)]]
MAP_INLINE bool Map__set_raw_existing(
	Map this,
	const void *restrict key,
	const void *restrict val,
	bool owned,
	u64 bucket,
	MapEntry *p2entry
) {
	if (p2entry != nullptr) {
		if (owned)
			map__free_entry(*p2entry);

		p2entry->key = key;
		p2entry->val = val;
		return true;
	}

	this->o_size++;

	if (this->o_size == this->o_cap) {
		if unlikely (!Map_oresize(this, this->o_cap*3 >> 1)) {
			if (owned)
				map__free_kv(key, val);

			this->o_size--;
			return false;
		}
	}

	this->overflow[this->o_size] = (MapEntry) {
		.key  = key,
		.val  = val,
		.next = this->buckets[bucket].next
	};

	this->buckets[bucket].next = this->o_size;

	return false;
}

#define Map__set_raw_nonexisting(this, KEY, VAL, bucket) ({   \
	/* NOTE: this is for if the BUCKET entry doesn't exist */ \
	this->buckets[bucket].key = KEY;                          \
	this->buckets[bucket].val = VAL;                          \
	this->m_size++;                                           \
	return false;                                             \
})

[[gnu::nonnull(1,2)]]
MAP_STATIC bool Map_set_raw4(Map this, const char *restrict key, const char *restrict val, bool owned) {
	// returns whether or not the element already existed
	const u64 bucket = Map_bucket(this, key);

	if (this->buckets[bucket].key == nullptr)
		Map__set_raw_nonexisting(this, key, val, bucket);

	return Map__set_raw_existing(this, key, val, owned, bucket, Map_get_entry(this, key, bucket));
}

[[gnu::nonnull(1,2,4)]]
MAP_STATIC bool Map_set_raw_by6(
	Map this,
	const void *restrict key,
	const void *restrict val,
	map_cmp_t cmp,
	map_hash_t hash,
	bool owned
) {
 	const u64 bucket = Map_bucket_from_hash(this, hash);

	if (this->buckets[bucket].key == nullptr)
		Map__set_raw_nonexisting(this, key, val, bucket);

	return Map__set_raw_existing(
		this,
		key,
		val,
		owned,
		bucket,
		Map_get_entry_by(this, key, cmp, bucket)
	);
}

[[nodiscard, gnu::nonnull(1), gnu::malloc]]
MAP_INLINE Map Map__mresize_by(Map this, u64 m_cap, bool custom, map_cmp_t cmp, map_hashfn_t hashfn) {
	// if m_cap is a lot smaller than this->o_cap, you can end up with a really
	// large overflow arena since Map_set_raw only ever calls Map_oresize, and
	// will not recursively call Map_mresize. this doesn't need a view version
	// since it will never overwrite an existing entry unless the original map
	// is corrupted and has duplicate elements; if that is the case, the current
	// implementation will leak the memory from the old key/value, since that
	// is a better option than freeing a pointer that didn't come from malloc.

	if (m_cap == this->m_cap)
		// not actually a resize, so don't do anything
		return this;

	Map new_map = Map_create(m_cap, this->o_cap);
	if unlikely (new_map == nullptr)
		return this;

	Map_foreach(this,
		// ownership shouldn't matter
		if (custom)
			Map_set_raw_by(new_map, entry.key, entry.val, cmp, hashfn(entry.key), MAP_UNOWNED);
		else
			Map_set_raw(new_map, entry.key, entry.val, MAP_UNOWNED);
	);

	if unlikely (Map_count(new_map) != Map_count(this)) {
		// resize failed
		Map__destroy_shallow(new_map);
		return this;
	}

	Map__destroy_shallow(this);
	return Map_normalize(new_map);
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_STATIC Map Map_mresize(Map this, u64 m_cap) {
	return Map__mresize_by(this, m_cap, /*custom*/ false, /*cmp*/ nullptr, /*hashfn*/ nullptr);
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_STATIC Map Map_mresize_by(Map this, u64 m_cap, map_cmp_t cmp, map_hashfn_t hashfn) {
	return Map__mresize_by(this, m_cap, /*custom*/ true, cmp, hashfn);
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_INLINE Map Map_rehash(Map this) {
	const u64 m_cap = this->m_cap;
	this->m_cap = 0; // bypass the check for if it is an actual resize
	return Map_mresize(this, m_cap);
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_INLINE Map Map_rehash_by(Map this, map_cmp_t cmp, map_hashfn_t hashfn) {
	const u64 m_cap = this->m_cap;
	this->m_cap = 0; // bypass the check for if it is an actual resize
	return Map_mresize_by(this, m_cap, cmp, hashfn);
}

[[gnu::nonnull(1)]]
MAP_INLINE Map Map__set_grow_impl(Map this, bool custom, map_cmp_t cmp, map_hashfn_t hashfn) {
	/*
	pseudocode:
	if bucket utilization > 0.75
		resize map by 150%

	if last slot not live
		return

	range_switch (bucket utilization) {
		case [0.75, 1): unreachable
		case [0.6, 0.75):
			resize map by 150%
		case [0.45, 0.6):
			if overflow utilization > 75%
				resize map by 150%
			else
				run GC
		case [0.3, 0.45):
			if overflow utilization > 75%
				resize overflow by 200%
			else
				run GC
		case [0, 0.3):
			if overflow utilization > 75%
				if map has less than 4096 buckets and overflow is at least 8x the size of the map
					resize the map by 150%
				else
					resize the overflow by 300%
			else
				run GC
	}
	*/

	#define MRESIZE(this, new_cap) \
		(custom ? Map_mresize_by(this, new_cap, cmp, hashfn) : Map_mresize(this, new_cap))

	if (this->m_size > this->m_cap*3 >> 2)
		// size >= 75% of cap => buckets almost full
		return MRESIZE(this, this->m_cap*3 >> 1);

	if likely (this->o_size + 1 < this->o_cap)
		// buckets and overflow are both *not* almost full
		return this;

	// overflow filled the last slot
	// k = m_size / m_cap

	if (this->m_size*5 >= this->m_cap*3)
		// 0.6 <= k: resize the map
		return MRESIZE(this, this->m_cap*3 >> 1);

	// NOTE: 5 | 20 and 3 | 9, so the compiler can reuse previous calculations
	if (this->m_size*20 >= this->m_cap*9) {
		// 0.45 <= k < 0.6: if o_tcnt >= o_cap/4, GC, else resize the map
		if (this->o_tcnt < this->o_cap >> 2) // if overflow utilization > 75%
			return MRESIZE(this, this->m_cap*3 >> 1);

		Map_gc(this);
		return this;
	}

	if (this->m_size*10 >= this->m_cap*3) {
		// 0.3 <= k < 0.45 : if o_tcnt >= o_cap/4, GC, else 2x the overflow
		// probably the overflow just wasn't large enough for the map
		if (this->o_tcnt < this->o_cap >> 2)
			Map_oresize(this, this->o_cap << 1);
		else
			Map_gc(this);

		return this;
	}

	// 0 <= k < 0.3 : if o_tcnt >= o_cap/4, GC, else { either 1.5x the map or 3x the overflow }

	// this is the pathological case. optimally, this should never happen. the hash function
	// used may or may not be good a protecting from hash flooding. Or maybe, the map was reserved
	// with significantly less overflow slots than buckets.

	if (this->o_tcnt >= this->o_cap >> 2)
		Map_gc(this);
	else if (this->m_cap < 0x1000 && this->m_cap < this->o_cap >> 3)
		// idk, maybe the hash collisions are only because of a bad prime or something.
		this = MRESIZE(this, this->m_cap*3 >> 1);
	else
		Map_oresize(this, this->o_cap*3);

	return this;

	#undef MRESIZE
}

[[gnu::nonnull]]
MAP_INLINE Map Map__set_grow(Map this) {
	return Map__set_grow_impl(this, /*custom*/ false, /*cmp*/ nullptr, /*hashfn*/ nullptr);
}

[[gnu::nonnull]]
MAP_INLINE Map Map__set_grow_by(Map this, map_cmp_t cmp, map_hashfn_t hashfn) {
	return Map__set_grow_impl(this, /*custom*/ true, cmp, hashfn);
}

[[nodiscard, gnu::nonnull(1,2)]]
MAP_STATIC Map Map_set4(Map this, const char *restrict key, const char *restrict val, bool owned) {
	if (Map_set_raw(this, key, val, owned))
		return this;

	return Map__set_grow(this);
}

[[nodiscard, gnu::nonnull(1,2)]]
MAP_STATIC Map Map_vset4(Map this, const vstring *restrict key, const void *restrict val, bool owned) {
	if (Map_set_raw_by(this, key, val, vstring_cmp, jhash(key->ptr, key->len), owned))
		return this;

	return Map__set_grow_by(this, vstring_cmp, vstring_hash);
}

[[nodiscard, maybe_unused, gnu::nonnull(1,2,4,6)]]
MAP_STATIC Map Map_set_by7(
	Map this,
	const void *restrict key,
	const void *restrict val,
	map_cmp_t cmp,
	map_hash_t hash,
	map_hashfn_t hashfn,
	bool owned
) {
	if (Map_set_raw_by(this, key, val, cmp, hash, owned))
		return this;

	return Map__set_grow_by(this, cmp, hashfn);
}

[[nodiscard, maybe_unused, gnu::nonnull]]
MAP_STATIC Map Map_vsetall(Map this, MapEntryVList entries) {
	// it stops at the first entry it can't insert, rather than just skipping that entry.
	// the value pointers can be null, in which case, they are not touched
	// when inserting an entry with a duplicate key, it will not free the `.ptr` in the
	// key or value. It will, however free the `vstring *` pointer itself. So make sure
	// that either the underlying character arrays are owned somewhere else, or that
	// there are no duplicate keys in the entries list.

	vstring *pkey, *pval;

	while (entries.count --> 0) {
		// NOTE: these cannot be a single `malloc(2*sizeof(vstring))`
		pkey = malloc(sizeof(vstring));
		if unlikely (pkey == nullptr)
			return this;

		pval = malloc(sizeof(vstring));

		if unlikely (pval == nullptr) {
			free(pkey);
			return this;
		}

		*pkey = entries.array->key;
		*pval = entries.array->val;

		this = Map_vset(this, pkey, pval, MAP_OWNED);
		entries.array++;
	}

	return this;
}

[[nodiscard, maybe_unused, gnu::nonnull]]
MAP_STATIC Map Map_csetall3(Map this, MapEntryCList entries, bool owned) {
	// similar to `Map_setall`, except for it doesn't have to take ownership. To
	// accomplish that, the list has to be C strings so it doesn't have to memcpy them.
	// it can still take ownership though.

	while (entries.count --> 0) {
		this = Map_set(this, entries.array->key, entries.array->val, owned);
		entries.array++;
	}

	return this;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_cgetall(ConstMap this, const char *keys[], u64 count) {
	// update the keys array to have the values instead.

	while (count --> 0) {
		*keys = Map_get(this, *keys);
		keys++;
	}
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_vgetall(ConstMap this, vstring_list keys) {
	// update the keys array to have the values instead.

	while (keys.count --> 0) {
		keys.array[0] = *(vstring *) Map_get_by(
			this,
			keys.array,
			vstring_cmp,
			jhash(keys.array->ptr, keys.array->len)
		);

		keys.array++;
	}
}

[[maybe_unused, gnu::nonnull, gnu::pure]]
MAP_STATIC MapIter Map_iter(ConstMap this) {
	// find the first bucket that has at least one entry. The argument being `ConstMap`
	// just means that this function will not mutate, resize, or invalidate the map.
	// But the iterator returned can still be used to mutate the map. Since the iterator
	// type does not have a `const` on it, you could use this to mutate a constant map,
	// but if that is your goal, just cast it to `Map` yourself. Even if it is a mutable
	// map, probably don't mutate too much, since Map_mresize will invalidate the iterator.

	for (u64 i = 0; i < this->m_cap; i++)
		if (this->buckets[i].key != nullptr) return (MapIter) {
			.item   = (MapEntry *) this->buckets + i,
			.bucket = i
		};

	return (MapIter) {
		.item   = nullptr,
		.bucket = 0, // bucket doesn't matter
	};
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC MapIter Map_next(ConstMap this, MapIter iter) {
	// return the next element after the current one.
	if unlikely (iter.item == nullptr)
		// iterating a finished iterator is strange
		return iter;

	if (iter.item->next != 0) {
		iter.item = this->overflow + iter.item->next;
		return iter;
	}

	for (u64 i = 1 + iter.bucket; i < this->m_cap; i++)
		if (this->buckets[i].key != nullptr) return (MapIter) {
			.item   = (MapEntry *) this->buckets + i,
			.bucket = i
		};

	return (MapIter) {
		.item   = nullptr,
		.bucket = 0, // bucket doesn't matter
	};
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_clear2(Map this, bool owned) {
	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	if (owned) Map_foreach(this,
		map__free_entry(entry);

		#ifdef __SSE2__
			_mm_storeu_si128((__m128i *) p2entry, (__m128i) {0});
		#else
			p2entry->key = nullptr;
			p2entry->val = nullptr;
		#endif

		p2entry->next = 0;
	);

	// this is similar to the block in `Map_create2`, but with the AVX2 branch removed, and `this` instead of `map`.
	#ifdef __SSE2__
		*(__m128i *) this = (__m128i) {0};
		((u64 *) this)[2] = 0;
	#else
		this->m_size = 0;
		this->o_size = 0;
		this->o_tcnt = 0;
	#endif

	#pragma GCC diagnostic pop
}

[[nodiscard, maybe_unused, gnu::nonnull]]
MAP_STATIC Map Map_copy2(ConstMap this, bool owned) {
	Map new_map = Map_create(this->m_cap, this->o_cap);
	if unlikely (new_map == nullptr)
		return nullptr;

	if (owned)
		Map_foreach(this,
			entry.key = strdup(entry.key);
			entry.val = strdup(entry.val);

			if unlikely (entry.key == nullptr || entry.val == nullptr) {
				// assume the rest of the things will all be null as well.
				// don't copy the rest of the elements.
				map__free_entry(entry);
				return new_map;
			}

			Map_set_raw(new_map, entry.key, entry.val, MAP_OWNED)
		);
	else {
		// neither of the maps owns the strings, so just copy all the pointers over.
		MapEntry *const overflow = new_map->overflow;

		memcpy(new_map, this, sizeof(struct MapImpl) + sizeof(MapEntry)*this->m_cap);
		memcpy(overflow, this->overflow, sizeof(MapEntry)*this->o_cap);

		new_map->overflow = overflow;
	}

	return new_map;
}

[[nodiscard, maybe_unused, gnu::nonnull(1)]]
MAP_STATIC Map Map_merge4(Map this, Map other, bool owned1, bool owned2) {
	// same semantics as `dict.update` in Python:
	//     if this has "x" => "a", and other has "x" => "b", other wins.
	// `other` is not destroyed. other=nullptr means add nothing. this=nullptr creates a new map
	// `other` could be `ConstMap` in all cases except for if !owned1 && owned2

	// case 1: map1 owned=false, map2 owned=false:
		// neither map owns the strings
		// shallow copies pointers
		// Map_merge(map1, map2, false)
	// case 2: map1 owned=true , map2 owned=false:
		// the old map doesn't own its keys, so strdup the pointers
		// Map_merge(map1, map2, true, false)
	// case 3: map1 owned=false, map2 owned=true:
		// if interpreted exactly, this would always cause memory leaks. instead it is a special case:
		// both maps own its keys and values, but ownership is transferred from map 2 to map 1.
		// similar to case 1, except existing keys and values will be freed, whereas they won't in case 1.
		// shallow copies pointers
		// Map_merge(map1, map2, false, true)
	// case 4: map1 owned=true , map2 owned=true:
		// both maps own their values, and ownership is not being transferred
		// makes full string copies
		// Map_merge(map1, map2, true, true)

	if (other == this || other == nullptr)
		return this;

	Map_foreach(other,
		if (owned1) {
			// update local copy
			entry.key = strdup(entry.key);
			entry.val = strdup(entry.val);
		}

		this = Map_set(this, entry.key, entry.val, owned1 || owned2);
	);

	if (!owned1 && owned2)
		// in the case where both maps are owned, but ownership is being transferred,
		// clear the other map to prevent use after frees in case `this` changes.
		Map_clear(other, MAP_UNOWNED);

	return this;
}

[[gnu::nonnull, gnu::pure]]
MAP_INLINE u64 map__json_strlen(const char *s) {
	static constexpr u8 map__json_width_tbl[256] = {
	//	0  1  2  3  4  5  6  7  8  9  10 11 12 13 14 15
		6, 6, 6, 6, 6, 6, 6, 6, 2, 2, 2, 6, 2, 2, 6, 6, //  16
		6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, //  32
		1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, //  48
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, //  64
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, //  80
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 1, 1, 1, //  96
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 112
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 128
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 144
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 160
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 176
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 192
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 208
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 224
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 240
		1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, // 256
	};

	// total bytes needed to encode `s` as a JSON string body
	u64 len = 0;

	for (const u8 *p = (const u8 *) s; *p; p++)
		len += map__json_width_tbl[*p];

	return len;
}

[[gnu::nonnull]]
MAP_INLINE char *map__json_stpcpy(char *dst, const char *src) {
	static constexpr char hex[] = "0123456789abcdef";

	for (const u8 *p = (const u8 *) src; *p; p++)
		switch (*p) {
			case '\\': *(u16 *) dst = MC16('\\\\'); dst += 2; break;
			case '"':  *(u16 *) dst = MC16('\\"');  dst += 2; break;
			case '\b': *(u16 *) dst = MC16('\\b');  dst += 2; break;
			case '\f': *(u16 *) dst = MC16('\\f');  dst += 2; break;
			case '\n': *(u16 *) dst = MC16('\\n');  dst += 2; break;
			case '\r': *(u16 *) dst = MC16('\\r');  dst += 2; break;
			case '\t': *(u16 *) dst = MC16('\\t');  dst += 2; break;
			default:
				if unlikely (*p < u8' ') {
					// most characters should be normal
					*(u32 *) dst = MC32('\\u00');
					dst += 4;
					*dst++ = hex[*p >> 4];
					*dst++ = hex[*p & 0xF];
				} else
					*dst++ = (char) *p;
		}

	return dst;
}

[[nodiscard, maybe_unused, gnu::nonnull, gnu::malloc]]
MAP_STATIC char *Map_tojson(ConstMap this, const u8 mode) {
	// PACK -> {"a":"b","c":"d"}
	// LINE -> {"a": "b", "c": "d"}
	// FULL -> {\n\t"a": "b",\n\t"c": "d"\n}

	if unlikely (mode != MAP_JSON_MODE_PACK
		&& mode != MAP_JSON_MODE_LINE
		&& mode != MAP_JSON_MODE_FULL
	) return nullptr;

	u64 size = Map_count(this);

	if (size == 0) {
		char *const json = malloc(4);
		if (json != nullptr)
			memcpy(json, (char[]) {'{', '}', 0, 0}, 4);
		return json;
	}

	// stuff that is per kv pair
	size *= (u64) (
		(mode != MAP_JSON_MODE_PACK)*2 // leading '\t'/' ', space after colon
		+ 3*2                          // strlen("'':") + strlen("'',")
		+ (mode == MAP_JSON_MODE_FULL) // trailing newline
	);

	Map_foreach(this,
		size += map__json_strlen(entry.key) + map__json_strlen(entry.val);
	);

	// stuff that is only once
	// mode=PACK wastes one byte, and mode=LINE wastes two bytes
	size += 2; // '{\n' for mode=FULL. the extra 1-2 byte savings in the other cases is not worth the logic.

	char *const json = malloc(size + 1); // +1 for the null terminator
	if unlikely (json == nullptr)
		return nullptr;

	char *cur = json + (mode != MAP_JSON_MODE_LINE);
	if (mode == MAP_JSON_MODE_FULL)
		*cur++ = '\n';

	Map_foreach(this,
		if (mode != MAP_JSON_MODE_PACK)
			*cur++ = mode == MAP_JSON_MODE_LINE ? ' ' : '\t';

		*cur++ = '"';
		cur     = map__json_stpcpy(cur, entry.key);
		*cur++ = '"';
		*cur++ = ':';

		if (mode != MAP_JSON_MODE_PACK)
			*cur++ = ' ';

		*cur++ = '"';
		cur    = map__json_stpcpy(cur, entry.val);
		*cur++ = '"';
		*cur++ = ',';

		if (mode == MAP_JSON_MODE_FULL)
			*cur++ = '\n';
	);

	// fix up the trailing separator left by the last entry into the closing brace
	if (mode == MAP_JSON_MODE_FULL)
		cur[-2] = '\n'; // ",\n" -> "\n}"

	*json   = '{'; // do this now because it would get overwritten with mode=LINE.
	cur[-1] = '}'; // remove the trailing comma
	*cur    = '\0';
	return json;
}

#ifndef MAP_NODEFINE_CLEANUP_ARRAY
[[gnu::nonnull]]
MAP_INLINE void cleanup_array(const void *p) {
	free(* (void **) p);
}
#endif

#ifndef MAP_H_NO_FUN
[[gnu::nonnull]]
MAP_STATIC u64 map_dedup_shuffle_det(const char *strings[], const u64 count) {
	// deterministic in that passing the same list in multiple times will give the same
	// shuffled list, so long as the hash key doesn't change between calls. If you reorder
	// the elements in the input, the change in the output will only be localized. calling
	// this multiple times consecutively will only converge on the same output if there are
	// never more than 3 strings that end up in the same bucket.

	AF_ViewMap const set = Map_create(count*3 >> 1);
	u64 i;

	for (i = 0; i < count; i++)
		Map_set_raw(set, strings[i], /*no value*/ nullptr, MAP_UNOWNED);

	i = 0;
	Map_foreach(set,
		strings[i++] = entry.key
	);

	return i;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC u64 map_dedup_shuffle(const char *strings[], const u64 count) {
	// funky function to shuffle an array of strings using a hash map,
	// and also deduplicates the list at the same time.
	// returns the new list length.

	// this is a "stable" shuffling function, which I define to mean if you reorder the inputs,
	// then you will get, at most, local changes to the output. And if you insert a new element,
	// or delete an element, it will not change the ordering of the other elements (unless it
	// puts it over the next boundary so the bucket count changes). "local changes" means that
	// you might get a few consecutive output elements reordered, but the overall structure of
	// the output will not change.

	// NOTE: if you ignore a nonzero return value, the array will
	//       most likely have the wrong strings duplicated.

	// this is not a exactly helper function. it is its own thing.
	// not reentrant. if you want that, then wrap the deterministic version yourself.

	static map_hash_t key = 0; // this doesn't need the `= 0` for correctness.
	static bool key_initialized = false;

	if (!key_initialized) {
		// delayed initialization
		key_initialized = true;
		key = map_key();
	}

	// doing `key++` will also probably work fine, but this is barely slower, so idc.
	#ifdef MAP_H_HASH128
		key += map__u128c(9e3779b97f4a7c15,bf58476d1ce4e5b9);
	#else
		key += 0x9e3779b97f4a7c15llu;
	#endif

	const map_hash_t old_key = map_key();

	map_key(key);
	const u64 new_len = map_dedup_shuffle_det(strings, count);
	map_key(old_key);

	return new_len;
}
#endif // #ifndef MAP_H_NO_FUN

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void *Map_tovstring_owned(Map this) {
	// the exiting map is assumed to contain C strings as opposed to random structs.
	// the keys and values in the map are assumed to all be non-null
	// ignore the return value, it is just there for consistency.

	// NOTE: the following notes are not specifically for this function. they are about using
	//       structs as keys and vals in general with the `_by` variant functions

	// NOTE: if the map was originally owning, you need to make sure that you delete the pointers
	//       separately from what `Map_delete_by` deletes; it does not know what kind of offsets
	//       and fields are in the struct, so it only frees the struct itself.
	// NOTE: this assumes that changing to string views does not effect the buckets that each
	//       element lands in, which implies the comparison function must just run strcmp on the
	//       pointers. A small caveat is that this only works because the strings that already
	//       existed in the map were already null-terminated C strings, so strcmp actually works.
	//       you may more realistically want to compare lengths and use strncmp if they match.
	// NOTE: none of the code currently cares about whether the comparison function returns +1 or
	//       -1, or whatever else for different values, only that it returns 0 when they are the
	//       same and something nonzero (i32) when they aren't.
	// NOTE: they key and val fields don't necessarily need to be the same type, the calling code
	//       just has to be able to figure out what it is

	Map_foreach(this,
		vstring *tmp;

		// viewify the key
		tmp = malloc(sizeof(*tmp));
		tmp->ptr = (char *) entry.key;
		tmp->len = strlen(entry.key);
		entry.key = (char *) tmp;

		// viewify the value
		tmp = malloc(sizeof(*tmp));
		tmp->ptr = (char *) entry.val;
		tmp->len = strlen(entry.val);

		entry.val = (char *) tmp;
	);

	return nullptr;
}

[[nodiscard, maybe_unused, gnu::nonnull]]
MAP_STATIC void *Map_tovstring_unowned(Map this) {
	// the exiting map is assumed to contain C strings as opposed to random structs.
	// the keys and values in the map are assumed to all be non-null
	// same notes as in the owned version

	// NOTE: if you want to be sure that this worked, check if the return value is
	//       null. If it is null, it did not work, otherwise it fully worked.

	vstring *const buf = malloc(2 * Map_count(this) * sizeof(vstring));
	if unlikely (buf == nullptr)
		return nullptr;

	vstring *tmp = buf;

	Map_foreach(this,
		// viewify the key
		tmp->ptr  = (char *) entry.key;
		tmp->len  = strlen(entry.key);
		entry.key = (char *) tmp++;

		// viewify the value
		tmp->ptr  = (char *) entry.val;
		tmp->len  = strlen(entry.val);
		entry.val = (char *) tmp++;
	);

	return buf;
}

// destroy private macros
#undef MAP_SIZE_SMALLEST // pass 0 to Map_create for the same effect as as this
#undef Map__set_raw_nonexisting
#undef Map__destroy_shallow
#undef map__alloc
#undef map__free
#undef map__free_kv
#undef map__free_entry

// jhash stuff
#undef jhash_mulhi64
#undef jhash_bswap64
#undef map__u128c

#endif // MAP_H_IMPL
