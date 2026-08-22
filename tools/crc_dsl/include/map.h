// SPDX-License-Identifier: MIT

/*
	map.h v0.9.0
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

	resizable and cache-friendly C-string => C-string GNU C23 single-header hashmap API
	(it can be used for stuff that aren't C strings, but that is not the core usage)

	to compile separately:
		gcc -c -x c -DMAP_H_BUILD map.h -o map.o

		#define MAP_H_SEPARATE
		#include "map.h"

	to include directly:
		#define MAP_H_IMPL
		#include "map.h"

	NOTES:
	1. The following helper macros exist for public use:
		- VA_IF: for arity-based dispatch: #define f(x, y...) VA_IF(f2(x, y), f1(x), y)
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
		- map_key([val]): with an argument given, it sets the map key and returns nothing. with
		  no argument given, it returns the map key.
		- Map_dump(map[, indent[, format]]) -> Map: log out the map. if format == 0, use JSON,
		  otherwise use basic formatting.
		- Map_transfer(dst, src[, owned]): transfer key-value pairs from the src map to the dst
		  map. If owned, the old map is cleared to prevent potential double frees.
		- jhash(in, len[, key]): the underlying hash function below `map_hash`, usable for types
		  other than C strings. The key defaults to `map_key()`
		- map_stpcpy(dst, src): same as stpcpy. (if stpcpy is available, it will just call it).
	2. the following types exist for public use:
		- u8/i8, u16/i16, u32/i32, u64/i64, u128/i128
		- vstring: fat string pointer (string view, typically non-owning)
		- vstring_list: fat pointer to vstring. not used internally
		- map_hash_t: either u64 or u128, depending on the hash mode
		- map_cmp_t: a function that takes two `const void` pointers and returns `i32`
		- MapEntry
		- Map / ConstMap
		- MapEntryVView / MapEntryCView: key/val pair of either vstring or char *
		- MapEntryVList / MapEntryCList: fat pointer to the corresponding view type.
		- MapIter: map iterator object. use this if Map_foreach generates too much code
		- AF_Map / AF_ViewMap: auto-freeing variants of `Map`.
	3. function naming convention:
		- map_x     : "static method", no live Map instance involved
		- Map_x     : "instance method", takes `Map this` as first arg. 
		              Map_create is the only exception (the constructor).
		- Map__x    : unsafe to call directly; internal use only.
		- Map_x_ref : same as Map_x, but takes `Map *pthis` and doesn't return the new `this`.
		- Map_xN    : an arity-dispatch variant (i.e. Map_delete4, Map_set3).
		              not recommended for use, but still technically part of the public API.
	4. Before including, define `MAP_H_IMPL` to pull in the actual implementation. To compile this
	   separately as an object or DLL and link later, define `MAP_H_SEPARATE`; this will remove
	   `static` from all function declarations and definitions. `MAP_H_BUILD` defines both
	   `MAP_H_IMPL` and `MAP_H_SEPARATE`. define `MAP_H_NO_FUN` if you hate fun so it will not
	   include the extra fun stuff like `map_dedup_shuffle`. define `MAP_H_DEFAULT_OWNED` or
	   `MAP_H_DEFAULT_UNOWNED` to specify the default ownership model (owned is the default
	   default). define MAP_H_HASH128 or MAP_H_HASH64 to select jhash128 or jhash64. jhash64 is
	   the default. define MAP_H_MIN_OCAP to set the minimum overflow arena size (default is 4).
	5. the `setall` functions are really only for if you are creating a map from nothing *and*
	   it is easier to create a list and call one function instead of doing some kind of iterator
	   and calling `Map_set` for each entry object.
	6. the keys and values in the map should either all be owned by the map, or all non-owning
	   views. If they aren't all the same, you have to figure out which is which and call `Map_set`
	   with the correct `owning` value for each one; it will cause heap corruption if you get it
	   wrong, so probably just don't do that.
	7. `vstring` is assumed to be a view into an externally-allocated string, so from the point of
	   view of the map, there is nothing to take ownership of. So MapEntryVList is just a list of
	   views. MapEntryCList is the version that has C strings.
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
	16. See each specific function for comments on its specific API (only for some functions)

	this library will work with all GCC warning flags, except for the following:
		-Wcast-qual    (casting away const)
		-Wuseless-cast (casting away const in macros is sometimes useless)
		-Wc++-compat
		-Wpedantic
		-Wtraditional
		-Wtraditional-conversion
		-Wsystem-headers (probably this one depends)

	Cache lines are assumed to be 64 bytes long.

	with MAP_H_HASH128, if using -nostdlib and linking manually, you must pass -lgcc and give
	ld the path to it, since for whatever reason, it doesn't know it by default.
*/

