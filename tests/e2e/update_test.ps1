# Real Windows update test: install the Setup, seed data, open the app, update it in-app with the same Setup, and check that the new
# copy opens, its window talks to the local server, and the data is still there. Screenshots + app.log are saved for debugging.
param([string]$Setup = "installer_out\DementedToolbox-Setup.exe", [string]$Out = "e2e_out")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
$Setup = (Resolve-Path $Setup).Path
$data = Join-Path $env:APPDATA "DementedToolbox"
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
function Shot($name) { try { $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); $bmp.Save((Join-Path $Out "$name.png")); $g.Dispose(); $bmp.Dispose() } catch { Write-Host "screenshot failed: $_" } }
function Diag { try { Invoke-RestMethod -TimeoutSec 3 http://127.0.0.1:8765/api/diag } catch { $null } }
function WaitUi($label, $notPid, $secs) {
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $secs) {
    $d = Diag
    if ($d -and $d.pid -ne $notPid -and $d.ui_ok -gt 0) { Write-Host "$label ok after $([int]((Get-Date) - $t0).TotalSeconds)s: pid $($d.pid) data $($d.data | ConvertTo-Json -Compress)"; return $d }
    Start-Sleep 2
  }
  return $null
}
function Dump {
  Get-Process | Where-Object { $_.Name -match "DementedToolbox|msedgewebview2|DementedToolbox-Setup" } | Format-Table Id, Name, StartTime -AutoSize | Out-String | Write-Host
  if (Test-Path "$data\app.log") { Copy-Item "$data\app.log" $Out -Force; Write-Host "---- app.log"; Get-Content "$data\app.log" -Tail 80 }
}

Write-Host "== install"
$p = Start-Process $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
$exe = Join-Path $env:LOCALAPPDATA "Programs\Demented Toolbox\DementedToolbox.exe"
if (!(Test-Path $exe)) { throw "not installed at $exe" }

Write-Host "== seed data (an email account + an order)"
python -c "import sqlite3,os,sys; sys.path.insert(0,'app'); os.environ.pop('DT_DATA',None); from dt import db; c=db.connect(); c.execute(""INSERT INTO mail_accounts(email,password,host,port,enabled,created_at) VALUES('keep@icloud.com','x','imap.mail.me.com',993,0,'2026-01-01')""); c.execute(""INSERT INTO orders(retailer,order_number,status,order_date,total,created_at,updated_at) VALUES('Target','E2E1','placed','2026-11-01',10,'x','x')""); c.commit(); print(db.counts())"

Write-Host "== first launch"
$env:DT_E2E = "1"
Start-Process $exe
$first = WaitUi "first launch" 0 90
Shot "1-first-launch"
if (!$first) { Dump; throw "the app's window never reached its server on a normal launch" }

Write-Host "== in-app update"
Remove-Item Env:DT_E2E
try { Invoke-RestMethod -Method Post -ContentType "application/json" -Body (@{ path = $Setup } | ConvertTo-Json) http://127.0.0.1:8765/api/update/e2e_install -TimeoutSec 10 | Out-Null } catch { Write-Host "install call: $_" }
$t0 = Get-Date
for ($i = 0; $i -lt 6; $i++) { Start-Sleep 5; Shot ("2-during-update-{0:d2}" -f $i) }
$after = WaitUi "relaunch after update" $first.pid 120
Shot "3-after-update"
Start-Sleep 30
$d = Diag
Shot "4-after-update-30s-later"
Dump
if (!$after) { throw "after the in-app update the app did not come back with a working window" }
if (!$d -or $d.pid -ne $after.pid) { throw "the relaunched app did not stay up (pid changed or gone): $($d | ConvertTo-Json -Compress)" }
if ($d.data.mail_accounts -lt 1 -or $d.data.orders -lt 1) { throw "data was lost across the update: $($d.data | ConvertTo-Json -Compress)" }
Write-Host "UPDATE TEST PASSED"
