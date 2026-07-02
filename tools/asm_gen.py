"""
dedicated assembly backend for crcc.py

assembly assumptions:
1. there are 8 bits in a byte
2. register size is 16, 32, or 64 bits
3. pointer size is the same as the register size
4. at least 5 registers (stack pointer + 4 GP)
5. stack grows downwards
6. pushing to stack is pre-decrement (and popping is post-decrement)
7. ABI passes the first two arguments in registers

beyond these assumptions, it is basically the lowest common denominator. the last three are
the easiest to get around. The first two would require a full rewrite to get around. 3 would
just be annoying to get around

register 0 must be the in  parameter (data, arg 1)
register 1 must be the out parameter (crc , arg 2)

NOTE: the number of registers you give should be the number of volatile registers.

the distinction used between CISC and RISC is not the actual distinction, so it is not 100%
accurate. it is decided based on if `*mem ^= reg;` can be encoded in a single instruction. it
is classified as CISC if it can, and RISC if it cannot. Some CISC architectures can't, so it
isn't 100% accurate, but it should only misclassify CISC as RISC and not the other way around.
"""

# TODO: fix the `if emit_comments:` blocks in both the CISC and RISC IR generator functions.
#       if any of the steps needs the imm register, the comments will be wrong.

from gf2_cse import __version__

__all__ = ["gen_ir"]

def gen_ir_header(
	tmp_defs: dict[int, set],
	crc_name: str,
	sum_len: int,
	data_len: int,
	reg_size: int,
	save_list: list[int] | tuple[int, ...],
	emit_spacing: bool,
	emit_comments: bool,
	emit_round_numbers: bool,
) -> list[str]:
	stack_size = (sum_len + data_len << 3) + len(tmp_defs)

	if reg_size not in {16, 32, 64}:
		raise ValueError(f"invalid register width {reg_size!r}. must be 16, 32, or 64")

	if data_len >= (1 << 32):
		raise ValueError(f"invalid data length: {data_len!r}. must fit in 32 bits")

	if stack_size >= (1 << 32):
		raise ValueError(f"invalid stack size: {stack_size!r}. must fit in 32 bits")

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
		f""
	]

	if save_list:
		output += [
			f"%foreach[save][{','.join(save_list)}] do{" | nonvolatile registers" if emit_comments else ''}",
			f"\t@sub @reg[sp], @imm[{reg_size >> 3}]",
			f"\t@stw @reg[sp], @reg[$save]",
			f"%endfor",
			f"",
		]

	output += [
		f"@sub @reg[sp], @imm[{reg_size >> 3}]",
		f"@stw @reg[sp], @reg[1]",
		f"| register 1 is free now",
		f"",
	]

	if reg_size in {32, 64}:
		output += [
			f"| always use one register for >=32 bits",
			f"| i0 = reg1",
			f"@mvl @reg[1], @imm[{stack_size & 0xffffffff}]",
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
				f"@mvl @reg[1], @imm[{stack_size}]",
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
				f"@mvl @reg[1], @imm[{stack_size >> 16}]",
				f"@mvl @reg[2], @imm[{stack_size & ((1 << 16) - 1)}]",
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
		f"@mvl @reg[1], @imm[{data_len}]",
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
	save_list: list[int] | tuple[int, ...],
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
		f"",
		f"@deflabel[epilogue]",
		f"| restore the crc pointer",
		f"@mvl @reg[1], @imm[{stack_size}]",
		f"@add @reg[sp], @reg[1]",
		f"@ldw @reg[1], @reg[sp]",
		f"@sub @reg[sp], @imm[{8*sum_len}]",
		f"",
		# NOTE: out[i] => stack + i
		f"%if[streq][$byteorder][big]",
		f"\t@mvl @reg[2], @imm[{sum_len - 1}]",
		f"\t@add @reg[1], @reg[2]",
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
	]

	if save_list:
		output += [
			f"",
			f"%foreach[save][{','.join(reversed(save_list))}] do{" | nonvolatile registers" if emit_comments else ''}",
			f"\t@ldw @reg[$save], @reg[sp]",
			f"\t@add @reg[sp], @imm[{reg_size >> 3}]",
			f"%endfor",
			f"",
		]

	output.append("@ret")

	if not emit_spacing:
		output = [line for line in output if line]

	if not emit_comments:
		output = [line for line in output if line[0] != '|']

	return output

def get_offset(id: int | None, type: str, in_ofs: int, tmp_ofs: int, out_ofs: int) -> int:
	if id is None:
		if type == "out":
			# sanity check
			raise ValueError("constant 1 signal cannot be an output")

		return 0

	if id < 0:
		return tmp_ofs + id

	return id + (out_ofs if type == "out" else in_ofs)

