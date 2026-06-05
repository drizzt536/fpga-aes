"""
fully-combinational HDL code generator for CRC functions given a fixed-length byte-aligned input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than the default is used.
"""

if __name__ != "__main__":
	raise Exception("crc-gen.py should only be used at the top level.")

import argparse

# NOTE: zlib implements the same CRC32 standard as Ethernet uses.

syntaxes = "systemverilog", "sv", "verilog", "v", "vhdl", "vhd", "python", "py", "python-first", "py1", "plain", "p", "json", "j", "raw"

parser = argparse.ArgumentParser()
parser.add_argument("--data-len", "-l", type=int, default=4, help="bytes length of checksum input data. default is 4")
parser.add_argument("--in-port", "--in-var", "-I", type=str, default="data", help="input port/variable name. default is 'data'")
parser.add_argument("--out-port", "--out-var", "-O", type=str, default="crc", help="output port/variable name. default is 'crc'")
parser.add_argument("--syntax", "-s", type=str.lower, choices=syntaxes, default=syntaxes[0], help=f"output language. default is '{syntaxes[0]}'")
parser.add_argument("--algorithm", "--alg", "-a", type=lambda s: None if s is None else str.lower(s).strip(), default=None, help=f"CRC name. overrides other options. default is 'crc32'")
parser.add_argument("--output", "--out", "-o", type=str, default="-", help=f"output file. default is '-'")
parser.add_argument("--list-algorithms", "-L", action="store_true", help="list available algorithms and exit")

custom_crc_group = parser.add_argument_group("custom CRC overrides (triggers custom mode if --polynomial is set)")
custom_crc_group.add_argument("--polynomial", "--poly", "-p", type=int, help="polynomial. don't omit the uppermost bit")
custom_crc_group.add_argument("--init", "-i"   , type=int, default=0, help="initial value. default is 0")
custom_crc_group.add_argument("--xor-out", "-x", type=int, default=0, help="final XOR mask (default: 0)")
custom_crc_group.add_argument("--reflect", "-r", action="store_true", help="enable reflection. default is off")

optimize_group = parser.add_argument_group(
	"optimization settings (gate count)",
	"defaults: optimize off, lookahead depth 0, n max 2, beam size 1, LNS: off, 1 trial, window size 3, unseeded"
)
optimize_group.add_argument("--optimize"    , action="store_true", help="enable optimization without touching settings")
optimize_group.add_argument("--optimize-depth"     , type=int    , help="enable optimization and set search lookahead depth.")
optimize_group.add_argument("--optimize-nmax"      , type=int    , help="enable optimization and set n max.")
optimize_group.add_argument("--optimize-beam"      , type=int    , help="enable optimization and set beam size.")
optimize_group.add_argument("--optimize-lns", action="store_true", help="enable optimization+LNS without touching settings")
optimize_group.add_argument("--optimize-lns-trials", type=int    , help="enable LNS and set the count.")
optimize_group.add_argument("--optimize-lns-window", type=int    , help="enable LNS and set the window size.")
optimize_group.add_argument("--optimize-lns-seed"  , type=int    , help="enable LNS, switch to predictable mode, and set the seed")
optimize_group.add_argument("--verbose"            , type=int    , help="set optimization verbosity level")
args = parser.parse_args()

# TODO: implement the rest of the configuration logic:
optimize = args.optimize or args.optimize_lns or       args.optimize_depth      is not None \
			or args.optimize_nmax       is not None or args.optimize_beam       is not None \
			or args.optimize_lns_trials is not None or args.optimize_lns_window is not None \
			or args.optimize_lns_seed   is not None
lns = args.optimize_lns or                         args.optimize_lns_trials is not None \
		or args.optimize_lns_window is not None or args.optimize_lns_seed   is not None
optimize_depth   = args.optimize_depth      if args.optimize_depth      is not None else 0
optimize_nmax    = args.optimize_nmax       if args.optimize_nmax       is not None else 2
optimize_beam    = args.optimize_beam       if args.optimize_beam       is not None else 1
lns_trials       = args.optimize_lns_trials if args.optimize_lns_trials is not None else 1
lns_window       = args.optimize_lns_window if args.optimize_lns_window is not None else 3
lns_seed         = args.optimize_lns_seed
optimize_verbose = args.verbose or 0

