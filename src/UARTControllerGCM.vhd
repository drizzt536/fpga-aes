library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;
use work.AESIO.all;

/*
throughput calculation:
10M baud/s = 10,000,000 bits per second. Half of those are receiving and the other half
are sending, so it is actually 5,000,000 bits throughput. Only 8/10 UART bits actually
carries data, so it is 4,000,000 data bits throughput per second. But only half of
those 8 UART data bits carries information (it sends a nibble as hex rather than
sending a byte as a byte), so it is 2,000,000 useful data bits throughput per second.
A block is 128 bits, so it is 2,000,000 / 128 = 15,625 blocks throughput per second.
*/

-- NOTE: the end-frame 1 is not required in RX. I could argue that this is a
--       feature and not a bug since it also works if you do pass the end thing.
--       all devices this is likely to communicate with will send it anyway, so
--       I don't believe this is a bug worth fixing. The other reason I don't
--       want to fix it is because this is much more convenient in the simulator.
-- NOTE: this does not pad anything. it is like giving `-nopad` to OpenSSL. If you
--       want padding, then you have to do it yourself.
-- NOTE: the caller has responsibility to only send at most 2^32 blocks per nonce.
--       if they don't, then this will repeat a key+nonce+counter group.
-- TODO: enter some kind of error state if the number of blocks gets too high. probably
--       just start sending 'F' over and over when they request commands other than 'R'.

entity UARTControllerGCM is
	port (
		RX, clk    : in  lbit;
		TX         : out lbit;
		debug_LEDs : out std_logic_vector(1 downto 0)
	);
end entity;

architecture UARTControllerGCM_arch of UARTControllerGCM is
	constant ZERO_BLOCK  : AESBlock  := (others => x"00");
	constant ZERO_UQWORD : RawUQWord := (others => '0');

	signal clk_cycle     : natural range 0 to UART_WRAP := 0;
	signal bit_num       : natural range 0 to 10 := 0;
		-- 0 through 7 and 10 are used in the READING state
		-- 10 is the sentinel value, instead of -1 for smaller bit size.
		-- 0 through 8 are used in the WRITING state.
	signal data_ofs      : natural range 0 to 63 := 0;
		-- nibble index into the data.
		-- for key, it will be 0 to 63.
		-- for IV, iblk, and oblk, it will be only ever be 0 to 31.
	signal frame_data    : byte        := x"00";
	signal local_TX      : lbit        := '1';
	signal state         : state_t     := IDLE;
	signal mode          : mode_t      := ENCRYPT; -- write mode. encrypt by default
	signal copy_to       : copy_to_t   := TO_NOWHERE;
	signal copy_from     : copy_from_t := FROM_OBLK;
	signal key           : MasterKey   := (others => x"00");
	signal IV            : AESBlock    := ZERO_BLOCK;
	signal iblk          : AESBlock    := ZERO_BLOCK; -- input block
	signal T             : AESBlock    := ZERO_BLOCK;
	signal in_auth_tag   : AESBlock    := ZERO_BLOCK; -- input auth tag for checking.
	signal AAD_block     : AESBlock    := ZERO_BLOCK;
	signal C_size        : RawUQWord   := ZERO_UQWORD;
	signal AAD_size      : RawUQWord   := ZERO_UQWORD;

	-- these ones are driven elsewhere combinationally
	signal J0            : AESBlock; -- original IV with counter = 1
	signal auth_tag      : AESBlock; -- the final output
	signal T_keystream   : AESBlock; -- the keystream for the auth tag encryption.
	signal oblk          : AESBlock; -- output block (multiplexed from the other two outputs)
	signal keystream     : AESBlock; -- keystream for the encrypted block.
	signal H             : AESBlock; -- GHASH multiplier
