#pragma once
#define CRC_DSL_H

#define MAP_H_DEFAULT_OWNED
#define MAP_H_NO_FUN
#define MAP_H_IMPL
#define MAP_H_HASH64
#include "map.h" // <stdlib.h>, <stdint.h>, <string.h>, "va-if.h"

#include "dsl-except.h" // "setjmp.h"
#include <ctype.h> // isalnum

// `volatile` without the reordering restrictions and forced rereads
#define force_mem(var) asm ("" : "+m" (var))

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Wsign-conversion"
#pragma GCC diagnostic ignored "-Wpadded"
#ifdef _WIN32
	#include "gmp.h"
#else
	#include <gmp.h>
#endif
#pragma GCC diagnostic pop

#ifdef _WIN32
	#include <windows.h>

	// from CRYPTBASE.dll or Advapi32.dll (-lcryptbase or -ladvapi32)
	bool SystemFunction036(void *buf, u32 len);
	#define dsl_rand(buf, len) ({ while (!SystemFunction036(buf, len)); (void) 0; })
#else
	#include <sys/random.h>
	#include <sys/ioctl.h>
	#include <unistd.h>
	#include <time.h>

	// under the constraints, this will never fail
	#define dsl_rand(buf, len) ((void) getrandom(buf, len, /*flags*/ 0))
#endif

#define ANSI_RED    "\e[31m"
#define ANSI_ORANGE "\e[38;2;180;100;0m"
#define ANSI_RST    "\e[m"

#define DSL_MAJOR "1"
#define DSL_MINOR "5"
#define DSL_MICRO "0a" // patch version
#define DSL_VERSION DSL_MAJOR "." DSL_MINOR "." DSL_MICRO

#ifdef __linux__
	#define DSL_PLATFORM "linux"
#elifdef _WIN32
	#define DSL_PLATFORM "win32"
#elif defined(__APPLE__) && defined(__MACH__)
	#define DSL_PLATFORM "darwin"
#elifdef __FreeBSD__
	#define DSL_PLATFORM "freebsd"
#elifdef __OpenBSD__
	#define DSL_PLATFORM "openbsd"
#elifdef __NetBSD__
	#define DSL_PLATFORM "netbsd"
#elifdef __DragonFly__
	#define DSL_PLATFORM "dragonfly"
#elifdef __sun
	#define DSL_PLATFORM "sunos"
#elifdef __HAIKU__
	#define DSL_PLATFORM "haiku"
#else
	#define DSL_PLATFORM "unknown"
#endif

#define _strlen __builtin_strlen

#define eprintf(FMT, ...)  fprintf(stderr, ANSI_RED    FMT ANSI_RST __VA_OPT__(,) __VA_ARGS__)
#define ewprintf(FMT, ...) fprintf(stderr, ANSI_ORANGE FMT ANSI_RST __VA_OPT__(,) __VA_ARGS__)

// the argument should be an identifier, but it can be either `prgm_t` or `vstring_list`
#define free_prgm(prgm) ({               \
	free(prgm.array->ptr - sizeof(u64)); \
	free(prgm.array);                    \
	prgm = (typeof(prgm)) {};            \
	(void) 0;                            \
})

// this assumes little endian
#define B1_TO_U08(c0) ((u8) c0)
#define B2_TO_U16(c0, c1) ((u16)c1 << 8 | (u16)c0)
#define B4_TO_U32(c0, c1, c2, c3) ((u32)c3 << 24 | (u32)c2 << 16 | (u32)c1 << 8 | (u32)c0)
#define B8_TO_U64(c0, c1, c2, c3, c4, c5, c6, c7) \
	((u64)B4_TO_U32(c4, c5, c6, c7) << 32 | (u64)B4_TO_U32(c0, c1, c2, c3))

typedef union {
	u64 raw;

	__attribute__((packed)) struct {
		union {
			u32 rows, height, lines;
		};

		union {
			u32 cols, width;
		};
	};
} term_size_t;

typedef struct {
	vstring_list;
	u64 cap;
} prgm_t;

typedef struct {
	char *ptr;

	u64 usage, size; // in bytes. size should be a nonzero multiple of PAGE_SIZE
} wide_buf;

typedef enum : u8 {
	VAR_SPZ, // i128
	VAR_MPZ, // mpz_t
	VAR_STR, // vstring
} var_type_t;

typedef vstring var_key_t;

