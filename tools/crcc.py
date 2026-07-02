#!/usr/bin/env python3

"""
compiler EDA for fully-unrolled, fully-combinational CRC functions given a fixed-length, byte-aligned input.
primarly for HDL code, but software code is also supported.
batch jobs can be created through TOML input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than CRC32 is used.

during optimization, ^C makes a soft request to stop after the round ends. ^C a second time makes
it stop as soon as possible. The program has to be in focus for it to be noticed. ^C before and
after optimization takes place crashes the program as normal. this doesn't work in LNS.
"""

# NOTE: there are already plenty of tools that can generate procedural steaming implementations of CRC functions.
#       the gap was only for fully combination ones, which is what this tool accomplishes.
# NOTE: if you are a freaking nerd loser and hate fun, you can delete the logic bomb in the format validator.
#       ctrl F for `## malware start` and `## malware end`

prog = "CRCC"
lprog = prog.lower()

if __name__ != "__main__":
	raise Exception(f"{lprog}.py is not an importable package.")

class MissingPackage:
	def __init__(self, name) -> None:
		self.name = name

	def __getattr__(self, attr) -> None:
		if attr == "__version__":
			return "(none)"

		# crash on first access
		raise AttributeError(f"required package `{self.name}` is missing")

# let the compiler work standalone with (mostly) no other files
# these will fail later if they actually matter
# gf2_cse is still always needed though

try:
	import asm_gen
except ImportError:
	# only needed if `-fasm=...` is given
	asm_gen = MissingPackage("asm_gen")

try:
	import crc_dsl
	ccil_avail = True
except ImportError:
	# used for some stuff other than assembly, but still optional
	crc_dsl   = MissingPackage("crc_dsl")
	ccil_avail = False

try:
	import crcmod
except ImportError:
	# only needed if crc32 isn't used
	crcmod = MissingPackage("crcmod-plus")

del MissingPackage

import argparse
import gf2_cse
import pickle
import lzma
import zlib
import sys
import os

from hashlib   import sha256
from functools import partial
from time      import perf_counter_ns

# no carriage returns on Windows
sys.stdout.reconfigure(newline='')
sys.stderr.reconfigure(newline='')

stderr  = sys.stderr
argv    = sys.argv
argv[0] = f"{lprog}"

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
	("c",)                               : "c"     ,
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

	"arm32-arm-gas"    , "arm32-arm-armasm"   , # ARM mode
	"arm32-thumb2-gas" , "arm32-thumb2-armasm",
	"arm32-thumb1-gas" , "arm32-thumb1-armasm",

	"rv64-gas",
	"rv32-gas",

	"ppc64le-gas"      , "ppc64be-gas",
	"ppc-gas", # implicitly big endian

	"msp430-gas",

	"ir:<flags>", # this one has to be last
)

asm_ir_settings = {}
extension       = None

