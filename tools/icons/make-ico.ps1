# 生成应用快捷方式图标（.ico，内含 16/32/48/256 四个 PNG 尺寸）：红色圆角方块 + 白色单字。
#   powershell -ExecutionPolicy Bypass -File tools\icons\make-ico.ps1 -Text 运 -Out agent\icons\xhs-workbench.ico
# 需要 Windows PowerShell（System.Drawing）。图标放进 agent\icons\，由中枢下发（/api/agent/icons/<应用 id>.ico），安装脚本给桌面 / 开始菜单快捷方式设上。
param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][string]$Out, [string]$Color = '#FF2442', [string]$Font = 'Microsoft YaHei UI')
Add-Type -AssemblyName System.Drawing
function New-Png([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.TextRenderingHint = 'AntiAliasGridFit'; $g.Clear([System.Drawing.Color]::Transparent)
    $r = [int]($size * 0.22)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $r * 2
    $path.AddArc(0, 0, $d, $d, 180, 90); $path.AddArc($size - $d - 1, 0, $d, $d, 270, 90)
    $path.AddArc($size - $d - 1, $size - $d - 1, $d, $d, 0, 90); $path.AddArc(0, $size - $d - 1, $d, $d, 90, 90); $path.CloseFigure()
    $g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($Color))), $path)
    $f = New-Object System.Drawing.Font $Font, ([single]($size * 0.62)), ([System.Drawing.FontStyle]::Bold), ([System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat; $fmt.Alignment = 'Center'; $fmt.LineAlignment = 'Center'
    $rect = New-Object System.Drawing.RectangleF 0, ([single]($size * 0.03)), $size, $size
    $g.DrawString($Text, $f, [System.Drawing.Brushes]::White, $rect, $fmt)
    $ms = New-Object System.IO.MemoryStream; $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()
    return , $ms.ToArray()
}
$sizes = 16, 32, 48, 256
$pngs = @(); foreach ($s in $sizes) { $pngs += , (New-Png $s) }
$ico = New-Object System.IO.MemoryStream; $w = New-Object System.IO.BinaryWriter $ico
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $b = if ($s -ge 256) { 0 } else { $s }
    $w.Write([byte]$b); $w.Write([byte]$b); $w.Write([byte]0); $w.Write([byte]0); $w.Write([uint16]1); $w.Write([uint16]32)
    $w.Write([uint32]$pngs[$i].Length); $w.Write([uint32]$offset); $offset += $pngs[$i].Length
}
foreach ($p in $pngs) { $w.Write($p) }
New-Item -ItemType Directory -Force (Split-Path -Parent ([IO.Path]::GetFullPath($Out))) | Out-Null
[IO.File]::WriteAllBytes([IO.Path]::GetFullPath($Out), $ico.ToArray())
Write-Host "wrote $Out ($($ico.Length) bytes)"