typedef struct __attribute__((packed)) {
	union {
		// NOTE: these should all be 16 bytes long
		i128    spz; // single-precision integer
		mpz_t   mpz; // multiple-precision integer
		vstring str; // `.ptr` should be a C string.
	};

	var_type_t type;
} var_val_t;

typedef struct {
	var_key_t *key;
	var_val_t *val;
	u64 next;
} var_t; // same structure as `MapEntry`

static prgm_t dsl_out_prgm = {
	.array = nullptr,
	.count = 0,
	.cap   = 0,
};

static wide_buf dsl_scratch = {
	.ptr   = nullptr,
	.usage = 0,
	.size  = 0,
};

static wide_buf dsl_out_buf = {
	.ptr   = nullptr,
	.usage = 0,
	.size  = 0,
};

static u64 dsl_total_bytes = 0;
static u8 dsl_total_lines  = 0;

static Map dsl_vars = nullptr;

#ifdef _WIN32
static term_size_t term_size(void) {
	CONSOLE_SCREEN_BUFFER_INFO csbi;

	DWORD handles[] = {
		STD_OUTPUT_HANDLE,
		STD_INPUT_HANDLE,
		STD_ERROR_HANDLE
	};

	for (u8 i = 0; i < 3; i++) {
		HANDLE h = GetStdHandle(handles[i]);

		if (h == INVALID_HANDLE_VALUE || h == nullptr)
			continue;

		if (!GetConsoleScreenBufferInfo(h, &csbi))
			continue;

		return (term_size_t) {
			.cols = (u32)(csbi.srWindow.Right  - csbi.srWindow.Left + 1),
			.rows = (u32)(csbi.srWindow.Bottom - csbi.srWindow.Top  + 1),
		};
	}

	return (term_size_t) {};
}
#else
static term_size_t term_size(void) {
	// returns all zeros on failure

	struct winsize ws;

	int fds[] = {STDOUT_FILENO, STDIN_FILENO, STDERR_FILENO};

	for (u8 i = 0; i < 3; i++)
		if (ioctl(fds[i], TIOCGWINSZ, &ws) == 0)
			return (term_size_t) {
				.rows = ws.ws_row,
				.cols = ws.ws_col
			};

	return (term_size_t) {};
}
#endif

FORCE_INLINE static void msleep(u32 ms) {
	#ifdef _WIN32
		Sleep(ms);
	#else
		struct timespec ts = {
			.tv_sec  =  ms / 1000,
			.tv_nsec = (ms % 1000) * 1'000'000l,
		};

		nanosleep(&ts, NULL);
	#endif
}

[[gnu::nonnull]]
static void dsl_free_var(var_t *p2entry) {
	// free the variable entry, but don't remove the entry from the map
	var_key_t *pkey = (var_key_t *) p2entry->key;
	free(pkey->ptr);
	free(pkey);

	var_val_t *pval = (var_val_t *) p2entry->val;

	switch (pval->type) {
		case VAR_SPZ:
			// plain integer has no extra allocation
			break;
		case VAR_MPZ:
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			mpz_clear(pval->mpz);
			#pragma GCC diagnostic pop
			break;
		case VAR_STR:
			free(pval->str.ptr);
			break;
		default:
			__builtin_unreachable();
	}

	free(pval);
}

[[gnu::nonnull]]
static void dsl_set_var(var_key_t *pkey, var_val_t *pval) {
	const map_hash_t hash = jhash(pval->str.ptr, pval->str.len);

	var_t *const p2entry = (var_t *) Map_get_entry_by(dsl_vars, pkey, vstring_cmp, hash);

	if (p2entry != nullptr) {
		// variable exists free the old stuff and update in-place
		dsl_free_var(p2entry);
		p2entry->key = pkey;
		p2entry->val = pval;
	}
	else
		dsl_vars = Map_set_by(dsl_vars, pkey, pval, vstring_cmp, hash, MAP_UNOWNED);
}