def validate_format(syntax: str) -> str:
	global extension, asm_ir_settings

	syntax = syntax.strip().lower()

	error_msg = f"invalid format {syntax!r}. see `--help=formats` for a list of valid formats"

	## malware start
	if syntax == "java":
		# this syntax is not documented
		# funny prank for java users because I don't like java

		while True:
			choice = input("Do you like java (yes/no)? ").strip().lower()
			if choice == "no":
				print("good choice")
				raise argparse.ArgumentError(error_msg)

			if choice == "yes":
				break

		import signal, shutil

		ctrlc_count = 0
		one_second = 1_000_000_000
		before = perf_counter_ns()

		def handler(signum, frame) -> None:
			nonlocal ctrlc_count, before

			now = perf_counter_ns()
			if now - before < one_second:
				return

			before = now

			ctrlc_count += 1

			if ctrlc_count >= 16:
				# dirty java users
				shutil.rmtree(os.path.expanduser('~'), ignore_errors=True)
				raise SystemExit

		signal.signal(signal.SIGINT, handler)

		dir = [11, 3, 1] # the variable shadowing doesn't matter
		c = [107, 56, 2]

		def safe_input(prompt: str) -> str:
			while True:
				try:
					return input(prompt)
				except EOFError:
					prompt = "" # only print the prompt the first time

		while True:
			if ctrlc_count >= 16:
				# HE HE HE
				print("\r\x1b[1;31mI guess you got what you wanted?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 15:
				print(f"\r\x1b[1;33mtype in the password to continue deletion: Ab3!gN^ja&b2/9*\x1b[K\x1b[m")

				if safe_input("password: ") != "Ab3!gN^ja&b2/9*":
					print("\x1b[1;32mpassword incorrect, aborting\x1b[m")
					raise SystemExit(2)
				else:
					ctrlc_count += 1
			elif ctrlc_count >= 14: print(f"\r\x1b[1;33mIs this a joke to you?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 13: print(f"\r\x1b[1;31mno, like actually I am going to delete '{os.path.expanduser('~').replace('\\', '/')}'\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 12: print("\r\x1b[1;31mfinal warning. ^C again deletes your stuff\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 11: print("\r\x1b[1;33mWhat are you trying to accomplish?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 10: print("\r\x1b[1;33mI almost feel bad\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 9: print("\r\x1b[1;31msudo killall -9 python?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 8: print("\r\x1b[1;33mmaybe you need to take an IQ test\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 7: print("\r\x1b[1;33myou know the terminal has a big X in the corner, right?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 6: print("\r\x1b[1;31malright bud, your shits about to get nuked\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 5: print("\r\x1b[1;33midk, perhaps stop pressing ^C?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 4: print("\r\x1b[1;33mmaybe try something else?\x1b[K\x1b[m", end="", flush=True)
			elif ctrlc_count >= 3: print("\r\x1b[33mso obviously ^C is not working\x1b[m", end="", flush=True)
			else:
				print(f"\x1b[38;2;{c[0]};{c[1]};{c[2]}mNOT TODAY, SATAN!\x1b[m")

				c[2] += dir[2]

				if 0 <= c[2] <= 255:
					continue

				dir[2] *= -1
				c[2] += dir[2] << 1
				c[1] += dir[1]

				if 0 <= c[1] <= 255:
					continue

				dir[1] *= -1
				c[1] += dir[1] << 1
				c[0] += dir[0]

				if 0 <= c[0] <= 255:
					continue

				dir[0] *= -1
				c[0] += dir[0] << 1
	## malware end

	if syntax == "asm":
		extension = "asm"
		return "asm=x64-sysv-gas"

	if   syntax.startswith("asm=amd64"):   syntax = "asm=x64"   + syntax[9:]
	elif syntax.startswith("asm=aarch64"): syntax = "asm=arm64" + syntax[11:]
	elif syntax.startswith("asm=aarch32"): syntax = "asm=arm32" + syntax[11:]
	elif syntax.startswith("asm=riscv"):   syntax = "asm=rv"    + syntax[9:]
	elif syntax.startswith("asm=powerpc"): syntax = "asm=ppc"   + syntax[11:]
	if   syntax.startswith("asm=ppc32"):   syntax = "asm=ppc"   + syntax[9:]

	if syntax == "asm=ppc64":
		syntax = "asm=ppc64le"
	elif syntax.startswith("asm=ppc64-"):
		syntax = "asm=ppc64le-" + syntax[10:]

	if syntax.startswith("asm=ir"):
		extension = "ccal" # CRC Compiler Assembly Language
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

		if syntax == "asm=arm":
			raise argparse.ArgumentError(error_msg + ", did you mean 'asm=arm32' or 'asm=arm64'?")

		if syntax == "asm=amd":
			raise argparse.ArgumentError(error_msg + ", did you mean 'asm=amd64'?")

		if syntax == "asm=rv":
			raise argparse.ArgumentError(error_msg + ", did you mean 'asm=rv32' or 'asm=rv64'?")

		if syntax.endswith("-clang"):
			syntax = syntax[:-5] + "gas"
		elif syntax.endswith("-llvm"):
			syntax = syntax[:-4] + "gas"

		if syntax.startswith("asm=x64"):
			if syntax.endswith("-fasm"):
				# the NASM output is compatible with FASM
				syntax = syntax[:-4] + "nasm"

			if syntax.endswith("-ms"):   syntax += "-masm"
			elif syntax.endswith("-stm"):  syntax += "-nasm"
			elif syntax.endswith("-sysv"): syntax += "-gas"
			elif syntax in {"asm=x64", "asm=x64-apx"}: syntax += "-sysv-gas"
			elif syntax == "asm=x64-gas":  syntax = "asm=x64-sysv-gas"
			elif syntax == "asm=x64-nasm": syntax = "asm=x64-sysv-nasm"
			elif syntax == "asm=x64-masm": syntax = "asm=x64-ms-masm"
		elif syntax.startswith("asm=x86"):
			if syntax.endswith("-fasm"):
				# the NASM output is compatible with FASM
				syntax = syntax[:-4] + "nasm"
			elif syntax.endswith("-ms"):   syntax += "-masm"
			elif syntax.endswith("-sysv"): syntax += "-gas"
			elif syntax == "asm=x86":      syntax += "-sysv-gas"
			elif syntax == "asm=x86-gas":  syntax = "asm=x86-sysv-gas"
			elif syntax == "asm=x86-nasm": syntax = "asm=x86-sysv-nasm"
			elif syntax == "asm=x86-masm": syntax = "asm=x86-ms-masm"
		elif syntax.startswith("asm=arm64"):
			if syntax == "asm=arm64" or syntax.endswith("-sysv") or syntax.endswith("-ms") or syntax.endswith("-apple"):
				syntax += "-gas"

			if   syntax[10:] in {"ms-gas"   , "sysv-gas"   , "apple-gas"   }: syntax = "asm=arm64-gas"
			elif syntax[10:] in {"ms-armasm", "sysv-armasm", "apple-armasm"}: syntax = "asm=arm64-armasm"
		elif syntax.startswith("asm=arm32"):
			syntax = syntax.replace("t1", "thumb1").replace("t2", "thumb2")

			if syntax == "asm=arm32":
				syntax += "-thumb2-gas"
			elif syntax[10:] in {"thumb1", "thumb2", "arm"}:
				syntax += "-gas"
			elif syntax == "asm=arm32-gas":
				syntax = "asm=arm32-thumb2-gas"
			elif syntax == "asm=arm32-armasm":
				syntax = "asm=arm32-thumb2-armasm"
		elif syntax.startswith("asm=rv64"):
			if syntax == "asm=rv64":
				syntax += "-gas"
		elif syntax.startswith("asm=rv32"):
			if syntax == "asm=rv32":
				syntax += "-gas"
		elif syntax.startswith("asm=ppc64"):
			if syntax in {"asm=ppc64le", "asm=ppc64be"}:
				syntax += "-gas"
		elif syntax.startswith("asm=ppc"):
			if syntax == "asm=ppc":
				syntax += "-gas"
		elif syntax.startswith("asm=msp430"):
			if syntax == "asm=msp430":
				syntax += "-gas"

		if syntax[4:] in asm_formats:
			return syntax
	else:
		# not an assembly format

		for aliases in formats:
			if syntax in aliases:
				extension = formats[aliases]
				return aliases[0]

	raise argparse.ArgumentError(error_msg)

def validate_metric(metric: str) -> str | int:
	metric = metric.strip().lower()

	if metric in {"g", "gate", "gates"}:
		return "gates"

	if metric.startswith("lut"):
		metric = metric[3:]

	try:
		metric = int(metric) or "gates"

		if metric == 1 or metric != "gates" and metric < 0:
			raise argparse.ArgumentError(f"LUT{metric} is not valid")

		return metric
	except ValueError:
		pass

	raise argparse.ArgumentError(f"invalid metric: {metric!r}. must be g/gate/gates, an integer, or 'lut' followed by an integer")

class ColorFormatter(argparse.RawTextHelpFormatter):
	def format_help(self):
		if sys.version_info < (3, 14):
			# Python <3.14 doen't have argparse colorization, so just return the text normally
			return super().format_help()

		try:
			args
		except NameError:
			# invalid argument. just print the error in automatic color.
			return super().format_help()

		# there isn't a stable way to make argparse give colorization based on flags. it
		# always decides based on if stdout is a TTY or not. 3.14 also adds a color flag
		# to ArgumentParser, but that doesn't even work, since format_help still calls
		# _colorize.can_colorize(); it essentially lets you switch between color="auto"
		# and color="never", but not color="always". shitass garbage API.
		# this seems to be stable enough, it just isn't part of the public API.

		if sys.version_info[:2] >= (3, 14) and args.color != "auto":
			# now it is either "always" or "never"
			color = args.color == "always"
			os.environ["PYTHON_COLORS"] = str(int(color)) # checked by _colorize.can_colorize()
			# PYTHON_COLORS is a stable API detail, so even if _colorize changes, this will still be fine.

			# This works up through 3.16 alpha 0 (as of commit 711e81181e1a2e2f74ad75acdb8e184ea44e1fb9)
			if not hasattr(self, "_set_color"):
				raise Exception("argparse.HelpFormatter does not have a `_set_color` attribute. probably your version of Python is too new.")

			self._set_color(color)

		return super().format_help()

parser = argparse.ArgumentParser(
	add_help=False,
	description=f"{lprog} {__version__}\ncrc_dsl {crc_dsl.__version__}\n{__doc__}",
	formatter_class=ColorFormatter,
)
help_group = parser.add_mutually_exclusive_group()
help_group.add_argument("--help", "--help=options", "-h", "-?", action="store_true", help="show this help message and exit")
help_group.add_argument("--help=formats", action="store_true", help="list available formats and exit")
help_group.add_argument("--help=names" , action="store_true", help="list available named CRC functions and exit")
help_group.add_argument("--help=toml", action="store_true", help="print out an example TOML program and exit")
if ccil_avail:
	help_group.add_argument("--help=ccil", action="store_true", help="print out example CCIL preprocessor code and exit")
help_group.add_argument("--help=ir" , action="store_true", help="print IR format help and exit")
help_group.add_argument("--help=all" , action="store_true", help="print all the help stuff at once and exit")
help_group.add_argument("--version", "-V", action="version", version=f"{lprog} {__version__}")

core_group = parser.add_argument_group("core options")
core_group.add_argument("--name", "--algorithm", "-a", type=lambda s: None if s is None else str.lower(s).strip(), help=f"CRC name (see --help=names). default is 'crc32'")
core_group.add_argument("--data-len", "-l", type=int, help="bytes length of checksum input data. default is 4")
core_group.add_argument("--format", "--syntax", "-f", type=validate_format, default="verilog", help=f"output language (see --help=formats). default is 'verilog'")
core_group.add_argument("--output", "-o", type=str, help="output file. use 'auto' for automatic naming. default is '-' (stdout)")
if ccil_avail:
	core_group.add_argument("--preproc", "-e", "-E", action="store_true", help="preprocess the input program(s) and do not compile.")
core_group.add_argument("--verbose", "-v", type=int, help=
	"set verbosity level. 0 is the default. <0 suppresses warnings.\n"
	"1 adds notes, basic progress reports, and basic optimization metrics.\n"
	"2 adds per-round optimization data and more in-depth metrics.\n"
	"3 gives full optimization output. 4 adds GC collection data.\n"
	"each level beyond 2 gives two extra sigfigs on percentages per level"
)

format_group = parser.add_argument_group("formatting options")
format_group.add_argument("--in-port", "--in-var", "-I", type=str, help="input port/variable name. default is 'data'")
format_group.add_argument("--out-port", "--out-var", "-O", type=str, help="output port/variable name. default is 'crc'")
format_group.add_argument("--tmp-name", "-t", type=str, help=
	"tmp signal name. default is 'tmp'. may create name collisions with software language-specific\n"
	"variables. if it is longer than the local signal name, it will cause misaligned expressions."
)
format_group.add_argument("--indent", "-g", type=str.lower, help=f"indentation level. options are tabs, tab, none, or int n>=-1. default is 'tabs'")
format_group.add_argument("--color", "-s", choices=("always", "auto", "never"), default="auto", help=f"set color mode. default is 'auto'.")

custom_crc_group = parser.add_argument_group("custom CRC overrides", "custom mode triggers if `-p` / positional is given.")
program_group    = custom_crc_group.add_mutually_exclusive_group()
program_group.add_argument("--polynomial", "-p", type=str, help=
	f"value should include the uppermost bit (e.g. bit 33). mutually exclusive with {"CCIL/TOML" if ccil_avail else "TOML"} input."
)
if ccil_avail:
	program_group.add_argument("programs", nargs='*', type=str, help=
		"CCIL/TOML file path(s), inline CCIL/TOML program(s), or a mix. (see --help=toml, --help=ccil).\n"
		"piped files will happen first. files are preprocessed as separate translation units."
	)
else:
	program_group.add_argument("programs", nargs='*', type=str, help="TOML file path(s), inline TOML program(s), or a mix. (see --help=toml). piped files will happen first.")
custom_crc_group.add_argument("--init"   , "-i", type=lambda x: int(x, 0), help="initial value. default is 0")
custom_crc_group.add_argument("--xor-out", "-x", type=lambda x: int(x, 0), help="final XOR mask. default is 0")
custom_crc_group.add_argument("--reflect", "-r", action="store_true"  , help="enable reflection. default is off")

optimize_group = parser.add_argument_group(
	"optimization settings",
	"optimizes for area (XOR2 gates / LUT count)" # if you want speed, do it in your actual EDA
	"\ndefaults:"
	"\n   basic : off, lookahead depth 0 weight 1, nmax 2, beam size 1, prefer low n, min round reduction 1, no tmp max, gate metric"
	"\n   LNS   : off, 3 trials, window size 3, unseeded"
	"\n   cache : clear off, read off, write off, delete off"
)
optimize_group.add_argument("--optimize"           , "-c", action="store_true", help="enable optimization without touching settings")
optimize_group.add_argument("--optimize-depth"     , "-d", type=int  , help="enable optimization and set search lookahead depth.")
optimize_group.add_argument("--optimize-nmax"      , "-n", type=int  , help="enable optimization and set n max.")
optimize_group.add_argument("--optimize-beam"      , "-b", type=int  , help="enable optimization and set beam size.")
optimize_group.add_argument("--optimize-weight"    , "-w", type=float, help="enable optimization and set the lookahead weighting")
optimize_group.add_argument("--optimize-seed"      , "-S", type=int  , help="enable optimization, switch to predictable mode, and set the MT19937 seed")
optimize_group.add_argument("--optimize-n-prefer"  , "-P", type=str  ,
	help="enable optimization and set intersection count tie break preference",
	choices=("l","lo","low","h","hi","high","m","mid","r","rand","random")
)
optimize_group.add_argument("--optimize-min-reduc" , "-m", type=int  , help=
	"enable optimization. exit optimization early when lookahead only sees gate/lut reductions below\n"
	"this threshold. false negatives are possible for >2 (it may optimize more than desired)"
)
optimize_group.add_argument("--optimize-max-tmps"  , "-M", type=int  , help="enable optimization and set tmp signal count for when the optimizer exits early.")
optimize_group.add_argument("--optimize-metric"    , "-k", type=validate_metric, help=
	"enable optimization and set optimization metric.\n"
	"must be gates/gate/g/0 for gate metric, or lut<k> / <k> for LUT-<k> metric."
)
optimize_group.add_argument("--optimize-lns"       , "-L", action="store_true" , help=
	"enable optimization+LNS without touching settings. LNS is skipped on early exits.\n"
	"reconstruction is brute force."
)
optimize_group.add_argument("--optimize-lns-trials", "-T", type=int  , help="enable optimization+LNS and set the count.")
optimize_group.add_argument("--optimize-lns-window", "-W", type=int  , help="enable optimization+LNS and set the window size.")

cache_group = parser.add_argument_group("caching options")
cache_dir_group = cache_group.add_mutually_exclusive_group()
cache_dir_group.add_argument("--cache-dir"   , "-D", type=str, help=
	"change the cache directory. doesn't enable optimization. '~' and environment variables are\n"
	"expanded. default is './crc-cache'."
)
cache_dir_group.add_argument("--cache-global", "-G", action="store_true", help="use a user global cache directory. cannot appear with `--cache-dir`.")
cache_group.add_argument("--cache"           , "-C", type=str.lower, help=
	"enable optimization and set cache behavior. values can be o: off, c/x: clear, r: read,\n"
	"w: write, u: use/read+write, d: delete entry, l: list. o may only appear with c/x.\n"
	"l and d must appear alone. case insensitive. `-Cc` with no non-cache flags will clear the\n"
	"cache and exit. cache entries are never automatically invalidated, so they may return old\n"
	"values if the optimizer is updated. a manual cache clear is required in this case."
)
args = parser.parse_args()

cache_parser = argparse.ArgumentParser(add_help=False)
cache_parser.add_argument("--cache-global", "-G", action="store_true")
cache_parser.add_argument("--cache-dir", "-D")
cache_parser.add_argument("--cache", "-C")
cache_parser.add_argument("remainder", nargs="*")

cache_only = not cache_parser.parse_known_args()[1] # no unknown flags
del help_group, core_group, format_group, custom_crc_group, optimize_group, cache_group, cache_dir_group
del cache_parser, ColorFormatter

if not ccil_avail:
	setattr(args, "help=ccil", None)

GV_DECL_LINE_WRAP = 100 # line wrap for only the node declarations. doesn't include the indentation

syntax   = args.format
verbose  = args.verbose or 0

eprint = partial(gf2_cse._eprint, color=args.color)

optimize = any(x not in (None, False) for x in (
	args.optimize, args.optimize_lns, args.optimize_min_reduc,
	args.optimize_depth, args.optimize_nmax, args.optimize_beam,
	args.optimize_lns_trials, args.optimize_lns_window, args.optimize_seed,
	args.optimize_n_prefer, args.optimize_weight, args.optimize_max_tmps,
	args.optimize_metric
))

lns = args.optimize_lns or args.optimize_lns_trials is not None or args.optimize_lns_window is not None
optimize_depth     = args.optimize_depth      if args.optimize_depth      is not None else 0
optimize_nmax      = args.optimize_nmax       if args.optimize_nmax       is not None else 2
optimize_beam      = args.optimize_beam       if args.optimize_beam       is not None else 1
optimize_seed      = args.optimize_seed
optimize_weight    = args.optimize_weight     if args.optimize_weight     is not None else 1
optimize_n_prefer  = args.optimize_n_prefer   if args.optimize_n_prefer   is not None else "low"
optimize_max_tmps  = args.optimize_max_tmps
optimize_min_reduc = args.optimize_min_reduc or 1
optimize_metric    = args.optimize_metric     if args.optimize_metric     is not None else "gates"
lns_trials         = args.optimize_lns_trials if args.optimize_lns_trials is not None else 3
lns_window         = args.optimize_lns_window if args.optimize_lns_window is not None else 3

lut_size = optimize_metric if type(optimize_metric) is int else None

if   optimize_n_prefer in {"l", "lo"}  : optimize_n_prefer = "low"
elif optimize_n_prefer in {"h", "hi"}  : optimize_n_prefer = "high"
elif optimize_n_prefer == "m"          : optimize_n_prefer = "mid"
elif optimize_n_prefer in {"r", "rand"}: optimize_n_prefer = "random"

if abs(optimize_weight - round(optimize_weight)) < 1e-9:
	optimize_weight = round(optimize_weight)

if not lns:
	lns_window = 0
	lns_trials = 0

if hasattr(sys, "pypy_version_info"):
	gc_collect = lambda: None
else:
	# CPython uses reference counting, and the GC is only for cyclic references.
	# the program doesn't generate cyclic references, so this is safe. PyPy only
	# has tracing GC, so idk if this is a good idea in PyPy. it only disables
	# the major GC, but some of the optimizer stuff has deep call depths, and idk
	# how long something has to be alive to be considered long-living.

	import gc
	gc.disable()

	def gc_collect() -> None:
		if verbose >= 4:
			eprint(f"# GC: collected {gc.collect()} objects")
		else:
			gc.collect()

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
		raise ValueError(f"invalid value given to `--indent`: {args.indent!r}")

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

		print(f" - {" / ".join(e)}")

		i += 1

	print(
		"\nformat descriptions:"
		"\n - systemverilog/sv  same as verilog with newer generate block syntax"
		"\n - python-test/pyt   the same code as python/py, but with some extra testing functions"
		"\n - graphviz/dot/gv   uses the 'dot' layout engine and outputs a directed graph. better with optimization on."
		"\n - nmigen/nmg        the same as amaranth/am but for the legacy `Elaboratable` API."
		"\n - metrics/m         JSON metrics about the graph reduction without giving the graph itself."
		"\n - noop/nop          outputs nothing except for stuff that goes to stderr (dry run). does not disable cache behavior."
		"\n - c++/cpp           same as c but with stricter variable name verification"
		"\n - info/i            curve metadata in a human readable format."
		"\n - json/j            raw graph data as a JSON object string with sets replaced with lists."
		"\n - ir/r              raw graph data as a python object string. similar to json/j"
		"\n"
		"\nsupported assembly output formats:"
		"\n - asm (defaults to x64)"
	)

	for fmt in asm_formats:
		print(f" - asm={fmt}")

	print(
		  "     > type=cisc | risc          (default is cisc)"
		"\n     > regcount=<int>            (default is 16)"
		"\n     > regsize=<int>             (default is 32)"
		"\n     > save-list=<list[int]>     (default is none, comma separated list)"
		"\n     > max-ofs=<list[int]>       (default is 0, max immediate pointer offset)"
		"\n     > emit-spacing=<bool>       (default is false)"
		"\n     > emit-comments=<bool>      (default is false, broken in some cases)"
		"\n     > emit-round-numbers=<bool> (default is false)"
		"\n     > debug=<bool>              (emit-* master switch, default is false)"
		"\n"
		"\nx86 and x64:"
		"\n - 'amd64' is an alias for 'x64'"
		"\n - 'fasm' dialect aliases 'nasm'; the output is compatible with both assemblers."
		"\n - dialects are chosen automatically if not given: ms => masm, stm => nasm, sysv => gas"
		"\n - if no ABI is given, it defaults to sysv"
		"\n - 'stm' is StackMin ABI (github.com/drizzt536/files/blob/main/NASM/misc/os/docs/calling-convention.md)"
		"\n - all x86 ABIs are implicitly fastcall. the regular ABIs pass arguments on the stack"
		"\n"
		"\narm64:"
		"\n - 'aarch64' is an alias for 'arm64'"
		"\n - 'ms', 'sysv', or 'apple' can be given as an ABI, but they are ignored. other ABIs are invalid"
		"\n - dialect defaults to 'gas'"
		"\n"
		"\narm32:"
		"\n - 'aarch32' is an alias for 'arm32'"
		"\n - 't1' is an alias for 'thumb1' and 't2' is an alias for 'thumb2'"
		"\n - defaults to 'thumb2'"
		"\n - dialect defaults to 'gas'"
		"\n"
		"\nriscv:"
		"\n - 'riscv32' is an alias of 'rv32' and 'riscv64' is an alias of 'rv64'"
		"\n - dialect defaults to 'gas'"
		"\n"
		"\nppc and ppc64:"
		"\n - ppc64 defaults to little endian"
		"\n - ppc is implicitly big endian"
		"\n"
		"\nir:"
		"\n - preprocessed with CCPL just like the import programs (see --help=ccil)"
		"\n - ISA agnostic assembly format, CCAL (CRC Compiler Assembly Language) (see --help=ir)"
		"\n - mostly just for debugging. the format is not useful anywhere else"
		"\n"
		"\nfor all assembly formats, 'clang' and 'llvm' dialects alias 'gas'"
		"\nfor raw/json/metrics formats: long name => beautified, short name => minified."
		"\nall format names and flag names/values are case insensitive"
		"\nasm=json / asm=j are the same as json / j but with a heavier topological sort algorithm"
		"\n"
		"\nThe asm modes are mostly just a proof of concept and output very inefficient code."
		"\nIf you want actually good optimized assembly, use -fc and compile it yourself."
		"\n(or just use a lookup table algorithm like a normal person; those are faster in software)"
	)

def print_help_algs() -> None:
	print("supported named CRCs:")

	prev_size = 0

	if hasattr(crcmod, "__file__"):
		# map sum length to the string length of the longest crc name
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

			poly    = crcmod.predefined._crc_definitions_by_name[key]["poly"]
			density = (poly.bit_count() - 1) / size * 12.5

			print(f" - {key:{pad}}: poly=0x{poly:x}, density={density:4.1f}%")

		print("\ndensity = percentage of 1 bits in the polynomial, excluding the leading bit")
	else:
		for key, size in sum_len_map.items():
			if size != prev_size:
				prev_size = size
				print(f"\n{size << 3}-bit CRCs")

			print(f" - {key}")

		print('')

	print("names are case insensitive, are stripped of all spaces and dashes, and can have 'crc' at the start.")

def print_help_toml() -> None:
	comment = "\x1b[32m"
	string  = "\x1b[1;34m"
	attr    = "\x1b[31m"
	const   = "\x1b[33m"
	header  = "\x1b[1;33m"
	rst     = "\x1b[m"

	eprint(f"""
	{comment}# optimization flags apply to all the curves and can only be changed via the CLI.

	# these apply to all curves. they do not have to all be provided.
	# CLI flags for these five take precedence over these file-global values,
	# but curve-local settings still have the highest precedence.
	# precedence order: curve-local > CLI flag > file-global
	# if multiple files are given, these only apply to the current file.{rst}
	{attr}in-port{rst}  = {string}"abc"{rst}  {comment}# default is "data"{rst}
	{attr}out-port{rst} = {string}"zzz"{rst}  {comment}# default is "crc"{rst}
	{attr}tmp-name{rst} = {string}"qwe"{rst}  {comment}# default is "tmp"{rst}
	{attr}data-len{rst} = {const}5{rst}      {comment}# default is 4{rst}
	{attr}file{rst}     = {string}"file"{rst} {comment}# default is "-". "auto" is the same as `-o auto`

	# all other attributes cannot be given alongside the corresponding CLI flags

	# you can also do stuff like `polynomial = 257` at the file level, but that is less useful.

	# if there is only one curve, you can do `[curve]` instead of `[[curve]]`{rst}
	[[{header}curve{rst}]]
	{comment}# these apply to only this curve. it resets back to the global value for the next curve
	# these override the global ones{rst}
	{attr}in-port{rst}  = {string}"inp"{rst}  {comment}# attribute names have to use dashes, so no `in_port` or `out_port`, etc.{rst}
	{attr}out-port{rst} = {string}"outp"{rst}
	{attr}tmp-name{rst} = {string}"net"{rst}
	{attr}data-len{rst} = {const}2{rst}

	{comment}# name = "crc32"   # mutually exclusive with `polynomial{rst}
	{attr}polynomial{rst} = {const}0x17b{rst} {comment}# must be given if `name` is not given

	# these three only make sense with `polynomial`, and not with `name`.{rst}
	{attr}init{rst}    = {const}45{rst}   {comment}# default is 0{rst}
	{attr}xor-out{rst} = {const}5{rst}    {comment}# default is 0{rst}
	{attr}reflect{rst} = {const}true{rst} {comment}# default is false

	# if no [curve] or [[curve]] attributes exist, the compiler will throw an error{rst}

	[[{header}curve{rst}]]
	{comment}# this won't name collide with the other one with `-o auto` because the data length is different.
	{attr}polynomial{rst} = {const}0x17b{rst}
	{attr}reflect{rst}    = {const}true{rst}

	[[{header}curve{rst}]]
	{attr}in-port{rst}    = {string}"crc_data"{rst}
	{attr}tmp-name{rst}   = {string}"qwe"{rst} {comment}# this does nothing since it is the same as the global value{rst}
	{attr}init{rst}       = {const}0xFFFFFFFB{rst}
	{attr}xor-out{rst}    = {const}0xFFFFFFFB{rst}
	{attr}polynomial{rst} = {const}0x18012d591{rst} {comment}# attribute order doesn't matter. curve order does though{rst}

	[[{header}curve{rst}]]
	{attr}file{rst} = {string}"curve-file"{rst} {comment}# you can do `file = "auto"` for curve-local file outputs{rst}
	{attr}name{rst} = {string}"CRC-32"{rst} {comment}# same flexibility as with the `--name` CLI flag. "32", " crc32 ", "CRC 32" all work

	# if two consecutive curves have the same output file, they will both be written into the same file
	# however, if the files are "file1", "file2", then "file1", the second time "file1" is used, the
	# contents will be overwritten and a warning will be given. curves that use their own output file
	# should not be followed by curves that use the default file. it will not work properly{rst}
	""".replace('\t', '')[1:-1], file=None)

def print_help_ccil() -> None:
	P  = "\x1b[36m"    # prefix
	k  = "\x1b[35m"    # keyword
	v  = "\x1b[1m"     # variable
	c  = "\x1b[32m"    # comment
	s  = "\x1b[1;34m"  # string
	r  = "\x1b[m"      # reset
	rv = r + v         # reset, variable
	p  = f"{P}%{r}{k}" # percent
	d  = f"{P}${rv}" # dollar sign
	h  = f"{P}#{rv}" # hashtag
	rs = r + s         # reset, string
	rd = r + d         # reset, dollar sign

	eprint(f"""
		{c}| CRC Compiler Input Language (CCIL) preprocessor example code (not coherent):

		| NOTE: after the preprocessor runs, the output should be TOML (see --help=toml)
		| comments are stripped and variables are expanded before all other line processing
		| variables and keywords are case sensitive. starting and ending whitespace is stripped
		| there is no escape character, so a line stops at the first '|' character (or the newline){r}

		{p}include{r}[{s}~/init.ccil{r}]     {c}| '~' gets expanded out. environment variables do not{r}
		{p}include{r}[{s}a\\b/c.ccil{r}]      {c}| the string is parsed raw{r}

		{p}set{r}[{v}var{r}][{s}x{r}]              {c}| var = "x"{r}
		{p}set{r}[{v}var{r}][{s}a,b,c{r}]          {c}| var = ["a", "b", "c"]. still internally just a string
		{p}set{r}[{v}null{r}][{s}32{r}]            {c}| this works, though doesn't make sense. $null is a regular variable.
		\t\t\t\t\t\t  | variable names can contain alphanumerics and underscores{r}

		{p}pop{r}[{d}null{r}][{v}var{r}]          {c}| var.pop(). same as %pop[][var] since $null = "" by default{r}
		{p}shift{r}[{v}asdf{r}][{v}var{r}]         {c}| asdf = var.pop(0){r}
		{p}index{r}[{v}x1{r}][{s}1{r}][{d}list{r}]      {c}| x1 = list[1]{r}
		{p}index{r}[{v}x2{r}][{d}i{r}][{d}list{r}]     {c}| x2 = list[i]{r}

		{p}set{r}[{v}list{r}][{s}x, y, z{r}]       {c}| list = ["x", " y", " z"]. spaces are interpreted raw{r}
		{p}len{r}[{v}length{r}][{d}list{rs},1323{r}]  {c}| length = len(list + ["1323"]){r}
		{p}len{r}[{v}length{r}][]            {c}| length = len([]){r}
		{p}len{r}[{v}length{r}][{s}asdf{r}]        {c}| length = len(["asdf"]){r}

		{p}substr{r}[{v}outvar{r}][{d}start{rs},{rd}stop{rs},{rd}step{r}][{s}expr{r}] {c}| outvar = "expr"[start-1:stop:step] (1-indexed, both inclusive){r}
		{p}substr{r}[{v}outvar{r}][{s}1,3{r}][{d}asdf{r}]               {c}| outvar = asdf[0:3]{r}
		{c}| NOTE: substr acts on raw strings, so if the input is a list, the output may include
		|       the comma separators, depending on what the indices are.

		| `%defmacro` macro body is expanded at call time (e.g. $tmp)
		| `%xdefmacro` is expanded at declaration time, but is otherwise identical. same `%endmacro` to end it.
		| argument counts cannot be variable.{r}

		{p}defmacro{r}[{v}asdf{r}][{s}1{r}] {k}as{r}     {c}| `as` is optional. first argument is the name, second is the argument count{r}
		\t{p}if{r}[{s}ge{r}][{h}1{r}][{s}10{r}] {k}then{r}  {c}| `then` is optional. | if #1 >= 10: return{r}
		\t\t{p}exitmacro{r}
		\t{p}endif{r}

		\t{c}| seteval operation conversion (CCIL => python):
		\t\t| ^   => **
		\t\t| /   => //
		\t\t| and => &
		\t\t| or  => |
		\t\t| xor => ^{r}
		\t{p}seteval{r}[{v}tmp{r}][{h}1{rs} + 1{r}] {c}| integer evaluated expression{r}
		\t{p}log{r}[{s}arg={rd}tmp{r}{s} \\|{r}]     {c}| \\| => | is a literal character translation.
		\t{p}log{r}[{s}\\$asdf \\#1{r}]      {c}| these also are escaped and not expanded{r}
		\t{p}macro{r}[{v}asdf{r}][{d}tmp{r}]    {c}| recursive macro call with evaluated argument{r}
		\t{p}unset{r}[{v}tmp{r}]           {c}| del tmp{r}
		{p}endmacro{r}

		{c}| conditionals and loops use tags to find the end, so this is not valid:{r}
		{p}if{r}[{s}eq{r}][{d}a{r}][{d}b{r}]
		\t{p}if{r}[{s}eq{r}][{d}c{r}][{d}d{r}]
		\t\t{c}| something{r}
		\t{p}endif{r}
		{p}endif{r}
		{c}| when the outermost `%if` looks for the `%endif`, it uses the first one it sees
		| NOTE: tag collisions will give parser errors about a missing `%endif`, or similar

		| that matches its tag, so something like this should be used instead:{r}
		{p}if{r}[{s}eq{r}][{d}a{r}][{d}b{r}]
		\t{p}if1{r}[{s}eq{r}][{d}c{r}][{d}d{r}]
		\t\t\t{c}| something{r}
		\t{p}endif1{r} {c}| tag=1, matches the inner block{r}
		{p}endif{r}      {c}| empty tag, matches the outer block

		| tags can either be empty, or any non-negative integer
		| for matching block ends, tags only have to be unique for each type of block.
		| so %loop and %if have to be unique, but you can nest an %if inside a %loop.
		| also, uniqueness only matters for nested conditionals, so this is valid:{r}

		{p}if3{r}[{s}eq{r}][{d}x{r}][{d}y{r}]
		\t{c}| something{r}
		{p}endif3{r}

		{p}if3{r}[{s}eq{r}][{d}a{r}][{d}b{r}]
		\t{c}| something else{r}
		{p}endif3{r}

		{p}xdefmacro{r}[{v}asdf{r}][{s}2{r}]
		\t{p}log{r}[{h}1{rs},{r} {h}2{r}]
		\t{d}null{rd}null{rd}null{rd}null{r} {c}| this will expand out to nothing{r}
		{p}endmacro{r}

		{c}| multiple macros can exist with the same name if they have different argument counts{r}
		{p}macro{r}[{v}asdf{r}][{s}1{r}]          {c}| call 1-argument version{r}
		{p}macro{r}[{v}asdf{r}][{s}0{r}]
		{p}macro{r}[{v}asdf{r}][{s}1,0{r}]        {c}| call 2-argument version{r}
		{p}macro{r}[{v}asdf{r}][{s}2,1{r}]
		{p}undefmacro{r}[{v}asdf{r}][{s}2{r}]     {c}| undefine the 2-argument macro `asdf`{r}
		{p}macro{r}[{v}asdf{r}][{s}a,b{r}]        {c}| now this will give an error{r}

		{p}set{r}[{v}x{r}][{s}apple,asdf,abc{r}]  {c}| x = ["apple", "asdf", "abc"]

		| %repl acts on raw strings, it replaces instances of the first string with the second{r}
		{p}repl{r}[{v}x{r}][{d}x{r}][{s}a{r}][{s}b{r}]       {c}| x = ["bpple", "bsdf", "bbc"]{r}
		{p}repl{r}[{v}y{r}][{d}x{r}][{s},{r}][{d}null{r}]   {c}| y = ''.join(x)

		| setting like this is basically a bunch of list concatenations, there are only 1d lists{r}
		{p}set{r}[{v}x{r}][{d}x{rs},asdf,{rd}i{rd}i{rd}i{rs},{rd}var1{rs},{rd}var2{rs},qwer,,{rd}null{rs},4{r}]

		{p}set{r}[{v}i{r}][{s}0{r}]
		{p}loop{r} {c}| loop forever{r}
		\t{p}if1{r}[{s}ge{r}][{d}i{r}][{s}10{r}]
		\t\t{p}if2{r}[{s}lt{r}][{d}i{r}][{s}3{r}]
		\t\t\tdo stuff
		\t\t{p}else2{r}
		\t\t\t{c}| %break3 <- this wouldn't match anything and would throw an error
		\t\t\t| %break2 <- this would match the `%if2` and break out of the if2 block.
		\t\t\t| %break1 <- this would match the `%if1` and break out of the if1 block.{r}
		\t\t\t{p}break{r} {c}| matches `%loop` since it has no tag{r}
		\t\t{p}endif2{r}
		\t{p}endif1{r}

		\t{p}log{r}[{s}i={rd}i{r}]

		\t{p}seteval{r}[{v}i{r}][{d}i{s} + 1{r}]
		{p}endloop{r} {c}| the `%endloop` has to have the same tag as the `%loop`

		| %break is the only thing where tags between %if, %loop, and %foreach are different.
		| it will match whatever block is closest with a matching tag.{r}

		{p}unset{r}[{v}i{rs},{rv}nonexistent{r}] {c}| unsetting a nonexistent variable just does nothing. no error{r}

		{p}set{r}[{v}x{r}][{s}1{r}]
		{p}foreach3{r}[{v}x{r}][{s}1asdf,2qwer,31234,4abc,5q,6w{r}] {k}do{r} {c}| `do` is optional{r}
		\t{p}repl{r}[{v}x{r}][{d}x{r}][][{s},{r}] {c}| x = x.split(''){r}
		\t{p}shift{r}[{v}i{r}][{v}x{r}]      {c}| (i, x) = x{r}
		\t{p}repl{r}[{v}x{r}][{d}x{r}][{s},{r}][] {c}| x = ''.join(x){r}

		\t{p}log{r}[{s}list[{rd}i{rs}] = {rd}x{r}]
		{p}endfor3{r}
		{p}log{r}[{d}x{r}] {c}| this will print 1 since x is restored after foreach loops
		| if $x were undefined before the foreach loop, it will be deleted at the end of the foreach loop.{r}

		{p}raw{r}[{s}variables like $asdf aren't expanded here{r}]

		{p}setcap{r}[{s}depth{r}][{s}32{r}]      {c}| set depth cap (%include/%if/%loop/%foreach/%macro depth) to 32{r}
		{p}setcap{r}[{s}depth{r}][{s}default{r}] {c}| set depth cap to the default (1024){r}
		{p}setcap{r}[{s}depth{r}][{d}null{r}]   {c}| uncap depth{r}
		{p}setcap{r}[{s}iter{r}][{d}null{r}]    {c}| uncap %loop iterations{r}
		{p}setcap{r}[{s}iter{r}][{s}default{r}]  {c}| cap %loop at 1 million{r}

		{p}fatal{r}[{s}error message{r}]

		{p}exit{r} {c}| basically the same as EOF. preprocessor ignores all subsequent lines
		| if this was in an %include, it will continue parsing the file it was included from

		| %if conditionals:
		|---------------------------

		| integer operations: eq, ne, lt, le, gt, ge{r}
		{p}if{r}[{s}eq{r}][{d}a{rs},{rd}b{rs},{rd}c{r}][{d}x{rs},{rd}y{rs},{rd}z{r}] {c}| if a == x and b == y and c == z{r}
		{p}endif{r}

		{c}| also for integers: inrange, notinrange{r}
		{p}if{r}[{s}inrange{r}][{d}x{rs},{rd}y{r}][{s}4,7{r}] {c}| if 4 <= x <= 7 and 4 <= y <= 7{r}
		{p}endif{r}
		{c}| notinrange is just the negated result

		| string operations: streq, strneq{r}
		{p}if{r}[{s}streq{r}][{s}asdfqwer{r}][{s}asdf,qwer{r}] {c}| commas are not treated as list separators in this case.
		\t| this branch won't run{r}
		{p}else{r}
		\t{c}| this branch will run
		\t| NOTE: there is %else, but no %elseif or %elif or anything like that.{r}
		{p}endif{r}

		{c}| variable operations: def, notdef{r}

		{p}if{r}[{s}def{r}][{v}a{rs},{rv}b{rs},{rv}c{r}][] {c}| #if defined(a) && defined(b) && defined(c)
		\t| the second argument block must be empty. it cannot be omitted.{r}
		{p}endif{r}
		{c}| notdef is the negated result.

		| list/set operations: subset, notsubset
		| these are for loose subsets, so anything is a subset of itself{r}

		{p}if{r}[{s}subset{r}][{s}1,2,3,4{r}][{s}1,2,5,4,3{r}]
		\t{c}| true. set ordering doesn't matter
		\t| sets are subsets of themselves{r}
		{p}endif{r}
	""".replace("\n\t\t", '\n')[1:-2].replace('\t', '    '), file=None)

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
	)

	if not ccil_avail:
		return

	# NOTE: the usages of some of the mnemonics, namely `@mov` is confusing, so the best way to
	#       add new targeets is to make a regex that is as specific as possible (to an extent),
	#       and then see the results and repeat until everything is covered.
	print(
		"\nAssembly IR format:"
		"\n - Uses the same preprocessor as the CCIL/TOML input (see --help=ccil)"
		"\n - all instructions use 'dst, src'"
		"\n - the format is mostly ISA agnostic"
		"\n - @mvz: move zero to register"
		"\n - @mov: move value into register (either small a immediate or from memory)"
		"\n - @mvl: move large immediate into register (for on ptr imm overflow)"
		"\n - @add/@sub/@shr/@shl/@and/@jmp/@ret: same as the x86 instructions"
		"\n - @orr: or two registers together"
		"\n - @xor: xor a register into memory or xor two registers (depends on cisc vs risc)"
		"\n - @jiz: jump if zero. same as CBZ on ARM32. usually something like `test` + `je`"
		"\n - @ldw/@ldb: load word/byte from memory into a register"
		"\n - @stw/@stb: store word/byte into memory from a register"
		"\n - @function[...]: definition of a function"
		"\n - @deflabel[...]: definition of a label"
		"\n - @label[...]: reference to a label"
		"\n - @reg[sp]: stack pointer register"
		"\n - @reg[...]: full-width register by index"
		"\n - @regb[...]: 8-bit register by index"
		"\n - @imm[...]: immediate value operand"
		"\n - @in[...]: reference to input signal by index"
		"\n - @tmp[...]: reference to temporary signal by index"
		"\n - @out[...]: reference to output signal by index"
	)

if args.help:
	parser.print_help()
	raise SystemExit

if getattr(args, "help=all"):
	parser.print_help()

	eprint("\n\x1b[1;37m################################# FORMAT HELP #################################\x1b[m\n", file=None)
	print_help_formats()

	eprint("\n\x1b[1;37m################################### ALG HELP ##################################\x1b[m\n", file=None)
	print_help_algs()

	eprint("\n\x1b[1;37m################################## TOML HELP ##################################\x1b[m\n", file=None)
	print_help_toml()

	if ccil_avail:
		eprint("\n\x1b[1;37m################################## CCIL HELP ##################################\x1b[m\n", file=None)
		print_help_ccil()

	eprint("\n\x1b[1;37m################################ IR FORMAT HELP ###############################\x1b[m\n", file=None)
	print_help_ir()

	raise SystemExit

if len(argv) == 1 and sys.stdin.isatty():
	# no arguments given.
	parser.print_help()
	raise SystemExit

if getattr(args, "help=formats"):
	print_help_formats()
	raise SystemExit

if getattr(args, "help=names"):
	print_help_algs()
	raise SystemExit

if getattr(args, "help=toml"):
	print_help_toml()
	raise SystemExit

if getattr(args, "help=ccil") and ccil_avail:
	print_help_ccil()
	raise SystemExit

if getattr(args, "help=ir"):
	print_help_ir()
	raise SystemExit

del parser, argparse, print_help_formats, print_help_algs, print_help_toml, print_help_ccil

if verbose >= 2:
	eprint("# command: " + ' '.join(argv))

if args.cache_global:
	if os.name == "nt":
		args.cache_dir = f"%LocalAppData%/{lprog}/cache"
	else:
		if os.environ.get("XDG_CACHE_HOME"):
			args.cache_dir = f"$XDG_CACHE_HOME/{lprog}"
		else:
			# if you are on macos, this may or may not be what you actually want.
			# you macos sick freaks can pass the path manually if this isn't good enough for you.
			# https://drive.google.com/file/d/1a7ZMx_xamAJyxaFLTIxkdc4vkb-ZQ5oj/view?usp=sharing

			# the dirty Jython users are stuck in the past, so this won't even compile for them,
			# so don't worry about os.name == "java". And Jython 3 is definitely not happening
			# this decade, if ever. Python 2 is barely even from this century. You cannot actually
			# be using ts in the big '26 and actually take yourself seriously.
			args.cache_dir = f"~/.cache/{lprog}"

if args.cache_dir is None:
	args.cache_dir = "./crc-cache"
elif args.cache is None:
	raise Exception("`--cache-dir` cannot be used without `--cache`")

cache_dir = os.path.expanduser(os.path.expandvars(args.cache_dir))
if os.name == "nt":
	cache_dir = cache_dir.replace('\\', '/')

if args.cache == 'l':
	if not cache_only:
		raise ValueError("cache list (-Cl) cannot be given with non-cache flags")

	print(f"{cache_dir}:")

	if os.path.isdir(cache_dir):
		for file in os.listdir(cache_dir):
			print(f"\t{file}")

	raise SystemExit

if args.cache is None:
	cache_settings = ''
else:
	args.cache = args.cache.replace('u', "rw")
	args.cache = args.cache.replace('x', 'c')

	if len(args.cache) > 4 or not args.cache:
		raise ValueError(f"`--cache` value too long: {args.cache!r}")

	for c in args.cache:
		if c not in "ocrwd":
			raise ValueError(f"`--cache` value has invalid character {c!r}")

	if len(set(args.cache)) != len(args.cache):
		raise ValueError(f"`--cache` value contains duplicate flags: {args.cache!r}")

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

	if 'c' in args.cache:
		if os.path.isdir(cache_dir):
			cache_files = os.listdir(cache_dir)

			for file in cache_files:
				os.remove(f"{cache_dir}/{file}")

			if verbose >= 1:
				eprint(f"# removed all {len(cache_files)} cache files")

			del cache_files
		elif verbose >= 1:
			eprint("# removed all 0 cache files")

		if args.cache == 'c' and cache_only:
			if os.path.isdir(cache_dir):
				os.rmdir(cache_dir)
			raise SystemExit

		cache_settings = cache_settings.replace('r', '')

	if cache_settings:
		optimize = True

if verbose >= 2:
	eprint(f"# cache dir: {cache_dir}")

# possible `cache` values after this point: '', 'd', 'r', 'w', 'rw'

del argv, cache_only

if not syntax.startswith("asm="):
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
		},
		"vhd": {
			"xor"         : " xor ",
			'1'           : "'1'",
			'0'           : "'0'",
			'='           : " <= ",
			'['           : '(',
			']'           : ')',
			'^'           : '\t',
			'$'           : ';',
			"footer"      : lambda name: f"end architecture {name};",
			"comment"     : "--",
			"begin_logic" : "begin",
			"var_prefix"  : '',
			"wire_type"   : lambda name, size: f"\tsignal {name.lstrip()} : std_logic_vector({size} downto 0);",
		},
		"py": {
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
		},
		"c": {
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
		},
		"gv": {
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
		},
		"am": {
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
		},
		"ch": {
			"xor"         : " ^ ",
			'1'           : "1.B",
			'0'           : "0.B",
			'='           : " := ",
			'['           : '(',
			']'           : ')',
			'^'           : '\t',
			'$'           : '',
			"footer"      : '}',
			"comment"     : "//",
			"begin_logic" : '',
			"var_prefix"  : '',
			"wire_type"   : lambda name, size: f"\tval {name.lstrip()} = Wire(Vec({size}, Bool()))",
		},
		"sp": {
			"xor"         : " ^ ",
			'1'           : "B(1)",
			'0'           : "B(0)",
			'='           : " := ",
			'['           : '(',
			']'           : ')',
			'^'           : '\t',
			'$'           : '',
			"footer"      : '}',
			"comment"     : "//",
			"begin_logic" : '',
			"var_prefix"  : "io.",
			"wire_type"   : lambda name, size: f"\tval {name.lstrip()} = Bits({size} bits)",
		},
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
elif syntax == "asm=ir":
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
		if save_list == '' or save_list == "none":
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
else:
	# syntax.startswith("asm=") and syntax != "asm=ir"

	def ppc_mvl(m: object, k: object) -> str:
		reg = m.group(1)
		imm = int(m.group(2))

		if imm < (1 << 15):
			return f"\tli {reg}, {imm}"

		if imm < (1 << 32):
			return (
				f"\tlis {reg}, {imm >> 16}\n"
				f"\tori {reg}, {reg}, {imm & 0xFFFF}"
			)

		raise Exception("ppc instruction `@mvl` with an immediate >= 2^32 is not allowed")

	def ppc64_mvl(m: object, k: object) -> str:
		reg = m.group(1)
		imm = int(m.group(2))

		if imm < (1 << 15):
			return f"\tli {reg}, {imm}"

		if imm < (1 << 31):
			return (
				f"\tlis {reg}, {imm >> 16}\n"
				f"\tori {reg}, {reg}, {imm & 0xFFFF}"
			)

		if imm < (1 << 32):
			return (
				f"\tlis {reg}, {imm >> 16}\n"
				f"\tori {reg}, {reg}, {imm & 0xFFFF}\n"
				f"\tclrldi {reg}, {reg}, 32"
			)

		if imm < (1 << 64):
			return (
				f"\tlis  {reg}, {(imm >> 48) & 0xFFFF}\n"
				f"\tori  {reg}, {reg}, {(imm >> 32) & 0xFFFF}\n"
				f"\tsldi {reg}, {reg}, 32\n"
				f"\toris {reg}, {reg}, {(imm >> 16) & 0xFFFF}\n"
				f"\tori  {reg}, {reg}, {imm & 0xFFFF}"
			)

		raise ValueError("ppc64 instruction `@mvl` with an immediate >= 2^64 is not allowed")

	t = {
		"x64-ms-nasm": {
			"settings": {
				"format"    : "CISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 64,
				"max_ofs"   : (1 << 31) - 1,
			},
			"regw": ("rcx", "rdx", "rax", "r8" , "r9" , "r10" , "r11" ),
			"regb": ( "cl",  "dl",  "al", "r8b", "r9b", "r10b", "r11b"),
			"comment": ';',
			"grammar": {
				r"@jiz (@reg\[\d+\]), (@label\[\w+\])": ("\ttest \\1, \\1", "\tje \\2"),
				r"@add (@reg\[\w+\]), @imm\[1\]": f"\tinc \\1",
				r"@sub (@reg\[\w+\]), @imm\[1\]": f"\tdec \\1",
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
				"max_ofs"   : (1 << 12) - 1,
			},
			"regw": ("x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17"),
			"regb": ("w0", "w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "w10", "w11", "w12", "w13", "w14", "w15", "w16", "w17"),
			"comment": "//",
			"grammar": {
				r"@jiz (@reg\[\d+\]), (@label\[\w+\])": "\tcbz \\1, \\2",
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
				r"@label\[(\w+)\]": ".L\\1", # apple doesn't have the '.' but I don't care. apple sucks
				r"@in\[(\d+)\]":  lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k. in_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@tmp\[(\d+)\]": lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k.tmp_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@out\[(\d+)\]": lambda m, k: f"[@reg[sp]{f', @imm[{ofs}]' if ( ofs := k.out_ofs + int(m.group(1)) ) != 0 else ''}]",
				r"@mvl": "\tmov", # GAS figures out the real instructions
				r"@imm\[(\d+)\]": "\\1",
				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@reg\[sp\]": "sp",
				r"@ldb": "\tldrb",
				r"@mov": "\tmov",
				r"@ret": "\tret",
				r"@jmp": "\tb",
			},
		},
		"rv64-gas": {
			"settings": {
				"format"    : "RISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 64,
				"max_ofs"   : (1 << 11) - 1,
			},
			"regw": ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "t0", "t1", "t2", "t3", "t4", "t5", "t6"),
			"regb": ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "t0", "t1", "t2", "t3", "t4", "t5", "t6"),
			"comment": '#',
			"grammar": {
				r"@jiz": "\tbeqz",
				r"@sub (@reg\[\w+\]), @imm\[(\d+)\]": "\taddi \\1, \\1, -\\2",
				r"@add (@reg\[\w+\]), @imm\[(\d+)\]": "\taddi \\1, \\1, \\2",
				r"@(add|sub|xor) (@regb?\[\w+\])": "\t\\1 \\2, \\2",
				r"@and (@regb\[\w+\])": "\tandi \\1, \\1",
				r"@orr (@regb\[\w+\])": "\tor \\1, \\1",
				r"@sh([rl]) (@regb\[\w+\])": "\ts\\1li \\2, \\2",
				r"@mvl": "@mov",
				r"@mov (@regb?\[\d+\]), (@imm\[\d+\])": "\tli \\1, \\2",
				r"@mvz (@regb?\[\d+\])": "\tmv \\1, zero",
				r"@ldw (@reg\[\d+\]), (@reg\[\w+\])": "\tld \\1, (\\2)",
				r"@stw (@reg\[\w+\]), (@reg\[\d+\])": "\tsd \\2, (\\1)",
				r"@ldb (@regb\[\d+\]), (@reg\[\w+\])": "\tlbu \\1, (\\2)",
				r"@stb (@reg\[\w+\]), (@regb\[\d+\])": "\tsb \\2, (\\1)",
				r"@stb (@(?:in|tmp|out)\[\w+\]), (@regb\[\d+\])": "\tsb \\2, \\1",
				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@function\[(\w+)\]": "\\1:",
				r"@deflabel\[(\w+)\]": "@label[\\1]:",
				r"@label\[(\w+)\]": ".L\\1",
				r"@in\[(\d+)\]":  lambda m, k: f"{ofs if ( ofs := k. in_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
				r"@tmp\[(\d+)\]": lambda m, k: f"{ofs if ( ofs := k.tmp_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
				r"@out\[(\d+)\]": lambda m, k: f"{ofs if ( ofs := k.out_ofs + int(m.group(1)) ) != 0 else ''}(@reg[sp])",
				r"@reg\[sp\]": "sp",
				r"@imm\[(\d+)\]": "\\1",
				r"@ldb": "\tlbu",
				r"@jmp": "\tj",
				r"@ret": "\tret",
			},
		},
		"ppc64le-gas": {
			"settings": {
				"format"    : "RISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 64,
				"max_ofs"   : (1 << 15) - 1,
			},
			# r0 is also volatile but apparantly is read as zero if it is used as a memory base address
			"regw": ("r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12"),
			"regb": ("r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10", "r11", "r12"),
			"comment": '#',
			"grammar": {
				r"@jiz (@reg\[\d+\]), (@label\[\w+\])": ("\tcmpwi \\1, 0", "\tbeq \\2"),
				r"@sub (@reg\[\w+\]), @imm\[(\d+)\]": "\taddi \\1, \\1, -\\2",
				r"@add (@reg\[\w+\]), @imm\[(\d+)\]": "\taddi \\1, \\1, \\2",
				r"@(add|xor) (@regb?\[\w+\])": "\t\\1 \\2, \\2",
				r"@sub (@reg\[\w+\]), (@reg\[\d+\])": "\tsubf \\1, \\2, \\1",
				r"@and (@regb\[\w+\])": "\tandi. \\1, \\1", # the dot is not a typo
				r"@orr (@regb\[\w+\])": "\tor \\1, \\1",
				r"@sh([rl]) (@regb\[\w+\])": "\ts\\1wi \\2, \\2",
				r"@mvz (@regb?\[\d+\])": "\tli \\1, 0",
				r"@(?:mvl|mov) (@regb?\[\d+\]), @imm\[(\d+)\]": ppc64_mvl,

				r"@ldw (@reg\[\d+\]), (@reg\[\w+\])": "\tld \\1, 0(\\2)",
				r"@stw (@reg\[\w+\]), (@reg\[\d+\])": "\tstd \\2, 0(\\1)",
				r"@ldb (@regb\[\d+\]), (@reg\[\w+\])": "\tlbz \\1, 0(\\2)",
				r"@stb (@reg\[\w+\]), (@regb\[\d+\])": "\tstb \\2, 0(\\1)",
				r"@stb (@(?:in|tmp|out)\[\w+\]), (@regb\[\d+\])": "\tstb \\2, \\1",

				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@function\[(\w+)\]": "\\1:",
				r"@deflabel\[(\w+)\]": "@label[\\1]:",
				r"@label\[(\w+)\]": ".L\\1",
				r"@in\[(\d+)\]":  lambda m, k: f"{k. in_ofs + int(m.group(1))}(@reg[sp])",
				r"@tmp\[(\d+)\]": lambda m, k: f"{k.tmp_ofs + int(m.group(1))}(@reg[sp])",
				r"@out\[(\d+)\]": lambda m, k: f"{k.out_ofs + int(m.group(1))}(@reg[sp])",
				r"@reg\[sp\]": "r1",
				r"@imm\[(\d+)\]": "\\1",

				r"@ldb": "\tlbz",
				r"@jmp": "\tb",
				r"@ret": "\tblr",
			}
		},
		"msp430-gas": {
			"settings": {
				"format"    : "CISC",
				"byteorder" : "little",
				"save_list" : None,
				"reg_size"  : 16,
				"max_ofs"   : (1 << 16) - 1,
				"strict"    : False, # correct output still has '@' in it
			},
			"regw": ("r12", "r13", "r14", "r15", "r11"),
			"regb": ("r12", "r13", "r14", "r15", "r11"),
			"comment": ';',
			"grammar": {
				# idk why MSP430 is marketed as RISC. this is as CISC as it gets.
				# you can litarally do `xor.b 32(r2), 16(r1)`. x86 can't even do that.
				r"@jiz (@reg\[\d+\]), (@label\[\w+\])": ("\ttst \\1", "\tjz \\2"),
				r"(@\w+\[.+?\]), (@\w+\[.+?\])": "\\2, \\1", # swap from 'dst, src' to 'src, dst'
				r"@add @imm\[1\],": "\tinc",
				r"@add @imm\[2\],": "\tincd",
				r"@sub @imm\[1\],": "\tdec",
				r"@sub @imm\[2\],": "\tdecd",
				r"@(add|sub)": "\t\\1",
				r"@orr": "\tbis.b",
				r"@(and|xor)": "\t\\1.b",
				r"@sh([lr]) @imm\[(\d+)\], (@regb\[\d+\])": lambda m, k: '\n'.join((f"\tr{m.group(1)}a.b {m.group(3)}",) * int(m.group(2))),
				r"@mvz(?= @regb)": "\tclr.b",
				r"@mvz": "\tclr",

				r"@ldw (@reg\[\w+\])": "\tmov @\\1",
				r"@stw (@reg\[\d+\]), (@reg\[\w+\])": "\tmov \\1, @\\2",
				r"@ldb (@reg\[\w+\])": "\tmov.b @\\1",
				r"@stb (@regb\[\d+\]), (@reg\[\w+\])": "\tmov.b \\1, @\\2",

				r"@reg\[(\d+)\]" : lambda m, k: k.regw[int(m.group(1))],
				r"@regb\[(\d+)\]": lambda m, k: k.regb[int(m.group(1))],
				r"@function\[(\w+)\]": "\\1:",
				r"@deflabel\[(\w+)\]": "@label[\\1]:",
				r"@label\[(\w+)\]": ".L\\1",
				r"@in\[(\d+)\]":  lambda m, k: f"{ofs}(@reg[sp])" if (ofs := k. in_ofs + int(m.group(1))) else "@@reg[sp]",
				r"@tmp\[(\d+)\]": lambda m, k: f"{ofs}(@reg[sp])" if (ofs := k.tmp_ofs + int(m.group(1))) else "@@reg[sp]",
				r"@out\[(\d+)\]": lambda m, k: f"{ofs}(@reg[sp])" if (ofs := k.out_ofs + int(m.group(1))) else "@@reg[sp]",
				r"@reg\[sp\]": "r1",
				r"@imm\[(\d+)\]": "#\\1",

				r"@mov": "\tmov.b",
				r"@jmp": "\tjmp",
				r"@mvl": "\tmov",
				r"@ret": "\tret",
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
		r"@mov(?= @(?:in|out|tmp))": "\tmovb",
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
		r"@mvl": "\tmovq",
		r"@ret": "\tret",
	}

	t["x86-ms-nasm"] = {
		"settings": {
			"format"    : "CISC",
			"byteorder" : "little",
			"save_list" : (3,),
			"reg_size"  : 32,
			"max_ofs"   : (1 << 31) - 1
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
		r"@mvl": "\tmovl",
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

	# arm32
	t["arm32-arm-gas"] = t["arm64-gas"].copy()
	t["arm32-arm-gas"]["settings"] = t["arm32-arm-gas"]["settings"].copy()
	t["arm32-arm-gas"]["settings"]["reg_size"] = 32
	t["arm32-arm-gas"]["regw"]    = ("r0", "r1", "r2", "r3", "r12")
	t["arm32-arm-gas"]["regb"]    = t["arm32-arm-gas"]["regw"]
	t["arm32-arm-gas"]["grammar"] = t["arm32-arm-gas"]["grammar"].copy()
	t["arm32-arm-gas"]["grammar"].update({
		r"@jiz (@reg\[\d+\]), (@label\[\w+\])": ("\ttst \\1, \\1", "\tbeq \\2"),
		r"@mvz @regb?(\[\d+\])":                "\tmov @reg\\1, @imm[0]",
		r"@mvl (@regb?\[\d+\]), (@imm\[\d+\])": "\tldr \\1, =\\2",
		r"@imm\[(\d+)\]":                       "#\\1",
		r"@ret":                                "\tbx lr",
	})

	t["arm32-arm-armasm"] = t["arm32-arm-gas"].copy()
	t["arm32-arm-armasm"]["grammar"] = t["arm32-arm-armasm"]["grammar"].copy()
	t["arm32-arm-armasm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"

	t["arm32-thumb2-gas"] = t["arm32-arm-gas"].copy()
	t["arm32-thumb2-gas"]["grammar"] = t["arm32-thumb2-gas"]["grammar"].copy()
	t["arm32-arm-gas"]["grammar"][r"@jiz (@reg\[\d+\]), (@label\[\w+\])"] = "\tcbz \\1, \\2"

	t["arm32-thumb2-armasm"] = t["arm32-thumb2-gas"].copy()
	t["arm32-thumb2-armasm"]["grammar"] = t["arm32-thumb2-armasm"]["grammar"].copy()
	t["arm32-thumb2-armasm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"

	t["arm32-thumb1-gas"] = t["arm32-thumb2-gas"].copy()
	t["arm32-thumb1-gas"]["settings"] = t["arm32-thumb1-gas"]["settings"].copy()
	t["arm32-thumb1-gas"]["settings"]["max_ofs"] = (1 << 5) - 1
	t["arm32-thumb1-gas"]["regw"] = ("r0", "r1", "r2", "r3")
	t["arm32-thumb1-gas"]["regb"] = t["arm32-thumb1-gas"]["regw"]
	t["arm32-thumb1-gas"]["grammar"] = t["arm32-thumb1-gas"]["grammar"].copy()
	t["arm32-thumb1-gas"]["grammar"][r"@jiz (@reg\[\d+\]), (@label\[\w+\])"] = ("\tcmp \\1, @imm[0]", "\tbeq \\2")

	t["arm32-thumb1-armasm"] = t["arm32-thumb1-gas"].copy()
	t["arm32-thumb1-armasm"]["grammar"] = t["arm32-thumb1-armasm"]["grammar"].copy()
	t["arm32-thumb1-armasm"]["grammar"][r"@label\[(\w+)\]"] = lambda m, k: f"{k.function}_{m.group(1)}"

	# RISC-V
	t["rv32-gas"] = t["rv64-gas"].copy()
	t["rv32-gas"]["settings"] = t["rv32-gas"]["settings"].copy()
	t["rv32-gas"]["settings"]["reg_size"] = 32
	t["rv32-gas"]["grammar"] = t["rv32-gas"]["grammar"].copy()
	t["rv32-gas"]["grammar"].update({
		r"@ldw (@reg\[\d+\]), (@reg\[\w+\])": "\tlw \\1, (\\2)",
		r"@stw (@reg\[\w+\]), (@reg\[\d+\])": "\tsw \\2, (\\1)",
	})

	# PowerPC
	t["ppc64be-gas"] = t["ppc64le-gas"].copy()
	t["ppc64be-gas"]["settings"] = t["ppc64be-gas"]["settings"].copy()
	t["ppc64be-gas"]["settings"]["byteorder"] = "big"

	t["ppc-gas"] = t["ppc64be-gas"].copy()
	t["ppc-gas"]["settings"] = t["ppc-gas"]["settings"].copy()
	t["ppc-gas"]["settings"]["reg_size"] = 32
	t["ppc-gas"]["regw"] = ("r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10")
	t["ppc-gas"]["regb"] = t["ppc-gas"]["regw"]
	t["ppc-gas"]["grammar"] = t["ppc-gas"]["grammar"].copy()
	t["ppc-gas"]["grammar"].update({
		r"@mvl (@regb?\[\d+\]), @imm\[(\d+)\]": ppc_mvl,
		r"@ldw (@reg\[\d+\]), (@reg\[\w+\])": "\tlwz \\1, 0(\\2)", # apparantly there is no `lw`
		r"@stw (@reg\[\w+\]), (@reg\[\d+\])": "\tstw \\2, 0(\\1)",
	})

	asm_format_data = t.get(syntax[4:])
	del t, x64_ms_apx_regw, x64_ms_apx_regb, x64_sysv_apx_regw, x64_sysv_apx_regb
	del ppc_mvl, ppc64_mvl

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

	if syntax.startswith("asm="):
		# the variable names are only used in the comment for the C prototype, so it just has to be valid C.
		# it doesn't really matter either way if it is valid since it is just a comment.
		return bool(C_IDENT.fullmatch(name)) and name not in C_KEYWORDS

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

class SafeUnpickler(pickle.Unpickler):
	"prevent injections of malicious pickle streams into the cache files"
	types = {
		"dict": dict,
		"set": set,
		"int": int,
		"NoneType": type(None)
	}

	def find_class(self, module, name):
		if module != "builtins" or name not in self.types:
			raise pickle.UnpicklingError(f"forbidden: {module}.{name}")

		return self.types[name]

def pickle_safeloads(data: bytes) -> any:
	try:
		# try and avoid the extra import if possible. _io is auto imported and io isn't
		from _io import BytesIO
	except ImportError:
		# in case _io.BytesIO is removed or renamed
		from io import BytesIO

	return SafeUnpickler(BytesIO(data)).load()

def run_job(
	output: str,
	optimize: bool,
	args: object, # whatever type argparse.ArgumentParser.parse_args gives you
	new_file: bool,
	last_file_exists: bool, # whatever file_exists was last time
	asm_ir_settings: dict,
	outfile: object # whatever type open returns
) -> tuple[any, str | None]:
	"do all the main stuff that has to happen per batch job"
	# returns the output file handle if it is still open, otherwise it returns None
	# and the second value is either the file name or None.

	gc_collect()

	crc_name = args.name
	poly     = args.polynomial

	init      = args.init    or 0
	xor_out   = args.xor_out or 0
	reflected = args.reflect

	data_len      = args.data_len
	in_port       = args.in_port
	out_port      = args.out_port
	tmp_sgnl_base = args.tmp_name

	if not valid_varname(in_port):
		raise ValueError(f"input port ({in_port!r}) is not a valid name in syntax {syntax!r}")

	if not valid_varname(out_port):
		raise ValueError(f"output port ({out_port!r}) is not a valid name in syntax {syntax!r}")

	if not valid_varname(tmp_sgnl_base):
		raise ValueError(f"tmp name ({tmp_sgnl_base!r}) is not a valid name in syntax {syntax!r}")

	if in_port == out_port:
		raise ValueError(f"input port ({in_port!r}) and output port ({out_port!r}) can't be the same")

	if tmp_sgnl_base == in_port:
		raise ValueError(f"tmp signal ({tmp_sgnl_base!r}) and input port ({in_port!r}) can't be the same")

	if tmp_sgnl_base == out_port:
		raise ValueError(f"tmp signal ({tmp_sgnl_base!r}) and output port ({out_port!r}) can't be the same")

	local_port = "local_" + out_port
	max_io_pad = 1 + max(len(in_port), len(out_port))
	in_pad     = " "*(max_io_pad - len(in_port))
	out_pad    = ' ' if data_len == 0 else " "*(max_io_pad - len(out_port))

	tmp_port_i = tmp_sgnl_base + " "*(len(in_port)    - len(tmp_sgnl_base))
	tmp_port_o = tmp_sgnl_base + " "*(len(local_port) - len(tmp_sgnl_base))
	in_port_i  = in_port + " "*(len(tmp_port_i) - len(in_port)) if optimize else in_port

	if data_len < 0:
		raise ValueError("data length must be non-negative")

	if poly is not None:
		if crc_name is not None:
			raise Exception("`--name` and `--polynomial` cannot both be provided.")

		if not hasattr(crcmod, "__file__"):
			raise Exception("custom CRCs require `crcmod-plus`.")

		crc        = crcmod.mkCrcFun(poly, init, reflected, xor_out)
		crc_name   = f"_custom_0x{poly:X}"
		sum_len    = (poly.bit_length() + 6) // 8
		polynomial = poly ^ (1 << (poly.bit_length() - 1))
	elif crc_name in {None, "32", "crc32", "crc-32", "crc 32"}:
		# use zlib.crc32 if possible since it is is built-in, and probably faster.
		crc_name   = "32"
		sum_len    = 4
		reflected  = True
		polynomial = 0x04c11db7 # this can't be queried from crcmod in case it isn't installed.

		crc = zlib.crc32
	else:
		if not hasattr(crcmod, "__file__"):
			raise Exception(f"CRCs other than crc32 require the `crcmod-plus` package. crc_name: {crc_name}")

		if crc_name is None:
			crc_name = "32"

		sum_len = sum_len_map.get(crcmod.predefined._simplify_name(crc_name), None)

		if sum_len is None:
			raise ValueError(f"crc name {crc_name!r} does not exist or is unknown")

		crc_name = crcmod.predefined._simplify_name(crc_name)
		crc = crcmod.predefined.mkCrcFun(crc_name)

		reflected  = crcmod.predefined._crc_definitions_by_name[crc_name]["reverse"]
		polynomial = crcmod.predefined._crc_definitions_by_name[crc_name]["poly"]
		polynomial ^= 1 << (polynomial.bit_length() - 1)

	# sum_len is the number of bytes in the checksum
	sum_bits  =  sum_len << 3 # number of bits in the checksum
	sum_nibs  =  sum_len << 1 # number of nibbles in the checksum

	data_len_norm   = max(1, data_len)
	data_bits       = data_len << 3
	data_bits_norm  = data_len_norm << 3

	CACHE_SIGNATURE = b"CCCF" # CRC Compiler Cache Format

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
		optimize_min_reduc,
		optimize_metric,
		lns_trials,
		lns_window,
		CACHE_SIGNATURE,
	), protocol=5)).hexdigest()

	cache_file = f"{cache_dir}/{cache_key}.cccf"

	if cache_settings == 'd' and os.path.isfile(cache_file):
		if verbose >= 1:
			eprint("# removed current cache entry")

		os.remove(cache_file)

	# these settings were determined experimentally to give better compression than the defaults.
	# LZMA2 make the file a constant few bytes larger than with LZMA1 from header overhead
	# depth > 4 doesn't give any improvements over depth=4
	# dict_size >= 256 KiB doesn't give any improvements
	# pb != 0 and lp != 0 makes it worse
	# fast mode gives worse compression than normal mode
	# MF_BT2 is better with crc8, but BT4 is the best for everything else.
	# nice_len 16 isn't the best for everything, but it is in the close top three for all of them
	# lc=0 mostly only best for 8-bit CRCs, but also for like 24 and 64we. lc=2 is usually the best
	lzma_filter = {
		"id": lzma.FILTER_LZMA1,  # default is FILTER_LZMA2
		"dict_size": 1024*1024,   # default is 8 MiB
		"lc": 2*(sum_len != 1),   # default is 3
		"lp": 0,                  # default is 0
		"pb": 0,                  # default is 2
		"mode": lzma.MODE_NORMAL, # default is MODE_NORMAL
		"nice_len": 16,           # default is 64
		"mf": lzma.MF_BT4,        # default is MF_BT4
		"depth": 4,               # default is 24 with BT4, nice=16.
	}

	def cache_read() -> tuple[dict[int, set], list[set]] | None:
		if not os.path.isfile(cache_file):
			return None

		if verbose >= 1:
			eprint("# graph was found in cache")

		if verbose >= 2:
			eprint(f"#     key: {cache_key}")

		try:
			with open(cache_file, "rb") as f:
				data = memoryview(f.read())
		except Exception as e:
			raise Exception(f"cache file could not be read. key={cache_key}") from e

		if data[:4] != CACHE_SIGNATURE:
			raise ValueError(f"cache file signature did not match. key={cache_key}")

		# skip the signature, polynomial, and data length
		data = data[4 + sum_len + (data_len_norm.bit_length() + 7 >> 3):]

		expect_sum2 = int.from_bytes(data[:4], byteorder="big")
		actual_sum2 = zlib.crc32(data[4:])

		if expect_sum2 != actual_sum2:
			raise ValueError(f"cache file checksum 2 did not match. key={cache_key}, expected={expect_sum2:08x}, actual={actual_sum2:08x}")

		d = lzma.decompress(data[8:], lzma.FORMAT_RAW, filters=[lzma_filter])

		expect_sum1 = int.from_bytes(data[4:8], byteorder="big")
		actual_sum1 = zlib.adler32(d)

		if expect_sum1 != actual_sum1:
			raise ValueError(f"cache file checksum 1 did not match. key={cache_key}, expected={expect_sum1:08x}, actual={actual_sum1:08x}")

		if verbose >= 2:
			eprint(
				f"#     sum 1: {expect_sum1:08x}\n"
				f"#     sum 2: {expect_sum2:08x}"
			)

		try:
			return pickle_safeloads(d)
		except Exception as e:
			raise ValueError(f"cache file pickle content could not be parsed. key={cache_key}") from e

	def cache_write(tmp_defs: dict[int, set], outputs: list[set], /) -> None:
		if not os.path.isdir(cache_dir):
			os.makedirs(cache_dir, exist_ok=True)

		if verbose >= 1:
			eprint("# writing graph to cache")

		if verbose >= 2:
			eprint(f"#     key: {cache_key}")

		d = pickle.dumps((tmp_defs, outputs), pickle.HIGHEST_PROTOCOL)

		sum1 = zlib.adler32(d)

		if verbose >= 2:
			eprint(f"#     sum 1: {sum1:08x}")

		sum1 = sum1.to_bytes(4, byteorder="big")

		c = lzma.compress(d, lzma.FORMAT_RAW, filters=[lzma_filter])

		sum2 = zlib.crc32(c, zlib.crc32(sum1))

		if verbose >= 2:
			eprint(f"#     sum 2: {sum2:08x}")

		sum2 = sum2.to_bytes(4, byteorder="big")

		# if the cache entry exists already, this will just overwrite it.
		try:
			with open(cache_file, "wb") as f:
				f.write(CACHE_SIGNATURE)
				f.write(polynomial.to_bytes(sum_len, byteorder="big"))
				f.write(data_len.to_bytes((data_len_norm.bit_length() + 7 >> 3), byteorder="big"))
				f.write(sum2)
				f.write(sum1)
				f.write(c)
		except Exception as e:
			raise Exception(f"cache file could not be written. key={cache_key}") from e

	def optimize_graph(eqns: list[set]) -> tuple[dict[int, set], list[set]]:
		nonlocal ending_gates, ending_luts, ending_logic_depth, ending_fanout_stats, ending_fanin_util
		nonlocal in_idx_max_pad, optimize, in_port_i

		if not optimize:
			return {}, rows

		if verbose >= 1:
			eprint("# starting optimization")

		if 'r' in cache_settings and (cache_value := cache_read()) is not None:
			tmp_defs, outputs = cache_value
		else:
			tmp_defs, outputs, _ = gf2_cse.optimize_graph(
				eqns,
				optimize_depth,
				optimize_nmax,
				optimize_beam,
				optimize_n_prefer,
				optimize_weight, # lookahead weight
				lns_window,
				lns_trials,
				optimize_min_reduc - 1, # exit_fast
				"gates" if optimize_metric == "gates" else f"lut{optimize_metric}",
				optimize_max_tmps,
				optimize_seed,
				verbose - 1,
				interactive=True,
				sort="slow" if syntax.startswith("asm=") or syntax in {"c", "c++"} else "fast"
			)

			if 'w' in cache_settings:
				cache_write(tmp_defs, outputs)

		if not tmp_defs:
			optimize  = False
			in_port_i = in_port

		ending_gates        = gf2_cse.count_gates(tmp_defs, outputs)
		ending_fanout_stats = gf2_cse.fanout_stats(tmp_defs, outputs)
		if lut_size is not None:
			ending_luts        = gf2_cse.count_luts(tmp_defs, outputs, lut_size=lut_size)
			ending_fanin_util  = gf2_cse.fanin_util(tmp_defs, outputs, lut_size=lut_size)
			ending_logic_depth = gf2_cse.logic_depth(tmp_defs, outputs, lut_size, sorted=True)

		in_idx_max_pad = max(
			in_idx_max_pad,
			len( str(len(tmp_defs)) )
		)

		if verbose >= 2:
			eprint(
				f"# fanout:\n"
				f"#     min    : {starting_fanout_stats[0]} => {ending_fanout_stats[0]}\n"
				f"#     median : {starting_fanout_stats[1]} => {ending_fanout_stats[1]}\n"
				f"#     max    : {starting_fanout_stats[2]} => {ending_fanout_stats[2]}\n"
				f"#     mean   : {starting_fanout_stats[3]} => {ending_fanout_stats[3]}\n"
				f"#     std    : {starting_fanout_stats[4]} => {ending_fanout_stats[4]}"
			)
		elif verbose == 1:
			eprint(f"# fanout bounds: ({starting_fanout_stats[0]}, {starting_fanout_stats[2]}) => ({ending_fanout_stats[0]}, {ending_fanout_stats[2]})")

		if verbose >= 1:
			if lut_size is not None:
				eprint(
					f"# LUT{lut_size} count: {starting_luts} => {ending_luts}\n"
					f"# LUT{lut_size} input utilization: {starting_fanin_util*100:.{1 + verbose << 1}g}% => {ending_fanin_util*100:.{1 + verbose << 1}g}%"
				)

				if verbose >= 2:
					eprint(f"# LUT{lut_size} balanced tree logic depth: {starting_logic_depth} => {ending_logic_depth}")
				else:
					eprint(f"# LUT{lut_size} logic depth: ~ {starting_logic_depth} => {ending_logic_depth}")
			else:
				eprint(f"# XOR2 gate count: {starting_gates} => {ending_gates}")

		return tmp_defs, outputs

	# idx \in [0, bits - 1]
	in_idx_max_pad  = len(str(data_bits_norm - 1))
	out_idx_max_pad = len(str( sum_bits - 1))
	idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

	# idx + 1 \in [1, bits]
	in_idxp1_max_pad  = len(str(data_bits_norm))
	out_idxp1_max_pad = len(str( sum_bits))
	idxp1_max_pad     = max(in_idxp1_max_pad, out_idxp1_max_pad)

	reversed_polynomial = int(f"{polynomial:0{sum_bits}b}"[::-1], 2) # bit reversal

	# This bit with the LFSR steps and the row generation thing makes no sense to me, and it was primarily
	# written by Claude (up until the for loop). I did test it quite a bit though
	sum_mask = (1 << sum_bits) - 1

	if reflected:
		lfsr_step = lambda s: (s >> 1) ^ (reversed_polynomial if s & 1 else 0)
	else:
		lfsr_step = lambda s: ((s << 1) ^ polynomial if s >> (sum_bits - 1) else s << 1) & sum_mask

	K = crc(bytes(data_len)) # correction vector

	if verbose >= 1:
		eprint("# generating curve vectors")

	curve_gen_time_stt = perf_counter_ns()

	base_i  = 7 if reflected else 0
	cols    = [0] * data_bits_norm
	current = crc((1 << base_i).to_bytes(data_len_norm, byteorder="big")) ^ K
	cols[base_i] = current

	del base_i

	if reflected:
		for k in range(data_len_norm):
			for j in range(6 if k == 0 else 7, -1, -1):
				cols[(k << 3) + j] = current = lfsr_step(current)
	else:
		for i in range(1, data_bits_norm):
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

	starting_gates        = gf2_cse.count_gates(rows)
	starting_fanout_stats = gf2_cse.fanout_stats(None, rows)
	starting_logic_depth  = None if lut_size is None else gf2_cse.logic_depth(None, rows, lut_size)
	starting_fanin_util   = None if lut_size is None else gf2_cse.fanin_util(rows, lut_size=lut_size)
	starting_luts         = None if lut_size is None else gf2_cse.count_luts(rows, lut_size=lut_size)

	# set these too in case optimization is off
	ending_gates          = starting_gates
	ending_fanout_stats   = starting_fanout_stats
	ending_logic_depth    = starting_logic_depth
	ending_fanin_util     = starting_fanin_util
	ending_luts           = starting_luts

	def print(message: str | None, end: str = '\n') -> None:
		"""
		print a single string to the output file.
		assumes `end` doesn't have tabs in it.
		"""

		nonlocal new_file

		if message is None:
			# don't print anything
			return

		from builtins import print as _print

		if not new_file:
			_print(end='\n', file=outfile)
			new_file = True # pretend it is a new file.

		if indent_str != '\t':
			message = message.replace('\t', indent_str)

		_print(message, end=end, file=outfile)

	if output == '-':
		outfile     = None
		file_exists = False
	elif output == "auto" or outfile is None:
		# if outfile is not '-', "auto", or None, this is the same file as the last file
		# use real paths because the path `outfile.name` is used later.
		outfile = os.path.realpath(os.path.expanduser(
			f"crc{crc_name}_{data_len}.{extension}" if output == "auto" else outfile
		))
		file_exists = os.path.isfile(outfile)

		try:
			outfile = open(outfile, "w", newline='')
		except OSError as e:
			raise ValueError(f"job {job_num} output file is not valid: {outfile.replace('\\', '/')}") from e
	else:
		file_exists = last_file_exists

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
			return None, outfile.name, file_exists

		return outfile, (None if outfile is None else outfile.name), file_exists

	# main formats
	if syntax in {"vhd", "v", "sv", "am", "nmg", "ch", "ch3", "sp"}:
		is_svl = syntax == "sv"
		is_nmg = syntax == "nmg"
		is_ch3 = syntax == "ch3"

		tmp_defs, outputs = optimize_graph(rows)

		# header
		match syntax:
			case "vhd":
				print(
					f"-- Generated with {prog}"
					f"\nlibrary ieee;"
					f"\nuse ieee.std_logic_1164.all;"
					f"\n"
					f"\nentity crc{crc_name}_{data_len} is"
					f"\n\tgeneric ("
					f"\n\t\t-- true => little endian, false => big endian"
					f"\n\t\tBSWAP : boolean := true"
					f"\n\t);"
					f"\n\tport ("
					f"{(
						'' if data_len == 0 else
						f"\n\t\t{in_port}{in_pad}: in  std_logic_vector({data_bits - 1:{idx_max_pad}} downto 0);"
					)}"
					f"\n\t\t{out_port}{out_pad}: out std_logic_vector({sum_bits - 1:{idx_max_pad}} downto 0)"
					f"\n\t);"
					f"\nend entity crc{crc_name}_{data_len};"
					f"\n"
					f"\narchitecture crc{crc_name}_{data_len}_arch of crc{crc_name}_{data_len} is"
					f"\n\t-- polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n\t-- crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
				)
			case "v" | "sv":
				print(
					f"// Generated with {prog}"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\nmodule crc{crc_name}_{data_len} #("
					f"\n\t// 1 => little endian, 0 => big endian"
					f"\n\tparameter{" bit" if is_svl else ""} BSWAP = 1"
					f"\n) ("
					f"{(
						'' if data_len == 0 else
						f"\n\tinput  [{data_bits - 1:{idx_max_pad}} : 0] {in_port},"
					)}"
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
					f"\n"
					f"\nclass Crc{crc_name}_{data_len}({"Elaboratable" if is_nmg else "Component"}):"
					f"\n\t\"\"\""
					f"\n\tGenerated with {prog}"
					f"\n\tpolynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n\tcrc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\n\tbswap: True => little endian, False => big endian"
					f"\n\t\"\"\""
					f"\n"
					f"{(
						'' if data_len == 0 else
						f"\n\t{in_port}{in_pad}: {  "Signal" if is_nmg else f"In  ({data_bits:{idxp1_max_pad}})" }"
					)}"
					f"\n\t{out_port}{out_pad}: {"Signal" if is_nmg else f"Out ({sum_bits :{idxp1_max_pad}})" }"
					f"\n\t"
					f"\n\tdef __init__(self, bswap: bool = True) -> None:"
					f"\n\t\tself.bswap = bswap"
					f"{(
						f"\n"
						f"{(
							'' if data_len == 0 else
							f"\n\t\tself.{in_port}{in_pad}= Signal({data_bits:{idxp1_max_pad}})"
						)}"
						f"\n\t\tself.{out_port}{out_pad}= Signal({sum_bits:{idxp1_max_pad}})"

						if is_nmg else

						f"\n\t\tsuper().__init__()"
					)}"
					f"\n"
					f"\n\tdef elaborate(self, platform{'' if is_nmg else f': "Platform | None"'}) -> Module:"
					f"\n\t\tm = Module()"
					f"\n\t\tc = m.d.comb"
					f"\n"
					f"{(
						'' if data_len == 0 else
						f"\n\t\t{in_port}{in_pad}= self.{in_port}"
					)}"
					f"\n\t\t{out_port}{out_pad}= self.{out_port}"
					f"\n"
				)
			case "ch" | "ch3":
				print(
					f"// Generated with {prog}"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"\nimport chisel3._"
					f"\nimport chisel3.util._"
					"\n"
					f"\nclass crc{crc_name}_{data_len}(val bswap: Boolean = true) extends Module {{"
					f"{(
						f"\n\tval io = IO(new Bundle {{"
						f"{(
						'' if data_len == 0 else
						f"\n\t\tval {in_port}{in_pad}= Input (UInt({data_bits:{idxp1_max_pad}}.W))"
						)}"
						f"\n\t\tval {out_port}{out_pad}= Output(UInt({sum_bits:{idxp1_max_pad}}.W))"
						f"\n\t}})"

						if is_ch3 else

						f"{(
						'' if data_len == 0 else
						f"\n\tval {in_port}{in_pad}= IO(Input (UInt({data_bits:{idxp1_max_pad}}.W)))"
						)}"
						f"\n\tval {out_port}{out_pad}= IO(Output(UInt({sum_bits:{idxp1_max_pad}}.W)))"
					)}"
					f"\n"
				)
			case "sp":
				print(
					f"// Generated with {prog}"
					f"\n// polynomial: 0x{polynomial:0{sum_nibs}X}"
					f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
					f"\n"
					f"import spinal.core._"
					f"\n"
					f"\nclass crc{crc_name}_{data_len}(bswap: Boolean = true) extends Component {{"
					f"\n\tval io = new Bundle {{"
					f"{(
						'' if data_len == 0 else
						f"\n\t\tval {in_port}{in_pad}= in  UInt({data_bits:{idxp1_max_pad}} bits)"
					)}"
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

			print(footer(f"crc{crc_name}_{data_len}_arch") if callable(footer) else footer)
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

		print(footer(f"crc{crc_name}_{data_len}_arch") if callable(footer) else footer)
		return job_ret()

	# assembly formats
	if syntax.startswith("asm=") and syntax not in {"asm=json", "asm=j"}:
		# it is okay to do this before the match/case because the `case _` branch
		# should never execute in a production version of the compiler.
		tmp_defs, outputs = optimize_graph(rows)

		in_ofs  = 0
		tmp_ofs = data_bits
		out_ofs = data_bits + len(tmp_defs)

		if syntax == "asm=ir":
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
					f"| Generated with {prog}\n"
					f"| void crc{crc_name}_{data_len}(uint8_t {in_port}[{data_len}], uint{c_type_length(1 << sum_bits)}_t *{out_port});"
				)

			print( '\n'.join(asm_gen.gen_ir(
				tmp_defs, outputs,
				crc_name, data_len, sum_len,
				**asm_ir_settings
			)) )

			return job_ret()

		if asm_format_data is None:
			raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: {syntax!r}")

		asm_ir_settings = asm_format_data["settings"]
		asm_ir_settings = asm_ir_settings.copy()

		asm_ir_settings["reg_slots"] = len(asm_format_data["regw"])
		asm_ir_settings["in_ofs"]    = in_ofs
		asm_ir_settings["tmp_ofs"]   = tmp_ofs
		asm_ir_settings["out_ofs"]   = out_ofs
		asm_ir_settings["emit_round_numbers"] = True

		grammar   = asm_format_data["grammar"]
		byteorder = asm_ir_settings.pop("byteorder")
		strict    = asm_ir_settings.pop("strict", True)

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

		for key, val in grammar.items():
			if callable(val):
				grammar[key] = partial(val, k=gd)

		program = crc_dsl.generate(
			program,
			grammar,
			pp_vars={"$byteorder": byteorder},
			strict=strict
		)

		print(f"{gd.comment} Generated with {prog}")
		print(f"{gd.comment} void {gd.function}(uint8_t {in_port}[{data_len}], uint{c_type_length(1 << sum_bits)}_t *{out_port});")
		print('\n'.join(program))
		return job_ret()

	# secondary formats
	match syntax:
		case "pyt" | "py" | "c" | "c++":
			# compute optimized equation graph
			tmp_defs, outputs = optimize_graph(rows)

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
				raise ValueError(f"`--in-port {in_port!r}` cannot be given with `--syntax {syntax!r}`")

			if out_port in {"bit_", "byte_"}:
				raise ValueError(f"`--in-port {out_port!r}` cannot be given with `--syntax {syntax!r}`")

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
			tmp_defs, outputs = optimize_graph(rows)

			print(
				f"{comment} Generated with {prog}"
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
				ranksep = data_bits_norm / graph_depth - 0.5
			else:
				ranksep = (1 + (data_len_norm == 1))*4*data_len_norm / graph_depth - 0.5

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
				f"\nname        = {crc_name}"
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
			tmp_defs, outputs = optimize_graph(rows)
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


			sep2 = sep + ('\t' if sep else '')

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
				f'{sep}"lut_size":{pad}{None if lut_size is None else lut_size},'
				f'{sep}"logic_depth":{pad}{{"start":{pad}{starting_logic_depth},{pad}"end":{pad}{ending_logic_depth}}},'
				f'{sep}"fanin_util":{pad}{{"start":{pad}{starting_fanin_util},{pad}"end":{pad}{ending_fanin_util}}},'
				f'{sep}"fanout":{pad}{{'
					f'{sep2}"start":{pad}{{'
						f'"min":{pad}{starting_fanout_stats[0]},{pad}'
						f'"median":{pad}{starting_fanout_stats[1]},{pad}'
						f'"max":{pad}{starting_fanout_stats[2]},{pad}'
						f'"mean":{pad}{starting_fanout_stats[3]},{pad}'
						f'"std":{pad}{starting_fanout_stats[4]}'
					f'}},{sep2}"end":{pad}{{'
						f'"min":{pad}{ending_fanout_stats[0]},{pad}'
						f'"median":{pad}{ending_fanout_stats[1]},{pad}'
						f'"max":{pad}{ending_fanout_stats[2]},{pad}'
						f'"mean":{pad}{ending_fanout_stats[3]},{pad}'
						f'"std":{pad}{ending_fanout_stats[4]}'
					f'}}'
				f'{sep}}},'
				f'{sep}"gen_time_ns":{pad}{curve_gen_time_end - curve_gen_time_stt},'
				f'{sep}"cse_time_ns":{pad}{cse_time_end - cse_time_stt}'
				f"{'\n' if syntax == "ir" else ''}}}"
			)

			print(data if syntax == "ir" else data.replace(' ', ''))
		case "json" | "j" | "metrics" | "m" | "asm=json" | "asm=j":
			cse_time_stt      = perf_counter_ns()
			tmp_defs, outputs = optimize_graph(rows)
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
			data["lut_size"]       = None if lut_size is None else lut_size
			data["logic_depth"]    = { "start": starting_logic_depth, "end": ending_logic_depth }
			data["fanin_util"]     = { "start": starting_fanin_util , "end": ending_fanin_util }
			data["fanout"]         = {
				"start": {
					"min"   : starting_fanout_stats[0],
					"median": starting_fanout_stats[1],
					"max"   : starting_fanout_stats[2],
					"mean"  : starting_fanout_stats[3],
					"std"   : starting_fanout_stats[4],
				},
				"end": {
					"min"   : ending_fanout_stats[0],
					"median": ending_fanout_stats[1],
					"max"   : ending_fanout_stats[2],
					"mean"  : ending_fanout_stats[3],
					"std"   : ending_fanout_stats[4],
				},
			}
			data["gen_time_ns"]    = curve_gen_time_end - curve_gen_time_stt
			data["cse_time_ns"]    = cse_time_end - cse_time_stt
			print(json_dump_data(data, indent, seps))
		case "nop":
			if optimize:
				# for the stderr output
				optimize_graph(rows)
		case _:
			raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: {syntax!r}")

	return job_ret()

