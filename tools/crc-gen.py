"""
HDL compiler for fully unrolled, fully-combinational CRC functions given a fixed-length, byte-aligned input.
batch jobs can be created through TOML input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than CRC32 is used.

"info" / "i" formats output curve metadata in a human readable format
"raw" / "r" formats output the raw graph data as a python object string. it is not valid JSON.
"json" / "j" formats output the raw graph data as a JSON object string with sets replaced with lists.
"m" format gives JSON metrics about the graph reduction without giving the reduced graph.
"python-test" / "pyt" formats output the same code as "python" / "py", but with some extra functions.
"nmigen" / "nmg" formats are the same as "amaranth" / "am" but for the legacy `Elaboratable` API.
"noop" / "nop" formats output nothing except for the stuff that goes to stderr.

during optimization, ^C makes a soft request to stop after the round ends. ^C a second time makes it stop
as soon as possible. The program has to be in focus for it to be noticed. ^C before and after optimization
takes place crashes the program as normal.
"""

# TODO: consider adding Veryl or Spade Rust output formats
# TODO: consider adding FIRRTL and CIRCT IR formats
# TODO: add assembly formats because that would be freaking awesome

if __name__ != "__main__":
	raise Exception("crc-gen.py should only be used at the top level.")

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
prog    = "crc-gen"
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
	("c"  , "c")                         : "c"     ,
	("c++", "cpp")                       : "cpp"   ,
	("metrics",)       : "txt"  , ("m",) : "txt"   ,
	("info",)          : "txt"  , ("i",) : "txt"   ,
	("raw",)           : "txt"  , ("r",) : "txt"   ,
	("json",)          : "json" , ("j",) : "json"  ,
	("asm=json",)      : "json" ,
	("nop", "noop")    : None   ,
}

extension = None

def format_validator(syntax: str) -> str:
	global extension

	syntax = syntax.strip().lower()

	for aliases in formats:
		if syntax in aliases:
			extension = formats[aliases]
			return aliases[0]

	flat_formats = [e for t in formats for e in t] # this nested syntax is stupid. it is backwards

	raise argparse.ArgumentTypeError(f"invalid format '{syntax}'. see `--help=formats` / `-F` for a list of valid formats")

parser = argparse.ArgumentParser(
	description=f"%(prog)s {__version__}\n{__doc__}",
	formatter_class=argparse.RawTextHelpFormatter,
)
parser.add_argument("--help=formats"   , "-F", action="store_true", help="list available formats and exit")
parser.add_argument("--help=algorithms", "-A", action="store_true", help="list available algorithms and exit")
parser.add_argument("--help=toml", action="store_true", help="print out an example TOML program and exit")
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
format_group.add_argument("--tmp-name", "-t", type=str, help="tmp signal name. default is 'tmp'. may creates name collisions with software language-specific variables.\nif it longer than the local signal name, it will cause misaligned expressions.")
format_group.add_argument("--indent", "-g", type=str.lower, help=f"indentation level. options are tabs, tab, none, or int n>=-1. default is 'tabs'")

custom_crc_group = parser.add_argument_group("custom CRC overrides", "custom mode triggers if `--polynomial` is given.")
custom_crc_group.add_argument("--polynomial", "--toml", "-p", type=str, help="polynomial/curve parameters. as an integer, it should include the uppermost bit (e.g. bit 33).\ncan also be a TOML file or inline TOML program (see --help=toml)")
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
optimize_group.add_argument("--optimize-min-gates" , "-m", type=int  , help="enable optimization. exit optimization early when lookahead only sees gate reductions below this threshold.\nfalse negatives are possible for >2 (it may optimize more than desired)")
optimize_group.add_argument("--optimize-max-tmps"  , "-M", type=int  , help="enable optimization. set tmp signal count for when the optimizer exits early.")
optimize_group.add_argument("--optimize-lns"       , "-L", action="store_true", help="enable optimization+LNS without touching settings. LNS is skipped on early exits")
optimize_group.add_argument("--optimize-lns-trials", "-T", type=int  , help="enable optimization+LNS and set the count.")
optimize_group.add_argument("--optimize-lns-window", "-W", type=int  , help="enable optimization+LNS and set the window size.")

