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

static const char *const help_text = 
    "Calculator - Help"
    "\n"
    "\nCOMMANDS"
    "\n    help                       print this help text"
    "\n    quit / exit                exit the program"
    "\n    del $var / del ${var}      delete a variable"
    "\n    reset                      delete all variables"
    "\n    dump                       print all defined variables and their types"
    "\n"
    "\nINPUT"
    "\n    Each line is either a standalone expression or an assignment:"
    "\n        1 + 2 + 3"
    "\n        $x = 1 + 2"
    "\n        $abc = $abc ^ $abc;"
    "\n"
    "\n    End a line with ';' to suppress printing the result."
    "\n    Assignments cannot be nested (e.g. $x = $y = 1 is not allowed)."
    "\n    Invalid input prints an error but is otherwise ignored."
    "\n"
    "\n    All input, intermediate, and output values are integers."
    "\n"
    "\n    if command-line arguments are given, they are concatenated together"
    "\n    with a space in-between and parsed as one command"
    "\n"
    "\nVARIABLES"
    "\n    Reference a variable as $name or ${name}."
    "\n    Adjacent values are implicitly concatenated (see CONCATENATION below)."
    "\n"
    "\nOPERATORS  (highest to lowest precedence)"
    "\n    ( )        grouping"
    "\n    unary      +x  -x  ~x  !x  &x"
    "\n                   +x   no-op"
    "\n                   -x   two's-complement negation"
    "\n                   ~x   one's-complement negation"
    "\n                   !x   logical negation (0 => 1, other => 0)"
    "\n                   &x   absolute value"
    "\n    ^          exponentiation"
    "\n    .          concat or combine"
    "\n    * / %      multiplication, truncating division, truncating modulo"
    "\n    + -        addition, subtraction"
    "\n    << >>      bitwise left/right shift"
    "\n    <<< >>>    bitwise left/right rotation"
    "\n    and        bitwise and"
    "\n    or  xor    bitwise or, bitwise xor"
    "\n"
    "\n    Negative shift/rotate amounts reverse direction:"
    "\n        x <<  -y ==  x >>  y     x >> -y  ==  x << y"
    "\n        x <<< -y ==  x >>> y     x >>> -y ==  x <<< y  (infinite two's complement)"
    "\n"
    "\n    x . y:"
    "\n        if y > 0:  concatenates x and y digit-wise in base 10"
    "\n        else:      (x . -y) + 2*y"
    "\n"
    "\nCONCATENATION"
    "\n    Adjacent primaries (literals and variables with nothing between them) are"
    "\n    concatenated as if joined by '.', except concatenation by juxtaposition"
    "\n    binds tighter than everything else. all literals are parsed as positive,"
    "\n    so: $x-2$y means $x - (2 . $y), not ($x . -2 . $y)."
    "\n    $x $y $z is an error, while $x$y$z works.";

static vstring line;

static bool read_line(void) {
	// returns true if a line was read

#if defined(__linux__) || defined(__APPLE__) || defined(__unix__)
	static u64 cap;

	i64 n = getline(&line.ptr, &cap, stdin);
	if (n < 1)
		return false;

	if (/*n > 0 &&*/ line.ptr[n - 1] == '\n')
		n--;

	line.len = (u64) n;
	return true;
#else // portable fallback (Windows, or anything without getline)
	static u64 cap = 1; // this cannot be 0, or it will not work.

	u64 len = 0;
	while (true) {
		if (len + 1 >= cap) {
			line.ptr = realloc(line.ptr, cap <<= 1);

			if (line.ptr == nullptr)
				dsl_oom();
		}

	#ifdef _WIN32
		int c = _getc_nolock(stdin);
	#else
		int c = getc(stdin);
	#endif

		if (c == EOF) {
			if (len == 0)
				return false;

			break;
		}

		if (c == '\n')
			break;

		line.ptr[len++] = (char) c;
	}

	line.len = len;
	return true;
#endif
}