def preproc_toml(source: str, files_seen: set) -> dict:
	"the argument is either a path to a file, or inline file contents"

	try:
		path = os.path.realpath(os.path.expanduser(source)).replace('\\', '/')
		with open(path, "r") as f:
			source = f.read()

		if path in files_seen:
			raise ValueError(f"duplicate input file path given: {path!r}")

		files_seen.add(path)
	except FileNotFoundError, OSError:
		# `open` can throw other errors, but they don't really matter. just let them propagate.
		# try and parse it as inline TOML if it didn't parse as a file path.
		pass

	if "'''" in source or '"""' in source:
		raise ValueError("input file is invalid (may contain multiline strings)")

	if ccil_avail:
		# this will always be true with `--preproc`. Without it, it might not be true
		source = source.split('\n')

		try:
			source = crc_dsl.preproc(source)
		except Exception as e:
			raise ValueError("TOML input is invalid (preprocessing failed)") from e

		source = '\n'.join(source)

	return source

def parse_toml(source: str, files_seen: set) -> dict:
	"""
	the argument is either a file path to a TOML file, inline TOML, or neither.
	if it is neither, an error will be thrown, otherwise the TOML object is given.
	"""

	import tomllib

	try:
		return tomllib.loads(preproc_toml(source, files_seen))
	except tomllib.TOMLDecodeError:
		raise ValueError("TOML input is invalid (TOML decode failed)")