#ifndef MAP_H_PROTO
#define MAP_H_PROTO

#define MAP_VMAJOR 0llu
#define MAP_VMINOR 9llu
#define MAP_VMICRO 0llu
#define MAP_VERSION ((MAP_VMAJOR << 16) | (MAP_VMINOR << 8) | MAP_VMICRO)

#include <stdlib.h>
#include <string.h>
#include "int-types.h" // u8, u32, u64, u128

#if defined(__AVX2__) || defined(__SSE2__)
	#include <immintrin.h>
#endif

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

#include "va-if.h"

#ifndef nullstr
	// so you can do `printf("%s\n", Map_get(map, key) ?: nullstr);` if you use `-Wall`
	#define nullstr "(null)"
#endif

typedef struct {
	union {
		char *ptr; // memory ownership is tied to the object
		u64 ofs;   // memory ownership is independent of the object
		//            (i.e. index into dynamically allocated buffer)
	};

	u64 len;
} vstring;

typedef struct { // not used internally
	vstring *array;
	u64 count;
} vstring_list;

typedef i32 (*map_cmp_t)(const void *, const void *);

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

#define _jhash3(in, len, key) _jhash(in, len, key)
#define _jhash2(in, len)      _jhash(in, len, map_key())

#define jhash(in, len, key...) VA_IF(_jhash3(in, len, key), _jhash2(in, len), key)

// NOTE: index 0 will be invalid, indicating there is no next
// String -> String hash map
typedef struct {
	const char *key, *val;
	u64 next; // index into arena
} MapEntry;

// MAPIMPL_NON_VA_BUCKETS must solve: (48 + 24*n) % 64 = 0 where n <= 11
//  - 48 == offsetof(struct MapImpl, buckets)
//  - 24 == sizeof(MapEntry)
//  - 64 == alignof(struct MapImpl)
//  - 11 == MAP_SIZE_SMALLEST
#define MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS 6

// if I use [[gnu::aligned(64)]], then the fuckass compiler will add 16 extra padding bytes,
// so I have to inline some of the buckets to make it work. It has to inline the exact amount
// to where sizeof(struct MapImpl) % 64 == 0, but it also has to be less than MAP_SIZE_SMALLEST + 1,
// because if you inline more buckets than the minimum amount of buckets, you are wasting memory.
// fuck you GCC. shit ass garbage compiler and bullshit language. NASM would never have this issue.
// NASM always lets me do exactly what I want to do without a problem. ILY NASM <3.
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
	// mid iteration. probably just don't do that unless you need to.
	MapEntry *item;
	u64 bucket;
} MapIter;

// you don't need C++ for RAII
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
		__builtin_unreachable();      \
	if (t_->m_size > t_->m_cap)        \
		__builtin_unreachable();        \
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
	while (entry.key != nullptr) {                           \
		BLOCK;                                               \
		prev_next = &p2entry->next;                          \
		p2entry   = (THIS)->overflow + entry.next;           \
		entry     = *p2entry;                                \
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
#define Map_normalize(this) ({        \
	const Map t_ = this;               \
	_Pragma("GCC diagnostic push")                          \
	_Pragma("GCC diagnostic ignored \"-Wnull-dereference\"") \
	if (t_->o_size + 1 >= t_->o_cap)      \
		Map_oresize(t_, t_->o_cap*3 >> 1); \
	_Pragma("GCC diagnostic pop")           \
	t_;                                      \
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

// the shitass dumb fuck compiler counts the number of arguments in the preprocessor
// before it actually expands out the arguments, so it can, and does, count wrong.
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

// pass extra `0` to satisfy the retarded compiler's dumb shit nonsense. imagine how
// crazy it would be if they wrote the compiler in a way that isn't brain-dead retarded.
// like holy fuck it isn't 1954 anymore, we are allowed to have nice things.
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

// basically `Map_vsetall`, but where the inputs are either constants or serparate variables.
// NOTE: if you get weird errors about the number of arguments, probably you have a mismatch
//       between `count`, and the number of variable arguments.
#define map_with(count, owned, x...) ({   \
	Map map_ = Map_create(count*3 >> 1);  \
	if (map_ != nullptr) {                \
		Map__with##count(map_, owned, x); \
	}                                     \
	Map_normalize(map_);                  \
	map_;                                 \
})

