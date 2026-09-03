#pragma once
#define DSL_EXCEPT_H

#include "setjmp.h" // "va-if.h", "int-types.h"
#include "dsl-vars.h" // "map.h" (FORCE_INLINE), until

#ifndef PAGE_SIZE
	#define PAGE_SIZE 4096llu
#endif

// swapping these will break everything.
#define EXCEPTION_FOUND    true
#define EXCEPTION_NOTFOUND false

#define DEFAULT_DEPTH_CAP       1024
#define DEFAULT_ITER_CAP        1'000'000
#define DSL_EXCEPT_START_SIZE   32

static u32 depth_cap = 0;
static u32 iter_cap  = 0;

typedef enum : u8 {
	EXCEPT_CONTINUE     =   1, // %continue\d*
	EXCEPT_BREAK        =   2, // %break\d*
	EXCEPT_EXIT_MACRO   =   4, // %exitmacro
	EXCEPT_EXIT_PROGRAM =   8, // %exit
	EXCEPT_EVAL_EXPAND  =  16, // %seteval try again with expanded variables

	EXCEPT_GROUP_NONE   =   0,
	EXCEPT_GROUP_TAGGED =   3, // loops and branches
	EXCEPT_GROUP_EXIT   =  12,
	EXCEPT_GROUP_ANY    = 255,
} except_type_t;

#define EXCEPT_TAG_NONE  UINT64_MAX      // for things that don't use tags
#define EXCEPT_TAG_ANY  (UINT64_MAX - 1) // only for queries

#define EXCEPT_ERR_OOM   (-256ll) // any memory-bandwidth related issue
#define EXCEPT_ERR_DEPTH (-257ll) // exception max depth exceeded
#define EXCEPT_ERR_LEXER (-258ll) // any non-OOM error during %seteval
// EXCEPT_ERR_UNCAUGHT_* is -1 through -255
// unreserved error codes start at -258

typedef struct __attribute__((packed)) {
	jmp_buf env; // NOTE: this has to come first
	u64 tag;     // NOTE: not used for all types
	except_type_t type;
} except_t; // exception

typedef struct {
	except_t *array;
	u64 count;         // number of exceptions in the stack
	u64 cap;           // number of exceptions the stack can hold before resize
	u64 dispatch_line; // this needs to be set manually
} except_stack_t;

static except_stack_t dsl_except;

#define dsl_free_except() do {       \
	if (dsl_except.array == nullptr) \
		break;                       \
	free(dsl_except.array);          \
	dsl_except.array = nullptr;      \
	dsl_except.count = 0;            \
	dsl_except.cap   = 0;            \
} while (false)

#define dsl__try_root() ({                           \
	__label__ done;                                  \
	i64 result;                                      \
	dsl_except.array = malloc(                       \
		DSL_EXCEPT_START_SIZE*sizeof(except_t));     \
	if (dsl_except.array == nullptr) {               \
		result = EXCEPT_ERR_OOM;                     \
		goto done;                                   \
	}                                                \
	dsl_except.count = 1;                            \
	dsl_except.cap   = DSL_EXCEPT_START_SIZE;        \
	dsl_except.dispatch_line = 0;                    \
	dsl_except.array[0].type = EXCEPT_EXIT_PROGRAM;  \
	dsl_except.array[0].tag  = EXCEPT_TAG_NONE;      \
	result = setjmp((jmp_buf *) dsl_except.array);   \
done:                                                \
	result;                                          \
})

static void dsl_free_except_from(u64 start) {
	// don't call with `start=0`.

	if (start > dsl_except.count)
		// this shouldn't happen
		return;

	dsl_except.count = start;

	if (start >= (DSL_EXCEPT_START_SIZE + 1)*2/3 && start <= (dsl_except.cap >> 1)) {
		start += start >> 1;
		dsl_except.cap = start;

		// shrink should never fail
		dsl_except.array = realloc(dsl_except.array, start * sizeof(except_t));
	}

	// NOTE: exception index `start` is always still alive due to how the shrink logic works
}

FORCE_INLINE
static void dsl_try_longjmp(i64 value, except_type_t type, u64 tag, u64 i, bool found) {
	// this function assumes the exception structure is initialized

	if (found) {
		if ((dsl_except.array[i].type & type) == 0)
			return;

		if (tag != EXCEPT_TAG_ANY && dsl_except.array[i].tag != tag)
			return;
	}

	// if no matches are found, default to the first one.
	// the external code should pass i=0 in that case.

	dsl_free_except_from(i);
	longjmp((jmp_buf *) &dsl_except.array[i], found ? value : -(i64) type);
}

[[noreturn, maybe_unused]]
FORCE_INLINE static void dsl_panic(i64 value) {
	// this is the same as `dsl_throw_far(value)` or `dsl_throw(value)`,
	// but it runs slightly less code
	// NOTE: pass found=true so it doesn't override the exit code.
	dsl_try_longjmp(value, EXCEPT_GROUP_ANY, EXCEPT_TAG_ANY, /*i*/ 0, EXCEPTION_FOUND);
	unreachable();
}

[[noreturn, maybe_unused]]
static void dsl_throw_far3(i64 value, except_type_t type, u64 tag) {
	// throw (caught by the farthest catch, not the closest catch)
	if (type == EXCEPT_GROUP_NONE) {
		type = EXCEPT_GROUP_ANY; // just so the value isn't 0.
		goto not_found;
	}

	for (u64 i = 0; i < dsl_except.count; i++)
		dsl_try_longjmp(value, type, tag, i, EXCEPTION_FOUND);

not_found:
	dsl_try_longjmp(
		value,
		type,
		tag,
		/*i*/ 0,
		EXCEPTION_NOTFOUND
	);
	unreachable();
}