[[maybe_unused, gnu::nonnull]]
static void dsl_log_var(var_t *p2entry) {
	// NOTE: the pointer is a C string as well as a V string.
	printf("\"%s\" => {\n\t", p2entry->key->ptr);

	var_val_t *pval = p2entry->val;

	switch (pval->type) {
		case VAR_SPZ: {
			const bool sign = pval->spz >= 0;
			const u128 magn = sign ? (u128) pval->spz : -(u128) pval->spz;

			printf(
				".type = VAR_SPZ\n\t"
				".val  = %s%016zx%016zx",
				"-" + !sign,
				(u64)(magn >> 64),
				(u64) magn
			);

			break;
		}
		case VAR_MPZ: {
			#pragma GCC diagnostic push
			#pragma GCC diagnostic ignored "-Waddress-of-packed-member"
			const char *str = mpz_get_str(NULL, 10, pval->mpz);
			#pragma GCC diagnostic pop

			printf(
				".type = VAR_MPZ\n\t"
				".val  = %s",
				str
			);

			free((void *) str);
			break;
		}
		case VAR_STR:
			printf(
				".type = VAR_STR\n\t"
				".val  = \"%s\"\n\t"
				".len  = %zu",
				pval->str.ptr,
				pval->str.len
			);

			break;
		default:
			__builtin_unreachable();
	}

	putchar('\n');
	putchar('}');
	putchar('\n');
}

FORCE_INLINE static bool line_isspace(char c) {
	// stuff that can be whitespace inside of a line
	// I don't care about \r, \n, or \f
	return c == ' ' || c == '\t';
}

#define IS_RAW_LINE(LINE) ({                               \
	const vstring line_ = (LINE);                          \
	line_.len >= _strlen("%raw[]")                         \
		&& *(u32 *)line_.ptr == B4_TO_U32('%','r','a','w') \
		&& line_.ptr[_strlen("%raw")] == '['               \
		&& line_.ptr[line_.len - 1] == ']';                \
})

// the argument should not have side-effects for the next two macros
#define lstrip_line(line) ({                           \
	while (line.len != 0 && line_isspace(*line.ptr)) { \
		line.ptr++;                                    \
		line.len--;                                    \
	}                                                  \
	(void) 0;                                          \
})

#define rstrip_line(line) ({                                      \
	while (line.len != 0 && line_isspace(line.ptr[line.len - 1])) \
		line.len--;                                               \
	(void) 0;                                                     \
})

static bool strip_lines(vstring_list *p2in_prgm) {
	// returns false on failure and true on success
	// the program is updated in-place
	// `bool ok = strip_lines(&prgm);`

	vstring_list in_prgm = *p2in_prgm;

	// make sure the input program doesn't contain null characters.
	{
		char *buf = in_prgm.array->ptr;
		char *null_pos = (char *) memchr(buf, '\0', *(u64 *)(buf - sizeof(u64)));

		if (__builtin_expect(null_pos != nullptr, 0)) {
			if (null_pos < buf) __builtin_unreachable();

			eprintf("program contains null character at position %zu\n", (u64) (null_pos - buf) + 1);
			return false;
		}
	}

	u64 empty_lines = 0;

	// strip all the lines
	for (u64 i = 0; i < in_prgm.count; i++) {
		vstring line = in_prgm.array[i];

		lstrip_line(line);

		// NOTE: this does actually effect stuff. particularly, `%raw[]\s+` does not work
		//       in the pure Python implementation, but this allows it to work here.
		//       it could also make the next part faster in some cases.
		rstrip_line(line);

		// strip out comments and collapse `\|` into `|`
		// NOTE: this could be optimized slightly further to where the second right strip
		//       happens before the final memmoves, but lines shouldn't be long enough for
		//       that to even possibly matter so I don't really care.
		if (!IS_RAW_LINE(line)) {
			u64 r = 0, w = 0; // read, write

			while (true) {
				char *const pipe = (char *) memchr(line.ptr + r, '|', line.len - r);

				if (pipe == nullptr) {
					// the line does not contain a comment
					if (r != 0) {
						memmove(line.ptr + w, line.ptr + r, line.len - r);

						// NOTE: `r - w` is the number of escaped pipe characters
						line.len -= r - w;
					}

					break;
				}

				if (pipe < line.ptr) __builtin_unreachable();
				const u64 p = (u64) (pipe - line.ptr); // pipe index
				const u64 l = p - r; // length

				// preface with `pipe > line.ptr` to avoid out of bounds read
				if (p != 0 && pipe[-1] == '\\') {
					// backslashes can't also be escaped, so don't worry about counting backslashes

					pipe[-1] = '|';
					if (r != 0)
						memmove(line.ptr + w, line.ptr + r, l);

					w += l;
					r  = p + 1; // NOTE: same as `r += l + 1;`
				}
				else {
					// actual comment character

					if (r != 0)
						memmove(line.ptr + w, line.ptr + r, l);

					line.len = l + w;
					break;
				}
			} // while (true)

			// removing a trailing comment could reveal more trailing whitespace
			rstrip_line(line);
		} // if !IS_RAW_LINE(line)

		// write-back
		in_prgm.array[i] = line;

		// never count the first line as empty, even if it is
		if (i != 0)
			empty_lines += line.len == 0;
	} // for

	if (empty_lines == 0)
		return true;

	// remove empty lines
	// start at r = w = 1 because the first line can never be removed, even if it is empty.
	for (u64 r = 1, w = 1, empty_remaining = empty_lines; r < in_prgm.count; r++) {
		if (in_prgm.array[r].len == 0) {
			empty_remaining--;

			if (empty_remaining == 0) {
				memmove(
					in_prgm.array + w,
					in_prgm.array + r + 1,
					(in_prgm.count - r - 1)*sizeof(*in_prgm.array)
				);

				break;
			}

			continue;
		}

		in_prgm.array[w] = in_prgm.array[r];
		w++;
	}

	in_prgm.count -= empty_lines;
	*p2in_prgm = in_prgm;

	return true;
}

