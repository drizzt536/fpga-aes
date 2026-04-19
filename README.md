The test pictures are all simulator screenshots using Questa from before I ported the project Quartus Prime.

"clocked" summaries use RAM for the S-Boxes, and unclocked ones are fully combinational and only use lookup tables. `KeyExpansion` is fully combinational either way, so it only effects `SubBytes`.

The board DIP switches SW\[1:6\] are set to ON, ON, OFF, OFF, OFF, ON.

I couldn't find docs anywhere saying the board clock speed, but the board runs at 100MHz by default.

The UART controllers send data using UART 100kbaud 8N1. Data is transmitted using hex characters, rather than raw bytes, for better demoing.
