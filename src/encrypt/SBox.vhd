library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity SBox is
	port (
		clk  : in  lbit;
		addr : in  byte;
		data : out byte
	);
end entity;

architecture SBox_arch of SBox is
begin
	process (clk)
	begin
		if rising_edge(clk) then
			data <= SBoxf(addr);
		end if;
	end process;
end architecture;