static vstring get_expr_varname(char *equals) {
	// on failed check, .ptr = nullptr

	char *p = line.ptr;

	// skip \s*
	while (p < equals && line_isspace(*p))
		p++;

	// skip '$'
	if (p >= equals || *p != '$')
		return (vstring) {};
	p++;

	// skip '{'
	const bool braced = p < equals && *p == '{';
	if (braced)
		p++;

	// skip \w+
	char *const name_start = p;

	while (p < equals && (isalnum(*p) || *p == '_'))
		p++;

	char *const name_end = p;

	if (name_end == name_start)
		// "$ =" or "${} = "
		return (vstring) {};

	// skip '}'
	if (braced) {
		if (p >= equals || *p != '}')
			return (vstring) {};

		p++;
	}

	// skip \s+
	while (p < equals && line_isspace(*p))
		p++;

	if (p != equals)
		return (vstring) {};

	return (vstring) {
		.ptr = name_start,
		.len = (u64) (name_end - name_start)
	};
}

#define EXCEPT_ERR_VARNAME -700

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

	// skip EXE path
	argc--;
	argv++;

	volatile bool interactive = argc == 0;

	if (!interactive) {
		// I'd say this VLA is okay because if you give like 500,000 arguments and it stack overflows,
		// then maybe that is your problem. at that point, just wrap it in quotes.
		vstring vargs[argc];

		u64 size = 0; // the left-out +1 for the null cancels out with the extra +1 from the spaces

		for (u32 i = 0; i < argc; i++) {
			const u64 len = strlen(argv[i]);
			vargs[i] = (vstring) {
				.ptr = argv[i],
				.len = len
			};

			size += len + /*space*/ 1;
		}

		if (size == 0)
			fatal(1, "SOF cannot immediately be followed by EOF.");

		line = (vstring) {
			.ptr = malloc(size),
			.len = size - 1, // don't include the null byte
		};

		if (line.ptr == nullptr)
			fatal(1, "out of memory.");

		char *end = line.ptr;

		for (u32 i = 0; i < argc; i++) {
			memcpy(end, vargs[i].ptr, vargs[i].len);
			end += vargs[i].len;
			*end++ = ' ';
		}

		end--;
		*end = '\0';

		// this will basicaly only ever run if you pass one argument.
		if (
			(line.len == _strlen("--help") && strcmp(line.ptr, "--help") == 0) ||
			(line.len == _strlen("-h")     && strcmp(line.ptr, "-h")     == 0) ||
			(line.len == _strlen("-?")     && strcmp(line.ptr, "-?")     == 0)
		) {
			puts(help_text);
			free(line.ptr); // so ASan shuts up.
			return 0;
		}
	}


	// all three sections in the variable value section have to be the same size
	static_assert(sizeof(mpz_t) == 16 && sizeof(i128) == 16 && sizeof(vstring) == 16);

	map_init_key();
	dsl_vars = Map_create();

	volatile bool retry = interactive;

