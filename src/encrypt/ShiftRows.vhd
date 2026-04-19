library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity ShiftRows is
	port (
		input  : in  AESBlock;
		output : out AESBlock
	);
end entity;

architecture ShiftRows_arch of ShiftRows is
	/*
	using indices:
	input			output
	00 04 08 12		00 04 08 12
	01 05 09 13		05 09 13 01
	02 06 10 14		10 14 02 06
	03 07 11 15		15 03 07 11

	again but transposed and with letters so the transform is clearer:
	input		output
	A B C D		A B C D
	E F G H		F G H E
	I J K L		K L I J
	M N O P		P M N O
	*/
begin
	a: for row in 0 to 3 generate
		b: for col in 0 to 3 generate
			output(col*4 + row) <= input(((col + row) mod 4)*4 + row);
		end generate;
	end generate;
end architecture;
