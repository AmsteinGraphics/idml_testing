<#
.SYNOPSIS
    Mirror InDesign files from a local working folder into the repo as they are saved.

.DESCRIPTION
    InDesign takes ownership of a document by writing a .idlk lock beside it and
    holding a file lock. Over \\wsl.localhost -- a UNC path served by a network
    redirector, not a local disk -- that locking is unreliable, and when InDesign
    cannot establish it the document opens [Read-Only]. Adobe does not support
    opening documents from network volumes at all.

    So keep InDesign's working copy on a local Windows disk, where locking works,
    and let this script copy each save back into the repo. The toolchain never
    cares where a file came from; only InDesign does.

    WHAT IT COPIES. Both .indd and .idml by default. The .indd is your working
    file and the repo is the only other place it exists; the .idml is what
    build_manual.py actually consumes. Copying only the .indd would keep a backup
    but feed the pipeline nothing.

    WHY IT WAITS. InDesign saves by writing and renaming, which fires several
    change events for one save, and the file is still being written when the
    first arrives. Copying then yields a truncated document. So a change starts a
    timer, the timer restarts on every further change, and the copy happens only
    once the file has been still for -QuietMs AND can be opened for reading.

.PARAMETER Source
    Local folder holding the working files. Default: %USERPROFILE%\Documents\dm42n

.PARAMETER Dest
    Folder in the repo to mirror into.

.PARAMETER QuietMs
    How long a file must stop changing before it is copied. Default 2000.

.EXAMPLE
    .\watch_indesign.ps1
    .\watch_indesign.ps1 -Source D:\work\dm42n -Dest \\wsl.localhost\Ubuntu\home\emy\github\idml_testing\manuals\dm42n\submissions
#>
# ASCII ONLY, deliberately. Windows PowerShell 5.1 reads a .ps1 as ANSI unless the
# file carries a UTF-8 BOM, and this repo writes files as UTF-8 without one. An
# em-dash in a string was enough to corrupt it into an unterminated string and
# take the whole script down at parse time.

[CmdletBinding()]
param(
    [string] $Source  = (Join-Path $env:USERPROFILE 'Documents\dm42n'),
    [string] $Dest    = '\\wsl.localhost\Ubuntu\home\emy\github\idml_testing\manuals\dm42n\submissions',
    [string[]] $Extensions = @('.indd', '.idml'),
    [int]    $QuietMs = 2000
)

$ErrorActionPreference = 'Stop'

function Write-Log {
    param([string] $Message, [string] $Colour = 'Gray')
    Write-Host ("[{0:HH:mm:ss}] {1}" -f (Get-Date), $Message) -ForegroundColor $Colour
}

# ---- checks before we start watching ---------------------------------------
if (-not (Test-Path -LiteralPath $Source)) {
    New-Item -ItemType Directory -Path $Source -Force | Out-Null
    Write-Log "created source folder $Source" 'Yellow'
}
if (-not (Test-Path -LiteralPath $Dest)) {
    throw "Destination not reachable: $Dest"
}
# Prove the destination is writable NOW rather than discovering it on the first
# save, when the useful copy is the one being lost.
$probe = Join-Path $Dest (".watchtest_" + [Guid]::NewGuid().ToString('N').Substring(0, 6))
try {
    [System.IO.File]::WriteAllText($probe, 'x')
    Remove-Item -LiteralPath $probe -Force
} catch {
    throw "Destination is not writable: $Dest`n$($_.Exception.Message)"
}

Write-Log "watching : $Source" 'Cyan'
Write-Log "mirroring to: $Dest" 'Cyan'
Write-Log ("extensions  : " + ($Extensions -join ', ')) 'Cyan'
Write-Log "Ctrl-C to stop." 'Cyan'

# ---- helpers ----------------------------------------------------------------
function Test-Readable {
    # True when nothing holds a write lock -- i.e. the save has finished.
    param([string] $Path)
    try {
        $fs = [System.IO.File]::Open($Path, 'Open', 'Read', 'None')
        $fs.Close()
        return $true
    } catch {
        return $false
    }
}

function Copy-WhenSettled {
    param([string] $Path)

    $name = Split-Path $Path -Leaf
    # Copy to a temporary name in the destination and rename into place, so a
    # reader in the repo never sees a half-written file.
    $final = Join-Path $Dest $name
    $temp  = "$final.part"

    for ($attempt = 1; $attempt -le 10; $attempt++) {
        if (-not (Test-Path -LiteralPath $Path)) { return }
        if (Test-Readable $Path) {
            try {
                Copy-Item -LiteralPath $Path -Destination $temp -Force
                if (Test-Path -LiteralPath $final) { Remove-Item -LiteralPath $final -Force }
                Rename-Item -LiteralPath $temp -NewName $name -Force
                $size = (Get-Item -LiteralPath $final).Length
                Write-Log ("copied {0}  ({1:N0} bytes)" -f $name, $size) 'Green'
                return
            } catch {
                Write-Log "copy of $name failed (try $attempt): $($_.Exception.Message)" 'Yellow'
                if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Log "gave up on $name - still locked after 10 tries" 'Red'
}

# ---- watch ------------------------------------------------------------------
# POLLING, not FileSystemWatcher. A -Action scriptblock registered against the
# watcher runs in its OWN runspace: it cannot see $Extensions or the pending
# table from this scope, so every event tested against an empty list and was
# silently discarded -- the script ran, logged its banner, and copied nothing.
# Passing state across that boundary means global variables and a good deal of
# ceremony, to detect changes no sooner than a poll does. For a handful of files
# saved by hand, a loop is both simpler and harder to get wrong.
#
# `seen`   : path -> the size/time signature last observed
# `since`  : path -> when the signature last changed
# `copied` : path -> the signature already mirrored, so a settled file is copied
#            once rather than every pass
$seen = @{}; $since = @{}; $copied = @{}

function Get-Signature {
    param([System.IO.FileInfo] $Item)
    return ("{0}|{1}" -f $Item.Length, $Item.LastWriteTimeUtc.Ticks)
}

try {
    while ($true) {
        $now = Get-Date
        $files = Get-ChildItem -LiteralPath $Source -File -ErrorAction SilentlyContinue |
                 Where-Object {
                     ($Extensions -contains $_.Extension.ToLower()) -and
                     -not $_.Name.StartsWith('~')
                 }

        foreach ($item in $files) {
            $path = $item.FullName
            $sig = Get-Signature $item

            if ($seen[$path] -ne $sig) {
                # still changing: note it and restart the quiet timer
                $seen[$path] = $sig
                $since[$path] = $now
                continue
            }
            if ($copied[$path] -eq $sig) { continue }        # this state is already mirrored
            if (($now - $since[$path]).TotalMilliseconds -lt $QuietMs) { continue }

            Copy-WhenSettled $path
            $copied[$path] = $sig
        }

        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Log 'stopping...' 'Cyan'
}
