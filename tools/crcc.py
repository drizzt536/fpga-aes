#!/usr/bin/env python3

"""
HDL compiler for fully unrolled, fully-combinational CRC functions given a fixed-length, byte-aligned input.
batch jobs can be created through TOML input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than CRC32 is used.

during optimization, ^C makes a soft request to stop after the round ends. ^C a second time makes
it stop as soon as possible. The program has to be in focus for it to be noticed. ^C before and
after optimization takes place crashes the program as normal. this doesn't work in LNS.
"""

# TODO: perhaps give mean fanout in addition to max fanout? idk if arithmetic or geometric is better though.

prog = "crcc"

if __name__ != "__main__":
	raise Exception(f"{prog}.py should only be used at the top level.")

class MissingPackage:
	def __init__(self, name) -> None:
		self.name = name

	def __getattr__(self, attr) -> None:
		if attr == "__version__":
			return "(none)"

		# crash on first access
		raise Exception(f"package `{self.name}` was not found but is required.")

# let the compiler work standalone (mostly) with no other files
# these will fail later if they actually matter
# gf2_cse is still always needed though

try:
	import asm_gen
except ImportError:
	# only needed if `-fasm=...` is given
	asm_gen = MissingPackage("asm_gen")

try:
	import crc_dsl
	dsl_avail = True
except ImportError:
	# used for some stuff other than assembly, but still optional
	crc_dsl   = MissingPackage("crc_dsl")
	dsl_avail = False

del MissingPackage

import argparse
import gf2_cse
import pickle
import lzma
import sys
import os

from hashlib import sha256
from time    import perf_counter_ns

stderr  = sys.stderr
argv    = sys.argv
argv[0] = f"{prog}.py"

__version__ = gf2_cse.__version__

# the first alias per format key is the canonical one. the value is the file extension
formats = {
	("v"  , "verilog")                   : "v"     ,
	("sv" , "systemverilog")             : "sv"    ,
	("vhd", "vhdl")                      : "vhd"   ,
	("ch" , "chisel", "ch6" , "chisel6") : "scala" ,
	("ch3", "chisel3")                   : "scala" ,
	("sp" , "spinal", "spinalhdl")       : "scala" ,
	("am" , "amaranth")                  : "py"    ,
	("nmg", "nmigen")                    : "py"    ,
	("py" , "python")                    : "py"    ,
	("pyt", "python-test")               : "py"    ,
	("gv" , "dot", "graphviz")           : "gv"    ,
	("c"  ,)                             : "c"     ,
	("c++", "cpp")                       : "cpp"   ,
	("i", "info",)                       : "txt"   ,
	("metrics",)    : "txt"     , ("m",) : "txt"   ,
	("ir",)         : "txt"     , ("r",) : "txt"   ,
	("json",)       : "json"    , ("j",) : "json"  ,
	("nop", "noop") : "txt"     ,
}

asm_formats = (
	"json / asm=j", # this one is just used for printing
	"x86-ms-nasm"      , "x86-ms-masm"    , "x86-ms-gas"      ,
	"x86-sysv-nasm"    ,                    "x86-sysv-gas"    ,

	"x64-ms-nasm"      , "x64-ms-masm"    , "x64-ms-gas"      ,
	"x64-stm-nasm"                                            ,
	"x64-sysv-nasm"                       , "x64-sysv-gas"    ,
	"x64-apx-ms-nasm"  , "x64-apx-ms-masm", "x64-apx-ms-gas"  ,
	"x64-apx-stm-nasm"                                        ,
	"x64-apx-sysv-nasm"                   , "x64-apx-sysv-gas",

	# Microsoft ABI / System V ABI / Apple are give the same output
	"arm64-gas"        , "arm64-armasm",

	"ir:<flags>",
)

asm_ir_settings = {}
extension       = None

def format_validator(syntax: str) -> str:
	global extension, asm_ir_settings

	syntax = syntax.strip().lower()

	if syntax == "asm":
		extension = "asm"
		return "asm=x64-sysv-gas"

	if syntax.startswith("asm=amd64"):     syntax = "asm=x64" + syntax[9:]
	elif syntax.startswith("asm=aarch64"): syntax = "asm=arm64" + syntax[11:]

	if syntax.startswith("asm=ir"):
		extension = "caf" # CRC Assembly Format
		l = len("asm=ir")

		if len(syntax) == l:
			return syntax

		if syntax[l] == ':':
			for expr in syntax[l + 1:].split(':'):
				key, val = expr.split('=', 1)
				asm_ir_settings[key] = val.replace('_', '-')

			return syntax[:l]
	elif syntax.startswith("asm="):
		if syntax in {"asm=json", "asm=j"}:
			extension = "json"
			return syntax

		extension = "asm"

		if syntax.endswith("-clang"):
			syntax = syntax[:-5] + "gas"

		if syntax.startswith("asm=x64"):
			if syntax.endswith("-fasm"):
				# the NASM output is compatible with FASM
				syntax = syntax[:-4] + "nasm"
			elif syntax.endswith("-ms"):   syntax += "-masm"
			elif syntax.endswith("-stm"):  syntax += "-nasm"
			elif syntax.endswith("-sysv"): syntax += "-gas"
			elif syntax in {"asm=x64", "asm=x64-apx"}:
				syntax += "-sysv-gas"
		elif syntax.startswith("asm=x86"):
			if syntax.endswith("-fasm"):
				# the NASM output is compatible with FASM
				syntax = syntax[:-4] + "nasm"
			elif syntax.endswith("-ms"):   syntax += "-masm"
			elif syntax.endswith("-sysv"): syntax += "-gas"
			elif syntax == "asm=x86":      syntax += "-sysv-gas"
		elif syntax.startswith("asm=arm64"):
			if syntax == "asm=arm64" or syntax.endswith("-sysv") or syntax.endswith("-ms") or syntax.endswith("-apple"):
				syntax += "-gas"

			if   syntax[10:] in {"ms-gas"   , "sysv-gas"   , "apple-gas"   }: syntax = "asm=arm64-gas"
			elif syntax[10:] in {"ms-armasm", "sysv-armasm", "apple-armasm"}: syntax = "asm=arm64-armasm"

		if syntax[4:] in asm_formats:
			return syntax
	else:
		# not an assembly format

		for aliases in formats:
			if syntax in aliases:
				extension = formats[aliases]
				return aliases[0]

	raise argparse.ArgumentTypeError(f"invalid format '{syntax}'. see `--help=formats` / `-F` for a list of valid formats")