#define Map_dump3(this, indent, format) ({          \
	const typeof(this) t_ = this;                   \
	if (format == 0) {                              \
		char *const json = Map_tojson(t_, indent);  \
		puts(json);                                 \
		free(json);                                 \
	}                                               \
	else /* basically just pass anything else */    \
		Map_foreach(t_, printf("\"%s\" = \"%s\"\n", \
			entry.key, entry.val                    \
		)); /* `indent` does nothing here */        \
	t_;                                             \
})

#define Map_dump2(this, indent) Map_dump3(this, indent, 0)
#define Map_dump1(this) Map_dump2(this, '\t')

#define Map_dump2_3(this, indent, format...) \
	VA_IF(Map_dump3(this, indent, format), Map_dump2(this, indent), format)
#define Map_dump(this, indent...) VA_IF(Map_dump2_3(this, indent), Map_dump1(this), indent)

#define Map_has(...)    (Map_get_entry(__VA_ARGS__) != nullptr)
#define Map_has_by(...) (Map_get_entry_by(__VA_ARGS__) != nullptr)

[[gnu::error("comptime error")]]
void comptime_error(...);

[[gnu::error("use `Map_destroy_ref(&map)`.")]]
Map Map_destroy(Map this);

#define map_key0() map_h_jhash_key
#define map_key(key...) VA_IF(map_key1(key), map_key0(), key)

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
#define Map_set_raw_by(this, key, val, cmp, hash, owned...) \
	VA_IF(Map_set_raw_by6(this, key, val, cmp, hash, owned), Map_set_raw_by5(this, key, val, cmp, hash), owned)

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
#define Map_set(this, key, val, owned...) \
	VA_IF(Map_set4(this, key, val, owned), Map_set3(this, key, val), owned)

#define Map_set_ref4(pthis, key, val, owned) ({ \
	Map *const p = pthis;                       \
	*p = Map_set(*p, key, val, owned);          \
	(void) 0;                                   \
})
#define Map_set_ref3(pthis, key, val) Map_set_ref4(pthis, key, val, MAP_DEF_OWNED)
#define Map_set_ref(pthis, key, val, owned...) \
	VA_IF(Map_set_ref4(pthis, key, val, owned), Map_set_ref3(pthis, key, val), owned)

#define Map_set_by5(this, key, val, cmp, hash) Map_set_by6(this, key, val, cmp, hash, MAP_DEF_OWNED)
#define Map_set_by(this, key, val, cmp, hash, owned...) \
	VA_IF(Map_set_by6(this, key, val, cmp, hash, owned), Map_set_by5(this, key, val, cmp, hash), owned)

#define Map_set_by_ref6(pthis, key, val, cmp, hash, owned) ({ \
	Map *const p = pthis;                                     \
	*p = Map_set_by(*p, key, val, cmp, hash, owned);          \
	(void) 0;                                                 \
})
#define Map_set_by_ref5(pthis, key, val, cmp, hash) Map_set_by_ref6(pthis, key, val, cmp, hash, MAP_DEF_OWNED)
#define Map_set_by_ref(pthis, key, val, cmp, hash, owned...) \
	VA_IF(Map_set_by_ref6(pthis, key, val, cmp, hash, owned), Map_set_by_ref5(pthis, key, val, cmp, hash), owned)

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
#define Map_csetall_ref2(pthis, entries) Map_csetall_ref3(this, entries, MAP_DEF_OWNED)
#define Map_csetall_ref(this, entries, owned...) \
	VA_IF(Map_csetall_ref3(this, entries, owned), Map_csetall_ref2(this, entries), owned)

