library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;
use work.AESIO.all;

-- NOTE: the end-frame 1 is not required in RX. I could argue that this is a
--       feature and not a bug since it also works if you do pass the end thing.
--       all devices this is likely to communicate with will send it anyway, so
--       I don't believe this is a bug worth fixing. The other reason I don't
--       want to fix it is because this is much more convenient in the simulator.
-- NOTE: this does not pad anything. it is like giving `-nopad` to OpenSSL. If you
--       want padding, then you have to do it yourself.
-- Assume the input is a multiple of 128 bits, or gets padded externally.

entity UARTControllerECB is
	port (
		RX, clk    : in  lbit;
		TX         : out lbit;
		debug_LEDs : out std_logic_vector(1 downto 0) -- DONE & READY
	);
end entity;

architecture UARTControllerECB_arch of UARTControllerECB is
	signal clk_cycle      : natural range 0 to UART_WRAP := 0;
	signal bit_num        : natural range 0 to 10        := 0;
		-- 0 through 7 and 10 are used in the READING state
		-- 10 is the sentinel value, instead of -1 for smaller bit size.
		-- 0 through 8 are used in the WRITING state.
	signal data_ofs       : natural range 0 to 63 := 0;
		-- nibble index into the data.
		-- for key, it will be 0 to 63.
		-- for iblk and oblk, it will be only ever be 0 to 31.
	signal frame_data     : byte      := x"00";
	signal local_TX       : lbit      := '1';
	signal state          : state_t   := IDLE;
	signal mode           : mode_t    := ENCRYPT; -- write mode. encrypt by default
	signal copy_to        : copy_to_t := TO_NOWHERE;
	signal key            : MasterKey := (others => x"00");
	signal iblk           : AESBlock  := (others => x"00"); -- input block

	-- these ones are driven elsewhere combinationally
	signal oblk           : AESBlock; -- output block (multiplexed from the other two outputs)
	signal encrypt_output : AESBlock;
	signal decrypt_output : AESBlock;
begin
	ff0: process (clk)
		-- NOTE: RX and TX are not in the sensitivity list.
		--       this is a polling approach and not an "interrupt" approach.

		-- both of these are initialized later when needed.
		variable local_frame_data: byte;
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
		elsif clk_cycle = UART_WRAP then
			-- only do stuff if it is on a UART cycle.
			clk_cycle <= 0;

			case state is
				when READING =>
					if bit_num = 10 then
						-- bit num 10 just means to burn a UART cycle.
						bit_num <= 0;
					elsif bit_num = 7 then
						local_frame_data          := frame_data;
						local_frame_data(bit_num) := RX;
						frame_data(bit_num)       <= RX;

						case copy_to is
							when TO_NOWHERE =>
								-- this is a command name.
								case local_frame_data is
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
										state      <= WRITING;
										mode       <= DECRYPT;
										bit_num    <= 0;
										data_ofs   <= 0;
										frame_data <= nibble_to_hex(get_nibble(oblk, 0));
									when ascii_to_byte('E') | ascii_to_byte('e') =>
										local_TX   <= '0';
										state      <= WRITING;
										mode       <= ENCRYPT;
										bit_num    <= 0;
										data_ofs   <= 0;
										frame_data <= nibble_to_hex(get_nibble(oblk, 0));
									when ascii_to_byte('R') | ascii_to_byte('r') =>
										-- reset everything to a known initial state.
										state     <= IDLE;
										copy_to   <= TO_NOWHERE;
										mode      <= ENCRYPT;
										bit_num   <= 0; -- not required
										data_ofs  <= 0; -- not required
										clk_cycle <= 0; -- not required
										key       <= (others => x"00");
										iblk      <= (others => x"00");
									when others =>
										-- unknown state, so just go back to IDLE.
										state <= IDLE;
								end case;
							when TO_KEY =>
								state <= IDLE;
								set_nibble(key, data_ofs, hex_to_nibble(local_frame_data));

								if data_ofs = KEY_SIZE/4 - 1 then
									copy_to  <= TO_NOWHERE;
									data_ofs <= 0; -- not required
								else
									data_ofs <= data_ofs + 1;
								end if;
							when TO_BLOCK =>
								state <= IDLE;
								set_nibble(iblk, data_ofs, hex_to_nibble(local_frame_data));

								if data_ofs = FINAL_NIBBLE then
									copy_to  <= TO_NOWHERE;
									data_ofs <= 0; -- not required
								else
									data_ofs <= data_ofs + 1;
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
							state      <= IDLE;
							data_ofs   <= 0; -- not required
						else
							frame_data <= nibble_to_hex(get_nibble(oblk, data_ofs + 1));
							data_ofs   <= data_ofs + 1;
						end if;
					else
						local_TX <= frame_data(bit_num);
						bit_num  <= bit_num + 1;
					end if;
				when others =>
					-- IDLE is already taken care of, and there aren't any other states
					null;
			end case;
		else
			clk_cycle <= clk_cycle + 1;
		end if; -- if state = IDLE, clk_cycle = UART_WRAP
	end if; -- if clk rising edge
	end process;

	-- NOTE: the fast versions are not required because encryption and decryption
	--       takes 14 cycles at 100MHz, which fits in the time between requesting
	--       the data and the first data bit. there are around 11 UART cycles between
	--       the end of a TO_BLOCK, TO_KEY, or TO_IV write and the beginning of when
	--       it starts sending the data. This means the maximum allowable UART frequency
	--       with fast = false is UART_FREQ = 11 / (14/100MHz) \approx 78.5MHz
	--       That is way beyond the speed that any UART to USB bridge can give, so
	--       the fully combinational fast mode is never required. 100MHz is basically
	--       the slowest FPGA clock speed, so this should hold for all modern FPGAs.
	enc0: EncryptBlock
		port map (
			clk  => clk,
			key  => key,
			ptxt => iblk,
			ctxt => encrypt_output
		);

	dec0: DecryptBlock
		port map (
			clk  => clk,
			key  => key,
			ctxt => iblk,
			ptxt => decrypt_output
		);

	oblk <= decrypt_output when mode = DECRYPT else encrypt_output;
	TX   <= local_TX;

	with state select
	debug_LEDs <=
		"00" when WRITING,		-- not done | not ready
		"10" when FINALIZING,	-- done     | not ready
		"01" when READING,		-- not done | ready
		"11" when IDLE,			-- done     | ready
		"10" when others;		-- ECB doesn't have FINALIZING
end architecture;