try_root_start:
	dsl_try_root(
	case 0:
		while (!interactive || read_line()) {
			lstrip_line(line);
			rstrip_line(line);

			if (line.len == 0)
				// skip empty lines
				continue;

			if (line.len == 4) {
				// four-byte commands
				if (memcmp(line.ptr, "quit", 4) == 0 || memcmp(line.ptr, "exit", 4) == 0)
					dsl_panic(EXCEPT_ERR_OK);
				else if (memcmp(line.ptr, "dump", 4) == 0) {
					if (Map_count(dsl_vars) == 0)
						puts("no variables present.");
					else
						Map_foreach(dsl_vars,
							dsl_dump_var((var_t *) p2entry);
						);
					continue;
				}
				else if (memcmp(line.ptr, "help", 4) == 0) {
					puts(help_text);
					continue;
				}
			}
			else if (line.len >= 5 && memcmp(line.ptr, "del $", 5) == 0) {
				vstring varname = line;
				varname.ptr += _strlen("del $");
				varname.len -= _strlen("del $");

				if (*varname.ptr == '{') {
					varname.ptr += _strlen("{");
					varname.len -= _strlen("{}");
				}

				printf("deleting $%.*s. map length = %zu\n",
					(int) varname.len, varname.ptr, Map_count(dsl_vars)
				);
				fflush(stdout);
				dsl_del_var(varname);
				printf("map length = %zu\n", Map_count(dsl_vars));
				fflush(stdout);
				continue;
			}
			else if (line.len == 5) {
				// there is only one 5-byte command
				if (memcmp(line.ptr, "reset", 5) == 0) {
					Map_foreach(dsl_vars,
						dsl_free_var((var_t *) p2entry);
					);

					Map_destroy_shallow_ref(&dsl_vars);
					map_init_key();
					dsl_vars = Map_create();
					continue;
				}
			}

			const bool echo = line.ptr[line.len - 1] != ';';

			if (!echo) {
				line.len--;

				rstrip_line(line); // skip whitespace before the semicolon

				if (line.len == 0)
					// non-echoing blank line
					continue;
			}

			char *const equals = memchr(line.ptr, '=', line.len);

			const bool set  = equals != nullptr;

			vstring expr = line;

			if (set) {
				const u64 i = (u64) (equals - line.ptr);
				expr.ptr += i + 1;
				expr.len -= i + 1;
			}

			{
				var_val_t result = dsl_eval(expr);

				if (set) {
					vstring varname = get_expr_varname(equals);

					if (varname.ptr == nullptr) {
						dsl_clear_val(result);
						eprintf("invalid variable name.");
						dsl_panic(EXCEPT_ERR_VARNAME);
					}

					{
						// the key pointer needs to be a freeable pointer for `dsl_set_var` to work.
						char *const tmp = malloc(varname.len + 1);
						if (tmp == nullptr) {
							dsl_clear_val(result);
							dsl_oom();
						}

						memcpy(tmp, varname.ptr, varname.len);
						tmp[varname.len] = '\0';

						varname.ptr = tmp;
					}

					var_key_t *key = malloc(sizeof(var_key_t));
					if (key == nullptr) {
						dsl_clear_val(result);
						dsl_oom();
					}

					var_val_t *val = malloc(sizeof(var_val_t));
					if (val == nullptr) {
						dsl_clear_val(result);
						dsl_oom();
					}

					*key = varname;
					*val = result;

					if (echo)
						dsl_puts_val(result);

					dsl_set_var(key, val);
					// no clear since there is still a reference.
				} // if set
				else {
					if (echo)
						dsl_puts_val(result);

					dsl_clear_val(result);
				} 
			} // bare block

			if (!interactive)
				break;
		} // while

		// ^D on Linux

		[[fallthrough]];
	case EXCEPT_ERR_OK:
		retry = false;
		break;
	{ // errors
		__label__ _default;
		const char *err_msg;
	case EXCEPT_ERR_OOM:     err_msg = "OOM";                      goto _default;
	case EXCEPT_ERR_DEPTH:   err_msg = "exception depth exceeded"; goto _default;
	case EXCEPT_ERR_LEXER:   err_msg = "lexer error";              goto _default;
	case EXCEPT_ERR_PARSER:  err_msg = "parser error";             goto _default;
	case EXCEPT_ERR_VARNAME: err_msg = "variable error";           goto _default;
	default:
		err_msg = "unknown error";
		if (res < 0)
		_default:
			eprintf("evaluation failed with exit code %zd: %s.", res, err_msg);
		break;
	}
	);

	if (retry)
		goto try_root_start;

	free(line.ptr);
	Map_foreach(dsl_vars,
		dsl_free_var((var_t *) p2entry);
	);

	Map_destroy_shallow_ref(&dsl_vars);
	return 0;
}
