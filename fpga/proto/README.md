# Swar hardware prototype (Basys3, no custom silicon)

The Basys3's built-in XADC samples a microphone at 961.5 kS/s. A lookup table turns each sample into the 8-bit code
our SAR ADC would give (post-layout transfer curve), the FPGA oversamples and filters it to 16 kS/s, and the laptop
recognises the keyword and lights the matching LED on the board.

Simulation (`tb_proto.v`, 1 kHz test tone at −1 dBFS, 50 Hz – 7 kHz): Swar path 58.7 dB SNDR (9.5 bit) from the 8-bit
chip model at an oversampling ratio of 60; reference path 79.7 dB. Built in Vivado 2020.2 (worst setup slack
+1.12 ns, about 8 % of the LUTs); `out/` holds the bitstream and the QSPI flash image. It has been flashed to a Basys3
and streams to the laptop; the microphone bias circuit was not yet working, so there is no measured hardware SNDR.

## Wiring

| From | To |
|---|---|
| MAX4466 VCC | JXADC 3V3 (pin 6 or 12) |
| MAX4466 GND | JXADC GND (pin 5 or 11) |
| MAX4466 OUT | 1 µF capacitor, then node X (electrolytic: + side to OUT) |
| node X | 56 kΩ to 3V3, 10 kΩ to GND (sets 0.5 V), and JXADC pin 1 |
| JXADC pin 7 | GND |
| Pmod JA pin 1 (optional) | LED + 330 Ω to GND, or a 3.3 V relay module input |

The XADC input range is 0 to 1 V. Turn the trimmer on the MAX4466 until loud speech lights four of the five level
LEDs (LD11–LD15) but not the fifth.

## Build and load (any PC with Vivado)

```
vivado -mode batch -source build.tcl                    # out/swar_proto.bit and .bin, about 10 minutes
vivado -mode batch -source program.tcl                  # load until power-off
vivado -mode batch -source program.tcl -tclargs flash   # permanent (QSPI flash, jumper JP1 on QSPI)
```

`build.tcl` prints the worst setup slack; it must not be negative. Without Vivado on the demo PC, copy
`out/swar_proto.bit` to a FAT32 USB stick, set JP1 to USB and power the board with the stick plugged in.

## Run the demo

```
python3 demo/live_demo.py --bridge 8791                                         # in WSL
powershell -ExecutionPolicy Bypass -File demo\board_bridge.ps1 -Port COM5       # in Windows
```

Open http://localhost:8765 and choose "Basys3 board".

## Switches and LEDs

| Control | Function |
|---|---|
| SW0 | up = comparator-noise model off (leave down) |
| SW2:SW1 | input attenuation 0 / 6 / 12 / 18 dB |
| SW15 | up = built-in 1 kHz test tone instead of the microphone |
| BTNC | reset |
| LD0–LD9 | recognised keyword: yes no up down left right on off stop go |
| LD10 | lamp state ("on" sets it, "off" clears it), same as Pmod JA pin 1 |
| LD11–LD15 | input level |

## Files

`proto_top.v` design, `basys3_proto.xdc` pins, `gen_roms.py` makes `chip_lut.hex` / `sine.hex`, `tb_proto.v` and
`check_sim.py` simulate and measure (`iverilog -g2005 -DSIM -o tb.vvp tb_proto.v proto_top.v && vvp -n tb.vvp &&
python3 check_sim.py`, about 15 minutes).