parser = argparse.ArgumentParser(
	add_help=False,
	description=f"%(prog)s {__version__}\ncrc_dsl {crc_dsl.__version__}\n{__doc__}",
	formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument("-h", "-?", "--help", "--help=options", action="help", help="show this help message and exit")
parser.add_argument("--help=formats"   , "-F", action="store_true", help="list available formats and exit")
parser.add_argument("--help=algorithms", "-A", action="store_true", help="list available algorithms and exit")
parser.add_argument("--help=toml", action="store_true", help="print out an example TOML program and exit")
if dsl_avail:
	parser.add_argument("--help=dsl", action="store_true", help="print out example DSL preprocessor code and exit")
parser.add_argument("--help=ir" , action="store_true", help="print IR format help")
parser.add_argument("--help=all" , action="store_true", help="print all the help stuff at once and exit")
parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")

core_group = parser.add_argument_group("core options")
core_group.add_argument("--algorithm", "--alg", "-a", type=lambda s: None if s is None else str.lower(s).strip(), help=f"CRC name (see --help=algorithms / -A). default is 'crc32'")
core_group.add_argument("--data-len", "-l", type=int, help="bytes length of checksum input data. default is 4")
core_group.add_argument("--syntax", "--format", "-f", type=format_validator, default="verilog", help=f"output language (see --help=formats / -F). default is 'verilog'")
core_group.add_argument("--output", "--out", "-o", type=str, default='-', help=f"output file. use 'auto' for automatic naming. default is '-' (stdout)")
core_group.add_argument("--lut-size", "-s", type=int, default=4, help="specify the FPGA LUT size. only effects verbose printouts and metrics.\n-1 is treated as infinity. default is 4")
core_group.add_argument("--verbose", "-v", type=int, help="set verbosity level. >=3 is the same as 2. <0 suppresses warnings.")

format_group = parser.add_argument_group("formatting options")
format_group.add_argument("--in-port", "--in-var", "-I", type=str, help="input port/variable name. default is 'data'")
format_group.add_argument("--out-port", "--out-var", "-O", type=str, help="output port/variable name. default is 'crc'")
format_group.add_argument("--tmp-name", "-t", type=str, help="tmp signal name. default is 'tmp'. may creates name collisions with software language-specific\nvariables. if it longer than the local signal name, it will cause misaligned expressions.")
format_group.add_argument("--indent", "-g", type=str.lower, help=f"indentation level. options are tabs, tab, none, or int n>=-1. default is 'tabs'")

custom_crc_group = parser.add_argument_group("custom CRC overrides", "custom mode triggers if `-p` / `--toml` / positional is given.")
program_group    = custom_crc_group.add_mutually_exclusive_group()
program_group.add_argument("--polynomial", "-p", type=str, help="value should include the uppermost bit (e.g. bit 33). mutually exclusive with `--toml`")
program_group.add_argument("programs", nargs='*', type=str, help="TOML file(s), inline TOML program(s), or a mix. (see --help=toml)." + (" uses DSL preprocessor (see --help=dsl). files are preprocessed separately" if dsl_avail else '')
)
custom_crc_group.add_argument("--init"   ,              "-i", type=int, help="initial value. default is 0")
custom_crc_group.add_argument("--xor-out",              "-x", type=int, help="final XOR mask. default is 0")
custom_crc_group.add_argument("--reflect", "-r", action="store_true"  , help="enable reflection. default is off")

optimize_group = parser.add_argument_group(
	"optimization settings",
	"optimizes for XOR2 gate count"
	"\ndefaults:"
	"\n   basic : off, lookahead depth 0 weight 1, nmax 2, beam size 1, prefer low n, min round reduction 1, no tmp max"
	"\n   LNS   : off, 3 trials, window size 3, unseeded"
	"\n   cache : clear off, read off, write off, delete off"
)
optimize_group.add_argument("--optimize"           , "-c", action="store_true", help="enable optimization without touching settings")
optimize_group.add_argument("--optimize-depth"     , "-d", type=int  , help="enable optimization and set search lookahead depth.")
optimize_group.add_argument("--optimize-nmax"      , "-n", type=int  , help="enable optimization and set n max.")
optimize_group.add_argument("--optimize-beam"      , "-b", type=int  , help="enable optimization and set beam size.")
optimize_group.add_argument("--optimize-weight"    , "-w", type=float, help="enable optimization and set the lookahead weighting")
optimize_group.add_argument("--optimize-seed"      , "-S", type=int  , help="enable optimization, switch to predictable mode, and set the MT19937 seed")
optimize_group.add_argument("--optimize-n-prefer"  , "-P", type=str  , help="enable optimization and set intersection count tie break preference", choices=("l", "lo", "low", "h", "hi", "high", "m", "mid", "r", "rand", "random"))
optimize_group.add_argument("--optimize-min-gates" , "-m", type=int  , help="enable optimization. exit optimization early when lookahead only sees gate reductions below\nthis threshold. false negatives are possible for >2 (it may optimize more than desired)")
optimize_group.add_argument("--optimize-max-tmps"  , "-M", type=int  , help="enable optimization. set tmp signal count for when the optimizer exits early.")
optimize_group.add_argument("--optimize-lns"       , "-L", action="store_true", help="enable optimization+LNS without touching settings. LNS is skipped on early exits.\nreconstruction is brute force")
optimize_group.add_argument("--optimize-lns-trials", "-T", type=int  , help="enable optimization+LNS and set the count.")
optimize_group.add_argument("--optimize-lns-window", "-W", type=int  , help="enable optimization+LNS and set the window size.")

cache_group = parser.add_argument_group("caching options")
cache_dir_group = cache_group.add_mutually_exclusive_group()
cache_dir_group.add_argument("--cache-dir"   , "-D", type=str  , help="change the cache directory. doesn't enable optimization. '~' and environment variables are\nexpanded. default is './crc-cache'.")
cache_dir_group.add_argument("--cache-global", "-G", action="store_true", help="use a user global cache directory. cannot appear with `--cache-dir`.")
cache_group.add_argument("--cache"           , "-C", type=str.lower, help="enable optimization and set cache behavior. combination of c/x: clear/expunge, o: off,\nr: read, w: write, u: use/read+write, d: delete entry. o may only appear with c/x. d must\nappear by itself. case insensitive. `%(prog)s -Cc` will clear the cache and exit. cache\nentries are never automatically invalidated, so they may return old values if the optimizer\nis updated. a manual cache clear is required in this case.")
args = parser.parse_args()

del core_group, format_group, custom_crc_group, optimize_group, cache_group, cache_dir_group, argparse

if not dsl_avail:
	setattr(args, "help=dsl", None)

gc_disabled = not hasattr(sys, "pypy_version_info")
del sys

if gc_disabled:
	# CPython uses reference counting, and the GC is only for cyclic references.
	# the program doesn't generate cyclic references, so this is safe. PyPy only
	# has tracing GC, so idk if this is a good idea in PyPy. it only disables
	# the major GC, but some of the optimizer stuff has deep call depths, and idk
	# how long something has to be alive to be considered long-living.

	import gc
	gc.disable()
	gc.collect()

optimize = any(x not in (None, False) for x in (
	args.optimize, args.optimize_lns, args.optimize_min_gates,
	args.optimize_depth, args.optimize_nmax, args.optimize_beam,
	args.optimize_lns_trials, args.optimize_lns_window, args.optimize_seed,
	args.optimize_n_prefer, args.optimize_weight, args.optimize_max_tmps,
))

lns = args.optimize_lns or args.optimize_lns_trials is not None or args.optimize_lns_window is not None
optimize_depth     = args.optimize_depth      if args.optimize_depth      is not None else 0
optimize_nmax      = args.optimize_nmax       if args.optimize_nmax       is not None else 2
optimize_beam      = args.optimize_beam       if args.optimize_beam       is not None else 1
optimize_seed      = args.optimize_seed
optimize_weight    = args.optimize_weight     if args.optimize_weight     is not None else 1
optimize_n_prefer  = args.optimize_n_prefer   if args.optimize_n_prefer   is not None else "low"
optimize_max_tmps  = args.optimize_max_tmps
optimize_min_gates = args.optimize_min_gates or 1
lns_trials         = args.optimize_lns_trials if args.optimize_lns_trials is not None else 3
lns_window         = args.optimize_lns_window if args.optimize_lns_window is not None else 3

if optimize_n_prefer == "l" or optimize_n_prefer == "lo"  : optimize_n_prefer = "low"
if optimize_n_prefer == "h" or optimize_n_prefer == "hi"  : optimize_n_prefer = "high"
if optimize_n_prefer == "m"                               : optimize_n_prefer = "mid"
if optimize_n_prefer == "r" or optimize_n_prefer == "rand": optimize_n_prefer = "random"

if abs(optimize_weight - round(optimize_weight)) < 1e-9:
	optimize_weight = round(optimize_weight)

if not lns:
	lns_window = 0
	lns_trials = 0

GV_DECL_LINE_WRAP = 100 # line wrap for only the node declarations. doesn't include the indentation

lut_size = None if args.lut_size == -1 else args.lut_size
syntax   = args.syntax
output   = args.output
verbose  = args.verbose or 0
eprint   = gf2_cse._eprint

if args.indent is None or args.indent in ("tabs", "tab", "t", "-1"):
	indent_str = '\t'
elif args.indent == "none":
	indent_str = ''
else:
	try:
		n = int(args.indent)
		if n < 0:
			raise ValueError("")

		indent_str = ' ' * n

		del n
	except ValueError:
		raise ValueError(f"invalid value given to `--indent`: '{args.indent}'")

# these come from crcmod.predefined._crc_definitions_table
sum_len_map = {
	"8": 1,
	"8itu": 1,
	"8maxim": 1,
	"8rohc": 1,
	"8darc": 1,
	"8icode": 1,
	"8wcdma": 1,

	"16": 2,
	"16buypass": 2,
	"16dds110": 2,
	"16genibus": 2,
	"16maxim": 2,
	"16mcrf4xx": 2,
	"16riello": 2,
	"16usb": 2,
	"x25": 2,
	"xmodem": 2,
	"modbus": 2,
	"kermit": 2,
	"ccittfalse": 2,
	"augccitt": 2,
	"16dect": 2,
	"16teledisk": 2,
	"16dnp": 2,
	"16en13757": 2,
	"16t10dif": 2,

	"24": 3,
	"24flexraya": 3,
	"24flexrayb": 3,

	"xfer": 4,
	"32q": 4,
	"32": 4,
	"32bzip2": 4,
	"32d": 4,
	"32mpeg": 4,
	"posix": 4,
	"jamcrc": 4,
	"32c": 4,

	"64": 8,
	"64jones": 8,
	"64we": 8,
}

def print_help_formats(formats: tuple[tuple[str, ...], ...] = formats) -> None:
	formats = list(formats)

	print("supported basic output formats:")

	i = 0
	while i < len(formats):
		e = formats[i] # alias list

		# combine stuff like ("info",), ("i",) into one tuple
		if (
			i + 1 < len(formats)          # not the last format
			and len(e) == 1               # alias list has one element
			and len(formats[i + 1]) == 1  # next alias list only has one element
		):
			e = formats[i] + formats[i + 1]
			formats.pop(i + 1)

		print(f" - {' / '.join(e)}")

		i += 1

	print(
		"\nsupported assembly output formats:"
		"\n - asm (defaults to x64)"
	)

	for fmt in asm_formats:
		print(f" - asm={fmt}")

	print(
		  "     > type=cisc | risc          (default is cisc)"
		"\n     > regcount=<int>            (default is 16)"
		"\n     > regsize=<int>             (default is 32)"
		"\n     > save-list=<list[int]>     (default is [], comma separated list)"
		"\n     > max-ofs=<list[int]>       (default is 0, max immediate pointer offset)"
		"\n     > emit-spacing=<bool>       (default is false)"
		"\n     > emit-comments=<bool>      (default is false)"
		"\n     > emit-round-numbers=<bool> (default is false)"
		"\n     > debug=<bool>              (emit-* master switch, default is false)"
		"\n"
		"\nformat descriptions:"
		"\n - 'python-test' / 'pyt'  the same code as 'python' / 'py', but with some extra testing functions"
		"\n - 'json' / 'j'           raw graph data as a JSON object string with sets replaced with lists."
		"\n - 'ir' / 'r'             raw graph data as a python object string. similar to 'json' / 'j'"
		"\n - 'metrics' / 'm'        JSON metrics about the graph reduction without giving the graph itself."
		"\n - 'nmigen' / 'nmg'       the same as 'amaranth' / 'am' but for the legacy `Elaboratable` API."
		"\n - 'info' / 'i'           curve metadata in a human readable format."
		"\n - 'noop' / 'nop'         outputs nothing except for stuff that goes to stderr (dry run)."
		"\n"
		"\nx86 and x64:"
		"\n - 'amd64' is an alias for 'x64'"
		"\n - 'fasm' can be used instead of 'nasm' in the format names; the output is compatible with both."
		"\n - dialects are chosen automatically if not given: ms => masm, stm => nasm, sysv => gas"
		"\n - if no ABI is given, it defaults to sysv"
		"\n - 'stm' is StackMin ABI (github.com/drizzt536/files/blob/main/NASM/misc/os/docs/calling-convention.md)"
		"\n - all x86 ABIs are implicitly fastcall. the regular ABIs pass arguments on the stack"
		"\n"
		"\narm64:"
		"\n - 'aarch64' is an alias for 'arm64'"
		"\n - 'ms', 'sysv', or 'apple' can be given as an ABI, but they are ignored. other ABIs are invalid"
		"\n - dialect defaults to gas"
		"\n"
		"\ndialect 'clang' aliases dialect 'gas' for all assembly formats"
		"\nfor raw/json/metrics formats: long name => beautified, short name => minified."
		"\nall format names and flag names/values are case insensitive"
	)

def print_help_algs() -> None:
	print("supported named CRCs:")

	prev_size = 0

	try:
		import crcmod

		# map sum length to the string length of the longest algorithm name
		len_max = {1:0, 2:0, 3:0, 4:0, 8:0}

		for key, val in sum_len_map.items():
			if len(key) > len_max[val]:
				len_max[val] = len(key)

		pad = len_max[1] + 1

		for key, size in sum_len_map.items():
			if size != prev_size:
				pad = len_max[size] + 1
				prev_size = size
				print(f"\n{size << 3}-bit CRCs")

			poly    = crcmod.predefined._crc_definitions_by_name[key]['poly']
			density = (poly.bit_count() - 1) / size * 12.5

			print(f" - {key:{pad}}: poly=0x{poly:x}, density={density:4.1f}%")
	except ImportError:
		for key, size in sum_len_map.items():
			if size != prev_size:
				prev_size = size
				print(f"\n{size << 3}-bit CRCs")

			print(f" - {key}")

	print("\nnames are case insensitive, are stripped of all spaces and dashes, and can have 'crc' at the start.")

def print_help_toml() -> None:
	print("""
	# optimization flags apply to all the curves and can only be changed via the CLI.
	# these apply to all curves. they do not have to all be provided
	# if a TOML file/raw input is given, then the CLI flags for these cannot be used
	in-port  = "abc" # default is "data"
	out-port = "zzz" # default is "crc"
	tmp-name = "qwe" # default is "tmp"
	data-len = 5     # default is 4

	# if there is only one curve, you can do `[curve]` instead of `[[curve]]`
	[[curve]]
	# these apply to only this curve. it resets back to the global value for the next curve
	# these override the global ones
	in-port  = "inp"  # the names have to use dashes, so no `in_port`.
	out-port = "outp"
	tmp-name = "net"
	data-len = 2

	# name = "crc32"   # mutually exclusive with `polynomial
	polynomial = 0x17b # must be given if `name` is not given

	# these three only make sense with `polynomial`, and not with `name`.
	init       = 45    # default is 0
	xor-out    = 5     # default is 0
	reflect    = false # default is false

	# if no [curve] or [[curve]] attributes exist, the compiler will just do nothing and exit

	[[curve]]
	name = "CRC-32" # same flexibility as with the `--algorithm` CLI flag

	[[curve]]
	# this won't name collide with the other one with `-o auto` because the data length is different.
	polynomial = 0x17b
	reflect    = true

	[[curve]]
	in-port    = "crc_data"
	tmp-name   = "qwe" # this does nothing since it is the same as the global value
	init       = 0xFFFFFFFB
	xor-out    = 0xFFFFFFFB
	polynomial = 0x18012d591 # attribute order doesn't matter. curve order does though
	""".replace('\t', '')[1:-1])

def print_help_dsl() -> None:
	print("""
		| DSL preprocessor help code (not one coherant program):

		| comments are stripped and variables are expanded before all other line processing
		| variables and keywords are case sensitive. starting and ending whitespace is stripped
		| there is no escape character, so a line stops at the first '|' character (or the newline)

		%include[~/init.caf]      | '~' gets expanded out. environment variables do not
		%include[a\\b\\c.caf]       | the string is parsed raw

		%set[var][x]              | var = "x"
		%set[var][a,b,c]          | var = ["a", "b", "c"]. still internally just a string
		| variable names can contain alphanumerics and underscores

		%pop[$null][var]          | var.pop()
		%shift[asdf][var]         | asdf = var.pop(0)
		%index[x1][1][$list]      | x1 = list[1]
		%index[x2][$i][$list]     | x2 = list[i]

		%set[list][x, y, z]       | list = ["x", " y", " z"]. spaces are interpreted raw
		%len[length][$list,1323]  | length = len(list + ["1323"])
		%len[length][]            | length = len([])
		%len[length][asdf]        | length = len(["asdf"])

		%substr[outvar][$start,$stop,$step][expr] | outvar = "expr"[start-1:stop:step] (1-indexed, both inclusive)
		%substr[outvar][1,3][$asdf] | outvar = asdf[0:3]
		| NOTE: substr acts on raw strings, so if the input is a list, the output may
		|       include the comma separators, depending on what the indices are.

		| `%defmacro` macro body is expanded at call time (e.g. $tmp)
		| `%xdefmacro` is expanded at declaration time, but is otherwise identical. same `%endmacro` to end it.
		| argument counts cannot be variable.

		%defmacro[asdf][1] as     | `as` is optional. first argument is the name, second is the argument count
		\t%if[ge][#1][10] then  | `then` is optional. | if #1 >= 10: return
		\t\t%exitmacro
		\t%endif

		\t| seteval operation conversion (DSL => python):
		\t\t| ^   => **
		\t\t| /   => //
		\t\t| and => &
		\t\t| or  => |
		\t\t| xor => ^
		\t%seteval[tmp][#1 + 1] | integer evaluated expression
		\t%log[arg=$tmp]
		\t%macro[asdf][$tmp]
		\t%unset[tmp]           | del tmp
		%endmacro

		| conditionals and loops use tags to find the end, so this is not valid:
		%if[eq][$a][$b]
		\t%if[eq][$c][$d]
		\t\tsomething
		\t%endif
		%endif
		| when the outermost `%if` looks for the `%endif`, it uses the first one it sees
		| NOTE: tag collisions will give parser errors about a missing `%endif`

		| that matches its tag, so something like this should be used instead:
		%if[eq][$a][$b]
		\t%if1[eq][$c][$d]
		\t\tsomething
		\t%endif1 | tag=1, matches the inner block
		%endif | empty tag, matches the outer block

		| tags can either be empty, or any integer
		| for matching block ends, tags only have to be unique for each type of block.
		| so %loop and %if have to be unique, but you can nest an %if inside a %loop.
		| also, uniqueness only matters for nested conditionals, so this is valid:

		%if3[eq][$x][$y]
		\tsomething
		%endif3

		%if3[eq][$a][$b]
		\tsomething else
		%endif3

		%xdefmacro[asdf][2]
		\t%log[#1, #2]
		\t$null$null$null$null | this will expand out to nothing
		%endmacro

		| multiple macros can exist with the same name if they have different argument counts
		%macro[asdf][1]    | call version 1
		%macro[asdf][0]
		%macro[asdf][1,0]  | call version 2
		%macro[asdf][2,1]

		%set[x][apple,asdf,abc]  | x = ["apple", "asdf", "abc"]

		| %repl acts on raw strings, it replaces instances of the first string with the second
		%repl[x][$x][a][b]       | x = ["bpple", "bsdf", "bbc"]
		%repl[y][$x][,][$null]   | y = ''.join(x)

		| setting like this is basically a bunch of list concatenations, there are only 1d lists
		%set[x][$x,asdf,$i$i$i,$var1,$var2,qwer,,$null,4]

		%set[i][0]
		%loop | loop forever
		\t%if1[ge][$i][10]
		\t\t%if2[lt][$i][3]
		\t\t\tdo some stuff
		\t\t%else2
		\t\t\t| %break3 | this wouldn't match anything and would throw an error
		\t\t\t| %break2 | this would match the  `%if2` and break out of the if block.
		\t\t\t| %break1 | this would match the `%if1` and break out of the if block.
		\t\t\t%break | matches `%loop` since it has no tag
		\t\t%endif2
		\t%endif1

		\t%log[i=$i]

		\t%seteval[i][$i + 1]
		%endloop | the `%endloop` has to have the same tag as the `%loop`

		| %break is the only thing where tags between %if, %loop, and %foreach are different.
		| it will match whatever block is closest with a matching tag.

		%unset[i,nonexistent] | unsetting a nonexistent variable just does nothing. no error

		%set[x][1]
		%foreach3[x][1asdf,2qwer,31234,4abc,5q,6w] do | `do` is optional
		\t%repl[x][$x][][,] | x = x.split('')
		\t%shift[i][x]      | (i, x) = x
		\t%repl[x][$x][,][] | x = ''.join(x)

		\t%log[list[$i] = $x]
		%endfor3
		%log[$x] | this will print 1 since x is restored after foreach loops
		| if $x were undefined before the foreach loop, it will be deleted at the end of the foreach loop.

		%fatal[error message]

		%if[subset][$format][arm32,avr]
		\t%raw[variables aren't expanded here]
		%endif

		%exit | basically the same as EOF. preprocessor ignores all subsequent lines
		| if this was in an %include, it will continue parsing the file it was included from

		| %if conditionals:
		|---------------------------

		| integer operations: eq, ne, lt, le, gt, ge
		%if[eq][$a,$b,$c][$x,$y,$z] | if a == x and b == y and c == z
		%endif

		| also: inrange, notinrange
		%if[inrange][$x,$y][4,7] | if 4 <= x <= 7 and 4 <= y <= 7
		%endif
		| notinrange is just the negated result

		| string operations: streq, strneq
		%if[streq][asdfqwer][asdf,qwer] | commas are not treated as list separators in this case.
		\t| this branch won't run
		%else
		\t| this branch will run
		\t| there is %else, but no %elseif or %elif or anything like that.
		%endif

		| variable operations: def, notdef

		%if[def][a,b,c][] | #if defined(a) && defined(b) && defined(c)
		\t| the second argument block must be empty. it cannot be omitted.
		\t| notdef is the negated result.
		%endif

		| list/set operations: subset, notsubset
		| these are for loose subsets, so anything is a subset of itself

		%if[subset][1,2,3,4][1,2,5,4,3]
		\t| true. order doesn't matter
		%endif
	""".replace("\n\t\t", "\n")[1:-2])

def print_help_ir() -> None:
	print(
		"HDL IR format:"
		"\n - input is an array of bits and output is an array of bits"
		"\n - a positive set value corresponds to an input bit, e.g. 2 => in[2]"
		"\n - a negative set value corresponds to a temporary bit, e.g. -4 => tmp[4]"
		"\n - input bits are 0-indexed and temporary bits are 1-indexed."
		"\n - a None / null corresponds to a constant 1 (NOT gate)"
		"\n - tmp signals are topologically sorted so they can only depend on tmps with lower ids"
		"\n - a set of {None, 6, 2, -4} corresponds to `1 ^ in[6] ^ in[2] ^ tmp[4]`"
		"\n - asm=json uses a priority queue instead of a FIFO, so it has different sorting"
	)

	if not dsl_avail:
		return

	print(
		"\nAssembly IR format:"
		"\n - Uses the same DSL preprocessor as the TOML input (see --help=dsl)"
		"\n - all instructions use 'dst, src'"
		"\n - the format is mostly ISA agnostic"
		"\n - @mvz: move zero to register"
		"\n - @mov: move value into register (either small a immediate or from memory)"
		"\n - @mvl: move large immediate into register (cannot be done in one instruction)"
		"\n - @add/@sub/@shr/@shl/@and/@xor/@jmp/@ret: same as the x86 instructions"
		"\n - @orr: or two registers together"
		"\n - @xor: xor a register into memory or xor two registers (depends on cisc vs risc)"
		"\n - @jiz: jump if zero. same as CBZ on ARM32. usually something like `test` + `je`"
		"\n - @ldw/@ldb: load word/byte from memory into a register"
		"\n - @stw/@stb: store word/byte into memory from a register"
		"\n - @function[...]: definition of a function"
		"\n - @deflabel[...]: definition of a label"
		"\n - @label[...]: reference to a label"
		"\n - @label[...]: reference to a label"
		"\n - @reg[sp]: stack pointer register"
		"\n - @reg[...]: full-width register by index"
		"\n - @regb[...]: 8-bit register by index"
		"\n - @imm[...]: immediate value operand"
		"\n - @in[...]: reference to input signal by index"
		"\n - @tmp[...]: reference to temporary signal by index"
		"\n - @out[...]: reference to output signal by index"
	)

if getattr(args, "help=all"):
	parser.print_help()

	print("\n################################# FORMAT HELP #################################")
	print_help_formats()

	print("\n################################### ALG HELP ##################################")
	print_help_algs()

	print("\n################################## TOML HELP ##################################")
	print_help_toml()

	if dsl_avail:
		print("\n################################### DSL HELP ##################################")
		print_help_dsl()

	print("\n################################ IR FORMAT HELP ###############################")
	print_help_ir()

	exit(0)

if len(argv) == 1:
	# no arguments given.
	parser.print_help()
	exit(0)

del parser

if getattr(args, "help=formats"):
	print_help_formats()
	exit(0)

if getattr(args, "help=algorithms"):
	print_help_algs()
	exit(0)

if getattr(args, "help=toml"):
	print_help_toml()
	exit(0)

if getattr(args, "help=dsl") and dsl_avail:
	print_help_dsl()
	exit(0)

if getattr(args, "help=ir"):
	print_help_ir()
	exit(0)

if verbose >= 2:
	eprint("# command: " + ' '.join(argv))

if args.cache_global:
	if os.name == "nt":
		args.cache_dir = f"%LocalAppData%/{prog}/cache"
	else:
		if os.environ.get("XDG_CACHE_HOME"):
			args.cache_dir = f"$XDG_CACHE_HOME/{prog}"
		else:
			# if you are on macos, this may or may not be what you actually want.
			# you macos sick freaks can pass the path manually if this isn't good enough for you.
			# https://drive.google.com/file/d/1a7ZMx_xamAJyxaFLTIxkdc4vkb-ZQ5oj/view?usp=sharing

			# the dirty Jython users are stuck in the past, so this won't even compile for them,
			# so don't worry about os.name == "java". And Jython 3 is definitely not happening
			# this decade, if ever. Python 2 is barely even from this century. You cannot actually
			# be using ts in the big '26 and actually take yourself seriously.
			args.cache_dir = f"~/.cache/{prog}"

if args.cache_dir is None:
	args.cache_dir = './crc-cache'
elif args.cache is None:
	raise Exception("`--cache-dir` cannot be used without `--cache`")

cache_dir = os.path.expanduser(os.path.expandvars(args.cache_dir))
if os.name == "nt":
	cache_dir = cache_dir.replace('\\', '/')

if args.cache is None:
	cache_settings = ''
else:
	args.cache = args.cache.replace('u', "rw")
	args.cache = args.cache.replace('x', 'c')

	if len(args.cache) > 4 or not args.cache:
		raise ValueError(f"`--cache` value too long: '{args.cache}'")

	for c in args.cache:
		if c not in "ocrwd":
			raise ValueError(f"`--cache` value has invalid character '{c}'")

	if len(set(args.cache)) != len(args.cache):
		raise ValueError(f"`--cache` value contains duplicate flags: '{args.cache}'")

	if 'd' in args.cache:
		if len(args.cache) != 1:
			raise ValueError(f"`--cache` 'd' must appear alone.")

		cache_settings = 'd'
	elif 'o' in args.cache:
		if 'r' in args.cache or 'w' in args.cache:
			raise ValueError("cache cannot be enabled and disabled at the same time")

		cache_settings = ''
	else:
		cache_settings = ''
		if 'r' in args.cache: cache_settings += 'r'
		if 'w' in args.cache: cache_settings += 'w'

	# possible `cache` values after this point: '', 'd', 'r', 'w', 'rw', 'c', 'cw'

	if 'c' in args.cache and syntax != "nop":
		if os.path.isdir(cache_dir):
			cache_files = os.listdir(cache_dir)

			for file in cache_files:
				os.remove(f"{cache_dir}/{file}")

			if verbose >= 1:
				eprint(f"# removed all {len(cache_files)} cache files")

			del cache_files
		elif verbose >= 1:
			eprint("# removed all 0 cache files")

		if len(args.cache) == 1:
			argv[1] = argv[1].replace("--cache", "-C").replace('=', '')

			solo_short = len(argv) == 2 and len(argv[1]) == 3
			solo_long  = len(argv) == 3 and argv[1] == '-C' and argv[2].lower() in 'cx'

			if solo_long or solo_short:
				if os.path.isdir(cache_dir):
					os.rmdir(cache_dir)
				exit(0)

			del solo_long, solo_short

		cache_settings = cache_settings.replace('r', '')

	if cache_settings:
		optimize = True

# possible `cache` values after this point: '', 'd', 'r', 'w', 'rw'

del argv

syntax_data = {
	"v": {
		"xor"         : " ^ ",
		'1'           : '1',
		'0'           : '0',
		'='           : " = ",
		'['           : '[',
		']'           : ']',
		'^'           : "assign ",
		'$'           : ';',
		"footer"      : "\nendmodule",
		"comment"     : "//",
		"begin_logic" : '',
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"wire [{size} : 0] {name.strip()};",
	}, "vhd": {
		"xor"         : " xor ",
		'1'           : "'1'",
		'0'           : "'0'",
		'='           : " <= ",
		'['           : '(',
		']'           : ')',
		'^'           : '\t',
		'$'           : ';',
		"footer"      : "end architecture;",
		"comment"     : "--",
		"begin_logic" : "begin",
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"\tsignal {name.lstrip()} : std_logic_vector({size} downto 0);",
	}, "py": {
		"xor"         : " ^ ",
		'1'           : '1',
		'0'           : '0',
		'='           : " = ",
		'['           : '[',
		']'           : ']',
		'^'           : '\t',
		'$'           : '',
		"footer"      : None,
		"comment"     : '#',
		"begin_logic" : '',
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"\t{name.lstrip()} = [0] * {size}",
	}, "c": {
		"xor"         : " ^ ",
		'1'           : '1',
		'0'           : '0',
		'='           : " = ",
		'['           : '[',
		']'           : ']',
		'^'           : '\t',
		'$'           : ';',
		"footer"      : '}',
		"comment"     : "//",
		"begin_logic" : '',
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"\tuint8_t {name.lstrip()}[{size}];",
	}, "gv": {
		"xor"         : '","',
		'1'           : '1',
		'0'           : '0',
		'='           : None,
		'['           : '[',
		']'           : ']',
		'^'           : None,
		'$'           : None,
		"footer"      : '}',
		"comment"     : "//",
		"begin_logic" : None,
		"var_prefix"  : '',
		"wire_type"   : None,
	}, "am": {
		"xor"         : " ^ ",
		'1'           : '1',
		'0'           : '0',
		'='           : ".eq(",
		'['           : '[',
		']'           : ']',
		'^'           : "\t\tc += ",
		'$'           : ')',
		"footer"      : "\n\t\treturn m",
		"comment"     : '#',
		"begin_logic" : '',
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"\t\t{name.lstrip()} = Signal({size})",
	}, "ch": {
		"xor"         : " ^ ",
		'1'           : "1.B",
		'0'           : "0.B",
		'='           : " := ",
		'['           : '(',
		']'           : ')',
		'^'           : '\t',
		'$'           : '',
		"footer"      : '}',
		"comment"     : '//',
		"begin_logic" : '',
		"var_prefix"  : '',
		"wire_type"   : lambda name, size: f"\tval {name.lstrip()} = Wire(Vec({size}, Bool()))",
	}, "sp": {
		"xor"         : " ^ ",
		'1'           : "B(1)",
		'0'           : "B(0)",
		'='           : " := ",
		'['           : '(',
		']'           : ')',
		'^'           : '\t',
		'$'           : '',
		"footer"      : '}',
		"comment"     : '//',
		"begin_logic" : '',
		"var_prefix"  : 'io.',
		"wire_type"   : lambda name, size: f"\tval {name.lstrip()} = Bits({size} bits)",
	}
}

syntax_data["sv"]  = syntax_data["v"]
syntax_data["pyt"] = syntax_data["py"]
syntax_data["c++"] = syntax_data["c"]
syntax_data["nmg"] = syntax_data["am"]
syntax_data["ch3"] = syntax_data["ch"].copy()
syntax_data["ch3"]["var_prefix"] = "io."

tokens = syntax_data.get(syntax, {})

xor         = tokens.get("xor")
b1          = tokens.get("1")
b0          = tokens.get("0")
assign      = tokens.get("=")
lbr         = tokens.get("[")
rbr         = tokens.get("]")
prefix      = tokens.get("^")
suffix      = tokens.get("$")
footer      = tokens.get("footer")
comment     = tokens.get("comment")
begin_logic = tokens.get("begin_logic") # begin actual logic
vpfx        = tokens.get("var_prefix")
wire_type   = tokens.get("wire_type")

del syntax_data, tokens

if syntax == "asm=ir":
	if "type" not in asm_ir_settings:
		ir_type = "cisc"
	else:
		ir_type = asm_ir_settings.pop("type")
		if ir_type not in {"cisc", "risc"}:
			raise ValueError("IR option `type` must be 'cisc' or 'risc'")

	if "regcount" not in asm_ir_settings:
		regcount = 16
	else:
		try:
			regcount = int(asm_ir_settings.pop("regcount"))
		except ValueError:
			raise ValueError("IR option `regcount` must be an integer")

		if regcount < 4:
			raise ValueError("IR option `regcount` must be at least 4")

	if "regsize" not in asm_ir_settings:
		regsize = 32
	else:
		regsize = asm_ir_settings.pop("regsize")

		try:
			regsize = int(regsize)
		except ValueError:
			raise ValueError("IR option `regsize` must be an integer")

	if "save-list" not in asm_ir_settings:
		save_list = None
	else:
		save_list = asm_ir_settings.pop("save-list")
		if save_list == '':
			save_list = None
		else:
			try:
				save_list = [int(x) for x in save_list.split(',')]
			except ValueError:
				raise ValueError("IR option `save-list` must be a list of integers")

	if "max-ofs" not in asm_ir_settings:
		max_ofs = 32
	else:
		max_ofs = asm_ir_settings.pop("max-ofs")

		if max_ofs == "none":
			max_ofs = None
		else:
			try:
				max_ofs = int(max_ofs)
			except ValueError:
				raise ValueError("IR option `max-ofs` must be an integer")

			if max_ofs < -1:
				raise ValueError("IR option `max_ofs` must be at least -1")

	if "emit-spacing" not in asm_ir_settings:
		emit_spacing = False
	else:
		emit_spacing = asm_ir_settings.pop("emit-spacing")
		if emit_spacing not in {"true", "false"}:
			raise ValueError("IR option `emit-spacing` must be a boolean")

		emit_spacing = emit_spacing == "true"

	if "emit-comments" not in asm_ir_settings:
		emit_comments = False
	else:
		emit_comments = asm_ir_settings.pop("emit-comments")
		if emit_comments not in {"true", "false"}:
			raise ValueError("IR option `emit-comments` must be a boolean")

		emit_comments = emit_comments == "true"

	if "emit-round-numbers" not in asm_ir_settings:
		emit_round_numbers = False
	else:
		emit_round_numbers = asm_ir_settings.pop("emit-round-numbers")
		if emit_round_numbers not in {"true", "false"}:
			raise ValueError("IR option `emit-round-numbers` must be a boolean")

		emit_round_numbers = emit_round_numbers == "true"

	if "debug" in asm_ir_settings:
		debug = asm_ir_settings.pop("debug")

		if debug not in {"true", "false"}:
			raise ValueError("IR option `debug` must be a boolean")

		if debug == "true":
			emit_spacing       = True
			emit_comments      = True
			emit_round_numbers = True

		del debug

	if asm_ir_settings:
		valid_ir_settings = {
			"type", "regcount", "regsize", "save-list", "max-ofs",
			"emit-spacing", "emit-comments", "emit-round-numbers", "debug"
		}

		raise ValueError(f"unknown flag(s) given to `-fasm=ir:<flags>`: '{"', '".join(asm_ir_settings)}'. must be '{"', '".join(valid_ir_settings)}'")

	asm_ir_settings = {
		"format"    : ir_type,
		"reg_slots" : regcount,
		"reg_size"  : regsize,
		"save_list" : save_list,
		"max_ofs"   : max_ofs,
		"emit_spacing"  : emit_spacing,
		"emit_comments" : emit_comments,
		"emit_round_numbers" : emit_round_numbers,
	}

	del ir_type, regcount, regsize, save_list, max_ofs, emit_spacing, emit_comments, emit_round_numbers

if syntax.startswith("asm=") and syntax != "asm=ir":
	t = {
		"x64-ms-nasm": {
			"settings": {
				"format"    : "CISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 64,
				"max_ofs"   : (1 << 31) - 1
			},
			"regw": ("rcx", "rdx", "rax", "r8" , "r9" , "r10" , "r11" ),
			"regb": ( "cl",  "dl",  "al", "r8b", "r9b", "r10b", "r11b"),
			"comment": ';',
			"grammar": {
				r"@jiz (@reg\[\d+\]), (@label\[\w+\])": ("\ttest \\1, \\1", "\tje \\2"),
				r"@add (@reg\[\w+\]), @imm\[1\]\b": f"\tinc \\1",
				r"@sub (@reg\[\w+\]), @imm\[1\]\b": f"\tdec \\1",
				r"@imm\[(\d+)\]": "\\1",
				r"@stw (@reg\[\w+\])": "\tmov qword @ptr[\\1]",
				r"@stb (@reg\[\w+\])": "\tmov byte @ptr[\\1]",
				r"@ldw (@reg\[\w+\]), (@reg\[\w+\])": "\tmov \\1, qword @ptr[\\2]",
				r"@ldb (@regb\[\w+\]), (@reg\[\w+\])": "\tmov \\1, byte @ptr[\\2]",
				r"@mvz (@regb?\[\w+\])": "\txor \\1, \\1",
				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@function\[(\w+)\]": "\\1:",
				r"@deflabel\[(\w+)\]": "@label[\\1]:",
				r"@label\[(\w+)\]": ".\\1",
				r"@in\[(\d+)\]":  lambda m, k: f"byte @ptr[@reg[sp]{f' + {ofs}' if ( ofs := k. in_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@tmp\[(\d+)\]": lambda m, k: f"byte @ptr[@reg[sp]{f' + {ofs}' if ( ofs := k.tmp_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@out\[(\d+)\]": lambda m, k: f"byte @ptr[@reg[sp]{f' + {ofs}' if ( ofs := k.out_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@reg\[sp\]": "rsp",
				r"@mvl\b": "\tmov",
				r"@add\b": "\tadd", r"@sub\b": "\tsub",
				r"@shl\b": "\tshl", r"@shr\b": "\tshr",
				r"@and\b": "\tand", r"@orr\b": "\tor",
				r"@xor\b": "\txor", r"@mov\b": "\tmov",
				r"@jmp\b": "\tjmp", r"@ret\b": "\tret",
				r"@ptr\b": '',
				r"@mvl\b": "\tmov", # even a 64-bit immediate move is still just `mov`
			},
		},
		"arm64-gas": {
			"settings": {
				"format"    : "RISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 64,
				"max_ofs"   : (1 << 12) - 1
			},
			"regw": ("x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17"),
			"regb": ("w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "w10", "w11", "w12", "w13", "w14", "w15", "w16", "w17"),
			"comment": "//",
			"grammar": {
				r"@jiz": "\tcbz",
				r"@(add|sub|and|orr) (@regb?\[\w+\])": f"\t\\1 \\2, \\2",
				r"@sh([lr]) (@regb?\[\w+\])": f"\tls\\1 \\2, \\2",
				r"@xor (@regb?\[\w+\])": f"\teor \\1, \\1",
				r"@mvz @regb?(\[\d+\])": "\tmov @reg\\1, xzr",
				r"@ldw (@reg\[\w+\]), (@reg\[\w+\])": "\tldr \\1, [\\2]",
				r"@ldb (@regb\[\w+\]), (@reg\[\w+\])": "\tldrb \\1, [\\2]",
				r"@stw (@reg\[\w+\]), (@reg\[\w+\])": "\tstr \\2, [\\1]",
				r"@stb (@reg\[\w+\]), (@regb\[\w+\])": "\tstrb \\2, [\\1]",
				r"@stb (@\w+\[\w+\]), (@regb\[\w+\])": "\tstrb \\2, \\1",
				r"@function\[(\w+)\]": "\\1:",
				r"@deflabel\[(\w+)\]": "@label[\\1]:",
				r"@label\[(\w+)\]": "L\\1",
				r"@in\[(\d+)\]":  lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k. in_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@tmp\[(\d+)\]": lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k.tmp_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@out\[(\d+)\]": lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k.out_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@imm\[(\d+)\]": "\\1",
				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@reg\[sp\]": "sp",
				r"@ldb": "\tldrb",
				r"@mov": "\tmov",
				r"@ret": "\tret",
				r"@jmp": "\tb",
				r"@mvl": "\tmov", # GAS figures out the real instructions
			},
		},
	}

	x64_ms_apx_regw = ("r16" , "r17" , "r18" , "r19" , "r20" , "r21" , "r22" , "r23" , "r24" , "r25" , "r26" , "r27" , "r28" , "r29" )
	x64_ms_apx_regb = ("r16b", "r17b", "r18b", "r19b", "r20b", "r21b", "r22b", "r23b", "r24b", "r25b", "r26b", "r27b", "r28b", "r29b")

	x64_sysv_apx_regw = x64_ms_apx_regw + ("r30" , "r31" )
	x64_sysv_apx_regb = x64_ms_apx_regb + ("r30b", "r31b")

	# Microsoft ABI
	t["x64-ms-masm"] = t["x64-ms-nasm"].copy()
	t["x64-ms-masm"]["grammar"] = t["x64-ms-masm"]["grammar"].copy()
	t["x64-ms-masm"]["grammar"][r"@ptr\b"]          = "ptr "
	t["x64-ms-masm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"

	t["x64-ms-gas"] = t["x64-ms-nasm"].copy()
	t["x64-ms-gas"]["grammar"] = {
		r"(@\w+\[.+?\]), (@\w+\[.+?\])": "\\2, \\1", # swap from 'dst, src' to 'src, dst'
		r"@imm\[(\d+)\]": "$\\1",
		r"@jiz (@label\[\w+\]), (@reg\[\d+\])": ("\ttestq \\2, \\2", "\tje \\1"),
		r"@add \$1, (@reg\[\w+\])": "\tincq \\1",
		r"@sub \$1, (@reg\[\w+\])": "\tdecq \\1",
		r"@stw (@reg\[\d+\]), (@reg\[\w+\])": "\tmovq \\1, (\\2)",
		r"@stb (@regb\[\d+\]), (@reg\[\w+\])": "\tmovb \\1, (\\2)",
		r"@ldw (@reg\[\w+\])": "\tmovq (\\1)",
		r"@ldb (@reg\[\w+\])": "\tmovb (\\1)",
		r"@mvz (@reg\[\d+\])": "\txorq \\1, \\1",
		r"@mvz (@regb\[\d+\])": "\txorb \\1, \\1",
		r"@reg\[(\d+)\]" : lambda m, k: '%' + k.regw[int(m.group(1))],
		r"@regb\[(\d+)\]": lambda m, k: '%' + k.regb[int(m.group(1))],
		r"@function\[(\w+)\]": "\\1:",
		r"@deflabel\[(\w+)\]": "@label[\\1]:",
		r"@label\[(\w+)\]": ".\\1",
		r"@in\[(\d+)\]":  lambda m, k: f"{ofs if ( ofs := k. in_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
		r"@tmp\[(\d+)\]": lambda m, k: f"{ofs if ( ofs := k.tmp_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
		r"@out\[(\d+)\]": lambda m, k: f"{ofs if ( ofs := k.out_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
		r"@reg\[sp\]": "%rsp",
		r"@add": "\taddq", r"@sub": "\tsubq",
		r"@shl": "\tshlq", r"@shr": "\tshrq",
		r"@and": "\tandb", r"@orr": "\torb",
		r"@mov(?=.+b)": "\tmovb",
		r"@mov": "\tmovq",
		r"@xor": "\txorb",
		r"@jmp": "\tjmp",
		r"@ret": "\tret",
	}

	t["x86-ms-nasm"] = {
		"settings": {
			"format"    : "CISC",
			"byteorder" : "little",
			"save_list" : (3,),
			"reg_size"  : 32,
		},
		"regw": ("ecx", "edx", "eax", "ebx"),
		"regb": ( "cl",  "dl",  "al",  "bl"),
		"comment": ';',
		"grammar": t["x64-ms-nasm"]["grammar"].copy()
	}
	t["x86-ms-nasm"]["grammar"][r"@stw (@reg\[\w+\])"]                = "\tmov dword @ptr[\\1]"
	t["x86-ms-nasm"]["grammar"][r"@ldw (@reg\[\w+\]), (@reg\[\w+\])"] = "\tmov \\1, dword @ptr[\\2]"
	t["x86-ms-nasm"]["grammar"][r"@reg\[sp\]"]                        = "esp"

	t["x86-ms-masm"] = t["x86-ms-nasm"].copy()
	t["x86-ms-masm"]["grammar"] = t["x86-ms-masm"]["grammar"].copy()
	t["x86-ms-masm"]["grammar"][r"@ptr\b"]          = "ptr "
	t["x86-ms-masm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"

	t["x86-ms-gas"] = t["x86-ms-nasm"].copy()
	t["x86-ms-gas"]["grammar"] = t["x64-ms-gas"]["grammar"].copy()
	t["x86-ms-gas"]["grammar"].update({
		r"@jiz (@label\[\w+\]), (@reg\[\d+\])": ("\ttestl \\2, \\2", "\tje \\1"),
		r"@add \$1, (@reg\[\w+\])": "\tincl \\1",
		r"@sub \$1, (@reg\[\w+\])": "\tdecl \\1",
		r"@stw (@reg\[\d+\]), (@reg\[\w+\])": "\tmovl \\1, (\\2)",
		r"@ldw (@reg\[\w+\])": "\tmovl (\\1)",
		r"@mvz (@reg\[\d+\])": "\txorl \\1, \\1",
		r"@reg\[sp\]": "%esp",
		r"@add": "\taddl", r"@sub": "\tsubl",
		r"@shl": "\tshll", r"@shr": "\tshrl",
		r"@mov": "\tmovl",
	})

	t["x64-apx-ms-nasm"] = t["x64-ms-nasm"].copy()
	t["x64-apx-ms-nasm"]["regw"] += x64_ms_apx_regw
	t["x64-apx-ms-nasm"]["regb"] += x64_ms_apx_regb

	t["x64-apx-ms-masm"] = t["x64-ms-masm"].copy()
	t["x64-apx-ms-masm"]["regw"] += x64_ms_apx_regw
	t["x64-apx-ms-masm"]["regb"] += x64_ms_apx_regb

	t["x64-apx-ms-gas"] = t["x64-ms-gas"].copy()
	t["x64-apx-ms-gas"]["regw"] += x64_ms_apx_regw
	t["x64-apx-ms-gas"]["regb"] += x64_ms_apx_regb

	# StackMin ABI. only NASM supported because I hate AT&T syntax and it isn't Windows
	t["x64-stm-nasm"] = t["x64-ms-nasm"].copy()
	t["x64-stm-nasm"]["regw"] = ("rax", "rbx", "rcx", "rdx", "rdi" , "rsi" )
	t["x64-stm-nasm"]["regb"] = ( "al",  "bl",  "cl",  "dl",  "dil",  "sil")

	t["x64-apx-stm-nasm"] = t["x64-stm-nasm"].copy()
	t["x64-apx-stm-nasm"]["regw"] += ("r16" , "r17" , "r18" , "r19" , "r20" , "r21" )
	t["x64-apx-stm-nasm"]["regb"] += ("r16b", "r17b", "r18b", "r19b", "r20b", "r21b")

	# System V ABI
	t["x64-sysv-nasm"] = t["x64-ms-nasm"].copy()
	t["x64-sysv-nasm"]["regw"] = ("rdi" , "rsi" , "rax", "rcx", "rdx", "r8" , "r9" , "r10" , "r11" )
	t["x64-sysv-nasm"]["regb"] = ( "dil",  "sil",  "al",  "cl",  "dl", "r8b", "r9b", "r10b", "r11b")

	t["x64-sysv-gas"] = t["x64-sysv-nasm"].copy()
	t["x64-sysv-gas"]["grammar"] = t["x64-ms-gas"]["grammar"]

	t["x86-sysv-nasm"] = t["x86-ms-nasm"]
	t["x86-sysv-gas"]  = t["x86-ms-gas"]

	t["x64-apx-sysv-nasm"] = t["x64-sysv-nasm"].copy()
	t["x64-apx-sysv-nasm"]["regw"] += x64_sysv_apx_regw
	t["x64-apx-sysv-nasm"]["regb"] += x64_sysv_apx_regb

	t["x64-apx-sysv-gas"] = t["x64-sysv-gas"].copy()
	t["x64-apx-sysv-gas"]["regw"] += x64_sysv_apx_regw
	t["x64-apx-sysv-gas"]["regb"] += x64_sysv_apx_regb

	# arm64
	t["arm64-armasm"] = t["arm64-gas"].copy()
	t["arm64-armasm"]["grammar"] = t["arm64-armasm"]["grammar"].copy()
	t["arm64-armasm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"
	t["arm64-armasm"]["grammar"][r"@imm\[(\d+)\]"]   = "#\\1"

	asm_format_data = t.get(syntax[4:])
	del t, x64_ms_apx_regw, x64_ms_apx_regb, x64_sysv_apx_regw, x64_sysv_apx_regb

import re
VHDL_IDENT    = re.compile(r"(?ai)^[a-z]\w*$")
C_IDENT       = re.compile(r"(?ai)^[a-z_]\w*$")
VERILOG_IDENT = re.compile(r"(?ai)^[a-z_][\w$]*$")
SCALA_IDENT   = VERILOG_IDENT # coincidental
del re

# these are more strict than necessary because these names are stupid to pick as a variable/signal name anyway
# not all of the "keywords" are actually real keywords
SCALA_KEYWORDS = {
	"abstract", "as", "case", "catch", "class", "def", "derives", "do", "else", "end", "extends", "extension",
	"false", "final", "finally", "for", "forSome", "if", "implicit", "import", "infix", "inline", "lazy", "match",
	"new", "null", "object", "opaque", "open", "override", "package", "private", "protected", "return", "sealed",
	"super", "this", "throw", "trait", "true", "try", "type", "using", "val", "var", "while", "with", "yield"
}

CHISEL_KEYWORDS = {
	"Bool", "Bundle", "Module", "Reg", "UInt", "Vec", "Wire", "clock", "io", "reset", "val"
}

SPINALHDL_KEYWORDS = {
	"Bits", "Bool", "Bundle", "Component", "UInt", "Vec", "clock", "downto", "in", "io", "out", "reset"
}

C_KEYWORDS = {
	"EOF", "NULL", "_BitInt", "_Bool", "_Complex", "_Imaginary", "__asm", "__asm__", "__attribute", "__attribute__",
	"__auto_type", "__cdecl", "__clrcall", "__declspec", "__fastcall", "__inline__", "__int128_t", "__restrict__",
	"__stdcall", "__thiscall", "__typeof", "__typeof__", "__vectorcall", "__volatile", "__volatile__", "alignas",
	"alignof", "asm", "auto", "bit_", "bool", "break", "byte_", "case", "char", "const", "constexpr", "continue",
	"default", "do", "double", "else", "enum", "extern", "false", "float", "for", "goto", "i_", "if", "inline",
	"int", "int16_t", "int32_t", "int64_t", "int8_t", "int_fast16_t", "int_fast32_t", "int_fast64_t", "int_fast8_t",
	"int_least16_t", "int_least32_t", "int_least64_t", "int_least8_t", "intptr_t", "long", "nullptr", "printf",
	"puts", "register", "restrict", "return", "short", "signed", "size_t", "sizeof", "ssize_t", "static",
	"static_assert", "stderr", "stdin", "stdout", "struct", "switch", "thread_local", "true", "typedef", "typeof",
	"typeof_unqual", "uint16_t", "uint32_t", "uint64_t", "uint8_t", "uint_fast16_t", "uint_fast32_t",
	"uint_fast64_t", "uint_fast8_t", "uint_least16_t", "uint_least32_t", "uint_least64_t", "uint_least8_t",
	"uintptr_t", "union", "unsigned", "void", "volatile", "while"
}

CPP_KEYWORDS = {
	"allocator", "and", "and_eq", "array", "bitand", "bitor", "catch", "char16_t", "char32_t", "char8_t", "class",
	"co_await", "co_return", "co_yield", "concept", "const_cast", "consteval", "constinit", "decltype", "delete",
	"dynamic_cast", "explicit", "export", "friend", "make_shared", "make_unique", "mutable", "namespace", "new",
	"noexcept", "not", "not_eq", "operator", "or", "or_eq", "private", "protected", "public", "reinterpret_cast",
	"requires", "shared_ptr", "static_cast", "string", "template", "this", "throw", "try", "typeid", "typename",
	"unique_ptr", "using", "vector", "virtual", "wchar_t", "weak_ptr", "xor", "xor_eq"
}

VERILOG_KEYWORDS = {
	"always", "and", "assign", "begin", "case", "deassign", "default", "disable", "else", "end", "endgenerate",
	"endmodule", "endtask", "event", "for", "force", "forever", "fork", "function", "generate", "genvar", "if",
	"initial", "inout", "input", "integer", "join", "module", "negedge", "or", "output", "parameter", "posedge",
	"real", "reg", "release", "repeat", "task", "time", "wait", "wire"
}

SYSTEMVERILOG_KEYWORDS = {
	"always_comb", "always_ff", "always_latch", "assert", "assume", "automatic", "bit", "byte", "class",
	"constraint", "cover", "covergroup", "coverpoint", "dist", "enum", "export", "final", "import", "inside",
	"interface", "localparam", "logic", "mailbox", "package", "priority", "process", "program", "property",
	"rand", "randc", "semaphore", "sequence", "solve", "static", "string", "struct", "typedef", "union",
	"unique", "virtual"
}

VHDL_KEYWORDS = {
	"abs", "access", "after", "alias", "all", "and", "architecture", "array", "assert", "attribute", "begin",
	"block", "body", "buffer", "bus", "case", "component", "configuration", "constant", "context", "downto",
	"else", "elsif", "end", "entity", "exit", "file", "for", "function", "generate", "generic", "guarded", "if",
	"impure", "in", "inertial", "is", "label", "library", "linkage", "literal", "loop", "map", "mod", "nand",
	"new", "next", "nor", "not", "null", "of", "on", "open", "or", "others", "out", "package", "port",
	"postponed", "procedure", "process", "protected", "pure", "range", "record", "register", "reject", "report",
	"return", "rol", "ror", "select", "severity", "shared", "signal", "sll", "srl", "subtype", "then", "to",
	"transport", "type", "unaffected", "units", "until", "use", "variable", "wait", "when", "while", "with",
	"xnor", "xor"
}

def valid_varname(name: str) -> bool:
	"returns whether or not a variable/signal name is valid in the current syntax"
	import keyword # for python

	if not name and syntax in {"py", "pyt", "am", "nmg", "ch", "gv", "c", "c++", "v", "sv", "vhd"}:
		return False

	match syntax:
		case "py" | "pyt" | "am" | "nmg":
			return (
				name.isidentifier()
				and not keyword.iskeyword(name)
				and not keyword.issoftkeyword(name)
			)
		case "gv":
			return (
				name.isascii()
				and name.isprintable()
				and '"' not in name
			)
		case "ch" | "sp":
			return (
				bool(SCALA_IDENT.fullmatch(name))
				and name not in SCALA_KEYWORDS
				and (syntax != "ch" or name not in CHISEL_KEYWORDS)
				and (syntax != "sp" or name not in SPINALHDL_KEYWORDS)
			)
		case "c" | "c++":
			return (
				bool(C_IDENT.fullmatch(name))
				and name not in C_KEYWORDS
				and (syntax != "c++" or (
					name not in CPP_KEYWORDS
					and not name.startswith("__")
					and (name[0] != "_" or name[1] != name[1].toupper())
				))
			)
		case "v" | "sv":
			return (
				bool(VERILOG_IDENT.fullmatch(name))
				and name not in VERILOG_KEYWORDS
				and (syntax != "sv" or name not in SYSTEMVERILOG_KEYWORDS)
			)
		case "vhd":
			return (
				bool(VHDL_IDENT.fullmatch(name))
				and name[-1] != '_'
				and "__" not in name
				and name.lower() not in VHDL_KEYWORDS
			)
		case _:
			# all other formats don't emit code so the names don't matter
			return True

def c_type_length(count: int) -> int:
	"returns the bit size of the smallest standard C integer type that can fit `count - 1`, or can have >=count different values."
	bits = (count - 1).bit_length()

	if bits <=  8: return  8
	if bits <= 16: return 16
	if bits <= 32: return 32
	return 64

def run_job(
	output: str,
	optimize: bool,
	args: object, # whatever type argparse.ArgumentParser.parse_args gives you
	extra_newline: bool,
	asm_ir_settings: dict,
	outfile: object # whatever type open returns
) -> tuple[any, str | None]:
	"do all the main stuff that has to happen per batch job"
	# returns the output file handle if it is still open, otherwise it returns None
	# and the second value is either the file name or None.

	if gc_disabled:
		gc.collect()

	crc_name = args.algorithm
	poly     = args.polynomial

	init      = args.init    or 0
	xor_out   = args.xor_out or 0
	reflected = args.reflect

	data_len      = args.data_len
	in_port       = args.in_port
	out_port      = args.out_port
	tmp_sgnl_base = args.tmp_name

	# NOTE: There is no version in the cache key because the version has to do with both the compiler itself
	#       and the optimizer, so a version change may or may not even mean the outputs have changed. For this
	#       reason, I have decided against versioning the cache key. if you want it expunged, do it yourself.
	cache_key = sha256(pickle.dumps((
		crc_name,
		poly,
		init,
		xor_out,
		reflected,
		data_len,
		lns,
		optimize_depth,
		optimize_nmax,
		optimize_beam,
		optimize_seed,
		optimize_weight,
		optimize_n_prefer,
		optimize_max_tmps,
		optimize_min_gates,
		lns_trials,
		lns_window
	), protocol=5)).hexdigest()

	cache_file = f"{cache_dir}/{cache_key}.xz"

	if verbose >= 2:
		eprint(f"# cache key: '{cache_key}'")

	if cache_settings == 'd' and os.path.isfile(cache_file):
		if verbose >= 1:
			eprint("# removed current cache entry")

		os.remove(cache_file)

	def cache_read() -> tuple[dict[int, set], list[set]] | None:
		if not os.path.isfile(cache_file):
			return None

		with lzma.open(cache_file, "rb") as f:
			return pickle.load(f)

	def cache_write(tmp_defs: dict[int, set], outputs: list[set], /) -> None:
		if not os.path.isdir(cache_dir):
			os.makedirs(cache_dir, exist_ok=True)

		# if the cache entry exists already, this will just overwrite it.
		with lzma.open(cache_file, "wb") as f:
			pickle.dump((tmp_defs, outputs), f, protocol=pickle.HIGHEST_PROTOCOL)

	if in_port == out_port:
		raise ValueError(f"input port ('{in_port}') and output port ('{out_port}') can't be the same")

	if tmp_sgnl_base == in_port:
		raise ValueError(f"tmp signal ('{tmp_sgnl_base}') and input port ('{in_port}') can't be the same")

	if tmp_sgnl_base == out_port:
		raise ValueError(f"tmp signal ('{tmp_sgnl_base}') and output port ('{out_port}') can't be the same")

	if not valid_varname(in_port):
		raise ValueError(f"input port ('{in_port}') is not a valid name in syntax '{syntax}'")

	if not valid_varname(out_port):
		raise ValueError(f"output port ('{out_port}') is not a valid name in syntax '{syntax}'")

	if not valid_varname(tmp_sgnl_base):
		raise ValueError(f"tmp name ('{tmp_sgnl_base}') is not a valid name in syntax '{syntax}'")

	local_port    = "local_" + out_port
	max_io_pad    = 1 + max(len(in_port), len(out_port))
	in_pad        = " "*(max_io_pad - len(in_port))
	out_pad       = " "*(max_io_pad - len(out_port))

	tmp_port_i = tmp_sgnl_base + " "*(len(in_port)    - len(tmp_sgnl_base))
	tmp_port_o = tmp_sgnl_base + " "*(len(local_port) - len(tmp_sgnl_base))

	if data_len < 1:
		# NOTE: it is probably possible to make sane code for data length 0, but I don't care enough.
		raise ValueError("data length must be at least 1")

	if poly is not None:
		if crc_name is not None:
			raise Exception("`--algorithm` and `--polynomial` cannot both be provided.")

		try:
			import crcmod
		except ImportError:
			raise Exception("custom CRCs require `crcmod-plus`.")

		crc        = crcmod.mkCrcFun(poly, init, reflected, xor_out)
		crc_name   = f"_custom_0x{poly:X}"
		sum_len    = (poly.bit_length() + 6) // 8
		polynomial = poly ^ (1 << (poly.bit_length() - 1))
	elif crc_name in {None, "32", "crc32", "crc-32", "crc 32"}:
		# use zlib.crc32 if possible since it is is built-in, and probably faster.
		crc_name   = '32'
		sum_len    = 4
		reflected  = True
		polynomial = 0x04c11db7 # this can't be queried from crcmod in case it isn't installed.

		from zlib import crc32 as crc
	else:
		try:
			import crcmod
		except ImportError:
			raise Exception(f"CRCs other than crc32 require the `crcmod-plus` package. crc_name: {crc_name}")

		if crc_name is None:
			crc_name = '32'

		sum_len = sum_len_map.get(crcmod.predefined._simplify_name(crc_name), None)

		if sum_len is None:
			raise ValueError(f"crc name '{crc_name}' does not exist or is unknown")

		crc_name = crcmod.predefined._simplify_name(crc_name)
		crc = crcmod.predefined.mkCrcFun(crc_name)

		reflected  = crcmod.predefined._crc_definitions_by_name[crc_name]["reverse"]
		polynomial = crcmod.predefined._crc_definitions_by_name[crc_name]["poly"]
		polynomial ^= 1 << (polynomial.bit_length() - 1)

	in_port_i = in_port + " "*(len(tmp_port_i) - len(in_port)) if optimize else in_port

	def optimize_gates(eqns: list[set]) -> tuple[dict[int, set], list[set]]:
		nonlocal ending_gates, ending_logic_depth, ending_max_fanout, in_idx_max_pad, optimize, in_port_i

		if not optimize:
			return {}, rows

		if 'r' in cache_settings and (cache_value := cache_read()) is not None:
			if verbose >= 1:
				eprint("# optimized graph was found in cache")

			tmp_defs, outputs = cache_value
		else:
			if verbose >= 1:
				eprint("# starting optimization")

			tmp_defs, outputs, _ = gf2_cse.optimize_gates(
				eqns,
				optimize_depth,
				optimize_nmax,
				optimize_beam,
				optimize_n_prefer,
				optimize_weight, # lookahead weight
				lns_window,
				lns_trials,
				optimize_min_gates - 1,
				optimize_max_tmps,
				optimize_seed,
				verbose,
				interactive=True,
				sort="slow" if syntax.startswith("asm=") or syntax in {"c", "c++"} else "fast"
			)

			if 'w' in cache_settings:
				cache_write(tmp_defs, outputs)

		if not tmp_defs:
			optimize  = False
			in_port_i = in_port

		ending_gates       = gf2_cse.count_gates(tmp_defs, outputs)
		ending_logic_depth = gf2_cse.logic_depth(tmp_defs, outputs, lut_size, sorted=True)
		ending_max_fanout  = gf2_cse.max_fanout(tmp_defs, outputs, nodes=False)

		in_idx_max_pad = max(
			in_idx_max_pad,
			len( str(len(tmp_defs)) )
		)

		if verbose >= 1:
			eprint(
				f"# XOR2 gates: {starting_gates} => {ending_gates}\n"
				f"# LUT{lut_size} logic depth: ~ {starting_logic_depth} => {ending_logic_depth}\n"
				f"# max fanout: {starting_max_fanout} => {ending_max_fanout}"
			)

		return tmp_defs, outputs

	# sum_len is the number of bytes in the checksum
	sum_bits  =  sum_len << 3 # number of bits in the checksum
	sum_nibs  =  sum_len << 1 # number of nibbles in the checksum
	data_bits = data_len << 3

	# idx \in [0, bits - 1]
	in_idx_max_pad  = len(str(data_bits - 1))
	out_idx_max_pad = len(str( sum_bits - 1))
	idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

	# idx + 1 \in [1, bits]
	in_idxp1_max_pad  = len(str(data_bits))
	out_idxp1_max_pad = len(str( sum_bits))
	idxp1_max_pad     = max(in_idxp1_max_pad, out_idxp1_max_pad)

	reversed_polynomial = int(f"{polynomial:0{sum_bits}b}"[::-1], 2) # bit reversal

	# This bit with the LFSR steps and the row generation thing makes no sense to me, and it was primarily
	# written by Claude (up until the for loop). I did test it quite a bit and I think it is probably correct.
	lfsr_mask = (1 << sum_bits) - 1

	if reflected:
		lfsr_step = lambda s: (s >> 1) ^ (reversed_polynomial if s & 1 else 0)
	else:
		lfsr_step = lambda s: ((s << 1) ^ polynomial if s >> (sum_bits - 1) else s << 1) & lfsr_mask

	K = crc(bytes(data_len)) # correction vector

	if verbose >= 1:
		eprint("# generating curve vectors")

	curve_gen_time_stt = perf_counter_ns()

	base_i  = 7 if reflected else 0
	cols    = [0] * data_bits
	current = crc((1 << base_i).to_bytes(data_len, byteorder="big")) ^ K
	cols[base_i] = current

	del base_i

	if reflected:
		for k in range(data_len):
			for j in range(6 if k == 0 else 7, -1, -1):
				cols[(k << 3) + j] = current = lfsr_step(current)
	else:
		for i in range(1, data_bits):
			cols[i] = current = lfsr_step(current)

	curve_gen_time_end = perf_counter_ns()

	del current

	if verbose >= 1:
		eprint("# generating matrix")

	rows = [
		{data_bits - 1 - n for n in range(data_bits) if (cols[n] >> bit) & 1}
		for bit in range(sum_bits)
	]

	for bit, eqn in enumerate(rows):
		if (K >> bit) & 1:
			eqn.add(None)

	starting_gates       = gf2_cse.count_gates(rows)
	starting_logic_depth = gf2_cse.logic_depth(None, rows, lut_size)
	starting_max_fanout  = gf2_cse.max_fanout(None, rows, nodes=False)

	# set these too in case optimization is off
	ending_gates         = starting_gates
	ending_logic_depth   = starting_logic_depth
	ending_max_fanout    = starting_max_fanout

	def print(message: str | None, end: str = '\n') -> None:
		"""
		print a single string to the output file.
		assumes `end` doesn't have tabs in it.
		"""

		nonlocal extra_newline

		if message is None:
			# don't print anything
			return

		from builtins import print as _print

		if extra_newline:
			_print(end='\n', file=outfile)
			extra_newline = False

		if indent_str != '\t':
			message = message.replace('\t', indent_str)

		_print(message, end=end, file=outfile)

	if output == '-':
		outfile = None
	else:
		if output == "auto":
			outfile = open(f"crc{crc_name}_{data_len}.{extension}", "w", newline='')
		elif outfile is None:
			outfile = open(output, "w", newline='')

	def get_terms(eqn: set) -> str:
		if None in eqn:
			has_const = True
			eqn.discard(None)
		else:
			has_const = False

		terms = xor.join(
			f"{vpfx}{in_port_i}{lbr}{n:{in_idx_max_pad}}{rbr}" if n >= 0 else f"{' '*len(vpfx)}{tmp_port_i}{lbr}{-n - 1:{in_idx_max_pad}}{rbr}"
			for n in sorted(eqn, reverse=True)
		)

		if   has_const:   terms = f"{b1}{xor}{terms}" if terms else b1
		elif terms == "": terms = b0
		elif K != 0:      terms = " "*len(f"{b1}{xor}") + terms

		if has_const:
			# restore the None
			eqn.add(None)

		return terms

	def make_declarations(tmp_defs, outputs, *, inclusive_bound_declarations: bool = True) -> None:
		nonlocal tmp_port_o

		wire_max_pad = 0 # only one of the wires is there, so no padding

		# some languages do stuff like `Signals(18)`, while others are only `17 downto 0` type stuff.
		minus = 0 if inclusive_bound_declarations else -1

		if optimize:
			wire_max_pad = max(
				len(str(len(tmp_defs) + minus)),
				len(str(sum_bits + minus))
			)

			print(wire_type(tmp_port_o, f"{len(tmp_defs) + minus:{wire_max_pad}}"))

		tmp_idx_max_pad = len(str(len(tmp_defs) + minus))

		max_pad_diff = out_idx_max_pad - tmp_idx_max_pad
		if   max_pad_diff < 0: tmp_port_o  = tmp_port_o[:max_pad_diff]
		elif max_pad_diff > 0: tmp_port_o += ' '*max_pad_diff

		# local signal declaration
		print(wire_type(local_port, f"{sum_bits + minus:{wire_max_pad}}"))

		print(begin_logic)

		## regular assignments
		for i in range(len(tmp_defs)):
			print(f"{prefix}{tmp_port_o}{lbr}{i:{tmp_idx_max_pad}}{rbr}{assign}{get_terms(tmp_defs[1 + i])}{suffix}")

		if optimize: print("") # separate `tmp_sgnl_base` from `local_crc`

		for i in range(sum_bits):
			print(f"{prefix}{local_port}{lbr}{i:{out_idx_max_pad}}{rbr}{assign}{get_terms(outputs[i])}{suffix}")

	def job_ret() -> tuple[any, str | None]:
		"helper function. use `return job_ret()`"

		if output == "auto":
			outfile.close()
			return None, outfile.name

		return outfile, (None if outfile is None else outfile.name)

	# main formats
	if syntax in {"vhd", "v", "sv", "am", "nmg", "ch", "ch3", "sp"}:
		is_svl = syntax == "sv"
		is_nmg = syntax == "nmg"
		is_ch3 = syntax == "ch3"

		tmp_defs, outputs = optimize_gates(rows)

		# header
		match syntax:
			case "vhd":
				print(
					f"-- Generated with {prog}.py"
					f"\nlibrary ieee;"
					f"\nuse ieee.std_logic_1164.all;"
					f"\n"
					f"\nentity crc{crc_name}_{data_len} is"
					f"\n\tgeneric ("
					f"\n\t\t-- true => little endian, false => big endian"
					f"\n\t\tBSWAP : boolean := true"
					f"\n\t);"
					f"\n\tport ("
					f"\n\t\t{in_port}{in_pad}: in  std_logic_vector({data_bits - 1:{idx_max_pad}} downto 0);"
					f"\n\t\t{out_port}{out_pad}: out std_logic_vector({sum_bits - 1:{idx_max_pad}} downto 0)"
					f"\n\t);"
					f"\nend entity;"
					f"\n"
					f"\narchitecture crc{crc_name}_{data_len}_arch of crc{crc_name}_{data_len} is"
					f"\n\t-- polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n\t-- crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
				)
			case "v" | "sv":
				print(
					f"// Generated with {prog}.py"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\nmodule crc{crc_name}_{data_len} #("
					f"\n\t// 1 => little endian, 0 => big endian"
					f"\n\tparameter{" bit" if is_svl else ""} BSWAP = 1"
					f"\n) ("
					f"\n\tinput  [{data_bits - 1:{idx_max_pad}} : 0] {in_port},"
					f"\n\toutput [{sum_bits - 1:{idx_max_pad}} : 0] {out_port}"
					f"\n);"
					f"\n"
				)
			case "am" | "nmg":
				print(
					f"{(
						"try:"
						"\n\tfrom nmigen import Module, Signal"
						"\nexcept ImportError:"
						"\n\tfrom amaranth import Module, Signal"
						if is_nmg else
						"from amaranth.lib.wiring import Component, In, Out"
						"\nfrom amaranth import Module, Signal"
					)}"
					f"\nclass Crc{crc_name}_{data_len}({"Elaboratable" if is_nmg else "Component"}):"
					f"\n\t\"\"\""
					f"\n\tGenerated with {prog}.py"
					f"\n\tpolynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n\tcrc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\n\tbswap: True => little endian, False => big endian"
					f"\n\t\"\"\""
					f"\n"
					f"\n\t{in_port}{in_pad}: {  "Signal" if is_nmg else f"In  ({data_bits:{idxp1_max_pad}})" }"
					f"\n\t{out_port}{out_pad}: {"Signal" if is_nmg else f"Out ({sum_bits :{idxp1_max_pad}})" }"
					f"\n\t"
					f"\n\tdef __init__(self, bswap: bool = True) -> None:"
					f"\n\t\tself.bswap = bswap"
					f"{(
						f"\n"
						f"\n\t\tself.{in_port}{in_pad}= Signal({data_bits:{idxp1_max_pad}})"
						f"\n\t\tself.{out_port}{out_pad}= Signal({sum_bits:{idxp1_max_pad}})"
						if is_nmg else
						f"\n\t\tsuper().__init__()"
					)}"
					f"\n"
					f"\n\tdef elaborate(self, platform{'' if is_nmg else f': "Platform | None"'}) -> Module:"
					f"\n\t\tm = Module()"
					f"\n\t\tc = m.d.comb"
					f"\n"
					f"\n\t\t{in_port}{in_pad}= self.{in_port}"
					f"\n\t\t{out_port}{out_pad}= self.{out_port}"
					f"\n"
				)
			case "ch" | "ch3":
				print(
					f"// Generated with {prog}.py"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\nimport chisel3._"
					f"\nimport chisel3.util._"
					"\n"
					f"\nclass crc{crc_name}_{data_len}(val bswap: Boolean = true) extends Module {{"
					f"{(
						f"\n\tval io = IO(new Bundle {{"
						f"\n\t\tval {in_port}{in_pad}= Input (UInt({data_bits:{idxp1_max_pad}}.W))"
						f"\n\t\tval {out_port}{out_pad}= Output(UInt({sum_bits:{idxp1_max_pad}}.W))"
						f"\n\t}})"
						if is_ch3 else
						f"\n\tval {in_port}{in_pad}= IO(Input (UInt({data_bits:{idxp1_max_pad}}.W)))"
						f"\n\tval {out_port}{out_pad}= IO(Output(UInt({sum_bits:{idxp1_max_pad}}.W)))"
					)}"
					f"\n"
				)
			case "sp":
				print(
					f"// Generated with {prog}.py"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"import spinal.core._"
					f"\n"
					f"\nclass crc{crc_name}_{data_len}(bswap: Boolean = true) extends Component {{"
					f"\n\tval io = new Bundle {{"
					f"\n\t\tval {in_port}{in_pad}= in  UInt({data_bits:{idxp1_max_pad}} bits)"
					f"\n\t\tval {out_port}{out_pad}= out UInt({sum_bits:{idxp1_max_pad}} bits)"
					f"\n\t}}"
					f"\n"
				)
			case _:
				raise Exception("`match` case mismatch with containing logic.")

		make_declarations(tmp_defs, outputs, inclusive_bound_declarations=syntax not in {"vhd", "v", "sv"})

		if sum_len == 1:
			# don't emit a generate block for sum length 1 since it does nothing.
			if syntax == "sp":
				print(f"\n\t{vpfx}{out_port}{assign}{local_port}.asUInt")
			elif syntax in {"ch", "ch3"}:
				print(f"\n\t{out_port}{assign}{local_port}.asUInt")
			else:
				print(f"\n{prefix}{out_port}{assign}{local_port}{suffix}")

			print(footer)
			return job_ret()

		# generate
		match syntax:
			case "vhd":
				print(
					f"\n\tendian_check: if BSWAP generate"
					f"\n\t\tlittle_endian: for i in 0 to {sum_len - 1} generate"
					f"\n\t\t\t{out_port}(8*i + 7 downto 8*i) <= {local_port}({sum_bits - 1} - 8*i downto {sum_bits - 8} - 8*i);"
					f"\n\t\tend generate;"
					f"\n\telse generate"
					f"\n\t{prefix}{out_port}{assign}{local_port}{suffix}"
					f"\n\tend generate;"
				)
			case "v" | "sv":
				print(
					f"{'' if is_svl else "\ngenvar i;"}"
					f"\ngenerate"
					f"\n\tif (BSWAP)"
					f"\n\t\tfor ({"genvar " if is_svl else ''}i = 0; i < {sum_len}; {"i++" if is_svl else "i = i + 1"})"
					f"\n\t\t\tassign {out_port}[8*i + 7 : 8*i] = {local_port}[{sum_bits - 1} - 8*i : {sum_bits - 8} - 8*i];"
					f"\n\telse"
					f"\n\t\t{prefix}{out_port}{assign}{local_port}{suffix}"
					f"\nendgenerate"
				)
			case "am" | "nmg":
				print(
					f"\n\t\tif self.bswap:"
					f"\n\t\t\tfor i in range({sum_len}):"
					f"\n\t\t\t\tc += {out_port}[8*i : 8*i + 8].eq( {local_port}[{sum_bits - 8} - 8*i : {sum_bits} - 8*i] )"
					f"\n\t\telse:"
					f"\n\t{prefix}{out_port}{assign}{local_port}{suffix}"
				)
			case "ch" | "ch3":
				print(
					f"\n\tio.{out_port} := ("
					f"\n\t\tif (bswap) "
					f"\n\t\t\tCat({local_port}.asBools.grouped(8).map(Cat(_)).toSeq.reverse)"
					f"\n\t\telse "
					f"\n\t\t\t{local_port}.asUInt"
					f"\n\t)"
				)
			case "sp":
				print(
					f"\n\tio.{out_port} := ("
					f"\n\t\tif (bswap)"
					f"\n\t\t\t{local_port}.subdivideIn(8 bits).reverse.asBits.asUInt"
					f"\n\t\telse"
					f"\n\t\t\t{local_port}.asUInt"
					f"\n\t)"
				)
			case _:
				raise Exception("`match` case mismatch with containing logic.")

		print(footer)
		return job_ret()

	# assembly formats
	if syntax.startswith("asm=") and syntax not in {"asm=json", "asm=j"}:
		# it is okay to do this before the match/case because the `case _` branch
		# should never execute in a production version of the compiler.
		tmp_defs, outputs = optimize_gates(rows)

		in_ofs  = 0
		tmp_ofs = data_bits
		out_ofs = data_bits + len(tmp_defs)

		if syntax == "asm=ir":
			asm_ir_settings = asm_ir_settings.copy()

			if verbose >= 1:
				eprint(
					f"# scheduling instructions\n"
					f"# stack offsets: in={in_ofs}, tmp={tmp_ofs}, out={out_ofs}, max={asm_ir_settings["max_ofs"]}"
				)

			asm_ir_settings["in_ofs"]  =  in_ofs
			asm_ir_settings["tmp_ofs"] = tmp_ofs
			asm_ir_settings["out_ofs"] = out_ofs

			if asm_ir_settings["emit_comments"]:
				print(
					f"| Generated with {prog}.py\n"
					f"| void crc{crc_name}_{data_len}(uint8_t {in_port}[{data_len}], uint{c_type_length(1 << sum_bits)}_t *{out_port});"
				)


			print( '\n'.join(asm_gen.gen_ir(
				tmp_defs, outputs,
				crc_name, data_len, sum_len,
				**asm_ir_settings
			)) )

			return job_ret()

		if asm_format_data is None:
			raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")

		asm_ir_settings = asm_format_data["settings"]

		asm_ir_settings["reg_slots"] = len(asm_format_data["regw"])
		asm_ir_settings["in_ofs"]    = in_ofs
		asm_ir_settings["tmp_ofs"]   = tmp_ofs
		asm_ir_settings["out_ofs"]   = out_ofs
		asm_ir_settings["emit_round_numbers"] = True

		grammar   = asm_format_data["grammar"]
		byteorder = asm_ir_settings.pop("byteorder")

		if verbose >= 1:
			eprint(
				f"# scheduling instructions\n"
				f"# stack offsets: in={in_ofs}, tmp={tmp_ofs}, out={out_ofs}, max={asm_ir_settings["max_ofs"]}"
			)

		program = asm_gen.gen_ir(
			tmp_defs, outputs,
			crc_name, data_len, sum_len,
			**asm_ir_settings
		)

		if verbose >= 1:
			eprint("# processing IR code")

		# basically just a static namespace
		class gd: # grammar data
			pass

		gd.regw     = asm_format_data["regw"]
		gd.regb     = asm_format_data["regb"]
		gd.in_ofs   = in_ofs
		gd.tmp_ofs  = tmp_ofs
		gd.out_ofs  = out_ofs
		gd.function = f"crc{crc_name}_{data_len}"
		gd.comment  = asm_format_data["comment"]

		from functools import partial

		for key, val in grammar.items():
			if callable(val):
				grammar[key] = partial(val, k=gd)

		program = crc_dsl.generate(
			program,
			grammar,
			pp_vars={"$byteorder": byteorder},
			strict=False # TODO: probably remove this once it isn't needed for testing
		)

		print(f"{gd.comment} Generated with {prog}.py")
		print(f"{gd.comment} void {gd.function}(uint8_t {in_port}[{data_len}], uint{c_type_length(1 << sum_bits)}_t *{out_port});")
		print('\n'.join(program))
		return job_ret()

	# secondary formats
	match syntax:
		case "pyt" | "py" | "c" | "c++":
			# compute optimized equation graph
			tmp_defs, outputs = optimize_gates(rows)

			if syntax in {"python-test", "pyt"}:
				# also give functions for testing the functionality
				# meant for only the first time, so you paste them to wherever
				# it is being used, and then switch to 'python' or 'py'

				print(
					"import crcmod, zlib"
					"\nfrom secrets import randbits"
					"\nfrom copy import deepcopy"
					"\n"
					"\ndef crc_check(fn: str, size: int = 1, data: bytes | None = None) -> tuple[int, int]:"
					"\n\tif data is None:"
					"\n\t\tdata = randbits(size * 8).to_bytes(size)"
					"\n"
					"\n\tuser     = eval(f\"crc{fn}_{size}\")(data)"
					"\n\texpected = crcmod.predefined.mkCrcFun(fn)(data)"
					"\n\tcorrect  = user == expected"
					"\n"
					"\n\treturn correct, data, user, expected, bin(user ^ expected)"
					"\n"
					"\ndef crc_check_some(fn: str, size: int = 1, n: int = 64):"
					"\n\tuser_fn = eval(f\"crc{fn}_{size}\")"
					"\n\tcrcmod_fn = crcmod.predefined.mkCrcFun(fn)"
					"\n"
					"\n\tfails = []"
					"\n"
					"\n\tfor i in range(n):"
					"\n\t\tdata = randbits(size * 8).to_bytes(size)"
					"\n\t\tuser = user_fn(data)"
					"\n\t\texpected = crcmod_fn(data)"
					"\n"
					"\n\t\tif user != expected:"
					"\n\t\t\tfails.append(data)"
					"\n"
					"\n\treturn fails or None"
					"\n"
					"\ndef crc_check_all(fn: str, size: int = 1):"
					"\n\tuser_fn = eval(f\"crc{fn}_{size}\")"
					"\n\tcrcmod_fn = crcmod.predefined.mkCrcFun(fn)"
					"\n"
					"\n\tfails = []"
					"\n"
					"\n\tfor i in range(2**(8*size)):"
					"\n\t\tdata = i.to_bytes(size)"
					"\n\t\tuser = user_fn(data)"
					"\n\t\texpected = crcmod_fn(data)"
					"\n"
					"\n\t\tif user != expected:"
					"\n\t\t\tfails.append(data)"
					"\n"
					"\n\treturn fails or None"
					"\n"
					"\ndef crc_check_vecs(fn: str, size: int = 1):"
					"\n\tuser_fn   = eval(f\"crc{fn}_{size}\")"
					"\n\tcrcmod_fn = crcmod.predefined.mkCrcFun(fn)"
					"\n"
					"\n\tfails = []"
					"\n"
					"\n\tfor data in [bytes(size)] + [(1 << n).to_bytes(size, byteorder='big') for n in range(8 * size)]:"
					"\n\t\tuser     = user_fn(data)"
					"\n\t\texpected = crcmod_fn(data)"
					"\n"
					"\n\t\tif user != expected:"
					"\n\t\t\tfails.append(data)"
					"\n"
					"\n\treturn fails or None"
					"\n"
					"\ndef test_equivalence(s: list[set], tmp_defs: dict[int, set], outputs: list[set]) -> bool:"
					"\n\t\"\"\""
					"\n\ts is the unoptimized equation list. tmp_defs and outputs are the optimized form."
					"\n\treturns true if they are equivalent and false if they are not equivalent."
					"\n\t\"\"\""
					"\n"
					"\n\timport gf2_cse"
					"\n\treturn gf2_cse.expand_gates(deepcopy(tmp_defs), deepcopy(outputs)) == s"
					"\n"
				)

			# "input bits" or "input data"
			in_bits = "inb" if in_port != "inb" else "ind"

			in_port_i  = in_bits
			tmp_port_i = tmp_sgnl_base

			if in_port in {"bit_", "byte_"}:
				raise ValueError(f"`--in-port '{in_port}'` cannot be given with `--syntax '{syntax}'`")

			if out_port in {"bit_", "byte_"}:
				raise ValueError(f"`--in-port '{out_port}'` cannot be given with `--syntax '{syntax}'`")

			if syntax in {"c", "c++"}:
				print(
					f"#include <stdint.h>"
					f"\n"
					f"\nuint{sum_bits}_t crc{crc_name}_{data_len}(uint8_t {in_port}[{data_len}]) {{"
					f"\n\tuint8_t {in_bits}[{data_bits}];"
					f"\n\tuint{c_type_length(data_bits)}_t idx = 0;"
					f"\n"
					f"\n\tfor (uint{c_type_length(data_len)}_t byte_ = 0; byte_ < {data_len}; byte_++)"
					f"\n\t\tfor (uint8_t bit_ = 8; bit_ --> 0 ;)"
					f"\n\t\t\t{in_bits}[idx++] = ({in_port}[byte_] >> bit_) & 1;"
					f"\n"
				)
			else:
				print(
					f"def crc{crc_name}_{data_len}({in_port}: bytes | bytearray) -> int:"
					f"\n\tassert isinstance({in_port}, bytes | bytearray), \"input must be bytes or bytearray\""
					f"\n\tassert len({in_port}) == {data_len}, \"input must be {data_len} bytes long\""
					f"\n"
					f"\n\t{in_bits} = []"
					f"\n\tfor byte_ in {in_port}:"
					f"\n\t\tfor bit_ in range(7, -1, -1):"
					f"\n\t\t\t{in_bits}.append((byte_ >> bit_) & 1)"
					f"\n"
				)

			make_declarations(tmp_defs, outputs, inclusive_bound_declarations=True)

			if syntax in {"c", "c++"}:
				print(
					f"\n\tuint{sum_bits}_t {out_port} = 0;"
					f"\n\tfor (uint{c_type_length(sum_bits)}_t i_ = 0; i_ < {sum_bits}; i_++)"
					f"\n\t\t{out_port} |= {local_port}[i_] << i_;"
					f"\n"
					f"\n\treturn {out_port};"
				)
			else:
				print(
					f"\n\t{out_port} = 0"
					f"\n\tfor i in range({sum_bits}):"
					f"\n\t\t{out_port} |= {local_port}[i] << i"
					f"\n"
					f"\n\treturn {out_port}"
				)

			print(footer)
		case "gv":
			# Graphviz is so different from the other syntaxes that most of the `syntax_data` attributes don't make sense.

			in_idx_max_pad = 0
			in_port_i = "in"

			starting_gates    = gf2_cse.count_gates(rows)
			tmp_defs, outputs = optimize_gates(rows)

			print(
				f"{comment} Generated with {prog}.py"
				f"\n{comment} compile: dot -Tpdf -O crc{crc_name}_{data_len}.gv"
				f"\ndigraph crc{crc_name}_{data_len} {{"
			)

			graph_depth = gf2_cse.graph_depth(tmp_defs, outputs)

			# NOTE: ranksep = (input_count * (width + nodesep)) / graph_depth - height
			#               = (data_bits * 1) / graph_depth - 0.5
			#       I have no idea where this ^^^^ came from, but it seems to work well,
			#       except for when it doesn't, but then you can just change it manually

			# try and give a sensible default rank separation.
			# if it is bad, then the user can just change it themselves.
			# I only tested crc8, crc16, crc32, and crc64.
			# I tested data lengths 1, 2, 4, 6, 16, and 32 for each
			if sum_len == 4:
				ranksep = data_bits / graph_depth - 0.5
			else:
				ranksep = (1 + (data_len == 1))*4*data_len / graph_depth - 0.5

			print(
				"\tlayout = dot;"
				"\n\tconcentrate = true;"
				"\n\tsplines = polyline;"
				f"\n\tranksep = {ranksep};"
				"\n"
				"\n\t// these ones should be the default"
				"\n\tnode [width = 0.75, height = 0.5];"
				"\n\tnodesep = 0.25;"
				"\n"
				"\n\t{"
				"\n\t\trank = same;"
			)

			decls: list[str] = []
			decl_len = 0
			for i in range(data_bits):
				decl = f'"in[{i}]";'

				if decl_len + len(decl) + len(decls) >= GV_DECL_LINE_WRAP:
					print("\t\t" + " ".join(decls))
					decls.clear()
					decl_len = 0

				decls.append(decl)
				decl_len += len(decl)

			if decls:
				print("\t\t" + " ".join(decls))

			if any(len(eqn) == 0 for eqn in outputs):
				print('\t\t"0";')

			if any(None in eqn for eqn in tmp_defs.values()) or any(None in eqn for eqn in outputs):
				print('\t\t"1";')

			print("\t}\n")

			if optimize:
				print(f"\t// {tmp_sgnl_base} declarations:")

			for i in range(len(tmp_defs)):
				terms = get_terms(tmp_defs[1 + i]).replace(' ', '').replace(',', ', ')
				print(f"\t{{\"{terms}\"}} -> \"{tmp_sgnl_base}[{i}]\";")

			if optimize: print("")

			print("\t{\n\t\trank = same;")

			decls    = []
			decl_len = 0
			for i in range(sum_bits):
				decl = f'"out[{i}]";'

				if decl_len + len(decl) + len(decls) >= GV_DECL_LINE_WRAP:
					print("\t\t" + " ".join(decls))
					decls.clear()
					decl_len = 0

				decls.append(decl)
				decl_len += len(decl)

			if decls:
				print("\t\t" + " ".join(decls))

			print("\t}\n")

			print("\t// outputs:")
			for i in range(sum_bits):
				terms = get_terms(outputs[i]).replace(' ', '').replace(',', ', ')
				print(f"\t{{\"{terms}\"}} -> \"out[{i}]\";")

			print(footer)
		case "i":
			# info
			print(
				"CRC Summary:"
				f"\ncustom      = {str(poly is not None).lower()}"
				f"\nalgorithm   = {crc_name}"
				f"\ndata len    = {data_len}"
				f"\nsum len     = {sum_len}"
				f"\nbase #gates = {gf2_cse.count_gates(rows)}"
				f"\nCRC(empty)  = 0x{K:0{sum_nibs}X}"
				f"\npolynomial  = 0x{polynomial:0{sum_nibs}X}"
				f"\nreversed polynomial = 0x{reversed_polynomial:0{sum_nibs}X}"
			)

			if poly is not None:
				print(
					"\nRocksoft Parameters:"
					f"\ninit    = 0x{init:0{sum_nibs}X}"
					f"\nxor_out = 0x{xor_out:0{sum_nibs}X}"
					f"\nreflect = {str(reflected).lower()}"
				)
		case "ir" | "r":
			# NOTE: the output for this is not JSON
			cse_time_stt      = perf_counter_ns()
			tmp_defs, outputs = optimize_gates(rows)
			cse_time_end      = perf_counter_ns()

			if syntax == "ir":
				sep = "\n\t"
				pad = ' '
			else:
				sep = ''
				pad = ''

			td = {}

			# reindex so it is in ascending order
			for i in range(1, len(tmp_defs) + 1):
				td[i] = tmp_defs[i]

			data = (
				f'{{'
				f'{sep}"tmp_defs":{pad}{td},'
				f'{sep}"outputs":{pad}{outputs},'
				f'{sep}"crc_name":{pad}"{crc_name}",'
				f'{sep}"data_len":{pad}{data_len},'
				f'{sep}"starting_gates":{pad}{starting_gates},'
				f'{sep}"ending_gates":{pad}{ending_gates},'
				f'{sep}"gate_reduction":{pad}{starting_gates - ending_gates},'
				f'{sep}"compression":{pad}{0.0 if starting_gates == 0.0 else 1 - ending_gates / starting_gates},'
				f'{sep}"logic_depth":{pad}{{"start":{pad}{starting_logic_depth},{pad}"end":{pad}{ending_logic_depth},{pad}"lut_size":{pad}{float("inf") if lut_size is None else lut_size}}},'
				f'{sep}"max_fanout":{pad}{{"start":{pad}{starting_max_fanout},{pad}"end":{pad}{ending_max_fanout}}},'
				f'{sep}"gen_time_ns":{pad}{curve_gen_time_end - curve_gen_time_stt},'
				f'{sep}"cse_time_ns":{pad}{cse_time_end - cse_time_stt}'
				f"{'\n' if syntax == "ir" else ''}}}"
			)

			print(data if syntax == "ir" else data.replace(' ', ''))
		case "json" | "j" | "metrics" | "m" | "asm=json" | "asm=j":
			cse_time_stt      = perf_counter_ns()
			tmp_defs, outputs = optimize_gates(rows)
			cse_time_end      = perf_counter_ns()

			tmp_syntax = syntax[4:] if syntax.startswith("asm=") else syntax

			def json_dump_data(data: dict[str, any], indent: str | None, seps: tuple[str, str]) -> str:
				import json

				# sets aren't serializable, so I have do this nonsense to make them print properly
				class Encoder(json.JSONEncoder):
					def default(self, obj) -> str:
						"assume the unknown object is a set"

						if type(obj) is not set:
							raise NotImplementedError("default() only implemented for sets")

						hasNone = None in obj
						obj.discard(None)
						lst = sorted(obj, reverse=True)

						if hasNone:
							lst.insert(0, None)

						return f"\u0000{json.dumps(lst, separators=inseps)}\u0000"

				return (json
					.dumps(data, indent=indent, separators=seps, cls=Encoder)
					.replace('"\\u0000', '')
					.replace('\\u0000"', '')
				)

			indent = '\t'        if len(tmp_syntax) > 1 else None
			seps   = (',', ': ') if len(tmp_syntax) > 1 else (',', ':')
			inseps = (', ', ':') if len(tmp_syntax) > 1 else (',', ':')

			data: dict[str, any] = {}

			if tmp_syntax[0] == 'j':
				td = {}

				# reindex so keys are in ascending order
				for i in range(1, len(tmp_defs) + 1):
					td[i] = tmp_defs[i]

				data["tmp_defs"]   = td
				data["outputs"]    = outputs

			# do this stuff after the other stuff for the dictionary key ordering.
			data["crc_name"]       = crc_name
			data["data_len"]       = data_len
			data["starting_gates"] = starting_gates
			data["ending_gates"]   = ending_gates
			data["gate_reduction"] = starting_gates - ending_gates
			data["compression"]    = 0.0 if starting_gates == 0.0 else 1 - ending_gates / starting_gates
			data["logic_depth"]    = {
				"start": starting_logic_depth,
				"end": ending_logic_depth,
				"lut_size": float("inf") if lut_size is None else lut_size
			}
			data["max_fanout"]     = {
				"start": starting_max_fanout,
				"end": ending_max_fanout
			}
			data["gen_time_ns"]    = curve_gen_time_end - curve_gen_time_stt
			data["cse_time_ns"]    = cse_time_end - cse_time_stt
			print(json_dump_data(data, indent, seps))
		case "nop":
			if optimize:
				# just for the output
				optimize_gates(rows)
		case _:
			raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")

	return job_ret()

