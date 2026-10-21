# Rev3.2 SAR ADC: summary (post-layout, verified 2026-10-21)

| Parameter | Value |
|---|---|
| Process | SCL C1D 1.2 µm CMOS, 2 metal layers |
| Architecture | 8-bit SAR, R-2R DAC (RNP resistors), dual StrongARM comparator (PMOS < code 64, NMOS ≥ 64), external S/H |
| Resolution | 8 bit |
| Supply voltage | 5.0 V nominal (4.5–5.5 V verified); separate AVDD / DVDD |
| Reference | VREFP = VDD, VREFN = 1.0 V (external) |
| Input range (FSR) | 1.0 V to VDD: 4.0 V at 5 V (3.5 V at 4.5 V, 4.5 V at 5.5 V) |
| LSB | 15.625 mV at 5 V (13.67 mV at 4.5 V, 17.58 mV at 5.5 V) |
| Clock / sample rate | 25 CLK cycles per conversion: **10 MHz → 400 kS/s** (selected); 50 MHz → 2 MS/s |
| Die size | 4 × 4 mm = 16 mm² (SCL standard pad frame, 40 slots) |
| ADC area (blocks) | 4.13 mm²: analog 1.30 mm² (DAC 0.94, bit drivers 0.23, comparators 0.11), digital 2.63 mm², decaps 0.20 mm² |
| Power (core, TT 5 V) | **13.9 mW at 400 kS/s** (DVDD 10.5, AVDD 0.3, reference 3.1 mW); 56.8 mW at 2 MS/s |
| Output pads | + ~3 mW at 400 kS/s, ~12 mW at 2 MS/s (15 pF board loads, estimate) |
| ENOB / SNDR | 7.79–7.94 bit / 48.7–49.6 dB (242 kHz sine, −0.5 dBFS, TT/SS/FF); 7.81 bit with pads + bond wires |
| SFDR / THD | 61.7–63.0 dB / −58.8 to −63.8 dBc |
| DNL / INL (static DAC) | TT: −0.20..+0.21 / 0.40 LSB; worst (FF): −0.25..+0.27 / 0.53 LSB |
| Missing codes / monotonic | none / yes (all corners, full-loop) |
| Comparator offset | ≤ 0.49 LSB (systematic, post-layout, TT/SS/FF) |
| FoM (Walden) | 152 pJ/step at 400 kS/s (124 pJ/step at 2 MS/s) |
| Outputs | 8-bit parallel DOUT[7:0] + DVALID + EOC, SAMPLE (S/H control), SPI (SCLK/SDO/CS_N) |
| Pads | 23 I/O (5 analog, 2 shield, 2 digital in, 14 out) + 8 digital power (4 DVDD, 4 DVSS); 9 slots unused |
| Corners verified | TT 27 °C, SS 4.5 V 85 °C, FF 5.5 V 0 °C, SF/FS, resistor cross corners |
| Physical checks | DRC 0, LVS match, antenna clean (KLayout, SCL decks) |
| Simulators | ngspice-45 and Cadence Spectre 20.1 (identical codes, 112/112) |

Sources: POSTLAYOUT_RC_SUMMARY.txt, POWER_SPECTRE_POSTLAYOUT.txt, dac_v4_static/, comparator_offset/OFFSET_V4_SUMMARY.txt,
spectre/clk10/, FULLCHIP_DRC_LVS.txt.