#define Map_mresize_ref(pthis, m_cap) ({ \
	Map *const p = pthis;                \
	*p = Map_mresize(*p, m_cap);         \
	(void) 0;                            \
})

#define Map_delete3(this, key, h) Map_delete4(this, key, h, MAP_DEF_OWNED)
#define Map_delete3_4(this, key, h, owned...) \
	VA_IF(Map_delete4(this, key, h, owned), Map_delete3(this, key, h), owned)
#define Map_delete2(this, key) Map_delete3(this, key, map_hash(key))
#define Map_delete(this, key, h...) VA_IF(Map_delete3_4(this, key, h), Map_delete2(this, key), h)

#define Map_delete_by4(this, key, cmp, hash) Map_delete_by5(this, key, cmp, hash, MAP_DEF_OWNED)
#define Map_delete_by(this, key, cmp, hash, owned...) \
	VA_IF(Map_delete_by5(this, key, cmp, hash, owned), Map_delete_by4(this, key, cmp, hash), owned)

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
[[gnu::nonnull, gnu::pure]] MAP_INLINE map_hash_t map_hash(const char *key);
MAP_INLINE void map_key1(map_hash_t key);
[[nodiscard, gnu::malloc]] MAP_STATIC Map Map_create2(u64 m_cap, u64 o_cap);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_destroy_ref1(Map *pthis);
[[maybe_unused, gnu::nonnull]] MAP_INLINE void Map_destroy_shallow_ref(const Map *pthis);
[[gnu::nonnull]] MAP_STATIC bool Map_gc(Map this);
[[gnu::nonnull]] MAP_STATIC bool Map_oresize2(Map this, u64 o_cap);
[[gnu::nonnull, gnu::pure]] MAP_STATIC MapEntry *Map_get_entry3(ConstMap this, const char *key, map_hash_t hash);
[[gnu::nonnull, gnu::pure]] MAP_STATIC void *Map_get_entry_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash);
[[gnu::nonnull, gnu::pure]] MAP_INLINE char *Map_get3(ConstMap this, const char *key, map_hash_t hash);
[[maybe_unused, gnu::nonnull]] MAP_STATIC bool Map_delete4(Map this, const char *key, u64 hash, bool owned);
[[maybe_unused, gnu::nonnull]] MAP_STATIC bool Map_delete_by5(Map this, const void *key, map_cmp_t cmp, u64 hash, bool owned);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_STATIC Map Map_mresize(Map this, u64 m_cap);
[[nodiscard, gnu::nonnull, gnu::malloc]] MAP_INLINE Map Map_rehash(Map this);
[[gnu::nonnull(1,2)]] MAP_STATIC bool Map_set_raw4(Map this, const char *restrict key, const char *restrict val, bool owned);
[[gnu::nonnull(1,2,4)]] MAP_STATIC bool Map_set_raw_by6(Map this, const void *restrict key, const void *restrict val, map_cmp_t cmp, map_hash_t hash, bool owned);
[[nodiscard, gnu::nonnull(1,2)]] MAP_STATIC Map Map_set4(Map this, const char *restrict key, const char *restrict val, bool owned);
[[nodiscard, gnu::nonnull(1,2,4)]] MAP_STATIC Map Map_set_by6(Map this, const void *restrict key, const void *restrict val, map_cmp_t cmp, map_hash_t hash, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_vsetall(Map this, MapEntryVList entries);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_csetall3(Map this, MapEntryCList entries, bool owned);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_getall(ConstMap this, const char *keys[], u64 count);
[[maybe_unused, gnu::nonnull]] MAP_STATIC MapIter Map_iter(ConstMap this);
[[maybe_unused, gnu::nonnull]] MAP_STATIC MapIter Map_next(ConstMap this, MapIter iter);
[[maybe_unused, gnu::nonnull]] MAP_STATIC void Map_clear2(Map this, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull]] MAP_STATIC Map Map_copy2(ConstMap this, bool owned);
[[nodiscard, maybe_unused, gnu::nonnull(1)]] MAP_STATIC Map Map_merge4(Map this, Map other, bool owned1, bool owned2);
[[nodiscard, maybe_unused, gnu::nonnull, gnu::malloc]] MAP_STATIC char *Map_tojson(ConstMap this, char indent);
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
	// it picks the nearest valid siize to the value given.

	// prime nearest to 2 * 1.5^(i + 6), except the first one is 11 and not 17, and the last
	// one is 2^32 - 5. also the first 6 are slightly faster so it could take 6 elements
	// instead of 7 to get to 173. (173/11)^(1/5) ~~ 1.735 instead of 1.5

	if (size > (1llu << 32) - 5)
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

