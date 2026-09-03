#pragma once
#define DSL_MAIN_H

/*
include hierarchy:
parser
	lexer
		ctype
		except
			setjmp
			vars
				gmp
					stddef
					limits
				map
					stdlib
					string
					stdio
					va-if
					int-types
						stdint
	ops
		va-if
		vars
*/

#include "dsl-parser.h" // "dsl-lexer.h", "dsl-ops.h", "dsl-except.h", "setjmp.h", "dsl-vars.h", <gmp.h>

#ifdef _WIN32
	#include <windows.h>
#else
	#include <sys/ioctl.h>
	#include <unistd.h>
	#include <time.h>
#endif

#define DSL_MAJOR "1"
#define DSL_MINOR "5"
#define DSL_MICRO "0a" // patch version
#define DSL_VERSION DSL_MAJOR "." DSL_MINOR "." DSL_MICRO

#ifdef _WIN32
	#define DSL_PLATFORM "win32"
#elifdef __linux__
	#define DSL_PLATFORM "linux"
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

// the argument should be an identifier, but it can be either `prgm_t` or `vstring_list`
#define free_prgm(prgm) ({               \
	free(prgm.array->ptr - sizeof(u64)); \
	free(prgm.array);                    \
	prgm = (typeof(prgm)) {};            \
	(void) 0;                            \
})

