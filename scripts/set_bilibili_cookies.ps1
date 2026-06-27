Write-Host "========================================"
Write-Host "   Bilibili Cookies Setup Tool"
Write-Host "========================================"
Write-Host ""
Write-Host "Steps:"
Write-Host "  1. Open bilibili.com in browser and login"
Write-Host "  2. Press F12, go to Network tab"
Write-Host "  3. Refresh page, click any request"
Write-Host "  4. Find `"Request Headers`" - `"Cookie`" line"
Write-Host "  5. Right-click and copy the Cookie value"
Write-Host ""
Write-Host "Example:"
Write-Host "  SESSDATA=abc123; bili_jct=def456; DedeUserID=12345"
Write-Host ""

$raw = Read-Host "Paste Cookie value"
if ([string]::IsNullOrWhiteSpace($raw)) { Write-Host "ERROR: Cookie cannot be empty"; exit 1 }

$t = [char]9
$lines = @(); $keys = @{}
foreach ($pair in ($raw -split ';' | ForEach-Object { $_.Trim() })) {
    if ($pair -match '^(.+?)=(.+)$') {
        $k = $matches[1].Trim(); $v = $matches[2].Trim()
        $keys[$k] = $true
        $lines += '.bilibili.com' + $t + 'TRUE' + $t + '/' + $t + 'FALSE' + $t + '2147483647' + $t + $k + $t + $v
    }
}

$out = Join-Path (Split-Path $PSScriptRoot -Parent) "bilibili\bilibili_cookies.txt"
$header = '# Netscape HTTP Cookie File'
$content = $header + [Environment]::NewLine + ($lines -join [Environment]::NewLine)
[System.IO.File]::WriteAllText($out, $content, [System.Text.UTF8Encoding]::new($false))

if ($keys.ContainsKey('DedeUserID') -and $keys.ContainsKey('SESSDATA')) {
    Write-Host ""
    Write-Host "[OK] Saved to bilibili\bilibili_cookies.txt"
    Write-Host ""
    Write-Host "Cookies:"
    Get-Content $out | Where-Object { $_ -notmatch '^#' }
    Write-Host ""
    Write-Host "[OK] Valid (contains DedeUserID and SESSDATA)"
    exit 0
} else {
    Write-Host ""
    Write-Host "[ERROR] Missing required cookies: DedeUserID and/or SESSDATA"
    Write-Host "        Make sure you are logged in to bilibili.com"
    exit 2
}
