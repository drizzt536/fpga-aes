library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity DecryptBlock is
	generic (fast: boolean := false);
	port (
		clk  : in  lbit;
		key  : in  MasterKey;
		ctxt : in  AESBlock;
		ptxt : out AESBlock
	);
end entity;

architecture DecryptBlock_arch of DecryptBlock is
	signal ks: KeySchedule;
	signal net: RoundNets;
begin
	ke0: KeyExpansion
		port map (
			key => key,
			ks  => ks
		);

	ark15: AddRoundKey
		port map (
			roundKey => RoundKey(ks(224 to 239)),
			input    => ctxt,
			output   => net(13)
		);

	main_rounds: for i in 13 downto 1 generate
		dec: DecryptionRound
			generic map (fast => fast, lastRound => false)
			port map (
				clk      => clk,
				roundKey => RoundKey(ks(16*i to 16*i + 15)),
				input    => net(i),
				output   => net(i - 1)
			);
	end generate;

	dec0: DecryptionRound
		generic map (fast => fast, lastRound => true)
		port map (
			clk      => clk,
			roundKey => RoundKey(ks(0 to 15)),
			input    => net(0),
			output   => ptxt
		);
end architecture;