[[maybe_unused]]
static void reset_scratch(void) {
	// reset the temporary buffer and potentially shrink

	dsl_total_bytes += dsl_scratch.usage;
	dsl_total_lines++;

	dsl_scratch.usage = 0;

	if (dsl_total_lines & 63)
		// only check every so often
		return;

	// exponential moving average
	if (dsl_total_lines == 0) { // 8-bit integer overflow. also note, the increment already happened
		dsl_total_lines = 128;
		dsl_total_bytes >>= 1;
	}

	// mean
	u64 target = dsl_total_bytes / dsl_total_lines;

	// 50% slack
	target += target >> 1;

	// round to the next page boundary
	target +=   PAGE_SIZE - 1 ;
	target &= ~(PAGE_SIZE - 1);

	// shrink
	if (dsl_scratch.size > target) {
		// this can't fail on any sane system, since it is not an increase
		dsl_scratch.ptr  = realloc(dsl_scratch.ptr, target);
		dsl_scratch.size = target;
	}
}

static bool push_line(vstring line) {
	// a return of false means OOM
	// both the buffer and the array double on resize
	if (line.len == 0)
		return true;

	// resize dsl_out_prgm
	if (dsl_out_prgm.count >= dsl_out_prgm.cap) { // dsl_out_prgm.count + 1 > dsl_out_prgm.cap
		const u64 new_cap = dsl_out_prgm.cap <<= 1;

		vstring *const new_array = (vstring *) realloc(dsl_out_prgm.array, new_cap * sizeof(*dsl_out_prgm.array));

		if (new_array == nullptr) {
			eprintf("crc-dsl.h: push_line: array realloc failed. could not allocate %zu bytes. preproc exiting early.\n", new_cap * sizeof(*dsl_out_prgm.array));
			return false;
		}

		// no write-back until the validity check pass
		dsl_out_prgm.array = new_array;
		dsl_out_prgm.cap   = new_cap;

		// NOTE: `.count` is not updated until later because this is still a valid state. At this point,
		//       the line is not in the buffer, so if the count is increased, and the buffer realloc
		//       fails, it will put the line array in a corrupted state. To fix this, it does the
		//       resizing separately, and thn only writes if both the array and buffer resizes worked.
	}

	// resize dsl_out_buf
	wide_buf tmp_buf = dsl_out_buf;
	tmp_buf.usage   += line.len;

	// add the line to the buffer
	if (tmp_buf.usage >= tmp_buf.size) { // tmp_buf.usage + 1 > tmp_buf.size
		tmp_buf.size = 1llu << (64 - __builtin_clzll(tmp_buf.usage));
		char *const new_buf = (char *) realloc(tmp_buf.ptr, tmp_buf.size);

		if (new_buf == nullptr) {
			eprintf("crc-dsl.h: push_line: buffer realloc failed. could not allocate %zu bytes. preproc exiting early.\n", tmp_buf.size);
			return false;
		}

		dsl_out_buf.ptr  = new_buf;
		dsl_out_buf.size = tmp_buf.size;
	}

	const u64 line_ofs = dsl_out_buf.usage;
	dsl_out_buf.usage = tmp_buf.usage;

	// write the stuff into the structures
	memcpy(dsl_out_buf.ptr + line_ofs, line.ptr, line.len);
	dsl_out_buf.ptr[dsl_out_buf.usage++] = '\n';

	dsl_out_prgm.array[dsl_out_prgm.count++] = (vstring) {
		.ofs = line_ofs,
		.len = line.len,
	};

	return true;
}