cache_group = parser.add_argument_group("caching options")
cache_dir_group = cache_group.add_mutually_exclusive_group()
cache_dir_group.add_argument("--cache-dir"   , "-D", type=str  , help="change the cache directory. doesn't enable optimization. '~' and environment variables are expanded.\ndefault is './crc-cache'.")
cache_dir_group.add_argument("--cache-global", "-G", action="store_true"  , help="use a user global cache directory. cannot appear with `--cache-dir`.")
cache_group.add_argument("--cache"           , "-C", type=str.lower, help="enable optimization and set cache behavior. combination of c/x: clear/expunge, o: off, r: read, w: write,\nu: use/read+write, d: delete entry. o may only appear with c/x. d must appear by itself. case insensitive.\n`%(prog)s -Cc` will clear the cache and exit. cache entries are never automatically invalidated, so they\nmay return old values if the optimizer is updated. a manual cache clear is required in this case.")
args = parser.parse_args()

del core_group, format_group, custom_crc_group, optimize_group, cache_group, cache_dir_group, argparse

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

# TODO: consider expanding on this line wrap idea?
GV_DECL_LINE_WRAP = 100

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
	"8darc": 1,
	"8icode": 1,
	"8itu": 1,
	"8maxim": 1,
	"8rohc": 1,
	"8wcdma": 1,

	"16": 2,
	"16buypass": 2,
	"16dds110": 2,
	"16dect": 2,
	"16dnp": 2,
	"16en13757": 2,
	"16genibus": 2,
	"16maxim": 2,
	"16mcrf4xx": 2,
	"16riello": 2,
	"16t10dif": 2,
	"16teledisk": 2,
	"16usb": 2,
	"x25": 2,
	"xmodem": 2,
	"modbus": 2,
	"kermit": 2,
	"ccittfalse": 2,
	"augccitt": 2,

	"24": 3,
	"24flexraya": 3,
	"24flexrayb": 3,

	"32": 4,
	"32bzip2": 4,
	"32c": 4,
	"32d": 4,
	"32mpeg": 4,
	"posix": 4,
	"32q": 4,
	"jamcrc": 4,
	"xfer": 4,

	"64": 8,
	"64we": 8,
	"64jones": 8,
}

def print_help_formats(formats: tuple[tuple[str, ...], ...] = formats) -> None:
	formats = list(formats)

	print("supported output formats (case insensitive):")

	i = 0
	while i < len(formats):
		e = formats[i] # alias list

		# combine stuff like ("info",), ("i",) into one tuple
		if (
			i + 1 < len(formats)             # not the last format
			and len(e) == 1                  # alias list has one element
			and len(formats[i + 1]) == 1     # next alias list only has one element
			and e[0][0] == formats[i + 1][0] # next format is the first letter of the current one
		):
			e = formats[i] + formats[i + 1]
			formats.pop(i + 1)

		print(f" - {' / '.join(e)}")

		i += 1

def print_help_algs() -> None:
	print("supported named CRCs:")

	prev_size = 0
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

	# if there is only one curve, you can do `[curve]` instead of `[[curve]]`, the compiler exits without doing anything
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

if getattr(args, "help=all"):
	parser.print_help()
	print("\n################################# FORMAT HELP #################################")
	print_help_formats()
	print("\n################################### ALG HELP ##################################")
	print_help_algs()
	print("\n################################## TOML HELP ##################################")
	print_help_toml()
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
syntax_data["ch3"] = {key: val for key, val in syntax_data["ch"].items()}
syntax_data["ch3"]["var_prefix"] = 'io.'

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

