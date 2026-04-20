library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
use work.AES.all;

package AESIO is
	type byte_to_nibble_t	is array(0 to 255) of nibble;
	type nibble_to_byte_t	is array(0 to  15) of byte;
	type copy_to_t			is (TO_NOWHERE, TO_IV, TO_KEY, TO_BLOCK, TO_AUTH_TAG, TO_AAD);
	type copy_from_t		is (FROM_OBLK, FROM_AUTH_TAG);
	type state_t			is (IDLE, READING, WRITING, FINALIZING);
	type mode_t				is (ENCRYPT, DECRYPT);

	attribute enum_encoding : string;
	attribute enum_encoding of copy_to_t : type is "binary";
	attribute enum_encoding of state_t   : type is "binary";
	attribute enum_encoding of mode_t    : type is "binary";

	-- the clock speed was determined experimentally.
	-- I couldn't find documentation about the clock speed.
	constant  CLK_FREQ : integer := 100_000_000; -- Sipeed Tang Mega 138K is 100MHz
	constant UART_FREQ : integer :=     100_000;

	-- If I don't double the frequency, then the fuckass board debugger
	-- CPU will send the wrong frequency, and PuTTY will spam garbage.
	-- the 2x multiplier is probably specific to the firmware version (the latest one).
	constant UART_WRAP : integer := CLK_FREQ / (2*UART_FREQ) - 1;

	constant hex_to_nibble_a: byte_to_nibble_t := (
		49 => x"1", 50 => x"2", 51 => x"3", 52 => x"4",
		53 => x"5", 54 => x"6", 55 => x"7", 56 => x"8",
		57 => x"9", 65 => x"A", 66 => x"B", 67 => x"C",
		68 => x"D", 69 => x"E", 70 => x"F", others => x"0"
	);

	function ascii_to_byte(c : character) return byte;

	constant nibble_to_hex_a: nibble_to_byte_t := (
		ascii_to_byte('0'), ascii_to_byte('1'), ascii_to_byte('2'), ascii_to_byte('3'),
		ascii_to_byte('4'), ascii_to_byte('5'), ascii_to_byte('6'), ascii_to_byte('7'),
		ascii_to_byte('8'), ascii_to_byte('9'), ascii_to_byte('A'), ascii_to_byte('B'),
		ascii_to_byte('C'), ascii_to_byte('D'), ascii_to_byte('E'), ascii_to_byte('F')
	);

	component UARTControllerECB is
		port (
			RX, clk    : in  lbit;
			TX         : out lbit;
			debug_LEDs : out std_logic_vector(1 downto 0)
		);
	end component;

	component UARTControllerCBC is
		port (
			RX, clk    : in  lbit;
			TX         : out lbit;
			debug_LEDs : out std_logic_vector(1 downto 0)
		);
	end component;
	
	component UARTControllerCTR is
		port (
			RX, clk    : in  lbit;
			TX         : out lbit;
			debug_LEDs : out std_logic_vector(1 downto 0)
		);
	end component;

	component UARTControllerGCM is
		port (
			RX, clk    : in  lbit;
			TX         : out lbit;
			debug_LEDs : out std_logic_vector(1 downto 0)
		);
	end component;

	-- TODO: CCM

	-- functions and procedures that are used by modes and not the core algorithm

	function hex_to_nibble(x : byte)        return nibble;
	function nibble_to_hex(x : nibble)      return byte;
	function is_valid_hex(x : byte)         return boolean;
	function block_eq(X, Y : AESBlock)      return boolean;
	function ghash_iter(T, C, H : AESBlock) return AESBlock;

	function get_nibble(
		arr : byte_array;
		idx : integer
	) return nibble;

	procedure set_nibble(
		signal arr : inout byte_array;
		idx        : in    integer;
		value      : in    nibble
	);

	procedure set_var_nibble(
		arr   : inout byte_array;
		idx   : in    integer;
		value : in    nibble
	);

	procedure incr_iv(
		signal IV : inout AESBlock;
		split_96_32 : boolean
	);
end package;

