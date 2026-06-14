"""
fully unrolled, fully-combinational HDL CRC code generator given a fixed-length, byte-aligned input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than CRC32 is used.

the "info" / "i" formats output curve metadata in a human readable format
the "raw" / "r" formats output the raw graph data as a python object string. it is not valid JSON.
the "json" / "j" formats output the raw graph data as a JSON object string with sets replaced with lists.
the "m" format gives JSON metrics about the graph reduction without giving the reduced graph.
the "python-test" / "pyt" formats output the same code as "python" / "py", but with some extra functions.
"""

__version__ = "2026.06.13.1"

if __name__ != "__main__":
	raise Exception("crc-gen.py should only be used at the top level.")

import argparse
import gf2_cse
import sys
stderr = sys.stderr
from time import perf_counter_ns

if __version__ != gf2_cse.__version__:
	raise Exception("version mismatch with gf2_cse.py")

syntaxes = "verilog", "v", "systemverilog", "sv", "vhdl", "vhd", "python", "py", "python-test", "pyt", "graphviz", "dot", "gv", "c", "info", "i", "raw", "r", "json", "j", "m"

parser = argparse.ArgumentParser(
	description=f"%(prog)s {__version__}\n{__doc__}",
	formatter_class=argparse.RawDescriptionHelpFormatter,
)
parser.add_argument("--data-len", "-l", type=int, default=4, help="bytes length of checksum input data. default is 4")
parser.add_argument("--in-port", "--in-var", "-I", type=str, default="data", help="input port/variable name. default is 'data'")
parser.add_argument("--out-port", "--out-var", "-O", type=str, default="crc", help="output port/variable name. default is 'crc'")
parser.add_argument("--tmp-name", "-t", type=str.lower, default="tmp", help="tmp signal name. default is 'tmp'. must be 3 characters long. might not work if it creates name collisions")
parser.add_argument("--syntax", "-s", type=str.lower, choices=syntaxes, default=syntaxes[0], help=f"output language. default is '{syntaxes[0]}'")
parser.add_argument("--algorithm", "--alg", "-a", type=lambda s: None if s is None else str.lower(s).strip(), default=None, help=f"CRC name. overrides other options. default is 'crc32'")
parser.add_argument("--output", "--out", "-o", type=str, default='-', help=f"output file. use 'auto' for automatic naming. default is '-' (stdout)")
parser.add_argument("--list-algorithms", "-A", action="store_true", help="list available algorithms and exit")
parser.add_argument("--verbose", "-v", type=int, help="set verbosity level. >=3 is the same as 2. mostly for optimization")
parser.add_argument("--version", "-V", action="version", version=f"%(prog)s {__version__}")

custom_crc_group = parser.add_argument_group("custom CRC overrides (triggers custom mode if --polynomial is set)")
custom_crc_group.add_argument("--polynomial", "--poly", "-p", type=int, help="polynomial. should include the uppermost bit (e.g. bit 33, bit 65)")
custom_crc_group.add_argument("--init"   , "-i", type=int, default=0  , help="initial value. default is 0")
custom_crc_group.add_argument("--xor-out", "-x", type=int, default=0  , help="final XOR mask. default is 0")
custom_crc_group.add_argument("--reflect", "-r", action="store_true"  , help="enable reflection. default is off")