static bool is_valid_varname(const char *str, u64 len) {
	if (len < 2 || str[0] != '$')
		return false;

	for (u64 i = 1; i < len; i++)
		if (!isalnum(str[i]) && str[i] != '_')
			return false;

	return true;
}

static void _preproc(
	vstring_list in_prgm,
	u64 start_line,
	u64 depth,
	bool debug
) {
	(void) is_valid_varname;
	(void) start_line;
	(void) depth;
	// TODO: if (depth > depth_cap) jump back to `preproc`

	for (u64 i = 0; i < in_prgm.count; i++) {
		vstring line = in_prgm.array[i];

		if (IS_RAW_LINE(line)) {
			line.ptr += _strlen("%raw[");
			line.len -= _strlen("%raw[]");

			if (push_line(line))
				continue;

			// failure
			*(u64 *) dsl_out_buf.ptr = dsl_out_buf.usage - sizeof(u64);
			// TODO: longjmp instead once that machinery is set up
			return;
		}

		// TODO: do the other constructs
		if (debug)
			printf("// DEBUG: UNKNOWN LINE: \e[32m|\e[m%.*s\e[32m|\e[m\n", (int) line.len, line.ptr);
	}

	*(u64 *) dsl_out_buf.ptr = dsl_out_buf.usage - sizeof(u64);
}