#define dsl_throw_far2(value, type) dsl_throw_far3(value, type, EXCEPT_TAG_ANY)
#define dsl_throw_far1(value)       dsl_throw_far2(value, EXCEPT_GROUP_ANY)

#define dsl_throw_far2_3(value, type, tag...) \
	VA_IF(dsl_throw_far3(value, type, tag), dsl_throw_far2(value, type), tag)

#define dsl_throw_far(value, type...) \
	VA_IF(dsl_throw_far2_3(value, type), dsl_throw_far1(value), type)

[[noreturn, maybe_unused]]
static void dsl_throw3(i64 value, except_type_t type, u64 tag) {
	if (type == EXCEPT_GROUP_NONE) {
		type = EXCEPT_GROUP_ANY; // just so the value isn't 0.
		goto not_found;
	}

	for (u64 i = dsl_except.count; i --> 0 ;)
		dsl_try_longjmp(value, type, tag, i, EXCEPTION_FOUND);

not_found:
	dsl_try_longjmp(
		value,
		type,
		tag,
		/*i*/ 0,
		EXCEPTION_NOTFOUND
	);
	unreachable();
}

#define dsl_throw2(value, type) dsl_throw3(value, type, EXCEPT_TAG_ANY)
#define dsl_throw1(value)       dsl_throw2(value, EXCEPT_GROUP_ANY)

#define dsl_throw2_3(value, type, tag...) \
	VA_IF(dsl_throw3(value, type, tag), dsl_throw2(value, type), tag)

#define dsl_throw(value, type...) \
	VA_IF(dsl_throw2_3(value, type), dsl_throw1(value), type)

[[maybe_unused, gnu::returns_twice]]
static i64 dsl__try2(except_type_t type, u64 tag) {
	// try/catch

	// NOTE: a negative return should indicate an error.
	// main codes:
	//       -256 => OOM. push failure.
	//       -257 => depth exceeded.
	// rest (these will only ever happen on the first push):
	//       -1   => uncaught %continue
	//       -2   => uncaught %break
	//       -3   => uncaught TAGGED
	//       -4   => uncaught %exitmacro
	//       -8   => uncaught %exit
	//       -12  => uncaught EXIT
	//       -255 => uncaught ANY

	if (tag == EXCEPT_TAG_ANY)
		// ANY is only a valid tag for queries.
		tag = EXCEPT_TAG_NONE;

	if (dsl_except.count >= depth_cap)
		dsl_panic(EXCEPT_ERR_DEPTH);

	if (dsl_except.count == dsl_except.cap) {
		u64 new_cap = dsl_except.cap*3 >> 1;

		if (new_cap > depth_cap)
			new_cap = depth_cap;

		except_t *const new_array = realloc(dsl_except.array, new_cap * sizeof(except_t));

		if (new_array == nullptr)
			// crash on OOM
			dsl_panic(EXCEPT_ERR_OOM);

		dsl_except.array = new_array;
		dsl_except.cap   = new_cap;
	}

	except_t *p2except = dsl_except.array + dsl_except.count++;

	p2except->type = type;
	p2except->tag  = tag;

	return setjmp((jmp_buf *) &p2except);
}

#define dsl__try1(type) dsl_try2(type, EXCEPT_TAG_NONE)
#define dsl__try(type, tag...) VA_IF(dsl_try2(type, tag), dsl_try1(type), tag)

#define dsl_try_root3(VAR, BEFORE, CASES) ({ \
	const i64 VAR = dsl__try_root();         \
	BEFORE;                                  \
	switch (VAR) { CASES; }                  \
	dsl_free_except();                       \
	VAR;                                     \
})
#define dsl_try_root2(BEFORE, BLOCK) dsl_try_root3(res, BEFORE, BLOCK)
#define dsl_try_root1(BLOCK) dsl_try_root2((void) 0, BLOCK)
#define dsl_try_root2_3(a, b, c...) VA_IF(dsl_try_root3(a, b, c), dsl_try_root2(a, b), c)
#define dsl_try_root(a, b...) VA_IF(dsl_try_root2_3(a, b), dsl_try_root1(a), b)

#define dsl_try5(type, tag, VAR, BEFORE, CASES) ({ \
	const i64 VAR = dsl__try(type, tag);           \
	BEFORE;                                        \
	switch (VAR) { CASES; }                        \
	VAR;                                           \
})

#define dsl_try4(type, tag, BEFORE, BLOCK) dsl_try5(type, tag, res, BEFORE, BLOCK)
#define dsl_try3(type, tag, BLOCK) dsl_try4(type, tag, (void) 0, BLOCK)
#define dsl_try2(type, BLOCK) dsl_try3(type, EXCEPT_TAG_NONE, BLOCK)

#define dsl_try4_5(a, b, c, d, e...) VA_IF(dsl_try5(a, b, c, d, e), dsl_try4(a, b, c, d), e)
#define dsl_try3_4_5(a, b, c, d...) VA_IF(dsl_try4_5(a, b, c, d), dsl_try3(a, b, c), d)
#define dsl_try(a, b, c...) VA_IF(dsl_try3_4_5(a, b, c), dsl_try2(a, b), c)
