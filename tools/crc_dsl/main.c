#ifdef _WIN32
	#define _UCRT
	#include <corecrt_startup.h>
	#define _STDSTREAM_DEFINED

	// `FILE` isn't defined yet, but it basically doesn't matter. `void` also works
	[[maybe_unused]] static void *stdin, *stdout, *stderr;
#endif

#ifndef DEBUG
	#define DEBUG false
#endif

#include <stdlib.h>
#include <stdio.h>
#include "crc-dsl.h" // <stdlib.h>, <stdint.h>, <string.h>, "map.h", "va-if.h", "setjmp.h"

#ifdef _WIN32
	#define fseek _fseeki64_nolock
	#define ftell _ftelli64_nolock
#endif

[[gnu::pure]]
FORCE_INLINE static u128 cstr_count_nonempty_lines(const char *buf) {
	// count lines, except ignore empty lines.
	// assumes null termination
	const char *const orig_buf = buf;
	u64 lines = 0;

	if unlikely (buf[0] == '\0')
		return 1; // 0 characters. 0 lines, but say 1 anyway.

	if (buf[0] == '\n')
		// the first line is always included
		lines++;

	do {
		buf++;

		if (buf[0] == '\n' && buf[-1] != '\n')
			lines++;
	} until (buf[0] == '\0');

	if (buf[-1] != '\n')
		lines++;

	return (u128)(buf - orig_buf) << 64 | lines;
}

#define PARSE_LINES_EOK			0
#define PARSE_LINES_EOPEN		1
#define PARSE_LINES_ESEEK		2
#define PARSE_LINES_EOOM		3
#define PARSE_LINES_ENULL		4
#if DEBUG
	#define PARSE_LINES_EBUG1	5 // not enough lines were allocated
	#define PARSE_LINES_EBUG2	6 // entry 0 pointer is not the buffer start
#endif

static u8 parse_lines(char *file_path, vstring_list *out_lines) {
	u8 result = 0;
	u128 file_data = 0;
	vstring_list lines = {
		.array = nullptr,
		.count = 0,
	};
	char *buf = nullptr;

	// open file
	FILE *f = fopen(file_path, "r");

	if unlikely (f == nullptr) {
		result = PARSE_LINES_EOPEN;
		goto done;
	}

	if unlikely (fseek(f, 0, SEEK_END) != 0) {
		fclose(f);
		result = PARSE_LINES_ESEEK;
		goto done;
	}

	// read in the file contents
	u64 n = (u64) ftell(f);
	fseek(f, 0, SEEK_SET);

	buf = (char *) malloc(sizeof(u64) + n + 1);

	if unlikely (buf == nullptr) {
		fclose(f);
		result = PARSE_LINES_EOOM;
		goto done;
	}

	n = fread(buf + sizeof(u64), sizeof(char), n, f);
	fclose(f);

	*(u64 *) buf = n;
	buf += sizeof(u64);
	buf[n] = '\0';

	// parse into lines
	file_data = cstr_count_nonempty_lines(buf);

	#define line_cap ((u64) file_data)

	lines.array = (vstring *) malloc(line_cap * sizeof(*lines.array));

	if unlikely (lines.array == nullptr) {
		free(buf - sizeof(u64));
		lines.count = line_cap; // for the diagnostic messages
		result = PARSE_LINES_EOOM;
		goto done;
	}

	if unlikely ((u64) (file_data >> 64) != n) {
		free(buf - sizeof(u64));
		lines.count = line_cap; // for the diagnostic messages
		result = PARSE_LINES_ENULL;
		goto done;
	}

	vstring line = {
		.ptr = buf,
		.len = 0,
	};

	for (char *pc = buf; likely(*pc != '\0'); pc++) {
		if likely (*pc != '\n') {
			line.len++;
			continue;
		}

		if (line.len == 0 && lines.count != 0) {
			// don't add empty lines to the list
			// unless it is the first string, then add it anyway
			line.ptr++;
			continue;
		}

	#if DEBUG
		if unlikely (lines.count >= line_cap) {
			result = PARSE_LINES_EBUG1;
			goto done;
		}
	#endif

		lines.array[lines.count++] = line;
		line.len = 0;
		line.ptr = pc + 1;
	} // for

	if (line.len != 0 || lines.count == 0) {
		// add the last line if it is non-empty or also the first line

	#if DEBUG
		if unlikely (lines.count >= line_cap) {
			result = PARSE_LINES_EBUG1;
			goto done;
		}
	#endif

		lines.array[lines.count++] = line;
	}

done:
#if DEBUG
	// NOTE: with low optimization, this thinks `lines.array->ptr` can be used
	//       uninitialized, but that is wrong. If the pointer is nonnull, it is
	//       always initialized.
	if unlikely (lines.array != nullptr && lines.array->ptr != buf) {
		free(buf - sizeof(u64));
		free(lines.array);
		return PARSE_LINES_EBUG2;
	}

	if unlikely (lines.count != line_cap)
		// this is not a hard error, so it can still return `result == 0` in this case.
		ewprintf("WARNING: parse_lines: lines.count (%zu) != line_cap (%zu)\n",
			lines.count, line_cap);
#endif

	*out_lines = lines;

	return result;

	#undef line_cap
}