typedef union {
	u64 raw;

	__attribute__((packed)) struct {
		union { u32 rows, height, lines; };
		union { u32 cols, width; };
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

static wide_buf dsl_out_buf;
static wide_buf dsl_scratch;
static prgm_t   dsl_out_prgm;
static u64      dsl_total_bytes;
static u8       dsl_total_lines; // using `u8` is for the wrapping behavior

#ifdef _WIN32
static term_size_t term_size(void) {
	// returns all zeros on failure

	// this API is genuinely retarded. Why are we using constant casing for fucking types?
	// whoever at microsoft came up with this shitass naming scheme should be hanged. fuck you
	CONSOLE_SCREEN_BUFFER_INFO csbi;

	// Yo microsoft, have you heard about abbreviations? Perhaps STDOUT_HANDLE? STDIN_HANDLE?
	// Imaging not making a bullshit API
	u32 handles[] = {STD_OUTPUT_HANDLE, STD_INPUT_HANDLE, STD_ERROR_HANDLE};

	for (u8 i = 0; i < 3; i++) {
		HANDLE h = GetStdHandle(handles[i]);

		if (h == INVALID_HANDLE_VALUE || h == nullptr)
			continue;

		if (!GetConsoleScreenBufferInfo(h, &csbi))
			continue;

		return (term_size_t) {
			.cols = (u32) (csbi.srWindow.Right  - csbi.srWindow.Left + 1),
			.rows = (u32) (csbi.srWindow.Bottom - csbi.srWindow.Top  + 1),
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

		nanosleep(&ts, nullptr);
	#endif
}

#define IS_RAW_LINE(LINE) ({                           \
	const vstring line_ = (LINE);                      \
	likely(line_.len >= _strlen("%raw[]"))             \
		&& unlikely(*(u32 *)line_.ptr == MC32('%raw')) \
		&& likely(line_.ptr[_strlen("%raw")] == '[')   \
		&& likely(line_.ptr[line_.len - 1] == ']');    \
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
		char *null_pos = memchr(buf, '\0', *(u64 *) (buf - sizeof(u64)));

		if unlikely(null_pos != nullptr) {
			if (null_pos < buf) unreachable();

			eprintf("program contains null character at position %zu.", (u64) (null_pos - buf) + 1);
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
		if likely (!IS_RAW_LINE(line)) {
			u64 r = 0, w = 0; // read, write

			while (true) {
				char *const pipe = memchr(line.ptr + r, '|', line.len - r);

				if (pipe == nullptr) {
					// the line does not contain a comment
					if likely (r != 0) {
						memmove(line.ptr + w, line.ptr + r, line.len - r);

						// NOTE: `r - w` is the number of escaped pipe characters
						line.len -= r - w;
					}

					break;
				}

				if (pipe < line.ptr) unreachable();
				const u64 p = (u64) (pipe - line.ptr); // pipe index
				const u64 l = p - r; // length

				// preface with `pipe > line.ptr` to avoid out of bounds read
				if (p != 0 && pipe[-1] == '\\') {
					// backslashes can't also be escaped, so don't worry about counting backslashes

					pipe[-1] = '|';
					if likely (r != 0)
						memmove(line.ptr + w, line.ptr + r, l);

					w += l;
					r  = p + 1; // NOTE: same as `r += l + 1;`
				}
				else {
					// actual comment character

					if likely (r != 0)
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
		if likely (i != 0)
			empty_lines += line.len == 0;
	} // for

	if unlikely (empty_lines == 0)
		return true;

	// remove empty lines
	// start at r = w = 1 because the first line can never be removed, even if it is empty.
	for (u64 r = 1, w = 1, empty_remaining = empty_lines; r < in_prgm.count; r++) {
		if (in_prgm.array[r].len == 0) {
			empty_remaining--;

			if (empty_remaining == 0) {
				// copy over the rest
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

static void reset_scratch(void) {
	// reset the temporary buffer (usage=0) and potentially shrink via EMA heuristic

	dsl_total_bytes += dsl_scratch.usage;
	dsl_total_lines++;

	dsl_scratch.usage = 0;

	if likelyp (dsl_total_lines & 63, 1.0d / 64)
		// only check every so often
		return;

	// exponential moving average
	if likelyp (dsl_total_lines == 0, 1.0d / 128) {
		// 8-bit integer overflow. also note, the increment already happened.
		dsl_total_lines = 128;
		dsl_total_bytes >>= 1;
	}

	// mean
	u64 target = dsl_total_bytes / dsl_total_lines;

	// 50% slack
	target += target >> 1;

	static_assert((PAGE_SIZE & (PAGE_SIZE - 1)) == 0, "power of 2");
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

static void push_line(vstring line) {
	// a return of false means OOM
	// both the buffer and the array double on resize
	if (line.len == 0)
		return;

	// resize dsl_out_prgm
	if unlikely (dsl_out_prgm.count >= dsl_out_prgm.cap) { // dsl_out_prgm.count + 1 > dsl_out_prgm.cap
		const u64 new_cap = dsl_out_prgm.cap <<= 1;

		vstring *const new_array = realloc(dsl_out_prgm.array, new_cap * sizeof(*dsl_out_prgm.array));

		if unlikely (new_array == nullptr) {
			eprintf("%s realloc failed. could not allocate %zu bytes.",
				"array", new_cap * sizeof(*dsl_out_prgm.array));
			goto oom;
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
	if unlikely (tmp_buf.usage >= tmp_buf.size) { // tmp_buf.usage + 1 > tmp_buf.size
		tmp_buf.size = 1llu << (64 - __builtin_clzll(tmp_buf.usage));
		char *const new_buf = realloc(tmp_buf.ptr, tmp_buf.size);

		if unlikely (new_buf == nullptr) {
			eprintf("%s realloc failed. could not allocate %zu bytes.", "buffer", tmp_buf.size);
			goto oom;
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

	return;
oom:
	*(u64 *) dsl_out_buf.ptr = dsl_out_buf.usage - sizeof(u64);
	dsl_panic(EXCEPT_ERR_OOM);
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
	bool debug
) {
	(void) is_valid_varname;
	(void) start_line;

	for (u64 i = 0; i < in_prgm.count; i++, reset_scratch()) {
		vstring line = in_prgm.array[i];

		if unlikely (IS_RAW_LINE(line)) {
			line.ptr += _strlen("%raw[");
			line.len -= _strlen("%raw[]");

			push_line(line);
		}
		else

		// TODO: when doing `%seteval`, set `dsl_except.dispatch_line` in case the lexer crashes.
		//       The lexer doesn't know the dispatch line, so it needs to be set before calling it.
		// TODO: when doing `%seteval`, set up a try/catch for in case there are invalid variables
		//       and the line needs to be expanded fully to be valid
		// TODO: after expanding, if the line starts with '\%', ptr++ and len-- and push the line as is.

		// TODO: do the other constructs
		if (debug)
			printf("// DEBUG: UNKNOWN LINE: \e[32m|\e[m%.*s\e[32m|\e[m\n", (int) line.len, line.ptr);
	}

	// just do this at every depth since the depth isn't stored here anymore. It can't hurt
	*(u64 *) dsl_out_buf.ptr = dsl_out_buf.usage - sizeof(u64);
}


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

	if unlikely (dsl_out_prgm.array == nullptr)
		goto catastrophic_oom;

	dsl_out_buf = (wide_buf) {
		.ptr   = malloc(PAGE_SIZE),
		.usage = sizeof(u64),
		.size  = PAGE_SIZE,
	};

	if unlikely (dsl_out_buf.ptr == nullptr)
		goto catastrophic_oom;

	if unlikely (!strip_lines(&in_prgm)) {
		// this vague message is okay becayse strip_lines gives its own more detailed message.
		eprintf("errors were encountered.");
		goto done;
	}

	// all three sections in the variable value section have to be the same size
	static_assert(sizeof(mpz_t) == 16 && sizeof(i128) == 16 && sizeof(vstring) == 16);

	volatile const map_hash_t old_map_key = map_key();
	map_init_key();

	// set up `dsl_vars`
	{
		char *term_width, *term_height;
		term_size_t term = term_size();

		if likely (term.raw != 0) {
			// max required size is 11 including the null byte
			term_width = malloc(16);

			if unlikely (term_width == nullptr)
				goto catastrophic_oom;

			term_height = malloc(16);

			if unlikely (term_height == nullptr)
				goto catastrophic_oom;

			sprintf(term_width , "%u", term.width);
			sprintf(term_height, "%u", term.height);
		} else {
			term_width  = (char *) "";
			term_height = (char *) "";
		}

	#if DEBUG
		if unlikely (dsl_vars != nullptr)
			fatal(1, "[BUG] `dsl_vars` is not null at the start of `preproc`.");
	#endif

		dsl_vars = Map_create();

		if unlikely (dsl_vars == nullptr)
			goto catastrophic_oom;

		// add requested starting variables
		for (u64 i = 0; i < start_vars.count; i++) {
			const MapEntryCView entry = start_vars.array[i];

			// convert from `char * => char *` to `var_key_t => var_val_t`
			var_key_t *pkey = malloc(sizeof(var_key_t));
			if unlikely (pkey == nullptr)
				goto catastrophic_oom;

			pkey->ptr = entry.key;
			pkey->len = strlen(entry.key);

			var_val_t *pval = malloc(sizeof(var_val_t));
			if unlikely (pval == nullptr)
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
				if unlikely (pkey == nullptr)
					goto catastrophic_oom;

				pkey->ptr = entry.key;
				pkey->len = strlen(entry.key);

				var_val_t *pval = malloc(sizeof(var_val_t));
				if unlikely (pval == nullptr)
					// don't bother freeing `pkey` since this just crashes anyway
					goto catastrophic_oom;

				pval->type    = VAR_STR;
				pval->str.ptr = entry.val;
				pval->str.len = strlen(entry.val);

				dsl_set_var(pkey, pval);
			} // for
		} // end bare block

		if likely (term.raw != 0) {
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

	if unlikely (dsl_scratch.ptr == nullptr)
		goto catastrophic_oom;

	dsl_total_bytes = 0;
	dsl_total_lines = 0;

	dsl_try_root(
	case 0:
		_preproc(in_prgm, /*start_line*/ 0, debug);
		{
			char *expr = (char *)
				"(((1))) ^ (~~2) . &&$term_width * (&7_3_4_1 / (10 + ~8)) %"
				"--9 + -10 << &-11 >> 12$term_height xor 13 or +14 xor 15 + 2^-3";

			printf("test expr: %s\n", expr);

			token_list tokens = lex((vstring) {
				.ptr = expr,
				.len = strlen(expr),
			});

			printf(" out expr: ");
			log_tokens_expr(tokens);
			log_tokens(tokens);
			free(tokens.array);
		}
		break;
	default:
		// TODO: check for the specific exit codes
		// NOTE: only negative codes are for errors
		if (res < 0)
			eprintf("preproc failed on line %zu with exit code %zd.", dsl_except.dispatch_line, res);
		break;
	);

	free(dsl_scratch.ptr);
	dsl_scratch = (wide_buf) {
		.ptr   = nullptr,
		.usage = 0,
		.size  = 0,
	};

	// replace the final newline with null

	puts("vars:");

	// destroy the variable map
	Map_foreach(dsl_vars,
		dsl_dump_var((var_t *) p2entry);
		dsl_free_var((var_t *) p2entry);
	);

	Map_destroy_shallow_ref(&dsl_vars);

	map_key(old_map_key); // restore the original key
done:
	if unlikely (dsl_out_prgm.count == 0) {
		// NOTE: this assumes dsl_out_prgm.size is at least 1
		dsl_out_prgm.count = 1;

		dsl_out_prgm.array[0] = (vstring) {
			.ofs = sizeof(u64),
			.len = 0,
		};
	}

	dsl_out_buf.ptr = realloc(dsl_out_buf.ptr, dsl_out_buf.usage + 1); // shrink buffer
	dsl_out_buf.ptr[dsl_out_buf.usage++] = '\0';

	for (u64 i = 0; i < dsl_out_prgm.count; i++)
		dsl_out_prgm.array[i].ptr = dsl_out_buf.ptr + dsl_out_prgm.array[i].ofs;

#if DEBUG
	if unlikely (dsl_out_prgm.array->ptr != dsl_out_buf.ptr + sizeof(u64))
		eprintf("`dsl_out_prgm.array->ptr` and `dsl_out_buf.ptr + 8` don't match.");
#endif

	// shrink line arrray
	dsl_out_prgm.array = realloc(dsl_out_prgm.array, dsl_out_prgm.count * sizeof(*dsl_out_prgm.array));

	return (vstring_list) {
		.array = dsl_out_prgm.array,
		.count = dsl_out_prgm.count,
	};

catastrophic_oom:
	fatal(1, "catastrophic OOM.");
}
