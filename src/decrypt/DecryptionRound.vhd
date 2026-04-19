library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

entity DecryptionRound is
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

architecture DecryptionRound_arch of DecryptionRound is
	signal net2, net1, net0: AESBlock;
begin
	isr: InvShiftRows port map (input => input, output => net2);

	isb: InvSubBytes
		generic map (fast => fast)
		port map (clk => clk, input => net2, output => net1);

	ark: AddRoundKey port map (
		input    => net1,
		output   => net0,
		roundKey => roundKey
	);

	lr: if lastRound generate
		output <= net0;
	else generate
		imc: InvMixColumns port map (input => net0, output => output);
	end generate;
end architecture;
