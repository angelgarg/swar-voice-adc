// Swar hardware prototype on a Basys3 (Artix-7 35T, 100 MHz). No custom silicon needed.
//
//   mic module -> JXADC pin 1 (0..1 V) -> XADC, 12 bit, 961.5 kS/s
//        |-> reference path : 12-bit samples ----------------------------> CIC /12 -> FIR /5 -> 16.03 kS/s
//        `-> Swar path      : chip_lut (the 8-bit code our SAR ADC gives,
//                             post-layout levels) + comparator noise ----> CIC /12 -> FIR /5 -> 16.03 kS/s
//   both streams -> UART 917.4 kbaud (USB cable) -> laptop: keyword CNN -> one byte back -> keyword LED / lamp
//
// The XADC stands in for the analog front end; the lookup table makes it behave like our chip (same transfer curve,
// 16 XADC steps per chip LSB). Oversampling ratio is 60 here (the chip plan is 125 at 2 MS/s).
//
// Switches (all down = normal use):
//   sw[0]    1 = comparator-noise model OFF (default on: sigma 0.35 chip LSB, as in model/voice_model.py)
//   sw[2:1]  input attenuation 0 / 6 / 12 / 18 dB (a repeatable "quiet talker")
//   sw[15]   1 = built-in 1 kHz test tone at -1 dBFS instead of the microphone
// LEDs: [9:0] keyword from the laptop (yes no up down left right on off stop go), [10] lamp, [15:11] input level.
// UART frame, one per output sample: {1,ref[13:7]} {0,ref[6:0]} {0,swar[13:7]} {0,swar[6:0]}  (14-bit two's complement)
// UART in: ASCII '0'..'9' = keyword index; "on" (6) sets the lamp output, "off" (7) clears it.
`timescale 1ns/1ps
module proto_top (
    input  wire        clk,        // 100 MHz
    input  wire        btnC,       // reset
    input  wire [15:0] sw,
    input  wire        vauxp6,     // JXADC pin 1: microphone, 0..1 V
    input  wire        vauxn6,     // JXADC pin 7: ground
    input  wire        uart_rx,
    output wire        uart_tx,
    output reg         lamp,       // Pmod JA1: relay / lamp
    output wire [15:0] led
);
    // ------------------------------------------------------------ reset
    reg [19:0] por = 0; reg rst = 1;
    always @(posedge clk) begin
        if (btnC) por <= 0; else if (!por[19]) por <= por + 1;
        rst <= !por[19];
    end
    reg [15:0] sw1, sws;
    always @(posedge clk) begin sw1 <= sw; sws <= sw1; end

    // ------------------------------------------------------------ XADC, VAUX6, continuous, ADCCLK = clk / 4
    wire [15:0] xdo; wire xdrdy, xeoc;
`ifdef SIM
    xadc_sim u_xadc (.clk(clk), .eoc(xeoc), .den(xeoc), .dout(xdo), .drdy(xdrdy));