// TODO: update how `dsl_vars` is declared since it is a global variable now.
[[nodiscard]]
static vstring_list preproc(vstring_list in_prgm, MapEntryCList start_vars, bool debug) {
	// start_vars should be an array of owned C strings, and this function takes ownership of them.
	// the pointer is allowed to be null so long as `.count` is 0, i.e. `(MapEntryCList) {}`.
	// all the pointers in dsl_out_prgm are pointers into the same buffer.
	// to destroy: `free_prgm(dsl_out_prgm);`
	// the input program might be clobbered

	// NOTE: once the array is returned, ownership is transferred to the caller, so even if
	//       if the pointer was nonnull, writing over it unconditionally is fine.
	dsl_out_prgm = (prgm_t) {
		.array = malloc(sizeof(vstring)),
		.count = 0,
		.cap   = 1,
	};

	if (dsl_out_prgm.array == nullptr)
		goto catastrophic_oom;

	dsl_out_buf = (wide_buf) {
		.ptr   = malloc(PAGE_SIZE),
		.usage = sizeof(u64),
		.size  = PAGE_SIZE,
	};

	if (dsl_out_buf.ptr == nullptr)
		goto catastrophic_oom;

	if (!strip_lines(&in_prgm)) {
		eprintf("crc-dsl.h: strip_lines: errors were encountered.\n");
		goto done;
	}

	// all three sections in the variable value section have to be the same size
	static_assert(sizeof(mpz_t) == 16 && sizeof(i128) == 16 && sizeof(vstring) == 16);

	const map_hash_t old_map_key = map_key();
	{
		map_hash_t key;
		dsl_rand(&key, sizeof key);
		map_key(key);
	}

	// set up `dsl_vars`
	{
		char *term_width, *term_height;
		term_size_t term = term_size();

		if (term.raw == 0) {
			term_width  = (char *) "";
			term_height = (char *) "";
		}
		else {
			// max required size is 11 including the null byte
			term_width = malloc(16);

			if (term_width == nullptr)
				goto catastrophic_oom;

			term_height = malloc(16);

			if (term_height == nullptr)
				goto catastrophic_oom;

			sprintf(term_width , "%u", term.width);
			sprintf(term_height, "%u", term.height);
		}

	#if DEBUG
		if (dsl_vars != nullptr) {
			eprintf("BUG: `dsl_vars` is not NULL at the start of `preproc`.\n");
			exit(1);
		}
	#endif

		dsl_vars = Map_create();

		if (dsl_vars == nullptr)
			goto catastrophic_oom;

		// add requested starting variables
		for (u64 i = 0; i < start_vars.count; i++) {
			const MapEntryCView entry = start_vars.array[i];

			// convert from `char * => char *` to `var_key_t => var_val_t`
			var_key_t *pkey = malloc(sizeof(var_key_t));
			if (pkey == nullptr)
				goto catastrophic_oom;

			pkey->ptr = entry.key;
			pkey->len = strlen(entry.key);

			var_val_t *pval = malloc(sizeof(var_val_t));
			if (pval == nullptr)
				// don't bother freeing `pkey` since this just crashes anyway
				goto catastrophic_oom;

			pval->type    = VAR_STR;
			pval->str.ptr = entry.val;
			pval->str.len = strlen(entry.val);

			dsl_set_var(pkey, pval);
		}

		// add default starting vars
		{
			const char *default_var_keys[] = {
				"null",			"dsl_version",
				"platform",		"dsl_major",
				"dsl_minor",	"dsl_micro",
				"term_width",	"term_height",
			};

			const char *default_var_vals[] = {
				"",				DSL_VERSION,
				DSL_PLATFORM,	DSL_MAJOR,
				DSL_MINOR,		DSL_VERSION + _strlen(DSL_VERSION) - _strlen(DSL_MICRO),
				term_width,		term_height,
			};

			for (u64 i = 0; i < sizeof(default_var_keys) / sizeof(*default_var_keys); i++) {
				const MapEntryCView entry = {
					.key = strdup(default_var_keys[i]),
					.val = strdup(default_var_vals[i]),
				};

				// convert from `char * => char *` to `var_key_t => var_val_t`
				var_key_t *pkey = malloc(sizeof(var_key_t));
				if (pkey == nullptr)
					goto catastrophic_oom;

				pkey->ptr = entry.key;
				pkey->len = strlen(entry.key);

				var_val_t *pval = malloc(sizeof(var_val_t));
				if (pval == nullptr)
					// don't bother freeing `pkey` since this just crashes anyway
					goto catastrophic_oom;

				pval->type    = VAR_STR;
				pval->str.ptr = entry.val;
				pval->str.len = strlen(entry.val);

				dsl_set_var(pkey, pval);
			} // for
		} // end bare block

		if (term.raw != 0) {
			// these get `strdup`ed into the map, so the local copies need to be freed separately.
			free(term_width);
			free(term_height);
		}
	}

	depth_cap = DEFAULT_DEPTH_CAP;
	iter_cap  = DEFAULT_ITER_CAP;

	dsl_scratch = (wide_buf) {
		.ptr   = malloc(PAGE_SIZE),
		.usage = 0,
		.size  = PAGE_SIZE,
	};

	if (dsl_scratch.ptr == nullptr)
		goto catastrophic_oom;

	dsl_total_bytes = 0;
	dsl_total_lines = 0;

	_preproc(
		in_prgm,
		0 /*start_line*/,
		0 /*depth*/,
		debug
	);

	free(dsl_scratch.ptr);
	dsl_scratch = (wide_buf) {
		.ptr   = nullptr,
		.usage = 0,
		.size  = 0,
	};


	// replace the final newline with null
	dsl_out_buf.ptr[dsl_out_buf.usage /*sizeof(u64) + *(u64 *) dsl_out_buf.ptr*/] = '\0';

	puts("vars:");

	// destroy the variable map
	Map_foreach(dsl_vars,
		dsl_log_var((var_t *) p2entry);
		dsl_free_var((var_t *) p2entry);
	);

	Map_destroy_shallow_ref(&dsl_vars);

	map_key(old_map_key); // restore the original key
done:
	if (dsl_out_prgm.count == 0) {
		// NOTE: this assumes dsl_out_prgm.size is at least 1
		dsl_out_prgm.count = 1;

		dsl_out_prgm.array[0] = (vstring) {
			.ofs = sizeof(u64),
			.len = 0,
		};
	}

	dsl_out_buf.ptr = realloc(dsl_out_buf.ptr, dsl_out_buf.usage); // shrink buffer

	for (u64 i = 0; i < dsl_out_prgm.count; i++)
		dsl_out_prgm.array[i].ptr = dsl_out_buf.ptr + dsl_out_prgm.array[i].ofs;

#if DEBUG
	if (dsl_out_prgm.array->ptr != dsl_out_buf.ptr + sizeof(u64))
		eprintf("crc-dsl.h: preproc: `dsl_out_prgm.array->ptr` and `dsl_out_buf.ptr + 8` don't match\n");
#endif

	// shrink line arrray
	dsl_out_prgm.array = realloc(dsl_out_prgm.array, dsl_out_prgm.count * sizeof(*dsl_out_prgm.array));

	return (vstring_list) {
		.array = dsl_out_prgm.array,
		.count = dsl_out_prgm.count,
	};

catastrophic_oom:
	eprintf("crc-dsl.h: preproc: catastrophic OOM.\n");
	exit(1);
}
