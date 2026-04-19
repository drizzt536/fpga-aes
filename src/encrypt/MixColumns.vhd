library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity MixColumns is
	port (
		input  : in  AESBlock;
		output : out AESBlock
	);
end entity;

architecture MixColumns_arch of MixColumns is
	/*
	input indices
	00 04 08 12
	01 05 09 13
	02 06 10 14
	03 07 11 15

	|c0'|   |2 3 1 1| |c0|
	|c1'| = |1 2 3 1| |c1|
	|c2'|   |1 1 2 3| |c2|
	|c3'|   |3 1 1 2| |c3|
	*/
begin
	a: for col in 0 to 3 generate
		signal c0, c1, c2, c3: ubyte;
	begin
		c0 <= ubyte(input(4*col + 0));
		c1 <= ubyte(input(4*col + 1));
		c2 <= ubyte(input(4*col + 2));
		c3 <= ubyte(input(4*col + 3));

		output(4*col + 0) <= byte(times2(c0) xor times3(c1) xor        c2  xor        c3 );
		output(4*col + 1) <= byte(       c0  xor times2(c1) xor times3(c2) xor        c3 );
		output(4*col + 2) <= byte(       c0  xor        c1  xor times2(c2) xor times3(c3));
		output(4*col + 3) <= byte(times3(c0) xor        c1  xor        c2  xor times2(c3));
	end generate;
end architecture;