optimize_group = parser.add_argument_group(
	"optimization settings (optimizes gate count)",
	"defaults: optimize off, lookahead depth 0, n max 2, beam size 1, lookahead weight 1, prefer low n, no tmp max, fast exit off, LNS: off, 3 trials, window size 3, unseeded"
)
optimize_group.add_argument("--optimize"           , "-c", action="store_true", help="enable optimization without touching settings")
optimize_group.add_argument("--optimize-depth"     , "-d", type=int  , help="enable optimization and set search lookahead depth.")
optimize_group.add_argument("--optimize-nmax"      , "-n", type=int  , help="enable optimization and set n max.")
optimize_group.add_argument("--optimize-beam"      , "-b", type=int  , help="enable optimization and set beam size.")
optimize_group.add_argument("--optimize-weight"    , "-w", type=float, help="enable optimization and set the lookahead weighting")
optimize_group.add_argument("--optimize-seed"      , "-S", type=int  , help="enable optimization, switch to predictable mode, and set the MT19937 seed")
optimize_group.add_argument("--optimize-n-prefer"  , "-P", type=str  , help="enable optimization and set intersection count tie break preference", choices=("l", "lo", "low", "h", "hi", "high", "m", "mid", "r", "rand", "random"))
optimize_group.add_argument("--optimize-max-tmps"  , "-m", type=int  , help="enable optimization. set tmp signal count for when the optimizer exits early.")
optimize_group.add_argument("--optimize-exit-fast" , "-e", action="store_true", help="enable optimization. exit optimization early when lookahead only sees 1-gate reductions.")
optimize_group.add_argument("--optimize-lns"       , "-L", action="store_true", help="enable optimization+LNS without touching settings. LNS is skipped on early exits")
optimize_group.add_argument("--optimize-lns-trials", "-T", type=int  , help="enable optimization+LNS and set the count.")
optimize_group.add_argument("--optimize-lns-window", "-W", type=int  , help="enable optimization+LNS and set the window size.")
args = parser.parse_args()

del parser, custom_crc_group, optimize_group, argparse

if not hasattr(sys, "pypy_version_info"):
	# CPython uses reference counting, and the GC is only for cyclic references.
	# the program doesn't generate cyclic references, so this is safe.
	# PyPy uses a tracing GC, so this is not a good idea in PyPy.

	import gc
	gc.disable()
	gc.collect()
	del gc

optimize = any(x not in (None, False) for x in (
	args.optimize, args.optimize_lns, args.optimize_exit_fast,
	args.optimize_depth, args.optimize_nmax, args.optimize_beam,
	args.optimize_lns_trials, args.optimize_lns_window, args.optimize_seed,
	args.optimize_n_prefer, args.optimize_weight, args.optimize_max_tmps
))
lns = args.optimize_lns or args.optimize_lns_trials is not None or args.optimize_lns_window is not None
optimize_depth     = args.optimize_depth      if args.optimize_depth      is not None else 0
optimize_nmax      = args.optimize_nmax       if args.optimize_nmax       is not None else 2
optimize_beam      = args.optimize_beam       if args.optimize_beam       is not None else 1
optimize_seed      = args.optimize_seed
optimize_weight    = args.optimize_weight     if args.optimize_weight     is not None else 1
optimize_n_prefer  = args.optimize_n_prefer   if args.optimize_n_prefer   is not None else "low"
optimize_max_tmps  = args.optimize_max_tmps
optimize_exit_fast = args.optimize_exit_fast
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

# a lot of the logic relies on it being 3 characters, both explicitly and implicitly.
# it might work fine, just probably not well.
tmp_sgnl_base = args.tmp_name
assert len(tmp_sgnl_base) == 3, "tmp signal name must be 3 characters long"

data_len   = args.data_len
in_port    = args.in_port
out_port   = args.out_port
local_port = "local_" + out_port
tmp_port_i = tmp_sgnl_base + " "*(len(in_port) - 3)    # 3 == len(tmp_sgnl_base)
tmp_port_o = tmp_sgnl_base + " "*(len(local_port) - 3) # 3 == len(tmp_sgnl_base)
in_port_i  = in_port + " "*(len(tmp_port_i) - len(in_port)) if optimize else in_port
syntax     = args.syntax
crc_name   = args.algorithm
poly       = args.polynomial
output     = args.output
verbose    = args.verbose or 0

eprint = gf2_cse._eprint

def optimize_gates(eqns: list[set]) -> tuple[dict[int, set], list[set], bool]:
	if verbose >= 1:
		eprint(f"# starting optimization")

	return gf2_cse.optimize_gates(
		eqns,
		optimize_depth,
		optimize_nmax,
		optimize_beam,
		optimize_n_prefer,
		optimize_weight, # lookahead weight
		lns_window,
		lns_trials,
		optimize_seed,
		optimize_exit_fast,
		optimize_max_tmps,
		verbose,
		sort=True
	)

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

if args.list_algorithms:
	print("supported algorithms:")
	for key in sum_len_map:
		print(f" - {key}")

	print("\nNOTE: names are case insensitive, and are stripped of spaces and dashes and of 'crc' at the start")
	exit(0)

if data_len < 1:
	# NOTE: it is probably possible to make sane code for data length 0, but I don't care enough.
	raise Exception("data length must be at least 1")