def parse_toml(source: str, files_seen: set) -> dict:
	"""
	the argument is either a file path to a TOML file, inline TOML, or neither.
	if it is neither, an error will be thrown, otherwise the TOML object is given.
	"""
	import tomllib

	try:
		path = os.path.realpath(source)
		with open(source, "r") as f:
			source = f.read()

		if path in files_seen:
			raise ValueError(f"duplicate TOML file path given: '{path}'")

		files_seen.add(path)
	except FileNotFoundError, OSError:
		# `open` can throw other errors, but they don't really matter. just let them propogate.
		# try and parse it as inline TOML if it didn't parse as a file path.
		pass

	if "'''" in source or '"""' in source:
		raise ValueError("TOML input is invalid (contains multiline strings)")

	if dsl_avail:
		# only use the DSL preprocessor if it exists
		source = source.split('\n')

		try:
			source = crc_dsl.preproc(source)
		except Exception as e:
			raise ValueError("TOML input is invalid (preprocessing failed)") from e

		source = '\n'.join(source)

	try:
		return tomllib.loads(source)
	except tomllib.TOMLDecodeError:
		raise ValueError("TOML input is invalid (TOML decode failed)")

def parse_input(args: object) -> list[dict[str, any]]:
	"figure out the curve dictionary stuff from the input TOML files"

	if args.polynomial is not None:
		# --polynomial
		try:
			return [{
				"name":       None,
				"polynomial": int(args.polynomial, 0),
				"init":       args.init    or 0,
				"xor-out":    args.xor_out or 0,
				"reflect":    args.reflect
			}]
		except ValueError:
			raise ValueError(f"`--polynomial` given a non-integer value: '{args.polynomial}'")
	elif not args.programs:
		# neither positional nor polynomial is given
		return [{
			"name":       args.algorithm, # this being None is handled later
			"polynomial": None,
			"init":       None,
			"xor-out":    None,
			"reflect":    None,
		}]

	if args.in_port   is not None: raise ValueError("TOML input and `--in-port` cannot both be given")
	if args.out_port  is not None: raise ValueError("TOML input and `--out-port` cannot both be given")
	if args.tmp_name  is not None: raise ValueError("TOML input and `--tmp-name` cannot both be given")
	if args.data_len  is not None: raise ValueError("TOML input and `--data-len` cannot both be given")
	if args.algorithm is not None: raise ValueError("TOML input and `--algorithm` cannot both be given")
	if args.init      is not None: raise ValueError("TOML input and `--init` cannot both be given")
	if args.xor_out   is not None: raise ValueError("TOML input and `--xor-out` cannot both be given")
	if args.reflect              : raise ValueError("TOML input and `--reflect` cannot both be given")

	files_seen = set()

	# make sure all the programs preprocess and parse before potentially giving any other errors
	toml_dicts = [parse_toml(toml, files_seen) for toml in args.programs]

	## propogate top-level attributes into each curve

	for i, toml in enumerate(toml_dicts, 1):
		# for each program:
		if "curve" not in toml:
			raise ValueError(f"TOML program {i} does not have a `curve` attribute")

		if type(toml["curve"]) is dict:
			toml["curve"] = [toml["curve"]]

		if type(toml["curve"]) is not list:
			raise ValueError(f"TOML program {i} `curve` is not a dictionary or a list")

		for curve in toml["curve"]:
			# for each curve in the program

			for key, val in toml.items():
				# for each top-level attribute in the program

				# curve attributes take precedence over top-level attributes
				if key != "curve" and key not in curve:
					curve[key] = val

	# in 3.15: curves = [*d["curve"] for d in toml_dicts]
	# I hate this syntax, it is backwards of what it should be
	curves = [curve for d in toml_dicts for curve in d["curve"]]

	## validate and normalize curve parameters

	for i, curve in enumerate(curves, 1):
		remainder = set(curve) - {
			"in-port", "out-port", "tmp-name", "data-len",
			"name", "polynomial", "init", "xor-out", "reflect"
		}

		if remainder:
			raise ValueError(f"TOML `[[curve]]` element {i} has unknown attributes: '{"', '".join(remainder)}'")

		if "in-port" in curve and type(curve["in-port"]) is not str:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `in-port` is not a string")

		if "out-port" in curve and type(curve["out-port"]) is not str:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `out-port` is not a string")

		if "tmp-name" in curve and type(curve["tmp-name"]) is not str:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `tmp-name` is not a string")

		if "data-len" in curve and type(curve["data-len"]) is not int:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `data-len` is not an integer")

		if "name" in curve:
			if type(curve["name"]) is not str:
				raise ValueError(f"TOML `[[curve]]` element {i} attribute `name` is not a string")

			if any(key in curve for key in ("polynomial", "init", "xor-out", "reflect")):
				raise ValueError(f"TOML file `[[curve]]` element {i} attribute `name` is not given alone")

			curve["polynomial"] = None
			curve["init"]       = None
			curve["xor-out"]    = None
			curve["reflect"]    = None
			continue

		curve["name"] = None

		if "polynomial" not in curve:
			raise ValueError(f"TOML `[[curve]]` element {i} doesn't have a `name` or `polynomial` attribute")
		elif type(curve["polynomial"]) is not int:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `polynomial` is not an integer")

		if "init" not in curve:
			curve["init"] = 0
		elif type(curve["init"]) is not int:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `init` is not an integer")

		if "xor-out" not in curve:
			curve["xor-out"] = 0
		elif type(curve["xor-out"]) is not int:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `xor-out` is not an integer")

		if "reflect" not in curve:
			curve["reflect"] = False
		elif type(curve["reflect"]) is not bool:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `reflect` is not a boolean")

	return curves

