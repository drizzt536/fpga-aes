The test pictures are all simulator screenshots using Questa from before I ported the project Quartus Prime.

"clocked" summaries use RAM for the S-Boxes, and unclocked ones are fully combinational and only use lookup tables. `KeyExpansion` is fully combinational either way, so it only effects `SubBytes`.

The board DIP switches SW\[1:6\] are set to ON, ON, OFF, OFF, OFF, ON.

I couldn't find docs anywhere saying the board clock speed, but the board runs at 100MHz by default.

The UART controllers send data using UART 100kbaud 8N1. They can properly interpret data send with 8N0 as well, but nothing uses that, so it doesn't really matter. Data is transmitted using hex characters, rather than raw bytes, for better demoing. 100kbaud was chosen completely arbitrarily, and the max baud rate should only be limited by the UART-USB bridge being used, which is probably around 3Mbaud. It is also limited to be less than around 16Mbaud due to board propogation delay, but that is less restrictive than the other constraint.

The board is fairly new, so it requires a fairly new version of Gowin FPGA Designer, namely V1.9.9 for the regular version and V1.9.11.03 for the commercial version. However, other than the pin assignments and the 0.5x UART speed workaround, nothing used is specific to Gowin, so the code should work on boards and IDEs from other companies with minimal to no changes.

Depending on the firmware version, you might need to change the code in `./src/AESIO.vhd` that gets the value for `UART_WRAP`. I make it multiply `UART_FREQ` by 2, but if your debugger firmware works, then you might not need that, or I've heard that sometimes the debugger sends at 4x the frequency, so you would need to divide by 4.

I have only tested CTR, so idk if the other mode of operations work or not. ECB and CBC at least compile though. I will fix this at some point.
