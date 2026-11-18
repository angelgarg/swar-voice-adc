# Load the design into a connected Basys3.  Run from this folder:
#     vivado -mode batch -source program.tcl                  (until power-off)
#     vivado -mode batch -source program.tcl -tclargs flash   (permanent: QSPI flash, JP1 on QSPI)
# If the flash step reports the wrong memory part, pass it as a second argument: older boards use
# s25fl032p-spi-x1_x2_x4, newer ones mx25l3233f-spi-x1_x2_x4.
set mode [expr {[llength $argv] > 0 ? [lindex $argv 0] : "ram"}]
set mem  [expr {[llength $argv] > 1 ? [lindex $argv 1] : "s25fl032p-spi-x1_x2_x4"}]
open_hw_manager
connect_hw_server
open_hw_target
set dev [lindex [get_hw_devices xc7a35t*] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev
if {$mode eq "flash"} {
    set cfg [create_hw_cfgmem -hw_device $dev [lindex [get_cfgmem_parts $mem] 0]]
    set_property PROGRAM.ADDRESS_RANGE {use_file} $cfg
    set_property PROGRAM.FILES [list "out/swar_proto.bin"] $cfg
    set_property PROGRAM.BLANK_CHECK 0 $cfg
    set_property PROGRAM.ERASE 1 $cfg
    set_property PROGRAM.CFG_PROGRAM 1 $cfg
    set_property PROGRAM.VERIFY 1 $cfg
    create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
    program_hw_devices $dev
    program_hw_cfgmem -hw_cfgmem $cfg
    boot_hw_device $dev
    puts "SWAR: flash programmed. Put JP1 on QSPI; the design now loads at every power-up."
} else {
    set_property PROGRAM.FILE {out/swar_proto.bit} $dev
    program_hw_devices $dev
    puts "SWAR: loaded (lost at power-off)."
}
close_hw_manager