def schedule_rounds(
	tmp_defs: dict[int, set],
	outputs: list[set],
	reg_slots: int = 8,
	in_ofs: int = 0,
	tmp_ofs: int = 0,
	out_ofs: int = 0,
	max_ofs: int | float = 0,
) -> list[tuple[str, set]]:
	# This could potentially be used to generate procedural HDL code as well.

	if reg_slots < 1:
		raise ValueError("there must be at least one register slot")

	td = {}

	# reindex so keys are in ascending order
	for i in range(1, len(tmp_defs) + 1):
		td[i] = tmp_defs[i].copy()

	out = [s.copy() for s in outputs]

	max_tmp_finished = 0

	while True:
		schedule = []

		imm_reg_req = False # extra register is required for @mvl

		# NOTE: this is the max one that is finished consecutively from the start.
		#       so if 1-31 are finished, 32 is not, and 33 is, it will say 31
		max_tmp_finished = next(iter(td)) - 1 if td else float("inf")

		removable_keys = []

		if max_tmp_finished is not None:
			# tmp values
			for i, eqn in td.items():
				if len(schedule) + imm_reg_req == reg_slots:
					break

				has_none = None in eqn
				eqn.discard(None)

				usable = sorted(dep for dep in eqn if dep >= -max_tmp_finished)

				if has_none:
					eqn.add(None)
					usable.append(None)

				if not usable:
					continue


				tmp_imm_reg_req = imm_reg_req

				# NOTE: dict key is positive, but the unified tmp id is negative

				if (get_offset(-i, "out", in_ofs, tmp_ofs, out_ofs) > max_ofs or
					get_offset(usable[0], "in", in_ofs, tmp_ofs, out_ofs) > max_ofs):
					tmp_imm_reg_req = True

				if tmp_imm_reg_req and not imm_reg_req and len(schedule) + 1 == reg_slots:
					# example: there are 8 registers, registers 0-6 don't need the imm register,
					#          and then register 7 does. that would push the register usage to 9,
					#          which is not allowed. so just try the next optionin this case.
					continue

				imm_reg_req = tmp_imm_reg_req

				schedule.append((-i, usable[0]))
				eqn.discard(usable[0])

				if not eqn:
					removable_keys.append(i)

		for key in removable_keys:
			del td[key]

		for i, eqn in enumerate(out):
			if len(schedule) + imm_reg_req == reg_slots:
				break

			has_none = None in eqn
			eqn.discard(None)

			usable = sorted(dep for dep in eqn if dep >= -max_tmp_finished)

			if has_none:
				eqn.add(None)
				usable.append(None)

			if not usable:
				continue

			tmp_imm_reg_req = imm_reg_req

			if (get_offset(i, "out", in_ofs, tmp_ofs, out_ofs) > max_ofs or
				get_offset(usable[0], "in", in_ofs, tmp_ofs, out_ofs) > max_ofs):
				tmp_imm_reg_req = True

			if tmp_imm_reg_req and not imm_reg_req and len(schedule) + 1 == reg_slots:
				continue

			imm_reg_req = tmp_imm_reg_req

			schedule.append((i, usable[0]))
			eqn.discard(usable[0])

		if not schedule:
			if len(td) or sum(map(len, out)):
				raise Exception("`schedule` is empty but `td` or `out` is not. a cyclic dependency is likely the cause")

			return

		yield schedule