if poly is not None:
	if crc_name is not None:
		raise Exception("`--algorithm` and `--polynomial` cannot both be provided.")

	try:
		import crcmod
	except ImportError:
		raise Exception("custom CRCs require `crcmod-plus`.")

	crc        = crcmod.mkCrcFun(poly, args.init, args.reflect, args.xor_out)
	crc_name   = f"_custom_0x{poly:X}"
	sum_len    = (poly.bit_length() + 6) // 8
	reflected  = args.reflect
	polynomial = poly ^ (1 << (poly.bit_length() - 1))
elif crc_name in {None, "32", "crc32", "crc-32", "crc 32"}:
	# use zlib.crc32 if possible since it is is built-in, and probably faster,.
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
		raise Exception(f"crc name '{crc_name}' does not exist or is unknown")

	crc_name = crcmod.predefined._simplify_name(crc_name)
	crc = crcmod.predefined.mkCrcFun(crc_name)

	reflected  = crcmod.predefined._get_definition_by_name(crc_name)["reverse"]
	polynomial = crcmod.predefined._get_definition_by_name(crc_name)["poly"]
	polynomial ^= 1 << (polynomial.bit_length() - 1)

if verbose >= 2:
	sys.argv[0] = "crc-gen.py"
	eprint("# command: " + ' '.join(sys.argv))

# sum_len is the number of bytes in the checksum
sum_bits = sum_len << 3 # number of bits in the checksum
sum_nibs = sum_len << 2 # number of nibbles in the checksum

data_bits = data_len << 3

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

base_i = 7 if reflected else 0
cols   = [0] * data_bits
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

if verbose >= 1:
	eprint("\r# curve generation complete\x1b[K", flush=True)

max_io_pad      = 1 + max(len(in_port), len(out_port))
in_pad          = " "*(max_io_pad - len(in_port))
out_pad         = " "*(max_io_pad - len(out_port))
in_idx_max_pad  = len(str(data_bits))
out_idx_max_pad = len(str(sum_bits))
idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

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
		"footer"      : '',
		"comment"     : '#',
		"begin_logic" : '',
		"wire_type"   : lambda name, size: f"\t{name.lstrip()} = [None] * {size}",
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
		"wire_type"   : None,
	}
}

syntax_data["sv"] = syntax_data["v"]
syntax_data["pyt"] = syntax_data["py"]

syntax = {
	"vhdl"          : "vhd",
	"verilog"       : "v",
	"systemverilog" : "sv",
	"python"        : "py",
	"python-test"   : "pyt",
	"info"          : "i",
	"graphviz"      : "gv",
	"dot"           : "gv",
}.get(syntax, syntax)

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
wire_type   = tokens.get("wire_type")

if output != "-":
	if output == "auto":
		extension = {
			"pyt" : "py",
			"raw" : "txt",
			"i"   : "txt",
			"r"   : "txt",
		}.get(syntax, syntax)

		output = f"crc{crc_name}_{data_len}.{extension}"

	outfile = open(output, "w") # auto closed on exit
	_print  = print
	# NOTE: eprint isn't used past this point, so it doesn't matter that this probably breaks it.

	def print(message: str, end: str = '\n') -> None:
		"print a single string to the output file"

		_print(message, end=end, file=outfile)

def get_terms(eqn: set) -> str:
	if None in eqn:
		has_const = True
		eqn.discard(None)
	else:
		has_const = False

	terms = xor.join(
		f"{in_port_i}{lbr}{n:{in_idx_max_pad}}{rbr}" if n >= 0 else f"{tmp_port_i}{lbr}{-n - 1:{in_idx_max_pad}}{rbr}"
		for n in sorted(eqn, reverse=True)
	)

	if   has_const:   terms = f"{b1}{xor}{terms}" if terms else b1
	elif terms == "": terms = b0
	elif K != 0:      terms = " "*len(f"{b1}{xor}") + terms

	if has_const:
		# restore the None
		eqn.add(None)

	return terms

def c_type_length(count: int) -> int:
	"returns the bit size of the smallest C integer type that can fit `count - 1`, or has >=count values."
	bits = (count - 1).bit_length()

	if bits <=  8: return  8
	if bits <= 16: return 16
	if bits <= 32: return 32
	return 64