#define jhash_bswap128(x) ( (u128) jhash_bswap64(x) << 64 | jhash_bswap64((x) >> 64) )

// this is an approximation. multiplication with `unsigned _BitInt(256)` is slow as shit, and I also don't
// need the entire result, so I will just not do that.
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
	// look at the 64-bit variant for explanitory comments.
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
			default: __builtin_unreachable(); break;
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

[[gnu::nonnull, gnu::pure]]
MAP_INLINE map_hash_t map_hash(const char *str) {
	return jhash128(str, strlen(str), map_key());
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
			default: __builtin_unreachable(); break;
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

[[gnu::nonnull, gnu::pure]]
MAP_INLINE map_hash_t map_hash(const char *str) {
	return jhash64(str, strlen(str), map_key());
}
#endif

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

	Map map = (Map) map__alloc(
		sizeof(struct MapImpl) + sizeof(MapEntry)*(m_cap - MAP_H_STRUCT_MAPIMPL_NON_VA_BUCKETS)
	);

	if (map == nullptr)
		return nullptr;

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

	if (map->overflow == nullptr) {
		map__free(map);
		return nullptr;
	}
	// zeroing the overflow arena doesn't matter

	static_assert(MAP_H_MIN_OCAP > 1);

	// unaligned loads always exist for AVX2, so just ignore errors from -Wcast-align=strict
	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	// key and next fields are empty for the reserved entry.
	#ifdef __AVX2__
		// this also zeros the key of the next entry, but that is fine.
		*(__m256i *) map->overflow = (__m256i) {0};
	#else
		map->overflow->key  = nullptr;
		map->overflow->next = 0;
	#endif

	#pragma GCC diagnostic pop

	// make sure all the `next` fields are 0 and `key` fields are null in the inline buckets
	memset(map->buckets, 0, sizeof(MapEntry)*m_cap);

	// the rest of the overflow is cold, so prefetch the first few cache lines.
	// since sizeof(MapEntry) == 24, this is roughly 10 inserts.
	__builtin_prefetch((char *) map->overflow + 64*1, 1, 3); // rw=write, L1
	__builtin_prefetch((char *) map->overflow + 64*2, 1, 3);
	__builtin_prefetch((char *) map->overflow + 64*3, 1, 3);
	__builtin_prefetch((char *) map->overflow + 64*4, 1, 3);

	return map;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_destroy_ref1(Map *pthis) {
	// make the user pass a pointer to their variable to avoid use after frees
	Map this = *pthis;

	if (this == nullptr)
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
	if (this == nullptr)
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

	MapEntry *new_overflow = (MapEntry *) malloc(sizeof(MapEntry)*this->o_cap);

	if (new_overflow == nullptr)
		return false;

	// this is the same zeroing block as in Map_create2
	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	#ifdef __AVX2__
		*(__m256i *) new_overflow = (__m256i) {0};
	#elifdef __SSE2__
		*(__m128i *) new_overflow = (__m128i) {0};
		((u64 *) new_overflow)[2] = 0;
	#else
		new_overflow[0] = (MapEntry) {0};
	#endif

	#pragma GCC diagnostic pop

	u64 new_id = 1; // index 0 is reserved, so start at 1.
	// the two preprocessor branches are logically identical.
	// the Map_foreach way is slightly slower, but it is way simpler.
#if 1
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
		} while (old_id != 0);
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
	__builtin_prefetch((char *) (new_overflow + new_id) + 64*2, 1, 3);
	__builtin_prefetch((char *) (new_overflow + new_id) + 64*3, 1, 3);

	return true;
}

