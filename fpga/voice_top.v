// Voice / keyword-spotting front end on a Basys3 (Artix-7, 100 MHz) for the Rev3.2 SCL SAR ADC.
// ADC (2 MS/s, 8-bit) -> CIC 4th order /25 (80 kS/s) -> 127-tap FIR /5 (16 kS/s, 0-7 kHz) -> UART 921600 baud
// (USB-UART to the PC and a Pmod pin to the ESP32-S3). Filter design: design/rev3.2/scripts/voice_model.py.
// ADC pins are 5 V: inputs through a 74LVC245 at 3.3 V, CLK / RST_N through a 74HCT buffer at 5 V.
// UART frame per 16 kS/s sample: 14-bit two's complement s -> byte 1 = {1, s[13:7]}, byte 2 = {0, s[6:0]}.
`timescale 1ns/1ps
module voice_top (
    input  wire       clk,          // 100 MHz
    input  wire       btnC,         // reset (active high)
    output wire       adc_clk,      // 50 MHz to the ADC CLK pad (via 74HCT)
    output reg        adc_rst_n,    // to the ADC RST_N pad (via 74HCT)
    input  wire [7:0] adc_dout,     // ADC DOUT[7:0] (via 74LVC245)
    input  wire       adc_eoc,      // ADC EOC
    input  wire       adc_dvalid,   // ADC DVALID
    output wire       uart_tx,      // USB-UART (PC)
    output wire       uart_esp,     // same stream to the ESP32-S3 RX
    output wire [15:0] led
);
    // ---------------- reset and ADC clock
    reg [19:0] por = 0; reg rst = 1;
    always @(posedge clk) begin
        if (btnC) por <= 0; else if (!por[19]) por <= por + 1;
        rst <= !por[19];
        adc_rst_n <= por[19];                       // ADC reset released ~10 ms after configuration / button
    end
    reg ck2 = 0;
    always @(posedge clk) ck2 <= ~ck2;              // 50 MHz
    assign adc_clk = ck2;

    // ---------------- ADC capture: EOC synchronised, DOUT latched 150 ns later (DOUT changes ~38 ns after EOC
    // and then holds for the whole next conversion, ~460 ns)
    wire        s_vld; wire [7:0] s_code;
    adc_if u_if (.clk(clk), .rst(rst), .eoc(adc_eoc), .dout(adc_dout), .vld(s_vld), .code(s_code));

    // ---------------- decimation
    wire        c_vld; wire signed [18:0] c_out;
    cic4_dec25 u_cic (.clk(clk), .rst(rst), .in_vld(s_vld), .code(s_code), .out_vld(c_vld), .out(c_out));
    wire        f_vld; wire signed [13:0] f_out;
    fir_dec5 u_fir (.clk(clk), .rst(rst), .in_vld(c_vld), .x(c_out), .out_vld(f_vld), .y(f_out));

    // ---------------- UART
    uart_stream u_tx (.clk(clk), .rst(rst), .vld(f_vld), .s(f_out), .tx(uart_tx));
    assign uart_esp = uart_tx;

    reg [23:0] hb = 0; always @(posedge clk) if (f_vld) hb <= hb + 1;
    assign led = {s_code, 5'b0, adc_dvalid, hb[13], adc_rst_n};
endmodule

module adc_if (input wire clk, rst, eoc, input wire [7:0] dout, output reg vld, output reg [7:0] code);
    reg [2:0] es; reg [4:0] cnt; reg arm;
    always @(posedge clk) begin
        es <= {es[1:0], eoc}; vld <= 1'b0;
        if (rst) begin arm <= 0; cnt <= 0; code <= 8'h80; end
        else if (es[2:1] == 2'b01) begin arm <= 1; cnt <= 0; end        // EOC rising (synchronised)
        else if (arm) begin
            cnt <= cnt + 1;
            if (cnt == 5'd15) begin code <= dout; vld <= 1'b1; arm <= 0; end
        end
    end
endmodule

// 4th-order CIC, decimation 25, input = code - 128 (9 bits signed). Register growth 4*log2(25) = 18.6 -> 29 bits,
// wrap-around arithmetic (exact). Output = CIC sum >>> 9 (CIC gain 25^4 = 390625 -> x * 763), 19 bits signed.
module cic4_dec25 (input wire clk, rst, in_vld, input wire [7:0] code, output reg out_vld, output reg signed [18:0] out);
    localparam W = 29;
    reg signed [W-1:0] i1, i2, i3, i4, d1, d2, d3, c1, c2, c3, c4; reg [4:0] n;
    wire signed [W-1:0] x = {{(W-9){1'b0}}, 1'b0, code} - 29'sd128;
    always @(posedge clk) begin
        out_vld <= 1'b0;
        if (rst) begin i1 <= 0; i2 <= 0; i3 <= 0; i4 <= 0; d1 <= 0; d2 <= 0; d3 <= 0; c4 <= 0; n <= 0; end
        else if (in_vld) begin
            i1 <= i1 + x; i2 <= i2 + i1 + x; i3 <= i3 + i2 + i1 + x; i4 <= i4 + i3 + i2 + i1 + x;   // cascaded, same-cycle
            n <= (n == 5'd24) ? 5'd0 : n + 1;
            if (n == 5'd24) begin                     // decimate: combs on the new i4
                c1 = (i4 + i3 + i2 + i1 + x) - c4;    // comb 1 delay = previous decimated i4 (c4 holds it)
                c2 = c1 - d1; c3 = c2 - d2; out <= (c3 - d3) >>> 9;
                d1 <= c1; d2 <= c2; d3 <= c3; c4 <= i4 + i3 + i2 + i1 + x; out_vld <= 1'b1;
            end
        end
    end
endmodule

// 127-tap FIR, decimation 5: circular buffer of 128 inputs (80 kS/s), one MAC per clock, 127 cycles per output.
// Coefficients Q1.17 (unity DC gain, fir_coef.hex). Output scaled to 14 bits: y = acc * 2749 >> (17 + 16).
module fir_dec5 (input wire clk, rst, in_vld, input wire signed [18:0] x, output reg out_vld, output reg signed [13:0] y);
    reg signed [17:0] coef [0:126]; initial $readmemh("fir_coef.hex", coef);
    reg signed [18:0] buf_ [0:127]; reg [6:0] wp, rp; reg [6:0] k; reg [2:0] ph; reg busy;
    reg signed [43:0] acc; reg signed [56:0] sc;
    integer i; initial for (i = 0; i < 128; i = i + 1) buf_[i] = 0;
    always @(posedge clk) begin
        out_vld <= 1'b0;
        if (rst) begin wp <= 0; ph <= 0; busy <= 0; acc <= 0; end
        else begin
            if (in_vld) begin
                buf_[wp] <= x; wp <= wp + 1;
                ph <= (ph == 3'd4) ? 3'd0 : ph + 1;
                if (ph == 3'd4) begin busy <= 1; k <= 0; rp <= wp; acc <= 0; end   // newest sample at wp
            end
            if (busy) begin
                acc <= acc + buf_[rp] * coef[k];      // tap k multiplies x[n-k]
                rp <= rp - 1; k <= k + 1;
                if (k == 7'd126) begin busy <= 0; sc = (acc + buf_[rp] * coef[k]) * 57'sd2749; y <= sc >>> 33; out_vld <= 1'b1; end
            end
        end
    end
endmodule

// UART 8N1 at 100 MHz / 109 = 917.4 kbaud (0.45 % from 921600), two bytes per sample from a small FIFO
module uart_stream (input wire clk, rst, vld, input wire signed [13:0] s, output reg tx);
    reg [7:0] fifo [0:15]; reg [3:0] wp, rp; reg [9:0] sh; reg [3:0] nb; reg [6:0] div; reg busy;
    always @(posedge clk) begin
        if (rst) begin wp <= 0; rp <= 0; busy <= 0; tx <= 1'b1; div <= 0; end
        else begin
            if (vld) begin fifo[wp] <= {1'b1, s[13:7]}; fifo[wp + 1] <= {1'b0, s[6:0]}; wp <= wp + 2; end
            if (!busy && rp != wp) begin sh <= {1'b1, fifo[rp], 1'b0}; rp <= rp + 1; busy <= 1; nb <= 0; div <= 0; end
            else if (busy) begin
                if (div == 7'd108) begin
                    div <= 0; tx <= sh[0]; sh <= {1'b1, sh[9:1]}; nb <= nb + 1;
                    if (nb == 4'd10) busy <= 0;
                end else div <= div + 1;
            end
        end
    end
endmodule