def run_job(output: str, optimize: bool, args: object, extra_newline: bool, outfile) -> tuple[any, str | None]:
	"do all the main stuff that has to happen per batch job"
	# returns the output file handle if it is still open, otherwise it returns None
	# and the second value is either the file name or None.

	global cache_settings

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

	tmp_port_i = tmp_sgnl_base + " "*(len(in_port) - len(tmp_sgnl_base))
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
			raise Exception("CRCs other than crc32 require the `crcmod-plus` package.")

		if crc_name is None:
			crc_name = '32'

		sum_len = sum_len_map.get(crcmod.predefined._simplify_name(crc_name), None)

		if sum_len is None:
			raise ValueError(f"crc name '{crc_name}' does not exist or is unknown")

		crc_name = crcmod.predefined._simplify_name(crc_name)
		crc = crcmod.predefined.mkCrcFun(crc_name)

		reflected  = crcmod.predefined._get_definition_by_name(crc_name)["reverse"]
		polynomial = crcmod.predefined._get_definition_by_name(crc_name)["poly"]
		polynomial ^= 1 << (polynomial.bit_length() - 1)

	in_port_i = in_port + " "*(len(tmp_port_i) - len(in_port)) if optimize else in_port

	def optimize_gates(eqns: list[set]) -> tuple[dict[int, set], list[set]]:
		nonlocal ending_logic_depth, ending_max_fanout, in_idx_max_pad
		global optimize, in_port_i

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

		ending_logic_depth = gf2_cse.logic_depth(tmp_defs, outputs, lut_size, sorted=True)
		ending_max_fanout  = gf2_cse.max_fanout(tmp_defs, outputs, nodes=False)

		in_idx_max_pad = max(
			in_idx_max_pad,
			len( str(len(tmp_defs)) )
		)

		if verbose >= 1:
			eprint(f"# LUT{lut_size} logic depth: ~ {starting_logic_depth} => {ending_logic_depth}")
			eprint(f"# max fanout: {starting_max_fanout} => {ending_max_fanout}")

		return tmp_defs, outputs

	# sum_len is the number of bytes in the checksum
	sum_bits  = sum_len << 3 # number of bits in the checksum
	sum_nibs  = sum_len << 1 # number of nibbles in the checksum
	data_bits = data_len << 3

	# idx \in [0, bits - 1]
	in_idx_max_pad  = len(str(data_bits - 1))
	out_idx_max_pad = len(str(sum_bits - 1))
	idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

	# idx + 1 \in [1, bits]
	in_idxp1_max_pad  = len(str(data_bits))
	out_idxp1_max_pad = len(str(sum_bits))
	idxp1_max_pad     = max(in_idxp1_max_pad, out_idxp1_max_pad)

	reversed_polynomial = int(f"{polynomial:0{sum_bits}b}"[::-1], 2)

	lfsr_mask = (1 << sum_bits) - 1

	if reflected:
		lfsr_step = lambda s: (s >> 1) ^ (reversed_polynomial if s & 1 else 0)
	else:
		lfsr_step = lambda s: ((s << 1) ^ polynomial if s >> (sum_bits - 1) else s << 1) & lfsr_mask

	K = crc(bytes(data_len)) # correction vector

	if verbose >= 1:
		eprint("# generating curve vectors", end="", flush=True)

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
		eprint("\r# generating matrix\x1b[K", end="", flush=True)

	rows = [
		{data_bits - 1 - n for n in range(data_bits) if (cols[n] >> bit) & 1}
		for bit in range(sum_bits)
	]

	for bit, eqn in enumerate(rows):
		if (K >> bit) & 1:
			eqn.add(None)

	starting_logic_depth = gf2_cse.logic_depth(None, rows, lut_size)
	ending_logic_depth   = starting_logic_depth
	starting_max_fanout  = gf2_cse.max_fanout(None, rows, nodes=False)
	ending_max_fanout    = starting_max_fanout

	if verbose >= 1:
		eprint("\r# curve generation complete\x1b[K", flush=True)

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
			outfile = open(f"crc{crc_name}_{data_len}.{extension}", "w")
		elif outfile is None:
			outfile = open(output, "w")

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
		minus = -1 if inclusive_bound_declarations else 0

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

		make_declarations(tmp_defs, outputs, inclusive_bound_declarations=syntax in {"vhd", "v", "sv"})

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
		case "raw" | "r":
			# NOTE: the output for this is not JSON
			starting_gates = gf2_cse.count_gates(rows)

			cse_time_stt      = perf_counter_ns()
			tmp_defs, outputs = optimize_gates(rows)
			cse_time_end      = perf_counter_ns()

			ending_gates = gf2_cse.count_gates(tmp_defs, outputs)
			if syntax == "raw":
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
				f"{'\n' if syntax == "raw" else ''}}}"
			)

			print(data if syntax == "raw" else data.replace(' ', ''))
		case "json" | "j" | "metrics" | "m" | "asm=json":
			starting_gates = gf2_cse.count_gates(rows)

			cse_time_stt      = perf_counter_ns()
			tmp_defs, outputs = optimize_gates(rows)
			cse_time_end      = perf_counter_ns()

			ending_gates = gf2_cse.count_gates(tmp_defs, outputs)

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

			indent = '\t'        if len(syntax) > 1 else None
			seps   = (',', ': ') if len(syntax) > 1 else (',', ':')
			inseps = (', ', ':') if len(syntax) > 1 else (',', ':')

			data: dict[str, any] = {}

			if syntax == 'j' or syntax.endswith("json"):
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

				cache_settings = '' # no caching
				optimize_gates(rows)
		case _:
			raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")

	return job_ret()

