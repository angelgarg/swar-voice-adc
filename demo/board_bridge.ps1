# Forwards the Basys3 serial port to the Swar demo server running in WSL.
#   1. in WSL:      python3 demo/live_demo.py --bridge 8791
#   2. in Windows:  powershell -ExecutionPolicy Bypass -File demo\board_bridge.ps1 -Port COM12
# Run it without -Port to list the serial ports. The Basys3 shows up as "USB Serial Port (COMx)".
# The board can be switched off, unplugged and plugged back in: the bridge reopens the port by itself.
param([string]$Port = "", [int]$Baud = 921600, [int]$Tcp = 8791)
if (-not $Port) {
    Write-Host "Serial ports found: $([System.IO.Ports.SerialPort]::GetPortNames() -join ', ')"
    Write-Host "Run again with -Port COMx"
    exit 1
}
$buf = New-Object byte[] 65536
$one = New-Object byte[] 1
while ($true) {
    $sp = $null; $client = $null
    try {
        $sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
        $sp.ReadBufferSize = 1048576
        $sp.Open()
        $client = New-Object System.Net.Sockets.TcpClient('127.0.0.1', $Tcp)
        $stream = $client.GetStream()
        Write-Host "$(Get-Date -Format HH:mm:ss) $Port open, connected to the demo server."
        $sp.DiscardInBuffer()
        $quiet = [Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $n = $sp.BytesToRead
            if ($n -gt 0) {
                $n = $sp.Read($buf, 0, [Math]::Min($n, $buf.Length))
                $stream.Write($buf, 0, $n)
                $quiet.Restart()
            } else {
                if ($quiet.ElapsedMilliseconds -gt 2000) { throw "no data from the board for 2 s" }
                Start-Sleep -Milliseconds 4
            }
            while ($stream.DataAvailable) {
                $one[0] = [byte]$stream.ReadByte()
                $sp.Write($one, 0, 1)
            }
        }
    } catch {
        Write-Host "$(Get-Date -Format HH:mm:ss) $($_.Exception.Message). Reconnecting."
    }
    if ($client) { try { $client.Close() } catch {} }
    if ($sp) { try { $sp.Close() } catch {}; try { $sp.Dispose() } catch {} }
    Start-Sleep -Milliseconds 800
}