`else
    XADC #(
        .INIT_40(16'h0016),        // no averaging, unipolar, continuous sampling, channel VAUX6
        .INIT_41(16'h310F),        // single-channel mode, alarms off
        .INIT_42(16'h0400)         // ADCCLK = DCLK / 4 = 25 MHz -> 25 MHz / 26 = 961.5 kS/s
    ) u_xadc (
        .DCLK(clk), .DEN(xeoc), .DADDR(7'h16), .DWE(1'b0), .DI(16'h0000), .DO(xdo), .DRDY(xdrdy),
        .RESET(1'b0), .CONVST(1'b0), .CONVSTCLK(1'b0), .VP(1'b0), .VN(1'b0),
        .VAUXP({9'b0, vauxp6, 6'b0}), .VAUXN({9'b0, vauxn6, 6'b0}),
        .EOC(xeoc), .EOS(), .BUSY(), .CHANNEL(), .ALM(), .OT(), .MUXADDR(),
        .JTAGBUSY(), .JTAGLOCKED(), .JTAGMODIFIED()
    );
`endif

    // ------------------------------------------------------------ test tone: 1000 Hz at 961.538 kS/s
    reg [11:0] sine_rom [0:4095]; initial $readmemh("sine.hex", sine_rom);
    reg [31:0] ph = 0; reg [11:0] sine_q = 12'd2048;
    always @(posedge clk) begin
        if (xdrdy) ph <= ph + 32'd4466766;
        sine_q <= sine_rom[ph[31:20]];
    end

    // ------------------------------------------------------------ comparator-noise model
    // 63-bit LFSR; six 3-bit fields summed: mean 21, sigma 5.6 XADC steps = 0.35 chip LSB
    reg [62:0] lfsr = 63'h1234_5678_9ABC_DEF1;
    always @(posedge clk) lfsr <= {lfsr[61:0], lfsr[62] ^ lfsr[61]};
    wire [5:0] nsum = lfsr[2:0] + lfsr[5:3] + lfsr[8:6] + lfsr[11:9] + lfsr[14:12] + lfsr[17:15];
    wire signed [6:0] noise = sws[0] ? 7'sd0 : $signed({1'b0, nsum}) - 7'sd21;

    // ------------------------------------------------------------ sample pipeline
    reg [7:0] chip_lut [0:4095]; initial $readmemh("chip_lut.hex", chip_lut);
    reg        v0, v1, v2, v3;
    reg [11:0] x0;                 // raw 12-bit sample (0 .. 4095)
    reg signed [12:0] xa;          // centred and attenuated
    reg [11:0] xn;                 // + noise, back to 0 .. 4095
    reg [7:0]  code;               // what the chip would output
    wire signed [12:0] xc  = $signed({1'b0, x0}) - 13'sd2048;
    wire signed [14:0] xnw = xa + 15'sd2048 + noise;
    always @(posedge clk) begin
        v0 <= xdrdy; v1 <= v0; v2 <= v1; v3 <= v2;
        if (xdrdy) x0 <= sws[15] ? sine_q : xdo[15:4];
        if (v0) xa <= xc >>> sws[2:1];
        if (v1) xn <= (xnw < 15'sd0) ? 12'd0 : (xnw > 15'sd4095) ? 12'd4095 : xnw[11:0];
        code <= chip_lut[xn];
    end

    // ------------------------------------------------------------ decimation, two identical chains
    wire r_cv, s_cv, r_fv, s_fv;
    wire signed [18:0] r_c, s_c; wire signed [13:0] r_y, s_y;
    wire signed [12:0] code_c = $signed({5'b0, code}) - 13'sd128;
    cic4 #(.R(12), .SH(23)) u_cic_r (.clk(clk), .rst(rst), .in_vld(v1), .x(xa),     .out_vld(r_cv), .out(r_c));
    cic4 #(.R(12), .SH(19)) u_cic_s (.clk(clk), .rst(rst), .in_vld(v3), .x(code_c), .out_vld(s_cv), .out(s_c));
    fir127_dec5 u_fir_r (.clk(clk), .rst(rst), .in_vld(r_cv), .x(r_c), .out_vld(r_fv), .y(r_y));
    fir127_dec5 u_fir_s (.clk(clk), .rst(rst), .in_vld(s_cv), .x(s_c), .out_vld(s_fv), .y(s_y));

    // ------------------------------------------------------------ UART out (the Swar sample arrives last)
    reg signed [13:0] r_hold;
    always @(posedge clk) if (r_fv) r_hold <= r_y;
    uart_frame4 u_tx (.clk(clk), .rst(rst), .vld(s_fv), .a(r_hold), .b(s_y), .tx(uart_tx));

    // ------------------------------------------------------------ UART in: keyword from the laptop
    wire rx_vld; wire [7:0] rx_b;
    uart_rx8 u_rx (.clk(clk), .rst(rst), .rx(uart_rx), .vld(rx_vld), .b(rx_b));
    reg [9:0] kw; reg [28:0] kw_t;
    always @(posedge clk) begin
        if (rst) begin kw <= 0; kw_t <= 0; lamp <= 1'b0; end
        else begin
            if (kw_t != 0) kw_t <= kw_t - 1; else kw <= 0;         // keyword LED stays on for 3 s
            if (rx_vld && rx_b[7:4] == 4'h3 && rx_b[3:0] < 4'd10) begin
                kw <= 10'd1 << rx_b[3:0]; kw_t <= 29'd300_000_000;
                if (rx_b[3:0] == 4'd6) lamp <= 1'b1;
                if (rx_b[3:0] == 4'd7) lamp <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------ input level meter (peak over ~42 ms)
    reg [11:0] pk = 0, pk_show = 0; reg [21:0] pk_t = 0;
    wire [11:0] mag = xa[12] ? (~xa[11:0] + 12'd1) : xa[11:0];
    always @(posedge clk) begin
        pk_t <= pk_t + 1;
        if (pk_t == 0) begin pk_show <= pk; pk <= 0; end
        else if (v1 && mag > pk) pk <= mag;
    end
    assign led = {pk_show > 12'd1900, pk_show > 12'd1000, pk_show > 12'd400, pk_show > 12'd150, pk_show > 12'd50,
                  lamp, kw};
endmodule

// 4th-order CIC decimator, one add per clock (registered integrators, combs done one per clock after each output).
// Input 13 bit signed. Gain R^4 = 20736 for R = 12; out = sum * 19292 >> SH  (SH = 19: x * 763, SH = 23: x * 763 / 16).
module cic4 #(parameter R = 12, parameter SH = 19)
    (input wire clk, rst, in_vld, input wire signed [12:0] x, output reg out_vld, output reg signed [18:0] out);
    reg signed [31:0] i1, i2, i3, i4, z1, z2, z3, z4, c1, c2, c3, c4;
    reg signed [47:0] pr; reg [5:0] n; reg [2:0] st;
    always @(posedge clk) begin
        out_vld <= 1'b0;
        if (rst) begin
            i1 <= 0; i2 <= 0; i3 <= 0; i4 <= 0; z1 <= 0; z2 <= 0; z3 <= 0; z4 <= 0;
            c1 <= 0; c2 <= 0; c3 <= 0; c4 <= 0; pr <= 0; n <= 0; st <= 0; out <= 0;
        end else begin
            if (in_vld) begin
                i1 <= i1 + x; i2 <= i2 + i1; i3 <= i3 + i2; i4 <= i4 + i3;
                n <= (n == R - 1) ? 6'd0 : n + 6'd1;
                if (n == R - 1) st <= 3'd1;
            end
            case (st)
                3'd1: begin c1 <= i4 - z1; z1 <= i4; st <= 3'd2; end
                3'd2: begin c2 <= c1 - z2; z2 <= c1; st <= 3'd3; end
                3'd3: begin c3 <= c2 - z3; z3 <= c2; st <= 3'd4; end
                3'd4: begin c4 <= c3 - z4; z4 <= c3; st <= 3'd5; end
                3'd5: begin pr <= c4 * 48'sd19292; st <= 3'd6; end
                3'd6: begin out <= pr >>> SH; out_vld <= 1'b1; st <= 3'd0; end
                default: ;
            endcase
        end
    end
endmodule

// 127-tap FIR, decimation 5 (80.1 kS/s -> 16.03 kS/s, passband 0-7 kHz with CIC droop compensation, fir_coef.hex,
// Q1.17). One multiply-accumulate per clock, RAM and multiplier registered. y = acc * 2749 >> 33 (14 bit, saturated).
module fir127_dec5 (input wire clk, rst, in_vld, input wire signed [18:0] x,
                    output reg out_vld, output reg signed [13:0] y);
    reg signed [17:0] coef [0:127]; initial $readmemh("fir_coef.hex", coef, 0, 126);
    reg signed [18:0] ram [0:127];
    integer i; initial for (i = 0; i < 128; i = i + 1) ram[i] = 0;
    reg [6:0] wp, rp, k, newest; reg [2:0] ph; reg start, run, v1, v2, l1, l2, l3, l4;
    reg signed [18:0] ram_q; reg signed [17:0] coef_q;
    reg signed [36:0] prod; reg signed [43:0] acc; reg signed [56:0] sc;
    wire signed [23:0] ys = sc >>> 33;
    always @(posedge clk) begin
        if (in_vld) ram[wp] <= x;
        ram_q <= ram[rp]; coef_q <= coef[k];
        prod <= ram_q * coef_q;
        sc <= acc * 57'sd2749;
        out_vld <= 1'b0;
        if (rst) begin
            wp <= 0; rp <= 0; k <= 0; newest <= 0; ph <= 0; start <= 0; run <= 0;
            v1 <= 0; v2 <= 0; l1 <= 0; l2 <= 0; l3 <= 0; l4 <= 0; acc <= 0; y <= 0;
        end else begin
            start <= 1'b0;
            if (in_vld) begin
                newest <= wp; wp <= wp + 7'd1;
                ph <= (ph == 3'd4) ? 3'd0 : ph + 3'd1;
                if (ph == 3'd4) start <= 1'b1;
            end
            if (start) begin run <= 1'b1; k <= 7'd0; rp <= newest; acc <= 0; end
            // address stage: tap k multiplies x[n - k]
            v1 <= run; l1 <= run && (k == 7'd126);
            if (run) begin rp <= rp - 7'd1; k <= k + 7'd1; if (k == 7'd126) run <= 1'b0; end
            v2 <= v1; l2 <= l1;                       // ram_q / coef_q valid
            if (v2) acc <= acc + prod;                // prod valid
            l3 <= l2; l4 <= l3;                       // l3: acc complete, l4: sc valid
            if (l4) begin
                y <= (ys > 24'sd8191) ? 14'sd8191 : (ys < -24'sd8191) ? -14'sd8191 : ys[13:0];
                out_vld <= 1'b1;
            end
        end
    end
endmodule

// UART 8N1, 100 MHz / 109 = 917.4 kbaud (0.45 % from 921600). Four bytes per frame.
module uart_frame4 (input wire clk, rst, vld, input wire signed [13:0] a, b, output reg tx);
    reg [31:0] fr; reg [2:0] left; reg [9:0] sh; reg [3:0] nb; reg [6:0] div; reg busy;
    always @(posedge clk) begin
        if (rst) begin left <= 0; busy <= 0; tx <= 1'b1; div <= 0; nb <= 0; sh <= 10'h3FF; fr <= 0; end
        else begin
            if (vld) begin fr <= {1'b1, a[13:7], 1'b0, a[6:0], 1'b0, b[13:7], 1'b0, b[6:0]}; left <= 3'd4; end
            else if (!busy && left != 0) begin
                sh <= {1'b1, fr[31:24], 1'b0}; fr <= {fr[23:0], 8'h00}; left <= left - 3'd1;
                busy <= 1'b1; nb <= 0; div <= 0;
            end
            if (busy) begin
                if (div == 7'd108) begin
                    div <= 0; tx <= sh[0]; sh <= {1'b1, sh[9:1]}; nb <= nb + 4'd1;
                    if (nb == 4'd10) busy <= 1'b0;
                end else div <= div + 7'd1;
            end
        end
    end
endmodule

// UART receiver 8N1, 109 clocks per bit, sampled mid-bit
module uart_rx8 (input wire clk, rst, rx, output reg vld, output reg [7:0] b);
    reg [2:0] s; reg [6:0] div; reg [3:0] nb; reg busy;
    always @(posedge clk) begin
        s <= {s[1:0], rx}; vld <= 1'b0;
        if (rst) begin busy <= 0; div <= 0; nb <= 0; b <= 0; end
        else if (!busy) begin
            if (s[2:1] == 2'b10) begin busy <= 1'b1; div <= 7'd54; nb <= 0; end      // start edge: wait half a bit
        end else if (div == 7'd108) begin
            div <= 0; nb <= nb + 4'd1;
            if (nb == 4'd0) begin if (s[1]) busy <= 1'b0; end                        // false start
            else if (nb <= 4'd8) b <= {s[1], b[7:1]};
            else begin busy <= 1'b0; vld <= s[1]; end                                // stop bit
        end else div <= div + 7'd1;
    end
endmodule

`ifdef SIM
// Simulation stand-in for the XADC: one conversion every 104 clocks; the sample is a slow triangle wave.
module xadc_sim (input wire clk, input wire den, output reg eoc, output reg [15:0] dout, output reg drdy);
    reg [6:0] c = 0; reg [11:0] v = 12'd2048; reg up = 1; reg d1 = 0;
    always @(posedge clk) begin
        c <= (c == 7'd103) ? 7'd0 : c + 7'd1;
        eoc <= (c == 7'd103);
        if (c == 7'd103) begin
            if (v > 12'd2600) up <= 0; else if (v < 12'd1500) up <= 1;
            v <= up ? v + 12'd1 : v - 12'd1;
        end
        d1 <= den; drdy <= d1;
        if (d1) dout <= {v, 4'b0};
    end
endmodule
`endif
