library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity AddRoundKey is
	port (
		input    : in  AESBlock;
		roundKey : in  RoundKey;
		output   : out AESBlock
	);
end entity;

architecture AddRoundKey_arch of AddRoundKey is
begin
	a: for i in 0 to 15 generate
		output(i) <= input(i) xor roundKey(i);
	end generate;
end architecture;
