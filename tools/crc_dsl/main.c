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

#include "dsl-main.h" // <stdlib.h>, <stdint.h>, <string.h>, <stdio.h>, "map.h", "va-if.h", "setjmp.h"

#ifdef _WIN32
	#define fseek _fseeki64_nolock
	#define ftell _ftelli64_nolock
#endif

[[gnu::pure]]
FORCE_INLINE static u64 cstr_count_nonempty_lines(const char *buf) {
	// count lines, except ignore empty lines.
	// assumes null termination at buf[n]
	const char *const orig_buf = buf;
	const u64 n = *(u64 *) (buf - sizeof(u64));
	u64 lines = 0;

	if (n == 0 || memchr(buf, '\0', n) != nullptr)
		return 0;

	if (buf[0] == '\n')
		// the first line is always included
		lines++;

	while (true) {
		buf++;
		buf = memchr(buf, '\n', n - /*i*/ (u64) (buf - orig_buf));

		if (buf == nullptr)
			break;

		if (buf[0] == '\n' && buf[-1] != '\n')
			lines++;
	}

	if (orig_buf[n - 1] != '\n')
		lines++;

	return lines;
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
	u64 line_cap = 0;
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
	line_cap = cstr_count_nonempty_lines(buf);

	if unlikely (line_cap == 0) {
		free(buf - sizeof(u64));
		result = PARSE_LINES_ENULL;
		goto done;
	}

	lines.array = (vstring *) malloc(line_cap * sizeof(*lines.array));

	if unlikely (lines.array == nullptr) {
		free(buf - sizeof(u64));
		lines.count = line_cap; // for the diagnostic messages
		result = PARSE_LINES_EOOM;
		goto done;
	}

	vstring line = {
		.ptr = buf,
		.len = 0,
	};

	for (char *pc = buf; *pc != '\0'; pc++) {
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
		ewprintf("lines.count (%zu) != line_cap (%zu)\n", lines.count, line_cap);
#endif

	*out_lines = lines;

	return result;

	#undef line_cap
}

#ifdef _WIN32
u8 mainCRTStartup(void);
u8 mainCRTStartup(void)
#else
u8 main(u32 argc, char **argv);
u8 main(u32 argc, char **argv)
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

#if DEBUG
	puts("debug: on");
#else
	puts("debug: off");
#endif

	// skip EXE path
	argc--;
	argv++;

	if (argc == 0)
		return 0;

	if (argc > 1)
		ewprintf("only the first argument is used. ignoring %u arguments.", argc - 1);

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
				eprintf("input file could not be opened.");
				return ret;
			case PARSE_LINES_ESEEK:
				eprintf("input file could not be seeked.");
				return ret;
			case PARSE_LINES_EOOM:
				eprintf("OOM. requested %zu bytes.", in_prgm.count * sizeof(vstring));
				return ret;
			case PARSE_LINES_ENULL:
				eprintf("file contains a null byte.");
				return ret;
		#if DEBUG
			case PARSE_LINES_EBUG1:
				eprintf("[BUG] not enough lines allocated. allocated %zu.", in_prgm.count);
				return ret;
			case PARSE_LINES_EBUG2:
				eprintf("[BUG] first line pointer is not 8 bytes past a freeable pointer.");
				return ret;
		#endif
			default:
				unreachable();
		}
	} // bare block

#if DEBUG
	puts("original file:");
	if (in_prgm.count != 0)
		printf("%s\n", in_prgm.array->ptr);

	puts("----------------------------------------------------------------------");
#endif

	printf("in_prgm: %zu line(s):\n", in_prgm.count);
	for (u64 i = 0; i < in_prgm.count; i++)
		printf("%.*s\n", (int) in_prgm.array[i].len, in_prgm.array[i].ptr);

	puts("----------------------------------------------------------------------");
	puts("preproc:");
	vstring_list out_prgm = preproc(in_prgm, /*vars*/ (MapEntryCList) {}, true);

	puts("----------------------------------------------------------------------");
	printf("out_prgm: %zu line(s):\n" "%s\n", out_prgm.count, out_prgm.array->ptr);

	free_prgm(in_prgm);
	free_prgm(out_prgm);
	return 0;
}
