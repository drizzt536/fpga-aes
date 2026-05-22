library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity EncryptBlock is
	generic (fast: boolean := false);
	port (
		clk  : in  lbit;
		key  : in  MasterKey;
		ptxt : in  AESBlock;
		ctxt : out AESBlock
	);
end entity;

architecture EncryptBlock_arch of EncryptBlock is
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
			roundKey => RoundKey(ks(0 to 15)),
			input    => ptxt,
			output   => net(13)
		);

	main_rounds: for i in 13 downto 1 generate
		enc: EncryptionRound
			generic map (fast => fast, lastRound => false)
			port map (
				clk      => clk,
				roundKey => RoundKey(ks(224 - 16*i to 239 - 16*i)),
				input    => net(i),
				output   => net(i - 1)
			);
	end generate;

	enc0: EncryptionRound
		generic map (fast => fast, lastRound => true)
		port map (
			clk      => clk,
			roundKey => RoundKey(ks(224 to 239)),
			input    => net(0),
			output   => ctxt
		);
end architecture;