match syntax:
	case "vhd" | "v" | "sv":
		is_sv = syntax == "sv"

		# compute optimized graph
		if optimize:
			tmp_defs, outputs, _ = optimize_gates(rows)
		else:
			tmp_defs = {}
			outputs  = rows

		print(f"{comment} Generated with tools/crc-gen.py")

		# header
		if syntax == "vhd":
			print(
				f"library ieee;"
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
		else:
			print(
				f"// polynomial: 0x{polynomial:0{sum_nibs}X}"
				f"\n// crc{crc_name}(0): 0x{K:0{sum_nibs}X}"
				f"\n"
				f"\nmodule crc{crc_name}_{data_len} #("
				f"\n\t// 1 => little endian, 0 => big endian"
				f"\n\tparameter{" bit" if is_sv else ""} BSWAP = 1"
				f"\n) ("
				f"\n\tinput  [{data_bits - 1:{idx_max_pad}} : 0] {in_port},"
				f"\n\toutput [{sum_bits - 1:{idx_max_pad}} : 0] {out_port}"
				f"\n);"
				f"\n"
			)

		wire_max_pad = 0 # only one of the wires is there, so no padding

		if optimize:
			wire_max_pad = max(
				len(str(len(tmp_defs) - 1)),
				len(str(sum_bits - 1))
			)

			print(wire_type(tmp_port_o, f"{len(tmp_defs) - 1:{wire_max_pad}}"))

		tmp_idx_max_pad = len(str(len(tmp_defs) - 1))

		max_pad_diff = out_idx_max_pad - tmp_idx_max_pad
		if   max_pad_diff < 0: tmp_port_o  = tmp_port_o[:max_pad_diff]
		elif max_pad_diff > 0: tmp_port_o += ' '*max_pad_diff

		# local signal declaration

		print(wire_type(local_port, f"{sum_bits - 1:{wire_max_pad}}"))
		print(begin_logic)

		for i in range(len(tmp_defs)):
			print(f"{prefix}{tmp_port_o}{lbr}{i:{tmp_idx_max_pad}}{rbr}{assign}{get_terms(tmp_defs[1 + i])}{suffix}")

		if optimize: print("") # separate `tmp_sgnl_base` from `local_crc`

		for i in range(sum_bits):
			print(f"{prefix}{local_port}{lbr}{i:{out_idx_max_pad}}{rbr}{assign}{get_terms(outputs[i])}{suffix}")

		# generate
		if sum_len > 1:
			if syntax == "vhd":
				print(
					f"\n\tendian_check: if BSWAP generate"
					f"\n\t\tlittle_endian: for i in 0 to {sum_len - 1} generate"
					f"\n\t\t\t{out_port}(8*i + 7 downto 8*i) <= {local_port}({sum_bits - 1} - 8*i downto {sum_bits - 8} - 8*i);"
					f"\n\t\tend generate;"
					f"\n\telse generate"
					f"\n\t\t{out_port} <= {local_port};"
					f"\n\tend generate;"
				)
			else:
				print(
					f"{'' if is_sv else "\ngenvar i;"}"
					f"\ngenerate"
					f"\n\tif (BSWAP)"
					f"\n\t\tfor ({"genvar " if is_sv else ''}i = 0; i < {sum_len}; {"i++" if is_sv else "i = i + 1"})"
					f"\n\t\t\tassign {out_port}[8*i + 7 : 8*i] = {local_port}[{sum_bits - 1} - 8*i : {sum_bits - 8} - 8*i];"
					f"\n\telse"
					f"\n\t\tassign {out_port} = {local_port};"
					f"\nendgenerate"
				)
		else:
			print(f"\n{prefix}{out_port}{assign}{local_port}{suffix}")

		print(footer)
	case "pyt" | "py" | "c":
		# compute optimized equation graph
		if optimize:
			tmp_defs, outputs, _ = optimize_gates(rows)
		else:
			tmp_defs = {}
			outputs  = rows

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
			raise Exception(f"`--in-port '{in_port}'` cannot be given with `--syntax '{syntax}'`")

		if out_port in {"bit_", "byte_"}:
			raise Exception(f"`--in-port '{out_port}'` cannot be given with `--syntax '{syntax}'`")

		if syntax == "c":
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

		if optimize:
			print(wire_type(tmp_sgnl_base if syntax == "c" else tmp_port_o, len(tmp_defs)))

		print(wire_type(local_port, sum_bits), end="\n\n")

		tmp_idx_max_pad = len(str(len(tmp_defs) - 1))

		max_pad_diff = out_idx_max_pad - tmp_idx_max_pad
		if   max_pad_diff < 0: tmp_port_o  = tmp_port_o[:max_pad_diff]
		elif max_pad_diff > 0: tmp_port_o += ' '*max_pad_diff

		for i in range(len(tmp_defs)):
			print(f"{prefix}{tmp_port_o}{lbr}{i:{tmp_idx_max_pad}}{rbr}{assign}{get_terms(tmp_defs[1 + i])}{suffix}")

		if optimize: print("")

		for i in range(sum_bits):
			print(f"{prefix}{local_port}{lbr}{i:{out_idx_max_pad}}{rbr}{assign}{get_terms(outputs[i])}{suffix}")

		if syntax == "c":
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

		GV_DECL_LINE_WRAP = 100

		in_idx_max_pad = 0
		in_port_i = "in"

		starting_gates = gf2_cse.count_gates(rows)
		if optimize:
			tmp_defs, outputs, _ = optimize_gates(rows)
		else:
			tmp_defs = {}
			outputs  = rows

		print(
			f"{comment} Generated with tools/crc-gen.py"
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
				f"\ninit    = 0x{args.init:0{sum_nibs}X}"
				f"\nxor_out = 0x{args.xor_out:0{sum_nibs}X}"
				f"\nreflect = {str(args.reflect).lower()}"
			)
	case "raw" | "r":
		# NOTE: the output for this is NOT JSON. It uses set syntax, which is why it is called raw and not json
		starting_gates = gf2_cse.count_gates(rows)

		cse_time_stt = perf_counter_ns()

		if optimize:
			tmp_defs, outputs, _ = optimize_gates(rows)
		else:
			tmp_defs = {}
			outputs  = rows

		cse_time_end = perf_counter_ns()

		ending_gates = gf2_cse.count_gates(tmp_defs, outputs)
		if syntax == "raw":
			sep = "\n\t"
			pad = ' '
		else:
			sep = ''
			pad = ''

		td   = {}

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
			f'{sep}"compression":{pad}{1 - ending_gates / starting_gates},'
			f'{sep}"gen_time_ns":{pad}{curve_gen_time_end - curve_gen_time_stt},'
			f'{sep}"cse_time_ns":{pad}{cse_time_end - cse_time_stt}'
			f"{'\n' if syntax == "raw" else ''}}}"
		)

		print(data if syntax == "raw" else data.replace(' ', ''))
	case "json" | "j" | "m":
		starting_gates = gf2_cse.count_gates(rows)

		cse_time_stt = perf_counter_ns()

		if optimize: tmp_defs, outputs, _ = optimize_gates(rows)
		else:        tmp_defs, outputs = {}, rows

		cse_time_end = perf_counter_ns()

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

					return f"\u0000{json.dumps(lst, separators=seps)}\u0000"

			return (json
				.dumps(data, indent=indent, separators=seps, cls=Encoder)
				.replace('"\\u0000', '')
				.replace('\\u0000"', '')
			)

		indent = '\t'         if syntax == "json" else None
		seps   = (', ', ': ') if syntax == "json" else (',', ':')

		data: dict[str, any] = {}

		if syntax != "m":
			td = {}

			# reindex so keys are in ascending order
			for i in range(1, len(tmp_defs) + 1):
				td[i] = tmp_defs[i]

			data["tmp_defs"] = td
			data["outputs"]  = outputs

		# do this stuff after the other stuff for the dictionary key ordering.
		data["crc_name"]       = crc_name
		data["data_len"]       = data_len
		data["starting_gates"] = starting_gates
		data["ending_gates"]   = ending_gates
		data["gate_reduction"] = starting_gates - ending_gates
		data["compression"]    = 1 - ending_gates / starting_gates
		data["gen_time_ns"]    = curve_gen_time_end - curve_gen_time_stt
		data["cse_time_ns"]    = cse_time_end - cse_time_stt

		print(json_dump_data(data, indent, seps))
	case _:
		raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")
