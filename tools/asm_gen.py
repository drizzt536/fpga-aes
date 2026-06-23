"""
dedicated assembly backend for crcc.py

assembly ISA assumptions:
1. there are 8 bits in a byte
2. register size is 16, 32, or 64 bits
3. pointer size is the same as the register size
4. at least 5 registers (stack pointer + 4 volatile GP)
5. stack grows downwards
6. pushing to stack is pre-decrement (and popping is post-decrement)

beyond these assumptions, it is basically the lowest common denominator. the last three are
the easiest to get around. The first two would require a full rewrite to get around. 3 would
just be annoying to get around

register 0 must be the in  parameter (data)
register 1 must be the out parameter (crc)

if you increase the data length too high, the output program will no longer be valid
because memory immediate offsets can only be so high

NOTE: the number of registers you give should be the number of volatile registers.

the distinction used between CISC and RISC is not the actual distinction, so it is not 100%
accurate. it is decided based on if `*mem ^= reg;` can be encoded in a single instruction. it
is classified as CISC if it can, and RISC if it cannot. Some CISC architectures can't, so it
isn't 100% accurate, but it should only misclassify CISC as RISC and not the other way around.
"""

# TODO: add a parameter for the maximum positive immediate offset that pointers can use,
#       and then if any of the offsets for a given round exceed that number, redo the round
#       with one less register, and do manual @reg[sp] adjustments to get around it.
#       something like @mvl @reg[7], @imm[1234321]. @mvl would need to depend on the
#       architecture, like x64 can do 64-bit immediate moves in one instruction, but ARM64
#       has to do it across four instructions

# TODO: add behavior to push and pop some of the registers at the start/end of the function.
#       this would drop the requirement for >=4 volatile registers. It would not, however,
#       drop the requirement to have >=4 registers, just they would no longer have to all be
#       volatile. This would allow x86 to be used, since it only has 3 volatile registers.
#       also, this will make it so you can use as many of the nonvolatile register as you want,
#       so for like if the pipeline is very deep, but most of the registers are nonvolatile

from gf2_cse import __version__

__all__ = ["gen_ir"]

def schedule_rounds(
	tmp_defs: dict[int, set],
	outputs: list[set],
	register_slots: int = 8
) -> list[tuple[str, set]]:
	# This could potentially be used to generate procedural HDL code as well.

	if register_slots < 1:
		raise ValueError("there must be at least one register slot")

	td = {}

	# reindex so keys are in ascending order
	for i in range(1, len(tmp_defs) + 1):
		td[i] = tmp_defs[i].copy()

	out = [s.copy() for s in outputs]

	max_tmp_finished = 0

	while True:
		schedule = []

		# NOTE: this is the max one that is finished consecutively from the start.
		#       so if 1-31 are finished, 32 is not, and 33 is, it will say 31
		max_tmp_finished = next(iter(td)) - 1 if td else float("inf")

		removable_keys = []

		if max_tmp_finished is not None:
			for i, eqn in td.items():
				if len(schedule) == register_slots:
					break

				has_none = None in eqn
				eqn.discard(None)

				usable = sorted(dep for dep in eqn if dep >= -max_tmp_finished)

				if has_none:
					eqn.add(None)
					usable.append(None)

				if not usable:
					continue

				schedule.append((-i, usable[0]))
				eqn.discard(usable[0])

				if not eqn:
					removable_keys.append(i)

		for key in removable_keys:
			del td[key]

		for i, eqn in enumerate(out):
			if len(schedule) == register_slots:
				break

			has_none = None in eqn
			eqn.discard(None)

			usable = sorted(dep for dep in eqn if dep >= -max_tmp_finished)

			if has_none:
				eqn.add(None)
				usable.append(None)

			if not usable:
				continue

			schedule.append((i, usable[0]))
			eqn.discard(usable[0])

		if not schedule:
			if len(td) or sum(map(len, out)):
				raise Exception("schedule is empty but td or out is not. a cyclic dependency is likely the cause")

			return

		yield schedule

