`ifndef TSIM
`define TSIM 40000000   // ns: all 80000 codes of codes.hex at 2 MS/s
`endif
// Testbench: behavioural ADC interface (25 CLK cycles per conversion, EOC 1 cycle, DOUT 38 ns after EOC) fed with
// codes.hex (post-layout ADC model output, voice_model.py), UART receiver -> fpga_out.txt (one 14-bit sample per line)
`timescale 1ns/1ps
module tb_voice;
    reg clk = 0; always #5 clk = ~clk;
    reg btn = 0; wire adc_clk, adc_rst_n, tx, tx2; wire [15:0] led;
    reg [7:0] dout = 8'h80; reg eoc = 0;
    voice_top dut (.clk(clk), .btnC(btn), .adc_clk(adc_clk), .adc_rst_n(adc_rst_n), .adc_dout(dout), .adc_eoc(eoc),
                   .adc_dvalid(1'b1), .uart_tx(tx), .uart_esp(tx2), .led(led));
    reg [7:0] codes [0:200000]; integer nc, ci = 0, cyc = 0;
    initial begin $readmemh("codes.hex", codes); end
    always @(posedge adc_clk) if (adc_rst_n) begin
        cyc <= (cyc == 24) ? 0 : cyc + 1;
        eoc <= (cyc == 23);
        if (cyc == 23) begin #38 dout <= codes[ci]; ci <= ci + 1; end
    end
    // UART receiver (917.4 kbaud = 109 clk per bit)
    integer f, nbytes = 0, nsamp = 0; reg [7:0] b; reg [7:0] hi; integer k; reg signed [13:0] s;
    initial f = $fopen("fpga_out.txt", "w");
    always @(negedge tx) if (adc_rst_n) begin
        #(109 * 10 * 1.5); b[0] = tx;
        for (k = 1; k < 8; k = k + 1) begin #(109 * 10); b[k] = tx; end
        if (b[7]) hi = b; else begin s = {hi[6:0], b[6:0]}; $fdisplay(f, "%0d", s); nsamp = nsamp + 1; end
        #(109 * 10 * 1.0);
    end
    initial begin
        #(`TSIM);
        $display("TB_DONE: %0d ADC codes used, %0d output samples", ci, nsamp); $fclose(f); $finish;
    end
endmodule