if not lns:
	lns_window = 0
	lns_trials = 0

if optimize:
	from crc_optimizer import optimize_gates as _optimize_gates

	def optimize_gates(eqns: list[set]) -> tuple[dict[int, set], list[set]]:
		return _optimize_gates(
			rows,
			optimize_depth,
			optimize_nmax,
			optimize_beam,
			lns_window,
			lns_trials,
			lns_seed,
			optimize_verbose
		)

data_len   = args.data_len
in_port    = args.in_port
out_port   = args.out_port
local_port = "local_" + out_port
tmp_port_i = "tmp" + " "*(len(in_port) - 3)    # 3 == len("tmp")
tmp_port_o = "tmp" + " "*(len(local_port) - 3) # 3 == len("tmp")
in_port_i  = in_port + " "*(len(tmp_port_i) - len(in_port)) if optimize else in_port
syntax     = args.syntax
crc_name   = args.algorithm
poly       = args.polynomial
output     = args.output

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
	raise Exception("data length must be at least 1")

if poly is not None:
	if crc_name is not None:
		raise Exception("`--algorithm` and `--polynomial` cannot both be provided.")

	try:
		import crcmod
	except ImportError:
		raise Exception("custom CRCs require `crcmod-plus`.")

	crc = crcmod.mkCrcFun(poly, args.init, args.reflect, args.xor_out)
	crc_name = f"crc_custom_0x{poly:X}"
	sum_len = (poly.bit_length() + 6) // 8
elif crc_name in {None, "32", "crc32", "crc-32", "crc 32"}:
	# use zlib.crc32 if possible since it is is built-in, and probably faster,.
	crc_name = '32'
	sum_len = 4

	from zlib import crc32 as crc
else:
	try:
		import crcmod
	except ImportError:
		raise Exception("CRCs other than crc32 require `crcmod-plus`.")

	if crc_name is None:
		crc_name = '32'

	sum_len = sum_len_map.get(crcmod.predefined._simplify_name(crc_name), None)

	if sum_len is None:
		raise Exception(f"crc name '{crc_name}' does not exist or is unknown")

	crc_name = crcmod.predefined._simplify_name(crc_name)
	crc = crcmod.predefined.mkCrcFun(crc_name)

cols = [crc((1 << n).to_bytes(data_len, byteorder='big')) for n in range(8*data_len)]

K = crc(bytes(data_len)) # correction vector

rows = [
	{8*data_len - 1 - n for n in range(8*data_len) if (cols[n] ^ K) & (1 << bit)}
	for bit in range(8*sum_len)
]

for bit, eqn in enumerate(rows):
	if (K >> bit) & 1:
		eqn.add(None)

# this bit is magic
reversed_polynomial = crc(b'\x80') ^ crc(b'\x00')
polynomial          = int(f"{reversed_polynomial:0{8*sum_len}b}"[::-1], 2)

max_io_pad      = 1 + max(len(in_port), len(out_port))
in_pad          = " "*(max_io_pad - len(in_port))
out_pad         = " "*(max_io_pad - len(out_port))
in_idx_max_pad  = len(str(8 * data_len))
out_idx_max_pad = len(str(8 * sum_len))
idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

syntax_data = {
	"vhd": {
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
		"wire_type"   : lambda name, size: f"\tsignal {name} : std_logic_vector({size} downto 0);",
	}, "v": {
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
	}, "py": {
		"xor"         : " ^ ",
		'1'           : '1',
		'0'           : '0',
		'='           : " = ",
		'['           : '[',
		']'           : ']',
		'^'           : "\t",
		'$'           : ',',
		"footer"      : None,
		"comment"     : "#",
		"begin_logic" : '',
		"wire_type"   : None,
	}
}

syntax_data["sv"] = syntax_data["v"]

syntax = {
	"vhdl"         : "vhd" , "vhd": "vhd",
	"verilog"      : "v"   , "v"  : "v",
	"systemverilog": "sv"  , "sv" : "sv",
	"python"       : "py"  , "py" : "py",
	"python-first" : "py1" , "py1": "py1",
	"plain"        : "p"   , "p"  : "p",
	"json"         : "json", "j"  : "j",
	"raw": "raw"
}[syntax]

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
	outfile = open(output, "w") # auto closed on exit
	_print  = print

	def print(message: str) -> None:
		_print(message, file=outfile)

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