def gen_ir_header(
	tmp_defs: dict[int, set],
	crc_name: str,
	sum_len: int,
	data_len: int,
	reg_size: int,
	emit_spacing: bool,
	emit_comments: bool,
	emit_round_numbers: bool,
) -> list[str]:
	stack_size = (sum_len + data_len << 3) + len(tmp_defs)

	if reg_size not in {16, 32, 64}:
		raise ValueError(f"invalid register width '{reg_size}'. must be 16, 32, or 64")

	if data_len >= (1 << 32):
		raise ValueError(f"invalid data length: '{data_len}'. must fit in 32 bits")

	if stack_size >= (1 << 32):
		raise ValueError(f"invalid stack size: '{stack_size}'. must fit in 32 bits")

	def stack_push(tmp_reg, imm) -> list[str]:
		return [
			f"@mov {tmp_reg}, {imm}",
			f"@sub @reg[sp], @imm[1]",
			f"@stb @reg[sp], {tmp_reg}",
		]

	def stack_push_zero(tmp_reg) -> list[str]:
		return [
			f"\t@mvz {tmp_reg}",
			f"\t@sub @reg[sp], @imm[1]",
			f"\t@stb @reg[sp], {tmp_reg}",
		]

	output = [
		f"@function[crc{crc_name}_{data_len}]",
		f"",
		# TODO: perhaps this next instruction might cause alignment issues on ISA that care, and
		#       on ABIs that suck. like if the call misaligns the stack and the callee is intended
		#       to fix it, this will not work. I don't think it will, but idk for sure. I think
		#       it is fine since it is assume that the pointer size is the same as the word size.
		f"@sub @reg[sp], @imm[{reg_size >> 3}]",
		f"@stw @reg[sp], @reg[1]",
		f"| register 1 is free now",
		f"",
	]

	if reg_size in {32, 64}:
		output += [
			f"| always use one register for >=32 bits",
			f"| i0 = reg1",
			f"@mov @reg[1], @imm[{stack_size & 0xffffffff}]",
			f"",
			f"@deflabel[zero]",
			f"\t@jiz @reg[1], @label[zero_done]",
			f"",
			f"\t@sub @reg[1], @imm[1]",
			f"",
			*stack_push_zero("@regb[2]"),
			f"\t@jmp @label[zero]",
			f"\t@deflabel[zero_done]",
		]
	elif reg_size == 16:
		if stack_size < (1 << 16):
			output += [
				f"| i0 = reg1",
				f"@mov @reg[1], @imm[{stack_size}]",
				f"",
				f"@deflabel[zero]",
				f"\t@jiz @reg[1], @label[zero_done]",
				f"",
				f"\t@sub @reg[1], @imm[1]",
				f"",
				*stack_push_zero("@regb[2]"),
				f"\t@jmp @label[zero]",
				f"\t@deflabel[zero_done]",
			]
		else:
			output += [
				f"| i0 = reg1",
				f"| i1 = reg2",
				f"@mov @reg[1], @imm[{stack_size >> 16}]",
				f"@mov @reg[2], @imm[{stack_size & ((1 << 16) - 1)}]",
				f"",
				f"@deflabel[zero]",
				f"\t@jiz @reg[1], @label[zero_level1]",
				f"",
				f"\t@sub @reg[1], @imm[1]",
				f"\t@jmp @label[zero_push]",
				f"",
				f"@deflabel[zero_level1]",
				f"\t@jiz @reg[2], @label[zero_done]",
				f"",
				f"\t@sub @reg[2], @imm[1]",
				f"",
				f"@deflabel[zero_push]",
				*stack_push_zero("@regb[3]"),
				f"\t@jmp @label[zero]",
			]

	# register 0: data (since function entry)
	# register 1: byte
	# register 2: tmp
	# register 3: idx

	output += [
		f"@mvz @reg[3]",
		f"@mov @reg[1], @imm[{data_len}]",
		f"",
		f"@deflabel[init]",
		f"\t@jiz @reg[1], @label[{"round1" if emit_round_numbers else "init_done"}]",
		f"",
		f"\t%foreach[bit][7,6,5,4,3,2,1,0] do{" | 8 bits per byte" if emit_comments else ''}",
		"\t\t@ldb @regb[2], @reg[0]",
		"\t\t@shr @regb[2], @imm[$bit]",
		"\t\t@and @regb[2], @imm[1]",
		"",
		"\t\t@add @reg[sp], @reg[3]",
		"\t\t@stb @reg[sp], @regb[2]",
		"\t\t@sub @reg[sp], @reg[3]",
		"",
		"\t\t@add @reg[3], @imm[1]",
		"\t%endfor",
		"",
		"\t@add @reg[0], @imm[1]",
		"\t@sub @reg[1], @imm[1]",
		"\t@jmp @label[init]",
		"" if emit_round_numbers else "@deflabel[init_done]",
	]

	if not emit_spacing:
		output = [line for line in output if line]

	if not emit_comments:
		output = [line for line in output if line[0] != '|']

	return output

