The test pictures are all simulator screenshots using Questa from before I ported the project Quartus Prime.

"clocked" summaries use RAM for the S-Boxes, and unclocked ones are fully combinational and only use lookup tables. `KeyExpansion` is fully combinational either way, so it only effects `SubBytes`.

The board DIP switches SW\[1:6\] are set to ON, ON, OFF, OFF, OFF, ON.

I couldn't find docs anywhere saying the board clock speed, but the board runs at 100MHz by default.

The UART controllers send data using UART 100kbaud 8N1. Data is transmitted using hex characters, rather than raw bytes, for better demoing.

The board is fairly new, so it requires a fairly new version of Gowin FPGA Designer, namely V1.9.9 for the regular version and V1.9.11.03 for the commercial version. However, other than the pin assignments and the 0.5x UART speed workaround, nothing used is specific to Gowin, so the code should work on boards and IDEs from other companies with minimal to no changes.	
