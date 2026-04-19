//Copyright (C)2014-2026 GOWIN Semiconductor Corporation.
//All rights reserved.
//File Title: Timing Constraints file
//Tool Version: V1.9.12.02 (64-bit) 
//Created Time: 2026-04-18 23:31:24
create_clock -name clk -period 10 -waveform {0 5} [get_ports {clk}]
