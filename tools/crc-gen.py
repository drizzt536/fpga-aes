"""
fully-combinational HDL code generator for CRC functions given a fixed-length input.

requires Python >=3.12.
requires crcmod-plus if a CRC function other than the default is used.
"""

if __name__ != "__main__":
	raise Exception("crc-gen.py should only be used at the top level.")

import argparse

# TODO: potentially try to do GCSE. idk how to do that though, so probably I don't really care too much
# NOTE: zlib implements the same CRC32 standard as Ethernet uses.

syntaxes = "systemverilog", "verilog", "v", "sv", "vhdl", "vhd", "python", "py", "python-first", "py1", "plain", "p", "json", "j"

parser = argparse.ArgumentParser()
parser.add_argument("--data-len", "-l", type=int, default=4, help="bytes length of checksum input data. default is 4")
parser.add_argument("--in-port", "--in-var", "-I", type=str, default="data", help="input port/variable name. default is 'data'")
parser.add_argument("--out-port", "--out-var", "-O", type=str, default="crc", help="output port/variable name. default is 'crc'")
parser.add_argument("--syntax", "-s", type=str.lower, choices=syntaxes, default=syntaxes[0], help=f"output language. default is '{syntaxes[0]}'")
parser.add_argument("--algorithm", "--alg", "-a", type=lambda s: None if s is None else str.lower(s).strip(), default=None, help=f"CRC name. overrides other options. default is 'crc32'")
parser.add_argument("--output", "--out", "-o", type=str, default="-", help=f"output file. default is '-'")
parser.add_argument("--list-algorithms", "-L", action="store_true", help="list available algorithms and exit")

custom_group = parser.add_argument_group("custom CRC overrides (triggers custom mode if --polynomial is set)")
custom_group.add_argument("--polynomial", "--poly", "-p", type=int, help="polynomial. don't omit the uppermost bit")
custom_group.add_argument("--init", "-i", type=int, default=0, help="initial value. default is 0")
custom_group.add_argument("--xor-out", "-x", type=int, default=0, help="final XOR mask (default: 0)")
custom_group.add_argument("--reflect", "-r", action="store_true", help="enable reflection. default is off")
args = parser.parse_args()

data_len = args.data_len
in_port  = args.in_port
out_port = args.out_port
tmp_port = "local_" + out_port
syntax   = args.syntax
crc_name = args.algorithm
poly     = args.polynomial
output   = args.output

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

	print("\nNOTE: names are case insensitive, and are stripped of spaces and dashes and 'crc' at the start")

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
	[8*data_len - 1 - n for n in range(8*data_len) if (cols[n] ^ K) & (1 << bit)]
	for bit in range(8*sum_len)
]

# idk why this part works
reversed_polynomial = crc(b'\x80') ^ crc(b'\x00')
polynomial = int(f"{reversed_polynomial:0{8*sum_len}b}"[::-1], 2)

max_pad         = 1 + max(len(in_port), len(out_port))
in_pad          = " "*(max_pad - len(in_port))
out_pad         = " "*(max_pad - len(out_port))
in_idx_max_pad  = len(str(8 * data_len))
out_idx_max_pad = len(str(8 * sum_len))
idx_max_pad     = max(in_idx_max_pad, out_idx_max_pad)

if output != "-":
	outfile = open(output, "w") # auto closed on exit
	_print  = print

	def print(message: str) -> None:
		_print(message, file=outfile)

