$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$assetDir = Join-Path $scriptDir "installer-assets"
$logoPath = (Resolve-Path (Join-Path $scriptDir "..\..\..\assets\logo.png")).Path
$iconPath = (Resolve-Path (Join-Path $scriptDir "..\icons\icon.ico")).Path

New-Item -ItemType Directory -Force -Path $assetDir | Out-Null
Copy-Item $iconPath (Join-Path $assetDir "installer-icon.ico") -Force

$logo = [System.Drawing.Bitmap]::new($logoPath)

function New-Canvas([int]$width, [int]$height) {
  $bmp = New-Object System.Drawing.Bitmap $width, $height
  $bmp.SetResolution(96, 96)
  return $bmp
}

function New-Graphics([System.Drawing.Bitmap]$bitmap) {
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
  $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  return $graphics
}

function New-RoundedRect([float]$x, [float]$y, [float]$width, [float]$height, [float]$radius) {
  $path = New-Object System.Drawing.Drawing2D.GraphicsPath
  $diameter = $radius * 2
  $path.AddArc($x, $y, $diameter, $diameter, 180, 90)
  $path.AddArc($x + $width - $diameter, $y, $diameter, $diameter, 270, 90)
  $path.AddArc($x + $width - $diameter, $y + $height - $diameter, $diameter, $diameter, 0, 90)
  $path.AddArc($x, $y + $height - $diameter, $diameter, $diameter, 90, 90)
  $path.CloseFigure()
  return $path
}

function Save-Bmp([string]$path, [int]$width, [int]$height, [scriptblock]$draw) {
  $bitmap = New-Canvas $width $height
  $graphics = New-Graphics $bitmap
  & $draw $graphics $bitmap
  $graphics.Dispose()
  $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Bmp)
  $bitmap.Dispose()
}

$cream = [System.Drawing.Color]::FromArgb(251, 246, 238)
$sand = [System.Drawing.Color]::FromArgb(240, 224, 202)
$clay = [System.Drawing.Color]::FromArgb(176, 58, 90)
$sage = [System.Drawing.Color]::FromArgb(212, 96, 90)
$moss = [System.Drawing.Color]::FromArgb(107, 93, 100)
$ink = [System.Drawing.Color]::FromArgb(43, 35, 31)
$muted = [System.Drawing.Color]::FromArgb(114, 94, 83)
$line = [System.Drawing.Color]::FromArgb(229, 207, 184)

$fontTitle = New-Object System.Drawing.Font("Segoe UI Semibold", 17, [System.Drawing.FontStyle]::Bold)
$fontBody = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Regular)
$fontSmall = New-Object System.Drawing.Font("Segoe UI", 8.5, [System.Drawing.FontStyle]::Regular)

$brushCream = New-Object System.Drawing.SolidBrush $cream
$brushSand = New-Object System.Drawing.SolidBrush $sand
$brushClay = New-Object System.Drawing.SolidBrush $clay
$brushSage = New-Object System.Drawing.SolidBrush $sage
$brushInk = New-Object System.Drawing.SolidBrush $ink
$brushMuted = New-Object System.Drawing.SolidBrush $muted
$brushMoss = New-Object System.Drawing.SolidBrush $moss
$penLine = New-Object System.Drawing.Pen $line, 1.0

Save-Bmp (Join-Path $assetDir "nsis-header.bmp") 150 57 {
  param($g, $bmp)
  $g.Clear($cream)
  $g.FillRectangle($brushSand, 0, 0, 46, 57)
  $g.FillRectangle($brushClay, 46, 0, 4, 57)
  $g.DrawImage($logo, (New-Object System.Drawing.Rectangle 7, 8, 32, 32))
  $g.DrawString("Retriqs", $fontSmall, $brushInk, 59, 10)
  $g.DrawString("Desktop installer", $fontSmall, $brushMuted, 59, 27)
}

Save-Bmp (Join-Path $assetDir "nsis-sidebar.bmp") 164 314 {
  param($g, $bmp)
  $g.Clear($sand)
  $g.FillRectangle($brushCream, 14, 14, 136, 286)
  $g.DrawRectangle($penLine, 14, 14, 135, 285)
  $path = New-RoundedRect 30 32 104 104 24
  $g.FillPath($brushCream, $path)
  $g.DrawPath((New-Object System.Drawing.Pen $line, 1.5), $path)
  $g.DrawImage($logo, (New-Object System.Drawing.Rectangle 42, 44, 80, 80))
  $path.Dispose()
  $g.FillEllipse($brushClay, 28, 178, 18, 18)
  $g.FillEllipse($brushSage, 118, 194, 22, 22)
  $g.FillEllipse($brushMoss, 42, 228, 10, 10)
  $g.FillRectangle($brushClay, 28, 266, 108, 6)
  $g.FillRectangle($brushSage, 28, 280, 76, 6)
}

Save-Bmp (Join-Path $assetDir "wix-banner.bmp") 493 58 {
  param($g, $bmp)
  $g.Clear($cream)
  $g.FillRectangle($brushSand, 0, 0, 104, 58)
  $g.FillRectangle($brushClay, 104, 0, 5, 58)
  $g.DrawImage($logo, (New-Object System.Drawing.Rectangle 18, 9, 40, 40))
  $g.DrawString("Retriqs", $fontTitle, $brushInk, 126, 8)
  $g.DrawString("Desktop setup", $fontBody, $brushMuted, 240, 16)
}

Save-Bmp (Join-Path $assetDir "wix-dialog.bmp") 493 312 {
  param($g, $bmp)
  $g.Clear($cream)
  $g.FillRectangle($brushSand, 0, 0, 184, 312)
  $g.FillRectangle($brushClay, 184, 0, 5, 312)
  $g.DrawImage($logo, (New-Object System.Drawing.Rectangle 40, 38, 102, 102))
  $g.DrawString("Retriqs", $fontTitle, $brushInk, 38, 176)
  $g.DrawString("Minimal local desktop workspace", $fontBody, $brushMuted, 38, 210)
  $g.DrawString("Install the app with its bundled", $fontBody, $brushMuted, 220, 92)
  $g.DrawString("local backend and decide later", $fontBody, $brushMuted, 220, 116)
  $g.DrawString("whether uninstall keeps your data.", $fontBody, $brushMuted, 220, 140)
  $g.FillRectangle($brushClay, 220, 196, 88, 6)
  $g.FillRectangle($brushSage, 220, 214, 132, 6)
}

$fontTitle.Dispose()
$fontBody.Dispose()
$fontSmall.Dispose()
$brushCream.Dispose()
$brushSand.Dispose()
$brushClay.Dispose()
$brushSage.Dispose()
$brushInk.Dispose()
$brushMuted.Dispose()
$brushMoss.Dispose()
$penLine.Dispose()
$logo.Dispose()