def gen_ir_footer(
	tmp_defs: dict[int, set],
	sum_len: int,
	data_len: int,
	reg_size: int,
	emit_spacing: bool,
	emit_comments: bool,
	emit_round_numbers: bool, # ignored
) -> list[str]:
	sum_range = ','.join( map(str, range(sum_len)) )

	stack_size = (sum_len + data_len << 3) + len(tmp_defs)

	# reg0 = zero
	# reg1 = crc
	# reg2 = byte index
	# reg3 = tmp byte value
	output = [
		f"@deflabel[epilogue]",
		f"| restore the crc pointer",
		f"@add @reg[sp], @imm[{stack_size}]",
		f"@ldw @reg[1], @reg[sp]",
		f"@sub @reg[sp], @imm[{8*sum_len}]",
		f"",
		# NOTE: out[i] => stack + i
		f"%if[streq][$byteorder][big]",
		f"\t@add @reg[1], @imm[{sum_len - 1}]",
		f"%endif",
		f"%foreach[byte][{sum_range}] do",
		f"\t@mvz @regb[2]",
		f"",
		f"\t%foreach1[bit][0,1,2,3,4,5,6,7] do{" | 8 bits per byte" if emit_comments else ''}",
		f"\t\t@ldb @regb[3], @reg[sp]",
		f"\t\t@shl @regb[3], @imm[$bit]",
		f"\t\t@orr @regb[2], @regb[3]",
		f"\t\t@add @reg[sp], @imm[1]",
		f"\t%endfor1",
		f"",
		f"\t@stb @reg[1], @regb[2]",
		f"",
		f"\t%if[streq][$byteorder][little]",
		f"\t\t@add @reg[1], @imm[1]",
		f"\t%else",
		f"\t\t@sub @reg[1], @imm[1]",
		f"\t%endif",
		f"%endfor",
		f"",
		f"@add @reg[sp], @imm[{reg_size >> 3}]",
		f"@ret",
	]

	if not emit_spacing:
		output = [line for line in output if line]

	if not emit_comments:
		output = [line for line in output if line[0] != '|']

	return output

def gen_cisc_ir(
	tmp_defs: dict[int, set],
	outputs: list[set],
	reg_slots: int = 8,
	emit_spacing: bool = True,
	emit_comments: bool = True,
	emit_round_numbers: bool = True
) -> list[str]:
	output_lines = []

	round_idx = 1
	for round_schedule in schedule_rounds(tmp_defs, outputs, reg_slots):
		dst_pad_len, src_pad_len = (max(len(str(id)) for id in x) for x in zip(*round_schedule))

		max_len = 0
		lines = []

		# Stage 1: load dependencies
		reg_idx = 0
		for _, src in round_schedule:
			src = "@imm[1]" if src is None else f"@tmp[{-src}]" if src < 0 else f"@in[{src}]"
			lines.append(f"@mov @regb[{reg_idx}], {src}")
			reg_idx += 1

		# Stage 2: xor dependencies into outputs
		reg_idx = 0
		for dst, _ in round_schedule:
			dst = f"@tmp[{-dst}]" if dst < 0 else f"@out[{dst}]"
			lines.append(f"@xor {dst}, @regb[{reg_idx}]")
			reg_idx += 1

		max_len = max(len(l) for l in lines)

		if emit_comments:
			for i, line in enumerate(lines):
				a, b = round_schedule[i % len(round_schedule)]
				lines[i] = (
					line.ljust(max_len)
					+ f" | ({a:{dst_pad_len}}, {'null' if b is None else b:{src_pad_len}})"
					+ f", step {1 + i // len(round_schedule)}, elem {1 + i % len(round_schedule)}"
				)

		if emit_spacing and round_idx > 1:
			output_lines.append('')

		if emit_round_numbers:
			output_lines.append(f"@deflabel[round{round_idx}]")

		output_lines += lines

		round_idx += 1

	return output_lines

