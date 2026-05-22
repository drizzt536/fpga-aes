library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity EncryptionRound is
	generic (
		fast      : boolean := false;
		lastRound : boolean := false
	);
	port (
		clk      : in  lbit;
		roundKey : in  RoundKey;
		input    : in  AESBlock;
		output   : out AESBlock
	);
end entity;

architecture EncryptionRound_arch of EncryptionRound is
	signal net2, net1, net0: AESBlock;
begin
	sb: SubBytes
		generic map (fast => fast)
		port map (clk => clk, input => input, output => net2);

	sr: ShiftRows port map (input => net2, output => net1);

	lr: if lastRound generate
		net0 <= net1;
	else generate
		mc: MixColumns port map (input => net1, output => net0);
	end generate;

	ark: AddRoundKey port map (
		input    => net0,
		output   => output,
		roundKey => roundKey
	);
end architecture;
