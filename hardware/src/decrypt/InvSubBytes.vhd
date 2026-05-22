library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity InvSubBytes is
	generic (fast: boolean := false);
	port (
		clk    : in  lbit;
		input  : in  AESBlock;
		output : out AESBlock
	);
end entity;

architecture InvSubBytes_arch of InvSubBytes is
begin
	iter: for i in 0 to 15 generate
		fst: if fast generate
			output(i) <= InvSBoxf(input(i));
		else generate
			sbox0: InvSBox
				port map (
					clk  => clk,
					addr => input(i),
					data => output(i)
				);
		end generate;
	end generate;
end architecture;