def gen_cisc_ir(
	tmp_defs: dict[int, set],
	outputs: list[set],
	reg_slots: int = 8,
	in_ofs: int = 0,
	tmp_ofs: int = 0,
	out_ofs: int = 0,
	max_ofs: int | float = 0,
	emit_spacing: bool = True,
	emit_comments: bool = True,
	emit_round_numbers: bool = True
) -> list[str]:
	output_lines = []

	imm_reg = f"@reg[{reg_slots - 1}]" # the last register

	round_idx = 1
	for round_schedule in schedule_rounds(tmp_defs, outputs, reg_slots, in_ofs, tmp_ofs, out_ofs, max_ofs):
		dst_pad_len, src_pad_len = (max(len(str(id)) for id in x) for x in zip(*round_schedule))

		max_len = 0
		lines = []

		# stage 1: load dependencies
		reg_idx = 0
		for _, src in round_schedule:
			if src is None:
				lines.append(f"@mov @regb[{reg_idx}], @imm[1]")
				reg_idx += 1
				continue

			ofs = get_offset(src, "in", in_ofs, tmp_ofs, out_ofs)

			if ofs > max_ofs:
				lines += [
					f"@mvl {imm_reg}, @imm[{ofs}]",
					f"@add @reg[sp], {imm_reg}",
					f"@ldb @regb[{reg_idx}], @reg[sp]",
					f"@sub @reg[sp], {imm_reg}",
				]
			else:
				src = f"@tmp[{-src}]" if src < 0 else f"@in[{src}]"
				lines.append(f"@mov @regb[{reg_idx}], {src}")

			reg_idx += 1

		# stage 2: xor dependencies into outputs
		reg_idx = 0
		for dst, _ in round_schedule:
			ofs = get_offset(dst, "out", in_ofs, tmp_ofs, out_ofs)

			if ofs > max_ofs:
				lines += [
					f"@mvl {imm_reg}, @imm[{ofs}]",
					f"@add @reg[sp], {imm_reg}",
					f"@xor @reg[sp], @regb[{reg_idx}]",
					f"@sub @reg[sp], {imm_reg}",
				]
			else:
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
	in_ofs: int = 0,
	tmp_ofs: int = 0,
	out_ofs: int = 0,
	max_ofs: int | float = 0,
	emit_spacing: bool = True,
	emit_comments: bool = True,
	emit_round_numbers: bool = True
) -> list[str]:
	output_lines = []

	imm_reg = f"@reg[{reg_slots - 1}]" # the last register

	# if there is an odd number of registers, the final one cannot be used for anything other
	# than potentially the imm register
	reg_slots >>= 1 # half for temporaries and half for read-ins

	round_idx = 1
	for round_schedule in schedule_rounds(tmp_defs, outputs, reg_slots, in_ofs, tmp_ofs, out_ofs, max_ofs):
		dst_pad_len, src_pad_len = (max(len(str(id)) for id in x) for x in zip(*round_schedule))

		max_len = 0
		lines = []

		# stage 1: load temporaries
		reg_idx = 0
		for dst_, _ in round_schedule:
			ofs = get_offset(dst_, "out", in_ofs, tmp_ofs, out_ofs)

			if ofs > max_ofs:
				lines += [
					f"@mvl {imm_reg}, @imm[{ofs}]",
					f"@add @reg[sp], {imm_reg}",
					f"@ldb @regb[{reg_idx}], @reg[sp]",
					f"@sub @reg[sp], {imm_reg}",
				]
			else:
				src = f"@tmp[{-dst_}]" if dst_ < 0 else f"@out[{dst_}]"
				lines.append(f"@ldb @regb[{reg_idx}], {src}")

			reg_idx += 1

		# stage 2: load dependencies
		# don't reset the register index
		for _, src_ in round_schedule:
			if src_ is None:
				lines.append(f"@mov @regb[{reg_idx}], @imm[1]")
				reg_idx += 1
				continue

			ofs = get_offset(src_, "in", in_ofs, tmp_ofs, out_ofs)

			if ofs > max_ofs:
				lines += [
					f"@mvl {imm_reg}, @imm[{ofs}]",
					f"@add @reg[sp], {imm_reg}",
					f"@ldb @regb[{reg_idx}], @reg[sp]",
					f"@sub @reg[sp], {imm_reg}",
				]
			else:
				src = f"@tmp[{-src_}]" if src_ < 0 else f"@in[{src_}]"
				lines.append(f"@ldb @regb[{reg_idx}], {src}")

			reg_idx += 1

		# stage 3: xor dependencies into temporaries
		reg_idx = 0
		for _, _ in round_schedule:
			# this is only registers, so it doesn't need the @mvl stuff
			lines.append(f"@xor @regb[{reg_idx}], @regb[{reg_idx + reg_slots}]")
			reg_idx += 1

		# stage 4: store temporaries back where they came from
		reg_idx = 0
		for dst_, _ in round_schedule:
			ofs = get_offset(dst_, "out", in_ofs, tmp_ofs, out_ofs)

			if ofs > max_ofs:
				lines += [
					f"@mvl {imm_reg}, @imm[{ofs}]",
					f"@add @reg[sp], {imm_reg}",
					f"@stb @reg[sp], @regb[{reg_idx}]",
					f"@sub @reg[sp], {imm_reg}",
				]
			else:
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
	format: str = "cisc", # "risc" | "cisc"
	save_list: list[int] | tuple[int, ...] = None,
	in_ofs:  int = 0,
	tmp_ofs: int = 0,
	out_ofs: int = 0,
	max_ofs: int | None = None,
	emit_spacing: bool = False,
	emit_comments: bool = False,
	emit_round_numbers: bool = False
):
	dispatch = {"cisc": gen_cisc_ir, "risc": gen_risc_ir}

	save_list = [] if save_list is None else [str(x) for x in save_list]

	if max_ofs is None:
		max_ofs = float("inf")

	if max_ofs < (reg_size >> 3):
		raise ValueError(f"max_ofs must be at least reg_size // 8 ({reg_size >> 3}). actual is {max_ofs}")

	if max_ofs < (data_len << 3):
		raise ValueError(f"max_ofs must be at least as large as 8*data_len ({data_len << 3}). actual is {max_ofs}")

	return gen_ir_header(
		tmp_defs,
		crc_name,
		sum_len,
		data_len,
		reg_size,
		save_list,
		emit_spacing,
		emit_comments,
		emit_round_numbers
	) + dispatch[format.lower()](
		tmp_defs,
		outputs,
		reg_slots,
		in_ofs,
		tmp_ofs,
		out_ofs,
		max_ofs,
		emit_spacing,
		emit_comments,
		emit_round_numbers,
	) + gen_ir_footer(
		tmp_defs,
		sum_len,
		data_len,
		reg_size,
		save_list,
		emit_spacing,
		emit_comments,
		emit_round_numbers
	)

if __name__ == "__main__":
	from gf2_cse import _eprint
	_eprint(f"\x1b[31masm_gen (v{__version__}) is not a top level program\x1b[m")
	raise SystemExit(1)
