# Build the Swar Basys3 prototype.  Run from this folder:
#     vivado -mode batch -source build.tcl
# Output: out/swar_proto.bit (load now / USB stick) and out/swar_proto.bin (permanent QSPI flash image)
set part xc7a35tcpg236-1
file mkdir out
read_verilog proto_top.v
read_xdc basys3_proto.xdc
synth_design -top proto_top -part $part
opt_design
place_design
phys_opt_design
route_design
report_utilization    -file out/utilization.rpt
report_timing_summary -file out/timing.rpt
write_bitstream -force out/swar_proto.bit
write_cfgmem -force -format bin -interface SPIx4 -size 4 -loadbit "up 0x0 out/swar_proto.bit" out/swar_proto.bin
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "SWAR BUILD DONE: worst setup slack = $wns ns (must be >= 0). Files are in out/"