begin
	ff0: process (clk)
		-- NOTE: RX and TX are not in the sensitivity list.
		--       this is a polling approach and not an "interrupt" approach.

		-- both of these are initialized later when needed.
		-- these exist because the updated value is needed immediately
		-- in the last round of the stuff they are doing.
		variable local_frame_data : byte;
		variable local_AAD_block  : AESBlock;
	begin
	if rising_edge(clk) then
		-- only do stuff on the rising edge

		if state = IDLE then
			-- the start of a frame can happen at any time.
			if RX = '0' then
				state     <= READING;
				bit_num   <= 10;
				clk_cycle <= UART_WRAP / 2;
			elsif clk_cycle = UART_WRAP then
				clk_cycle <= 0;
			else
				clk_cycle <= clk_cycle + 1;
			end if;
		elsif clk_cycle /= UART_WRAP then
			clk_cycle <= clk_cycle + 1;
		else
			-- only do stuff if it is on a UART cycle.
			clk_cycle <= 0;

			case state is
				when FINALIZING =>
					local_TX <= '0';

					if mode = ENCRYPT then
						frame_data <= nibble_to_hex(get_nibble(auth_tag, 0));
					else
						if block_eq(auth_tag, in_auth_tag) then
							frame_data <= ascii_to_byte('P');
						else
							frame_data <= ascii_to_byte('F');
						end if;
					end if;

					state <= WRITING;
				when READING =>
					if bit_num = 10 then
						-- bit num 10 just means to burn a UART cycle.
						bit_num <= 0;
					elsif bit_num = 7 then
						local_frame_data          := frame_data;
						local_frame_data(bit_num) := RX;
						frame_data(bit_num)       <= RX; -- not required

						case copy_to is
							when TO_NOWHERE =>
								-- this is a command name.
								case local_frame_data is
									when ascii_to_byte('I') | ascii_to_byte('i') =>
										state      <= IDLE;
										copy_to    <= TO_IV;
										C_size     <= ZERO_UQWORD;
										bit_num    <= 0; -- not required
										data_ofs   <= 0;
									when ascii_to_byte('K') | ascii_to_byte('k') =>
										state      <= IDLE;
										copy_to    <= TO_KEY;
										bit_num    <= 0; -- not required
										data_ofs   <= 0;
									when ascii_to_byte('B') | ascii_to_byte('b') =>
										state      <= IDLE;
										copy_to    <= TO_BLOCK;
										bit_num    <= 0; -- not required
										data_ofs   <= 0;
									when ascii_to_byte('D') | ascii_to_byte('d') =>
										local_TX   <= '0';
										copy_from  <= FROM_OBLK;
										state      <= WRITING;
										mode       <= DECRYPT;
										C_size     <= C_size + BLOCK_SIZE;
										bit_num    <= 0;
										data_ofs   <= 0;
										frame_data <= nibble_to_hex(get_nibble(oblk, 0));
									when ascii_to_byte('E') | ascii_to_byte('e') =>
										local_TX   <= '0';
										copy_from  <= FROM_OBLK;
										state      <= WRITING;
										mode       <= ENCRYPT;
										C_size     <= C_size + BLOCK_SIZE;
										bit_num    <= 0;
										data_ofs   <= 0;
										frame_data <= nibble_to_hex(get_nibble(oblk, 0));
									when ascii_to_byte('A') | ascii_to_byte('a') =>
										state      <= IDLE;
										copy_to    <= TO_AAD;
										AAD_size   <= AAD_size + BLOCK_SIZE;
										bit_num    <= 0;
										data_ofs   <= 0;
									when ascii_to_byte('F') | ascii_to_byte('f') =>
										-- finalize the authentication stuff
										T <= ghash_iter(
											T,
											WrapRawAESBlock(
												bit_array(AAD_size) & bit_array(C_size)
											),
											H
										);

										if mode = ENCRYPT then
											-- send the auth tag after encryption
											copy_from  <= FROM_AUTH_TAG;
											state      <= FINALIZING;
											bit_num    <= 0;
											data_ofs   <= 0;
										else
											-- send 'P' for PASS or 'F' for FAIL.
											-- It never actually reads from anywhere since
											-- it is set to be the final nibble
											state     <= FINALIZING;
											bit_num   <= 0;
											data_ofs  <= FINAL_NIBBLE;
										end if;
									when ascii_to_byte('T') | ascii_to_byte('t') =>
										-- read the auth tag from the caller
										state       <= IDLE;
										copy_to     <= TO_AUTH_TAG;
										bit_num     <= 0; -- not required
										data_ofs    <= 0;
									when ascii_to_byte('R') | ascii_to_byte('r') =>
										-- reset everything to a known initial state.
										state       <= IDLE;
										copy_to     <= TO_NOWHERE;
										mode        <= ENCRYPT;
										bit_num     <= 0; -- not required
										data_ofs    <= 0; -- not required
										clk_cycle   <= 0; -- not required
										C_size      <= ZERO_UQWORD;
										AAD_size    <= ZERO_UQWORD;
										in_auth_tag <= ZERO_BLOCK;
										AAD_block   <= ZERO_BLOCK;
										key         <= ZERO_BLOCK & ZERO_BLOCK;
										iblk        <= ZERO_BLOCK;
										IV          <= ZERO_BLOCK;
									when others =>
										-- unknown state, so just go back to IDLE.
										state <= IDLE;
								end case;
							when TO_IV =>
								state <= IDLE;

								if is_valid_hex(local_frame_data) then
									set_nibble(IV, data_ofs, hex_to_nibble(local_frame_data));

									if data_ofs = GCM_IV_SIZE/4 - 1 then
										IV(12)   <= x"00";
										IV(13)   <= x"00";
										IV(14)   <= x"00";
										IV(15)   <= x"01";
										copy_to  <= TO_NOWHERE;
										data_ofs <= 0; -- not required
									else
										data_ofs <= data_ofs + 1;
									end if;
								end if;
							when TO_KEY =>
								state <= IDLE;

								if is_valid_hex(local_frame_data) then
									set_nibble(key, data_ofs, hex_to_nibble(local_frame_data));

									if data_ofs = KEY_SIZE/4 - 1 then
										copy_to  <= TO_NOWHERE;
										data_ofs <= 0; -- not required
									else
										data_ofs <= data_ofs + 1;
									end if;
								end if;
							when TO_BLOCK =>
								state <= IDLE;

								if is_valid_hex(local_frame_data) then
									set_nibble(iblk, data_ofs, hex_to_nibble(local_frame_data));

									if data_ofs = FINAL_NIBBLE then
										copy_to  <= TO_NOWHERE;
										data_ofs <= 0; -- not required
									else
										data_ofs <= data_ofs + 1;
									end if;
								end if;
							when TO_AAD =>
								state <= IDLE;

								if is_valid_hex(local_frame_data) then
									set_nibble(
										AAD_block,
										data_ofs,
										hex_to_nibble(local_frame_data)
									);

									if data_ofs = FINAL_NIBBLE then
										local_AAD_block := AAD_block;
										set_var_nibble(
											local_AAD_block,
											data_ofs,
											hex_to_nibble(local_frame_data)
										);

										T        <= ghash_iter(T, local_AAD_block, H);
										copy_to  <= TO_NOWHERE;
										data_ofs <= 0; -- not required
									else
										data_ofs <= data_ofs + 1;
									end if;
								end if;
							when TO_AUTH_TAG =>
								state <= IDLE;

								if is_valid_hex(local_frame_data) then
									set_nibble(
										in_auth_tag,
										data_ofs,
										hex_to_nibble(local_frame_data)
									);

									if data_ofs = FINAL_NIBBLE then
										copy_to  <= TO_NOWHERE;
										data_ofs <= 0; -- not required
									else
										data_ofs <= data_ofs + 1;
									end if;
								end if;
							when others =>
								-- there are no other locations
								null;
						end case;
					else
						frame_data(bit_num) <= RX;
						bit_num             <= bit_num + 1;
					end if;
				when WRITING =>
					if bit_num = 9 then
						local_TX <= '0';
						bit_num  <= 0;
					elsif bit_num = 8 then
						local_TX <= '1';
						bit_num  <= 9; -- only matters if it isn't the final nibble

						if data_ofs = FINAL_NIBBLE then
							state    <= IDLE;
							data_ofs <= 0; -- not required

							if copy_from = FROM_OBLK then
								incr_iv(IV, true);

								-- always use the ciphertext regardless of the direction.
								if mode = ENCRYPT then
									T <= ghash_iter(T, oblk, H);
								else
									T <= ghash_iter(T, iblk, H);
								end if;
							end if;
						else
							-- NOTE: FROM_VALIDATION never gets here
							if copy_from = FROM_OBLK then
								frame_data <= nibble_to_hex(
									get_nibble(oblk, data_ofs + 1)
								);
							else -- FROM_AUTH_TAG
								frame_data <= nibble_to_hex(
									get_nibble(auth_tag, data_ofs + 1)
								);
							end if;

							data_ofs <= data_ofs + 1;
						end if;
					else
						local_TX <= frame_data(bit_num);
						bit_num  <= bit_num + 1;
					end if;
				when others =>
					-- IDLE is already taken care of, and there aren't any other states
					null;
			end case;
		end if; -- if state = IDLE, clk_cycle /= UART_WRAP
	end if; -- if clk rising edge
	end process ff0;

	TX <= local_TX;

	J0loop: for i in 0 to FINAL_BLOCK - 4 generate
		J0(i) <= IV(i);
	end generate;

	J0(12) <= x"00";
	J0(13) <= x"00";
	J0(14) <= x"00";
	J0(15) <= x"01";

	enc2: EncryptBlock
		port map (
			clk  => clk,
			key  => key,
			ptxt => J0,
			ctxt => T_keystream
		);

	gen_auth_tag : for i in 0 to 15 generate
		auth_tag(i) <= T(i) xor T_keystream(i);
	end generate;

	enc1: EncryptBlock
		port map (
			clk  => clk,
			key  => key,
			ptxt => ZERO_BLOCK,
			ctxt => H
		);

	-- NOTE: the fast versions are not required for a similar reason as for the other modes.
	--       however, the auth tag encryption step has to happen in one UART cycle.
	--       So the UART speed can't be any faster than 1 / (14/100MHz) \approx 7.1MHz
	--       this assumes a 100MHz FPGA clock, which may or may not be the case.
	enc0: EncryptBlock
		port map (
			clk  => clk,
			key  => key,
			ptxt => IV,
			ctxt => keystream
		);

	oblkloop: for i in 0 to FINAL_BLOCK generate
		oblk(i) <= iblk(i) xor keystream(i);
	end generate;

	-- interpret the lights as the inverse of what they show as
	debug_LEDs <=
		"11" when state = WRITING		else	-- not done, not ready
		"01" when state = FINALIZING	else	-- done    , not ready
		"10" when copy_to /= TO_NOWHERE	else	-- not done, ready (READING)
		"00" when state = IDLE			else	-- done, ready
		"00";									-- idk, just say its idle I guess.
end architecture;