[[gnu::nonnull]]
MAP_STATIC bool Map_oresize2(Map this, u64 o_cap) {
	// returns true if it succeeded and false if it failed.
	// shrinking the map is not recommended, especially if you have a MapIter for the map.

	// assert the invariants from the rest of the code in case it helps GCC with optimization.
	if (this->o_cap < MAP_H_MIN_OCAP || this->o_cap < this->o_size + 1)
		__builtin_unreachable();

	if (o_cap < MAP_H_MIN_OCAP || o_cap < this->o_size + 2)
		return false; // not allowed

	MapEntry *new_overflow = (MapEntry *) realloc(this->overflow, sizeof(MapEntry)*o_cap);
	if (new_overflow == nullptr)
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
MAP_STATIC void *Map_get_entry_by(ConstMap this, const void *key, map_cmp_t cmp, map_hash_t hash) {
	// same as Map_get_entry3 but with `cmp` instead of `strcmp`
	hash = Map_bucket_from_hash(this, hash);

	Map_foreach(this, hash,
		if (cmp(entry.key, key) == 0)
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

[[maybe_unused, gnu::nonnull]]
MAP_INLINE bool Map__delete_by(Map this, const void *key, map_cmp_t cmp, u64 hash, bool owned) {
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
		if (this->o_size + 2 >= this->o_cap >> 1 && !Map_gc(this))
			return true; // can't resize if GC failed

		// this is a shrink, so it will never fail
		Map_oresize(this, this->o_cap >> 1);
	}

	return true;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC bool Map_delete4(Map this, const char *key, u64 hash, bool owned) {
	return Map__delete_by(this, key, (map_cmp_t) strcmp, hash, owned);
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC bool Map_delete_by5(Map this, const void *key, map_cmp_t cmp, u64 hash, bool owned) {
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
		if (!Map_oresize(this, this->o_cap*3 >> 1)) {
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

#define Map__set_raw_nonexisting(this, KEY, VAL, bucket) ({ \
	this->buckets[bucket].key = KEY;                        \
	this->buckets[bucket].val = VAL;                        \
	this->m_size++;                                         \
	return false;                                           \
})

[[gnu::nonnull(1,2)]]
MAP_STATIC bool Map_set_raw4(Map this, const char *restrict key, const char *restrict val, bool owned) {
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

	return Map__set_raw_existing(this, key, val, owned, bucket, Map_get_entry_by(this, key, cmp, bucket));
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_STATIC Map Map_mresize(Map this, u64 m_cap) {
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
	if (new_map == nullptr)
		return this;

	Map_foreach(this,
		// ownership shouldn't matter
		Map_set_raw(new_map, entry.key, entry.val, MAP_UNOWNED)
	);

	if (Map_count(new_map) != Map_count(this)) {
		Map__destroy_shallow(new_map);
		return this;
	}

	Map__destroy_shallow(this);
	return Map_normalize(new_map);
}

[[nodiscard, gnu::nonnull, gnu::malloc]]
MAP_INLINE Map Map_rehash(Map this) {
	const u64 m_cap = this->m_cap;
	this->m_cap = 0; // bypass the check for if it is an actual resize
	return Map_mresize(this, m_cap);
}

[[gnu::nonnull]]
MAP_INLINE Map Map__set_grow(Map this) {
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

	if (this->m_size > this->m_cap*3 >> 2)
		// size >= 75% of cap => buckets almost full
		return Map_mresize(this, this->m_cap*3 >> 1);

	if (this->o_size + 1 < this->o_cap)
		// buckets and overflow are both not almost full
		return this;

	// overflow filled the last slot
	// k = m_size / m_cap

	if (this->m_size*5 >= this->m_cap*3)
		// 0.6 <= k: resize the map
		return Map_mresize(this, this->m_cap*3 >> 1);

	// NOTE: 5 | 20 and 3 | 9, so the compiler can reuse previous calculations
	if (this->m_size*20 >= this->m_cap*9) {
		// 0.45 <= k < 0.6: if o_tcnt >= o_cap/4, GC, else resize the map
		if (this->o_tcnt < this->o_cap >> 2) // if overflow utilization > 75%
			return Map_mresize(this, this->m_cap*3 >> 1);

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
		this = Map_mresize(this, this->m_cap*3 >> 1);
	else
		Map_oresize(this, this->o_cap*3);

	return this;
}

[[nodiscard, gnu::nonnull(1,2)]]
MAP_STATIC Map Map_set4(Map this, const char *restrict key, const char *restrict val, bool owned) {
	if (Map_set_raw(this, key, val, owned))
		return this;

	return Map__set_grow(this);
}

[[nodiscard, maybe_unused, gnu::nonnull(1,2,4)]]
MAP_STATIC Map Map_set_by6(Map this, const void *restrict key, const void *restrict val, map_cmp_t cmp, map_hash_t hash, bool owned) {
	if (Map_set_raw_by(this, key, val, cmp, hash, owned))
		return this;

	return Map__set_grow(this);
}

[[nodiscard, maybe_unused, gnu::nonnull]]
MAP_STATIC Map Map_vsetall(Map this, MapEntryVList entries) {
	// since it takes string views, it has to allocate new memory and copy the strings there,
	// so it is impossible to have a non-owning version of this code path without making
	// weird assumptions that I don't feel like making.
	// it stops at the first entry it can't insert, rather than just skipping that entry.
	// the value pointers can be null, in which case, they are not touched
	vstring vkey, vval;

	while (entries.count --> 0) {
		vkey = entries.array->key;
		vval = entries.array->val;

		if (vkey.len == UINT64_MAX || vval.len == UINT64_MAX)
			return this;

		char *key = (char *) malloc(vkey.len + 1);
		if (key == nullptr)
			return this;

		char *val;

		if (vval.ptr == nullptr)
			val = nullptr;
		else {
			val = (char *) malloc(vval.len + 1);

			if (val == nullptr) {
				free(key);
				return this;
			}

			memcpy(val, vval.ptr, vval.len);
			val[vval.len] = '\0';
		}

		// write the key after the value in case the value allocation failed (faster).
		memcpy(key, vkey.ptr, vkey.len);
		key[vkey.len] = '\0';

		this = Map_set(this, key, val, MAP_OWNED);
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
MAP_STATIC void Map_getall(ConstMap this, const char *keys[], u64 count) {
	// update the keys array to have the values instead.

	while (count --> 0) {
		*keys = Map_get(this, *keys);
		keys++;
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
		.item = nullptr,
		.bucket = 0 // bucket doen't matter
	};
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC MapIter Map_next(ConstMap this, MapIter iter) {
	// return the next element after the current one.
	if (iter.item == nullptr)
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
		.item = nullptr,
		.bucket = 0 // bucket doen't matter
	};
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC void Map_clear2(Map this, bool owned) {
	#pragma GCC diagnostic push
	#pragma GCC diagnostic ignored "-Wcast-align"

	if (owned) Map_foreach(this,
		map__free_entry(entry);

		#ifdef __SSE2__
			*(__m128i *) p2entry = (__m128i) {0};
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
	if (new_map == nullptr)
		return nullptr;

	if (owned)
		Map_foreach(this,
			entry.key = strdup(entry.key);
			entry.val = strdup(entry.val);

			if (entry.key == nullptr || entry.val == nullptr) {
				// assume the rest of hte things will all be null as well.
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

#if defined(__APPLE__) || defined(__GLIBC__) && (defined(_DEFAULT_SOURCE) || defined(_GNU_SOURCE))
	#define map_stpcpy stpcpy
#else
	#define map_stpcpy(dst, src) ({    \
		while ((*dst = *src) != '\0') { \
			dst++;                      \
			src++;                      \
		}                               \
		dst;                            \
	})
#endif

[[nodiscard, maybe_unused, gnu::nonnull, gnu::malloc]]
MAP_STATIC char *Map_tojson(ConstMap this, const char indent) {
	// '\0' -> {"a":"b","c":"d"}
	// ' '  -> {"a": "b", "c": "d"}
	// '\t' -> {\n\t"a": "b",\n\t"c": "d"\n}

	if (indent != '\0' && indent != ' ' && indent != '\t')
		return nullptr;

	u64 size = Map_count(this);

	if (size == 0) {
		char *const json = (char *) malloc(4);
		if (json == nullptr)
			return nullptr;

		memcpy(json, (char[]){'{', '}', 0, 0}, 4);
		return json;
	}

	// stuff that is per pair
	size *= (u64) (
		(indent != '\0')*2 // leading '\t'/' ', space after colon
		+ 3*2              // strlen("'':") + strlen("'',")
		+ (indent == '\t') // trailing newline
	);

	Map_foreach(this,
		size += strlen(entry.key) + strlen(entry.val)
	);

	// stuff that is only once
	// indent='\0' wastes one byte, and indent=' ' wastes two bytes
	size += 2; // '{\n' for indent='\t'. the extra 1-2 byte savings in the other cases is not worth the logic.

	char *const json = (char *) malloc(size + 1); // +1 for the null terminator
	if (json == nullptr)
		return nullptr;

	char *cur = json + (indent != ' ');
	if (indent == '\t')
		*cur++ = '\n';

	Map_foreach(this,
		if (indent != '\0')
			*cur++ = indent;

		*cur++ = '"';
		cur     = map_stpcpy(cur, entry.key);
		*cur++ = '"';
		*cur++ = ':';

		if (indent != '\0')
			*cur++ = ' ';

		*cur++ = '"';
		cur    = map_stpcpy(cur, entry.val);
		*cur++ = '"';
		*cur++ = ',';

		if (indent == '\t')
			*cur++ = '\n';
	);

	// fix up the trailing separator left by the last entry into the closing brace
	if (indent == '\t')
		cur[-2] = '\n'; // ",\n" -> "\n}"

	*json   = '{'; // do this now because it would get overwritten in indent=' ' mode.
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
MAP_STATIC u64 map_dedup_shuffle_det(const char *strings[], const u64 len) {
	// deterministic in that passing the same list in multiple times will give the same
	// shuffled list, so long as the hash key doesn't change between calls. If you reorder
	// the elements in the input, the change in the output will only be localized. calling
	// this multiple times consecutively will only converge on the same output if there are
	// never more than 3 strings that end up in the same bucket.

	AF_ViewMap const set = Map_create(len*3 >> 1);
	u64 i;

	for (i = 0; i < len; i++)
		Map_set_raw(set, strings[i], /*no value*/ nullptr, MAP_UNOWNED);

	i = 0;
	Map_foreach(set,
		strings[i++] = entry.key
	);

	return i;
}

[[maybe_unused, gnu::nonnull]]
MAP_STATIC u64 map_dedup_shuffle(const char *strings[], const u64 len) {
	// funky function to shuffle an array of strings using a hash map,
	// and also deduplicates the list at the same time.
	// returns the new list length.

	// this is a "stable" shuffling function, which I define to mean if you reorder the inputs,
	// then you will get, at most, local changes to the output. And if you insert a new element,
	// or delete an element, it will not change the ordering of the other elements (unless it
	// puts it over the next boundary so the bucket count changes). "local changes" means that
	// you might get a few consecutive output elements reodered, but the overall structure of
	// the output will not change.

	// NOTE: if you ignore a nonzero return value, the array will
	//       most likely have the wrong strings duplicated.

	// this is not a exactly helper function. it is its own thing.
	// not reentrant. if you want that, then wrap the detererministic version yourself.

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
	const u64 new_len = map_dedup_shuffle_det(strings, len);
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
	//       existed in the map were already null-termianted C strings, so strcmp actually works.
	//       you may more realistically want to compare lengths and use strncmp if they match.
	// NOTE: none of the code currently cares about whether the comparison function returns +1 or
	//       -1, or whatever else for different values, only that it returns 0 when they are the
	//       same and something nonzero (i32) when they aren't.
	// NOTE: they key and val fields don't necessarily need to be the same type, the calling code
	//       just has to be able to figure out what it is

	Map_foreach(this,
		vstring *tmp;

		// viewify the key
		tmp = (typeof(tmp)) malloc(sizeof(*tmp));
		tmp->ptr = (char *) entry.key;
		tmp->len = strlen(entry.key);
		entry.key = (char *) tmp;

		// viewify the value
		tmp = (typeof(tmp)) malloc(sizeof(*tmp));
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
	if (buf == nullptr)
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
