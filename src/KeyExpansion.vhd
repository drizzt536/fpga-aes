library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity KeyExpansion is
	port (
		key : in  MasterKey;
		ks  : out KeySchedule
	);
end entity;

architecture KeyExpansion_arch of KeyExpansion is
begin
	-- `key` is the AES master key.
	a: for i in 0 to 31 generate
		ks(i) <= key(i);
	end generate;

	b: for i in 8 to 59 generate
		signal tmp1, tmp2: Word;
	begin
		tmp1(0) <= ks(4*(i - 1) + 0);
		tmp1(1) <= ks(4*(i - 1) + 1);
		tmp1(2) <= ks(4*(i - 1) + 2);
		tmp1(3) <= ks(4*(i - 1) + 3);

		tmp2(0) <=	SBoxf(tmp1(1)) xor Rcon(i / 8) when (i mod 8) = 0 else
					SBoxf(tmp1(0)) when (i mod 8) = 4 else
					tmp1(0);
		tmp2(1) <=	SBoxf(tmp1(2)) when (i mod 8) = 0 else
					SBoxf(tmp1(1)) when (i mod 8) = 4 else tmp1(1);
		tmp2(2) <=	SBoxf(tmp1(3)) when (i mod 8) = 0 else
					SBoxf(tmp1(2)) when (i mod 8) = 4 else tmp1(2);
		tmp2(3) <=	SBoxf(tmp1(0)) when (i mod 8) = 0 else
					SBoxf(tmp1(3)) when (i mod 8) = 4 else tmp1(3);

		ks(4*i + 0) <= ks(4*(i - 8) + 0) xor tmp2(0);
		ks(4*i + 1) <= ks(4*(i - 8) + 1) xor tmp2(1);
		ks(4*i + 2) <= ks(4*(i - 8) + 2) xor tmp2(2);
		ks(4*i + 3) <= ks(4*(i - 8) + 3) xor tmp2(3);
	end generate;
end architecture;
