library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity InvMixColumns is
	port (
		input  : in  AESBlock;
		output : out AESBlock
	);
end entity;

architecture InvMixColumns_arch of InvMixColumns is
	/*
	input indices
	00 04 08 12
	01 05 09 13
	02 06 10 14
	03 07 11 15

	|c0'|   |e b d 9| |c0|
	|c1'| = |9 e b d| |c1|
	|c2'|   |d 9 e b| |c2|
	|c3'|   |b d 9 e| |c3|
	*/	
begin
	a: for col in 0 to 3 generate
		signal c0, c1, c2, c3: ubyte;
	begin
		c0 <= ubyte(input(4*col + 0));
		c1 <= ubyte(input(4*col + 1));
		c2 <= ubyte(input(4*col + 2));
		c3 <= ubyte(input(4*col + 3));

		output(4*col + 0) <= byte(times14(c0) xor times11(c1) xor times13(c2) xor times9 (c3));
		output(4*col + 1) <= byte(times9 (c0) xor times14(c1) xor times11(c2) xor times13(c3));
		output(4*col + 2) <= byte(times13(c0) xor times9 (c1) xor times14(c2) xor times11(c3));
		output(4*col + 3) <= byte(times11(c0) xor times13(c1) xor times9 (c2) xor times14(c3));
	end generate;
end architecture;