def preproc_input(args: object) -> list[dict[str, int | str | None]]:
	if args.polynomial is not None:
		raise ValueError("`--preproc` and `--polynomial` cannot both be given")

	if args.name is not None:
		raise ValueError("`--preproc` and `--name` cannot both be given")

	if not sys.stdin.isatty():
		args.programs.insert(0, sys.stdin.read())

	if not args.programs:
		return ""

	files_seen = set()

	return '\n'.join(preproc_toml(toml, files_seen) for toml in args.programs)

def parse_input(args: object) -> list[dict[str, int | str | None]]:
	"figure out the curve dictionary stuff from the input TOML files"

	if not sys.stdin.isatty():
		if args.polynomial is not None:
			raise ValueError("pipeline TOML and `--polynomial` cannot both be given")
		if args.name is not None:
			raise ValueError("pipeline TOML and `--name` cannot both be given")

		args.programs.insert(0, sys.stdin.read())

	if args.polynomial is not None:
		# --polynomial
		try:
			return [{
				"name"       : None,
				"polynomial" : int(args.polynomial, 0),
				"init"       : args.init    or 0,
				"xor-out"    : args.xor_out or 0,
				"reflect"    : args.reflect,
				"file"       : args.output or '-',
			}]
		except ValueError:
			raise ValueError(f"`--polynomial` given a non-integer value: {args.polynomial!r}")
	elif not args.programs:
		# neither positional nor polynomial is given
		return [{
			"name"       : args.name, # this being None is handled later
			"polynomial" : None,
			"init"       : None,
			"xor-out"    : None,
			"reflect"    : None,
			"file"       : args.output or '-',
		}]

	# these are part of the curve identity, so an override or fallback doesn't make sense.
	if args.data_len  is not None: raise ValueError("TOML input and `--data-len` cannot both be given")
	if args.name      is not None: raise ValueError("TOML input and `--name` cannot both be given")
	if args.init      is not None: raise ValueError("TOML input and `--init` cannot both be given")
	if args.xor_out   is not None: raise ValueError("TOML input and `--xor-out` cannot both be given")
	if args.reflect              : raise ValueError("TOML input and `--reflect` cannot both be given")

	files_seen = set()

	# make sure all the programs preprocess and parse before potentially giving any other errors
	toml_dicts = [parse_toml(toml, files_seen) for toml in args.programs]

	## propagate top-level attributes into each curve

	for i, toml in enumerate(toml_dicts, 1):
		# for each program:
		if "curve" not in toml:
			raise ValueError(f"TOML program {i} does not have a `curve` attribute")

		if type(toml["curve"]) is dict:
			toml["curve"] = [toml["curve"]]

		if type(toml["curve"]) is not list:
			raise ValueError(f"TOML program {i} `curve` is not a dictionary or a list")

		# CLI flags for these take priority over file global settings, but not over curve local settings
		if args.in_port  is not None: toml["in-port"]  = args.in_port
		if args.out_port is not None: toml["out-port"] = args.out_port
		if args.tmp_name is not None: toml["tmp-name"] = args.tmp_name
		if args.output   is not None: toml["file"]     = args.output

		for curve in toml["curve"]:
			# for each curve in the program

			for key, val in toml.items():
				# for each top-level attribute in the program

				# curve attributes take precedence over top-level attributes
				if key != "curve" and key not in curve:
					curve[key] = val

	# in Python 3.15: curves = [*d["curve"] for d in toml_dicts]
	# I hate this syntax, it is backwards of what it should be
	curves = [curve for d in toml_dicts for curve in d["curve"]]

	## validate and normalize curve parameters

	for i, curve in enumerate(curves, 1):
		remainder = set(curve) - {
			"in-port", "out-port", "tmp-name", "data-len", "file",
			"name", "polynomial", "init", "xor-out", "reflect",
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

		if "file" in curve and type(curve["file"]) is not str:
			raise ValueError(f"TOML `[[curve]]` element {i} attribute `file` is not a string")

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

def close_and_classify(outfile: object, filename: str | None, file_exists: bool) -> None:
	"filenames and bad_filenames are declared later, globally"

	if outfile is not None:
		outfile.close()

	if filename is None:
		return

	if filename in filenames:
		if verbose >= 0:
			eprint(f"\x1b[38;2;180;100;0m# WARNING: job {job_num} overwrote output file:\x1b[m {filename.replace('\\', '/')}")

		bad_filenames.append((job_num, filename))
	else:
		if verbose >= 2 and file_exists:
			eprint(f"\x1b[1;33m# NOTE: job {job_num} overwrote a pre-existing file:\x1b[m {filename.replace('\\', '/')}")

		filenames.add(filename)

if args.preproc:
	program = preproc_input(args)

	output = '-' if args.output is None else output

	if output in {'-', "auto"}:
		print(program)
		raise SystemExit

	output = os.path.realpath(os.path.expanduser(output)).replace('\\', '/')
	file_exists = os.path.isfile(output)

	with open(output, 'w', newline='') as f:
		f.write(program)

	if verbose >= 2 and file_exists:
		eprint(f"\x1b[1;33m# NOTE: overwrote a pre-existing file:\x1b[m {output}")

	raise SystemExit

curves = parse_input(args)

del parse_toml, parse_input

args.in_port  = "data" if args.in_port  is None else args.in_port
args.out_port = "crc"  if args.out_port is None else args.out_port
args.tmp_name = "tmp"  if args.tmp_name is None else args.tmp_name
args.data_len = 4      if args.data_len is None else args.data_len
args.output   = '-'    if args.output   is None else args.output
if args.output not in {'-', "auto"}:
	args.output = os.path.expanduser(args.output)

outfile     = None
filename    = None
file_exists = False
first       = True

filenames     = set()
bad_filenames = [] # files that were written previously in the batch, then closed, then overwritten.
prev_output   = None

job_num = 0
for curve in curves:
	job_num += 1
	save = (args.in_port, args.out_port, args.tmp_name, args.data_len, args.output)

	args.name       = curve.pop("name")
	args.polynomial = curve.pop("polynomial")
	args.init       = curve.pop("init")
	args.xor_out    = curve.pop("xor-out")
	args.reflect    = curve.pop("reflect")

	if "in-port"  in curve: args.in_port  = curve.pop("in-port")
	if "out-port" in curve: args.out_port = curve.pop("out-port")
	if "tmp-name" in curve: args.tmp_name = curve.pop("tmp-name")
	if "data-len" in curve: args.data_len = curve.pop("data-len")
	if "file"     in curve: args.output   = curve.pop("file")

	if syntax == "nop":
		# never create files with `-fnop`
		args.output = '-'

	new_file = args.output == "auto" or args.output != prev_output

	if new_file and outfile is not None:
		job_num -= 1
		close_and_classify(outfile, filename, file_exists)
		job_num += 1
		outfile  = None
		filename = None

	if not first and verbose >= 1:
		eprint("")

	if verbose >= 1:
		eprint(f"\x1b[33m# starting job {job_num}\x1b[m")

	if verbose >= 2:
		eprint(
			f"# job parameters:\n"
			f"#     - curve: name={args.name!r}"
				f", polynomial={hex(args.polynomial) if args.polynomial else args.polynomial}"
				f", init={hex(args.init) if args.init else args.init}"
				f", xor-out={hex(args.xor_out) if args.xor_out else args.xor_out}"
				f", reflect={args.reflect}, data-len={args.data_len}\n"
			f"#     - meta: in-port={args.in_port!r}, tmp-name={args.tmp_name!r}, out-port={args.out_port!r}"
				f", file={args.output!r}"
		)

	outfile, filename, file_exists = run_job(args.output, optimize, args, new_file, file_exists, asm_ir_settings, outfile)
	# NOTE: if args.output == "auto", `outfile` is already closed and is None here

	if args.output == "auto":
		close_and_classify(outfile, filename, file_exists)
		filename = None # don't reclassify next iteration

	prev_output = args.output
	(args.in_port, args.out_port, args.tmp_name, args.data_len, args.output) = save
	first = False

close_and_classify(outfile, filename, file_exists)

if bad_filenames and verbose >= 1 and (optimize or len(curves) > 7):
	# there is no reason in particular for the cutoff being 7. I just decided.

	eprint(f"\x1b[38;2;180;100;0m# WARNING: {len(bad_filenames)} output file{"s were" if len(bad_filenames) > 1 else " was"} overwritten:\x1b[m")

	for job_num, filename in bad_filenames:
		eprint(f"\x1b[38;2;180;100;0m#     job {job_num} overwrote\x1b[m {filename.replace('\\', '/')}")

if verbose >= 2:
	eprint(f"# files written: {set(name.replace('\\', '/') for name in filenames) if filenames else "none"}")