#ifdef _WIN32
u8 mainCRTStartup(void);
u8 mainCRTStartup(void)
#else
int main(int argc, char **argv);
int main(int argc, char **argv)
#endif

{

#ifdef _WIN32
	u32 argc;
	char **argv;
	_initialize_narrow_environment();
	_configure_narrow_argv(_crt_argv_unexpanded_arguments);

	argc = (u32) *__p___argc();
	argv =       *__p___argv();

	stdin  = __acrt_iob_func(0);
	stdout = __acrt_iob_func(1);
	stderr = __acrt_iob_func(2);
#endif

	// skip EXE path
	argc--;
	argv++;

	if (argc == 0)
		goto extra_stuff;

	// lines.array[i] are views into a buffer. they should not be freed independently.
	// lines.array[0].ptr is always a pointer to the start of a valid C string.
	// lines.array[0].ptr - sizeof(u64) is always freeable
	// *(u64 *) (lines.array[0].ptr - sizeof(u64)) is the number of characters in the buffer
	vstring_list in_prgm;
	{
		const u8 ret = parse_lines(*argv, &in_prgm);

		switch (ret) {
			case PARSE_LINES_EOK:
				break;
			case PARSE_LINES_EOPEN:
				eprintf("input file could not be opened.\n");
				return ret;
			case PARSE_LINES_ESEEK:
				eprintf("input file could not be seeked.\n");
				return ret;
			case PARSE_LINES_EOOM:
				eprintf("OOM. requested %zu bytes.\n", in_prgm.count * sizeof(vstring));
				return ret;
			case PARSE_LINES_ENULL:
				eprintf("file line %zu contains a null byte.\n", in_prgm.count + 1);
				return ret;
		#if DEBUG
			case PARSE_LINES_EBUG1:
				eprintf("BUG: not enough lines allocated. allocated %zu.\n", in_prgm.count);
				return ret;
			case PARSE_LINES_EBUG2:
				eprintf("BUG: first line pointer is not 8 bytes past a freeable pointer.\n");
				return ret;
		#endif
			default:
				__builtin_unreachable();
		}
	}

	puts("original file:");
	if (in_prgm.count != 0)
		printf("%s\n", in_prgm.array->ptr);

	puts("----------------------------------------------------------------------");
	printf("line-parsed in_prgm: %zu line(s):\n", in_prgm.count);
	for (u64 i = 0; i < in_prgm.count; i++)
		printf("%.*s\n", (int) in_prgm.array[i].len, in_prgm.array[i].ptr);

	puts("----------------------------------------------------------------------");
	puts("preproc:");
	vstring_list out_prgm = preproc(in_prgm, (MapEntryCList) {}, true);

	puts("----------------------------------------------------------------------");
	printf("out_prgm: %zu line(s):\n", out_prgm.count);
	/*for (u64 i = 0; i < out_prgm.count; i++)
		printf("%.*s\n", (int) out_prgm.array[i].len, out_prgm.array[i].ptr);*/

	printf("%s\n", out_prgm.array->ptr);

	free_prgm(in_prgm);
	free_prgm(out_prgm);

extra_stuff:
	{
		jmp_buf env;
		u64 i = 1;
		force_mem(i);

		i64 ret = setjmp(&env);
		printf("\ri = %zu, ret=%zd", i, ret);
		#ifndef _WIN32
			// ucrt printf auto flushes in between, but glibc printf doesn't
			fflush(stdout);
		#endif

		i++;
		msleep(25);
		if (i <= 32)
			longjmp(&env, (i64) i);

		putchar('\n');
	}

	dsl_try_root(
	// before
		printf("dsl_try_root returned %zd\n", res),
	// cases
		case 0:
			dsl_panic(-300);
		default:
			break;
	);

	dsl_free_except();

	// test basic GMP functionality.
	{
		mpz_t a, b;
		char *str;

		mpz_init_set_ui(a, 123'456'789);
		mpz_init_set_ui(b, 987'654'321);

		str = mpz_get_str(NULL, 10, a); printf("a = %s\n", str); free(str);
		str = mpz_get_str(NULL, 10, b); printf("b = %s\n", str); free(str);
		mpz_mul(a, a, b);
		str = mpz_get_str(NULL, 10, a); printf("c = %s\n", str); free(str);
	}

	return 0;
}