def gen_risc_ir(
	tmp_defs: dict[int, set],
	outputs: list[set],
	reg_slots: int = 8,
	emit_spacing: bool = True,
	emit_comments: bool = True,
	emit_round_numbers: bool = True
) -> list[str]:
	output_lines = []

	reg_slots >>= 1

	round_idx = 1
	for round_schedule in schedule_rounds(tmp_defs, outputs, reg_slots):
		dst_pad_len, src_pad_len = (max(len(str(id)) for id in x) for x in zip(*round_schedule))

		max_len = 0
		lines = []

		# Stage 1: load temporaries
		reg_idx = 0
		for dst_, _ in round_schedule:
			src = f"@tmp[{-dst_}]" if dst_ < 0 else f"@out[{dst_}]"
			lines.append(f"@ldb @regb[{reg_idx}], {src}")
			reg_idx += 1

		# Stage 2: load dependencies
		# don't reset the register index
		for _, src_ in round_schedule:
			src = "@imm[1]" if src_ is None else f"@tmp[{-src_}]" if src_ < 0 else f"@in[{src_}]"
			lines.append(f"{"@mov" if src_ is None else "@ldb"} @regb[{reg_idx}], {src}")
			reg_idx += 1

		# Stage 3: xor dependencies into temporaries
		reg_idx = 0
		for _, _ in round_schedule:
			lines.append(f"@xor @regb[{reg_idx}], @regb[{reg_idx + reg_slots}]")
			reg_idx += 1

		# Stage 4: store temporaries back where they came from
		reg_idx = 0
		for dst_, _ in round_schedule:
			dst = f"@tmp[{-dst_}]" if dst_ < 0 else f"@out[{dst_}]"
			lines.append(f"@stb {dst}, @regb[{reg_idx}]")
			reg_idx += 1

		max_len = max(len(l) for l in lines)

		if emit_comments:
			for i, line in enumerate(lines):
				a, b = round_schedule[i % len(round_schedule)]
				lines[i] = (
					line.ljust(max_len)
					+ f" | ({a:{dst_pad_len}}, {'null' if b is None else b:{src_pad_len}})"
					+ f", step {1 + i // len(round_schedule)}, elem {1 + i % len(round_schedule)}"
				)

		if emit_spacing and round_idx > 1:
			output_lines.append('')

		if emit_round_numbers:
			output_lines.append(f"@deflabel[round{round_idx}]")

		output_lines += lines
		round_idx += 1

	return output_lines

def gen_ir(
	tmp_defs: dict[int, set],
	outputs: list[set],
	crc_name: str,
	data_len: int,
	sum_len: int,
	reg_slots: int = 8,
	reg_size: int = 32,
	*,
	format: str, # "risc" | "cisc"
	emit_spacing: bool = False,
	emit_comments: bool = False,
	emit_round_numbers: bool = False
):
	dispatch = {"cisc": gen_cisc_ir, "risc": gen_risc_ir}

	return gen_ir_header(
		tmp_defs,
		crc_name,
		sum_len,
		data_len,
		reg_size,
		emit_spacing,
		emit_comments,
		emit_round_numbers
	) + dispatch[format.lower()](
		tmp_defs,
		outputs,
		reg_slots,
		emit_spacing,
		emit_comments,
		emit_round_numbers,
	) + gen_ir_footer(
		tmp_defs,
		sum_len,
		data_len,
		reg_size,
		emit_spacing,
		emit_comments,
		emit_round_numbers
	)

if __name__ == "__main__":
	from sys import stderr
	print(f"crc_asm (v{__version__}) is not a top level program", file=stderr)
	exit(1)
