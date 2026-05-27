from zlib import crc32
import argparse

syntaxes = "vhdl", "vhd", "verilog", "v", "python", "py"

parser = argparse.ArgumentParser()
parser.add_argument("--data-len", "-l", type=int, default=60, help="bytes length of checksum input data. default is 60")
parser.add_argument("--in-port", "-i",  type=str, default="data", help="input port/variable name. default is 'data'")
parser.add_argument("--out-port", "-o", type=str, default="crc", help="output port/variable name. default is 'crc'")
parser.add_argument("--syntax", "-s", type=str, choices=syntaxes, default=syntaxes[0], help=f"output language. default is '{syntaxes[0]}'")
args = parser.parse_args()

data_len = args.data_len
sum_len  = 4 # 32 bits
in_port  = args.in_port
out_port = args.out_port
syntax   = args.syntax.lower()

cols = [crc32((1 << n).to_bytes(data_len, byteorder='big')) for n in range(8*data_len)]

rows = [
	[8*data_len - 1 - n for n in range(8*data_len) if cols[n] & (1 << bit)]
	for bit in range(8*sum_len)
]

K = crc32(bytes(data_len))

max_pad = 1 + max(len(in_port), len(out_port))
in_pad  = " "*(max_pad - len(in_port))
out_pad = " "*(max_pad - len(out_port))

match syntax:
	case "vhdl" | "vhd":
		print(
			f"-- Generated with tools/crc32-gen.py"
			f"\nlibrary ieee;"
			f"\nuse ieee.std_logic_1164.all;"
			f"\n"
			f"\nentity crc32_{data_len} is"
			f"\n\tport ("
			f"\n\t\t{in_port}{in_pad}: in  std_logic_vector({8*data_len - 1} downto 0);"
			f"\n\t\t{out_port}{out_pad}: out std_logic_vector({8*sum_len - 1} downto 0)"
			f"\n\t);"
			f"\nend entity;"
			f"\n"
			f"\narchitecture crc32_{data_len}_arch of crc32_{data_len} is"
			f"\n\t-- polynomial: 0x04C11DB7"
			f"\n\t-- CRC32( 0 ): 0x{K:08x}"
			f"\nbegin"
		)

		for bit in range(8*sum_len):
			terms = " xor ".join(f"{in_port}({n})" for n in rows[bit])
			print(f"\t{out_port}({bit:2d}) <= '{(K >> bit) & 1}' xor {terms};")

		print("end architecture;")
	case "verilog" | "v":
		print(
			f"// Generated with tools/crc32-gen.py"
			f"\n// polynomial: 0x04C11DB7"
			f"\n// CRC32( 0 ): 0x{K:08x}"
			f"\n"
			f"\nmodule crc32_{data_len} ("
			f"\n\tinput  [{8*data_len -1}:0] {in_port},"
			f"\n\toutput [{8*sum_len - 1}:0] {out_port}"
			f"\n);"
			f"\n"
		)

		for bit in range(8*sum_len):
			terms = " ^ ".join(f"{in_port}[{n}]" for n in rows[bit])
			print(f"assign {out_port}[{bit:2d}] = 1'b{(K >> bit) & 1} ^ {terms};")

		print("\nendmodule")
	case "python" | "py":
		# for testing
		print(f"{out_port} = [")

		for bit in range(8*sum_len):
			terms = " ^ ".join(f"{in_port}[{n}]" for n in rows[bit])
			print(f"\t{(K >> bit) & 1} ^ {terms},")

		print("]")
	case _:
		raise NotImplementedError(
			f"unknown syntax '{syntax}'.\n"
			f"supported syntaxes: {repr(syntaxes)[1:-1]}"
		)

"""
## test code

data = bytes([
	0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE,
	0xFF, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC, 0xDD,
	0xEE, 0xFF, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB, 0xCC,
	0xDD, 0xEE, 0xFF, 0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xAA, 0xBB,
])

inp = []
for byte in data:
	for bit in range(7, -1, -1):
		inp.append((byte >> bit) & 1)


crc = [0] * 32
# this is not the best way to do this, but I don't really care
for bit in range(8*sum_len):
	terms = " ^ ".join(f"data[{n}]" for n in rows[bit])
	exec(f"crc[{bit}] = {(K >> bit) & 1} ^ {terms}")

print(f"expected = {crc32(data):032b}")
print(f"actual   = {"".join(str(x) for x in reversed(crc))}")
"""