match syntax:
	case "vhd" | "v" | "sv":
		is_sv = syntax == "sv"

		# compute optimized graph
		if optimize:
			tmp_defs, outputs = optimize_gates(rows)
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
				f"\n\t\t{in_port}{in_pad}: in  std_logic_vector({8*data_len - 1:{idx_max_pad}} downto 0);"
				f"\n\t\t{out_port}{out_pad}: out std_logic_vector({8*sum_len - 1:{idx_max_pad}} downto 0)"
				f"\n\t);"
				f"\nend entity;"
				f"\n"
				f"\narchitecture crc{crc_name}_{data_len}_arch of crc{crc_name}_{data_len} is"
				f"\n\t-- polynomial: 0x{polynomial:0{2*sum_len}X}"
				f"\n\t-- crc{crc_name}(0): 0x{K:0{2*sum_len}X}"
				f"\n"
			)
		else:
			print(
				f"// polynomial: 0x{polynomial:0{2*sum_len}X}"
				f"\n// crc{crc_name}(0): 0x{K:0{2*sum_len}X}"
				f"\n"
				f"\nmodule crc{crc_name}_{data_len} #("
				f"\n\t// 1 => little endian, 0 => big endian"
				f"\n\tparameter{" bit" if is_sv else ""} BSWAP = 1"
				f"\n) ("
				f"\n\tinput  [{8*data_len - 1:{idx_max_pad}}:0] {in_port},"
				f"\n\toutput [{8*sum_len - 1:{idx_max_pad}}:0] {out_port}"
				f"\n);"
				f"\n"
			)

		if optimize:
			print(wire_type(tmp_port_o, len(tmp_defs) - 1))

		tmp_idx_max_pad = len(str(len(tmp_defs) - 1))

		max_pad_diff = out_idx_max_pad - tmp_idx_max_pad
		if   max_pad_diff < 0: tmp_port_o  = tmp_port_o[:max_pad_diff]
		elif max_pad_diff > 0: tmp_port_o += ' '*max_pad_diff

		# local signal declaration
		print(wire_type(local_port, 8*sum_len - 1))
		print(begin_logic)

		for i in range(len(tmp_defs)):
			print(f"{prefix}{tmp_port_o}{lbr}{i:{tmp_idx_max_pad}}{rbr}{assign}{get_terms(tmp_defs[1 + i])}{suffix}")

		print(end='\n' if optimize else '') # separate `tmp` from `local_crc`

		for i in range(8*sum_len):
			print(f"{prefix}{local_port}{lbr}{i:{out_idx_max_pad}}{rbr}{assign}{get_terms(outputs[i])}{suffix}")

		# generate
		if sum_len > 1:
			if syntax == "vhd":
				print(
					f"\n\tendian_check: if BSWAP generate"
					f"\n\t\tlittle_endian: for i in 0 to {sum_len - 1} generate"
					f"\n\t\t\t{out_port}(8*i + 7 downto 8*i) <= {local_port}({8*sum_len - 1} - 8*i downto {8*sum_len - 8} - 8*i);"
					f"\n\t\tend generate;"
					f"\n\telse generate"
					f"\n\t\t{out_port} <= {local_port};"
					f"\n\tend generate;"
				)
			else:
				print(
					f"\ngenerate"
					f"\n\tif (BSWAP){"" if is_sv else " begin"}"
					f"{'' if is_sv else "\n\t\tgenvar i;"}"
					f"\n\t\tfor ({"genvar " if is_sv else ''}i = 0; i < {sum_len}; {"i++" if is_sv else "i = i + 1"})"
					f"\n\t\t\tassign {out_port}[8*i + 7 : 8*i] = {local_port}[{8*sum_len - 1} - 8*i : {8*sum_len - 8} - 8*i];"
					f"\n\t{"" if is_sv else "end "}else"
					f"\n\t\tassign {out_port} = {local_port};"
					f"\nendgenerate"
				)
		else:
			print(f"\n{prefix}{out_port}{assign}{local_port}{suffix}")

		print(footer)
	case "py" | "py1":
		# compute optimized graph
		if optimize:
			tmp_defs, outputs = optimize_gates(rows)
		else:
			tmp_defs = {}
			outputs  = rows

		if syntax in {"python-first", "py1"}:
			# also give functions for testing the functionality
			# meant for only the first time, so you paste them to wherever
			# it is being used, and then swithc to 'python' or 'py'

			print(
				"import crcmod, zlib"
				"\nfrom secrets import randbits"
				"\n"
				"\ndef crc_check(fn: str, size: int = 1, data: bytes | None = None) -> tuple[int, int]:"
				"\n\tfrom secrets import randbits"
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
			)


		# "input bits" or "input data"
		in_bits = "inb" if in_port != "inb" else "ind"

		in_port_i  = in_bits
		tmp_port_i = "tmp"

		if in_port in {"_bit", "_byte"}:
			raise Exception(f"`--in-port '{in_port}' cannot be given with `--syntax '{syntax}'`")

		if out_port in {"_bit", "_byte"}:
			raise Exception(f"`--in-port '{out_port}' cannot be given with `--syntax '{syntax}'`")

		print(
			f"def crc{crc_name}_{data_len}({in_port}: bytes) -> int:"
			f"\n\t{in_bits} = []"
			f"\n\tfor _byte in {in_port}:"
			f"\n\t\tfor _bit in range(7, -1, -1):"
			f"\n\t\t\t{in_bits}.append((_byte >> _bit) & 1)"
			f"\n"
		)

		if optimize:
			print(f"\ttmp = [None]*{len(tmp_defs)}\n")

		tmp_idx_max_pad = len(str(len(tmp_defs) - 1))

		max_pad_diff = out_idx_max_pad - tmp_idx_max_pad
		if   max_pad_diff < 0: tmp_port_o  = tmp_port_o[:max_pad_diff]
		elif max_pad_diff > 0: tmp_port_o += ' '*max_pad_diff

		for i in range(len(tmp_defs)):
			print(f"{prefix}tmp{lbr}{i:{tmp_idx_max_pad}}{rbr}{assign}{get_terms(tmp_defs[1 + i])}")

		if optimize:
			print()

		print(f"\t{local_port}{assign}[")

		for i in range(8*sum_len):
			print(f"\t{prefix}{get_terms(outputs[i]).lstrip()}{suffix}")

		print(
			f"\t]"
			f"\n"
			f"\n\t{out_port} = 0"
			f"\n\tfor i in range({8*sum_len}):"
			f"\n\t\t{out_port} |= {local_port}[i] << i"
			f"\n"
			f"\n\treturn {out_port}"
		)
	case "p":
		print(
			"CRC Summary:"
			f"\ncustom     = {str(poly is not None).lower()}"
			f"\nalgorithm  = {crc_name}"
			f"\ndata len   = {data_len}"
			f"\nsum len    = {sum_len}"
			f"\nCRC(empty) = 0x{K:0{2*sum_len}X}"
			f"\npolynomial = 0x{polynomial:0{2*sum_len}X}"
			f"\nreversed polynomial = 0x{reversed_polynomial:0{2*sum_len}X}"
		)

		if poly is not None:
			print(
				"\nRocksoft Parameters:"
				f"\ninit    = 0x{args.init:0{2*sum_len}X}"
				f"\nxor_out = 0x{args.xor_out:0{2*sum_len}X}"
				f"\nreflect = {str(args.reflect).lower()}"
			)
	case "json" | "j":
		import json
		# "j" gives minified and "json" gives beautified

		report = {
			"custom": poly is not None,
			"algorithm": crc_name,
			"data_len": data_len,
			"sum_len": sum_len,
			"K": K,
			"polynomial": polynomial,
			"reversed_polynomial": reversed_polynomial,
			"rocksoft_parameters": {
				"polynomial": args.polynomial, # different from the other one
				"init": None if poly is None else args.init,
				"xor_out": None if poly is None else args.xor_out,
				"reflect": None if poly is None else args.reflect
			}
		}

		indent = "\t" if syntax == "json" else None
		seps   = (", ", ": ") if syntax == "json" else (",", ":")

		print(json.dumps(report, indent=indent, separators=seps))
	case "raw":
		print(optimize_gates(rows) if optimize else ({}, rows))
	case _:
		raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")