package body AESIO is
	function ascii_to_byte(c : character) return byte is
	begin return byte(to_unsigned(character'pos(c), 8));
	end function;

	function hex_to_nibble(x : byte) return nibble is
	begin return hex_to_nibble_a( to_integer(ubyte(x)) );
	end function;

	function nibble_to_hex(x : nibble) return byte is
	begin return nibble_to_hex_a( to_integer(unsigned(x)) );
	end function;

	function is_valid_hex(x : byte) return boolean is
	begin
		for i in nibble_to_hex_a'range loop
			if x = nibble_to_hex_a(i) then
				return true;
			end if;
		end loop;
		return false;
	end function;

	function block_eq(X, Y : AESBlock) return boolean is
	begin
		iter: for i in 0 to FINAL_BLOCK loop
			if X(i) /= Y(i) then
				return false;
			end if;
		end loop;

		return true;
	end function;

	function ghash_iter(T, C, H : AESBlock) return AESBlock is
		variable X, Z, V : RawAESBlock;
		variable Zout    : AESBlock;
		variable V0      : lbit;
	begin
		-- NIST SP 800-38D section 6.3 an 6.4, p. 11-12 (PDF pages 19-20)

		-- t = 128 is the only supported value.

		-- the input is MSB-first for bytes, but LSB-first within bytes,
		-- so the conversion loops have to reverse the byte order.

		in_conv: for i in 0 to FINAL_BLOCK loop
			X(FINAL_BIT - 8*i downto FINAL_BIT - 8*i - 7) := T(i) xor C(i);
			V(FINAL_BIT - 8*i downto FINAL_BIT - 8*i - 7) := H(i);
		end loop;

		Z := (others => '0');

		proc: for i in FINAL_BIT downto 0 loop
			zproc: if X(i) = '1' then
				Z := Z xor V;
			end if;

			V0 := V(0);
			V  := V srl 1;

			vproc: if V0 = '1' then
				V(FINAL_BIT downto FINAL_BIT - 7) :=
				V(FINAL_BIT downto FINAL_BIT - 7) xor x"E1";
			end if;
		end loop;

		out_conv: for i in 0 to FINAL_BLOCK loop
			Zout(FINAL_BLOCK - i) := Z(8*i + 7 downto 8*i);
		end loop;

		return Zout;
	end function;

	function get_nibble(
		arr : byte_array;
		idx : integer
	) return nibble is
	begin
		if (idx mod 2) = 1 then
			return arr(idx / 2)(3 downto 0);
		else
			return arr(idx / 2)(7 downto 4);
		end if;
	end function;

	procedure set_nibble(
		signal arr : inout byte_array;
		idx        : in    integer;
		value      : in    nibble
	) is
	begin
		if (idx mod 2) = 1 then
			arr(idx / 2)(3 downto 0) <= value;
		else
			arr(idx / 2)(7 downto 4) <= value;
		end if;
	end procedure;

	procedure set_var_nibble(
		arr   : inout byte_array;
		idx   : in    integer;
		value : in    nibble
	) is
	begin
		if (idx mod 2) = 1 then
			arr(idx / 2)(3 downto 0) := value;
		else
			arr(idx / 2)(7 downto 4) := value;
		end if;
	end procedure;

	procedure incr_iv(
		signal IV : inout AESBlock;
		split_96_32 : boolean
	) is
		variable carry : lbit := '1';
	begin
		-- NOTE: this disregards the 96/32 split recommendation by NIST. The entire
		--       128-bit IV is the nonce. If you pass strictly less than 64 GiB at a
		--       time for a given nonce, and pass 00000001 as the lowest 32 bits of
		--       the nonce for GCM, then there will be no difference from the standard.
		--       Essentially, this is a superset of what the standard allows, and moves
		--       the responsibility to the caller to make it still secure and spec-compliant.

		-- pass true for the second argument for the recommended 96/32 split.

		iter: for i in FINAL_BLOCK downto 0 loop
			if split_96_32 and i < 12 then
				-- 32-bit increment
				exit;
			end if;

			if carry = '1' then
				if IV(i) = x"FF" then
					IV(i) <= x"00";
				else
					IV(i) <= byte(ubyte(IV(i)) + 1);
					carry := '0';
				end if;
			else
				exit;
			end if;
		end loop;

	end procedure;

end package body;