curves = parse_input(args)

del parse_toml, parse_input

args.in_port  = "data" if args.in_port  is None else args.in_port
args.out_port = "crc"  if args.out_port is None else args.out_port
args.tmp_name = "tmp"  if args.tmp_name is None else args.tmp_name
args.data_len = 4      if args.data_len is None else args.data_len

if syntax == "nop":
	# ignore `-o`. this is just so it doesn't create any files.
	output = '-'

	# don't do any caching either
	cache_settings = ''

outfile = None
first   = True

filenames     = set()
bad_filenames = set()

for curve in curves:
	save = (args.in_port, args.out_port, args.tmp_name, args.data_len)

	if not first and verbose >= 1:
		eprint("")

	if verbose >= 2:
		eprint(f"# job params={curve}")

	if "in-port"  in curve: args.in_port  = curve["in-port"]
	if "out-port" in curve: args.out_port = curve["out-port"]
	if "tmp-name" in curve: args.tmp_name = curve["tmp-name"]
	if "data-len" in curve: args.data_len = curve["data-len"]

	args.algorithm  = curve["name"]
	args.polynomial = curve["polynomial"]
	args.init       = curve["init"]
	args.xor_out    = curve["xor-out"]
	args.reflect    = curve["reflect"]

	outfile, filename = run_job(output, optimize, args, not first and output != "auto", asm_ir_settings, outfile)

	(args.in_port, args.out_port, args.tmp_name, args.data_len) = save
	first = False

	if output == "auto":
		if filename in filenames:
			bad_filenames.add(filename)
		else:
			filenames.add(filename)

if bad_filenames and verbose >= 0:
	eprint(f"\x1b[1;33m# warning: some output files were shadowed\x1b[m: '{"', '".join(bad_filenames)}'")

if verbose >= 2:
	eprint(f"# filenames: {filenames}")