def parse_polynomial(args: object) -> list[dict[str, any]]:
	"calculate the curve dictionary stuff from the TOML file"

	# give the program a structured input language so I can call this a compiler.
	try:
		if args.polynomial is None:
			return [{
				"name":       args.algorithm,
				"polynomial": None,
				"init":       None,
				"xor-out":    None,
				"reflect":    None,
			}]

		# if you have a file path like "12345", then just put `./` at the start.
		return [{
			"name":       None,
			"polynomial": int(args.polynomial, 0),
			"init":       args.init    or 0,
			"xor-out":    args.xor_out or 0,
			"reflect":    args.reflect
		}]
	except ValueError:
		# polynomial is not none and the int cast failed.
		pass

	import tomllib

	if '\n' in args.polynomial:
		try:
			toml = tomllib.loads(args.polynomial)
		except tomllib.TOMLDecodeError:
			raise ValueError("`--polynomial`/`--toml` given invalid TOML program")
	else:
		try:
			with open(args.polynomial, "rb") as f:
				toml = tomllib.load(f)
		except FileNotFoundError, OSError:
			# `open` can throw other errors, but they don't really matter. just let them propogate.
			# try and parse it as a TOML line if it didn't parse as a file path.
			try:
				toml = tomllib.loads(args.polynomial)
			except tomllib.TOMLDecodeError:
				raise ValueError("`--polynomial`/`--toml` input is not an integer, file path, or TOML program")

	args.polynomial = None

	if args.in_port   is not None: raise ValueError("`--polynomial=<toml>` and `--in-port` both given")
	if args.out_port  is not None: raise ValueError("`--polynomial=<toml>` and `--out-port` both given")
	if args.tmp_name  is not None: raise ValueError("`--polynomial=<toml>` and `--tmp-name` both given")
	if args.data_len  is not None: raise ValueError("`--polynomial=<toml>` and `--data-len` both given")
	if args.algorithm is not None: raise ValueError("`--polynomial=<toml>` and `--algorithm` both given")
	if args.init      is not None: raise ValueError("`--polynomial=<toml>` and `--init` both given")
	if args.xor_out   is not None: raise ValueError("`--polynomial=<toml>` and `--xor-out` both given")
	if args.reflect              : raise ValueError("`--polynomial=<toml>` and `--reflect` both given")

	# this can definitely be refactored to have less code, but it really isn't
	# that much stuff at the moment, so I don't really see a reason to do that

	# global settings
	if "in-port" in toml:
		if args.in_port is not None:
			raise ValueError("TOML attribute `in-port` and `--in-port` both given")

		args.in_port = toml.pop("in-port")

		if type(args.in_port) is not str:
			raise ValueError("TOML attribute `in-port` is not a string")

	if "out-port" in toml:
		if args.out_port is not None:
			raise ValueError("TOML attribute `out-port` and `--out-port` both given")

		args.out_port = toml.pop("out-port")

		if type(args.out_port) is not str:
			raise ValueError("TOML attribute `out-port` is not a string")

	if "tmp-name" in toml:
		if args.tmp_name is not None:
			raise ValueError("TOML attribute `tmp-name` and `--tmp-name` both given")

		args.tmp_name = toml.pop("tmp-name")

		if type(args.tmp_name) is not str:
			raise ValueError("TOML attribute `tmp-name` is not a string")

	if "data-len" in toml:
		if args.data_len is not None:
			raise ValueError("TOML attribute `data-len` and `--data-len` both given")

		args.data_len = toml.pop("data-len")

		if type(args.data_len) is not int:
			raise ValueError("TOML attribute `data-len` is not an integer")

	# curve parameters
	if "curve" in toml:
		curves = toml.pop("curve")

		if type(curves) is dict:
			curves = [curves]

		if type(curves) is not list:
			raise ValueError("TOML attribute `curve` is not a dictionary or a list")

		for i, curve in enumerate(curves):
			if type(curve) is not dict:
				raise ValueError(f"TOML `[[curve]]` index {i} is not a dictionary")

			if "in-port" in curve:
				if type(curve["in-port"]) is not str:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `in-port` is not a string")

			if "out-port" in curve:
				if type(curve["out-port"]) is not str:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `out-port` is not a string")

			if "tmp-name" in curve:
				if type(curve["tmp-name"]) is not str:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `tmp-name` is not a string")

			if "data-len" in curve:
				if type(curve["data-len"]) is not int:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `data-len` is not an integer")

			if "name" in curve:
				if type(curve["name"]) is not str:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `name` is not a string")

				if any(key in curve for key in ("polynomial", "init", "xor-out", "reflect")):
					raise ValueError(f"TOML file `[[curve]]` index {i} attribute `name` is not given alone")

				curve["polynomial"] = None
				curve["init"]       = None
				curve["xor-out"]    = None
				curve["reflect"]    = None
				continue
			else:
				curve["name"] = None

			if "polynomial" in curve:
				if type(curve["polynomial"]) is not int:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `polynomial` is not an integer")
			else:
				raise ValueError(f"TOML `[[curve]]` index {i} doesn't have a `name` or `polynomial` attribute")

			if "init" in curve:
				if type(curve["init"]) is not int:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `init` is not an integer")
			else:
				curve["init"] = 0

			if "xor-out" in curve:
				if type(curve["xor-out"]) is not int:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `xor-out` is not an integer")
			else:
				curve["xor-out"] = 0

			if "reflect" in curve:
				if type(curve["reflect"]) is not bool:
					raise ValueError(f"TOML `[[curve]]` index {i} attribute `reflect` is not a boolean")
			else:
				curve["reflect"] = False

			remainder = set(curve) - {
				"in-port", "out-port", "tmp-name", "data-len",
				"name", "polynomial", "init", "xor-out", "reflect"
			}

			if remainder:
				raise ValueError(f"TOML `[[curve]]` index {i} has unknown attributes: '{"', '".join(remainder)}'")
	else:
		curves = []

	if toml:
		raise ValueError(f"TOML has unknown attributes: '{"', '".join(toml)}'")

	return curves

curves = parse_polynomial(args)
args.in_port  = "data" if args.in_port  is None else args.in_port
args.out_port = "crc"  if args.out_port is None else args.out_port
args.tmp_name = "tmp"  if args.tmp_name is None else args.tmp_name
args.data_len = 4      if args.data_len is None else args.data_len

if syntax == "nop":
	# ignore `-o`. this is just so it doesn't create any files.
	output = '-'

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

	outfile, filename = run_job(output, optimize, args, not first and output != "auto", outfile)

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
