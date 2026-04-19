library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity InvSBox is
	port (
		clk  : in  lbit;
		addr : in  byte;
		data : out byte
	);
end entity;

architecture InvSBox_arch of InvSBox is
begin
	process (clk)
	begin
		if rising_edge(clk) then
			data <= InvSBoxf(addr);
		end if;
	end process;
end architecture;