match syntax:
	case "vhdl" | "vhd":
		print(
			f"-- Generated with tools/crc-gen.py"
			f"\nlibrary ieee;"
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
			f"\n\tsignal {tmp_port} : std_logic_vector({8*sum_len - 1} downto 0);"
			f"\nbegin"
		)

		for bit in range(8*sum_len):
			terms = " xor ".join(f"{in_port}({n:{in_idx_max_pad}})" for n in rows[bit])

			if (K >> bit) & 1:
				terms = f"'1' xor {terms}" if terms else "'1'"
			elif terms == "":
				terms = "'0'"
			elif K != 0:
				terms = " "*len("'1' xor ") + terms

			print(f"\t{tmp_port}({bit:{out_idx_max_pad}}) <= {terms};")

		if sum_len > 1:
			print(
				f"\n\tendian_check: if BSWAP generate"
				f"\n\t\tlittle_endian: for i in 0 to {sum_len - 1} generate"
				f"\n\t\t\t{out_port}(8*i + 7 downto 8*i) <= {tmp_port}({8*sum_len - 1} - 8*i downto {8*sum_len - 8} - 8*i);"
				f"\n\t\tend generate;"
				f"\n\telse generate"
				f"\n\t\t{out_port} <= {tmp_port};"
				f"\n\tend generate;"
			)
		else:
			print(f"\n\t{out_port} <= {tmp_port};")

		print("end architecture;")
	case "verilog" | "v" | "systemverilog" | "sv":
		is_sv = syntax in {"systemverilog", "sv"}

		print(
			f"// Generated with tools/crc-gen.py"
			f"\n// polynomial: 0x{polynomial:0{2*sum_len}X}"
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
			f"\nwire [{8*sum_len - 1}:0] {tmp_port};"
			f"\n"
		)

		for bit in range(8*sum_len):
			terms = " ^ ".join(f"{in_port}[{n:{in_idx_max_pad}}]" for n in rows[bit])

			if (K >> bit) & 1:
				terms = f"1 ^ {terms}" if terms else "1"
			elif terms == "":
				terms = "0"
			elif K != 0:
				terms = " "*len("1 ^ ") + terms

			print(f"assign {tmp_port}[{bit:{out_idx_max_pad}}] = {terms};")

		if sum_len > 1:
			print(
				f"\ngenerate"
				f"\n\tif (BSWAP){"" if is_sv else " begin"}"
				f"{"" if is_sv else "\n\t\tgenvar i;"}"
				f"\n\t\tfor ({"genvar " if is_sv else ""}i = 0; i < {sum_len}; {"i++" if is_sv else "i = i + 1"})"
				f"\n\t\t\tassign {out_port}[8*i + 7 : 8*i] = {tmp_port}[{8*sum_len - 1} - 8*i : {8*sum_len - 8} - 8*i];"
				f"\n\t{"" if is_sv else "end "}else"
				f"\n\t\tassign {out_port} = {tmp_port};"
				f"\nendgenerate"
			)
		else:
			print(f"assign {out_port} = {tmp_port};")

		print("\nendmodule")
	case "python" | "py" | "python-first" | "py1":
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


		in_bits = "inb" if in_port != "inb" else "bits"

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
			f"\n\t{tmp_port} = ["
		)

		if True:
			for bit in range(8*sum_len):
				terms = " ^ ".join(f"{in_bits}[{n:{in_idx_max_pad}}]" for n in rows[bit])

				if (K >> bit) & 1:
					terms = f"1 ^ {terms}" if terms else "1"
				elif terms == "":
					terms = "0"

				print(f"\t\t{terms},")
		else:
			# more explicit, for debugging
			for bit in range(8*sum_len):
				terms = " ^ ".join(f"{in_bits}[{n:{in_idx_max_pad}}]" for n in rows[bit]) or "0"

				if (K >> bit) & 1:
					terms = f"1 ^ {terms}"
				else:
					terms = f"0 ^ {terms}"

				print(f"\t\t{terms},")

		print(
			f"\t]"
			f"\n"
			f"\n\t{out_port} = 0"
			f"\n\tfor i in range({8*sum_len}):"
			f"\n\t\t{out_port} |= {tmp_port}[i] << i"
			f"\n"
			f"\n\treturn {out_port}"
		)
	case "plain" | "p":
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
				f"\reflect  = {str(args.reflect).lower()}"
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
				"init": args.init,
				"xor_out": args.xor_out,
				"reflect": args.reflect
			}
		}

		indent = "\t" if syntax == "json" else None
		seps   = (", ", ": ") if syntax == "json" else (",", ":")

		print(json.dumps(report, indent=indent, separators=seps))
	case _:
		raise Exception(f"mismatch between argparse syntax list and match/case syntax list. syntax: '{syntax}'")
