// Testbench for proto_top: built-in test tone (or the stand-in XADC triangle), UART bytes -> tb_uart.txt,
// one keyword byte sent back to check the LED / lamp logic.   iverilog -DSIM [-DSW=16'h8000] [-DTSIM=<ns>]
`ifndef TSIM
`define TSIM 170000000
`endif
`ifndef SW
`define SW 16'h8000
`endif
`timescale 1ns/1ps
module tb_proto;
    reg clk = 0; always #5 clk = ~clk;
    reg rx = 1; wire tx, lamp; wire [15:0] led;
    proto_top dut (.clk(clk), .btnC(1'b0), .sw(`SW), .vauxp6(1'b0), .vauxn6(1'b0),
                   .uart_rx(rx), .uart_tx(tx), .lamp(lamp), .led(led));
    integer f, k, nbytes = 0; reg [7:0] b;
    initial f = $fopen("tb_uart.txt", "w");
    always @(negedge tx) begin
        #(1090 * 1.5); b[0] = tx;
        for (k = 1; k < 8; k = k + 1) begin #1090; b[k] = tx; end
        $fdisplay(f, "%02x", b); nbytes = nbytes + 1;
        #1090;
    end
    task send(input [7:0] c); integer j; begin
        rx = 0; #1085;                                   // 921600 baud from the PC side (1085 ns per bit)
        for (j = 0; j < 8; j = j + 1) begin rx = c[j]; #1085; end
        rx = 1; #1085;
    end endtask
    initial begin
        #20000000; send("6"); #200000;
        $display("after 'on' : led[9:0]=%b lamp=%b", led[9:0], lamp);
        send("7"); #200000;
        $display("after 'off': led[9:0]=%b lamp=%b", led[9:0], lamp);
        send("x"); send("2"); #200000;
        $display("after 'up' : led[9:0]=%b lamp=%b", led[9:0], lamp);
    end
    initial begin
        #(`TSIM); $display("TB_DONE: %0d uart bytes, level leds %b", nbytes, led[15:11]); $fclose(f); $finish;
    end
endmodule
