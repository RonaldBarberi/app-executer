# Prepares app-executer-main on this PC: Python venv, Start Menu shortcut (icon and AppUserModelID) and the scheduler
# driver task. Safe to run again, e.g. after moving or copying the project folder to another PC.
param(
    [switch]$Desktop,          # also create a desktop shortcut
    [switch]$NoShortcut,       # don't create the Start Menu shortcut
    [switch]$NoScheduler,      # don't install the driver: CRON_DRIVER schedules won't run on this PC
    [switch]$RemoveScheduler   # only uninstall the driver task and exit
)

# 'Continue': in Windows PowerShell 5.1, 'Stop' turns any stderr output of a native check (python -c ...) into an error;
# every native call checks $LASTEXITCODE instead
$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$config = Get-Content -Raw -Encoding UTF8 (Join-Path $root 'config\config.json') | ConvertFrom-Json
$appName = $config.APP_NAME
$venv = Join-Path $root "venv-$appName"
$python = Join-Path $venv 'Scripts\python.exe'
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'

function Step($text) { Write-Host "`n> $text" -ForegroundColor Cyan }
function Ok($text) { Write-Host "  OK  $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  !   $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "  X   $text" -ForegroundColor Red; exit 1 }

$taskName = "$appName driver"
if ($RemoveScheduler) {
    Step 'Scheduler driver'
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Ok "'$taskName' removed: CRON_DRIVER schedules no longer run on this PC"
    } else {
        Ok "'$taskName' is not installed"
    }
    exit 0
}

# ---------- 1. Python 3.13 ----------
Step 'Python 3.13'
$pyExe, $pyArgs = $null, @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $found = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0) { $pyExe, $pyArgs = 'py', @('-3.13') }
}
if (-not $pyExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($version -eq '3.13') { $pyExe = 'python'; $found = & python -c "import sys; print(sys.executable)" }
}
if (-not $pyExe) {
    Fail 'Python 3.13 not found. Install it from python.org (with the "tcl/tk and IDLE" and "py launcher" options) and run this setup again.'
}
Ok $found
& $pyExe @pyArgs -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) { Fail 'This Python has no tkinter. Reinstall Python 3.13 with the "tcl/tk and IDLE" option.' }
Ok 'tkinter available'

# ---------- 2. Virtual environment ----------
Step "Virtual environment venv-$appName"
$healthy = $false
if (Test-Path $python) {
    # a venv copied from another PC points to a Python that doesn't exist here
    & $python -c "import tkinter, sys; assert sys.version_info[:2] == (3, 13)" 2>$null
    $healthy = ($LASTEXITCODE -eq 0) -and (Test-Path $pythonw)
}
if ($healthy) {
    Ok 'already exists and works'
} else {
    if (Test-Path $venv) { Warn 'exists but does not work on this PC (copied from another one?); recreating it' }
    & $pyExe @pyArgs -m venv --clear $venv
    if ($LASTEXITCODE -ne 0) { Fail 'could not create the virtual environment' }
    Ok 'created'
}

$requirements = Join-Path $root 'requirements.txt'
$packages = @(Get-Content $requirements -ErrorAction SilentlyContinue | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith('#') })
if ($packages.Count) {
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { Fail 'pip install -r requirements.txt failed' }
    Ok "$($packages.Count) dependencies installed"
} else {
    Ok 'no dependencies to install (standard library only)'
}

# ---------- 3. Folders the app reads ----------
Step 'Folders'
function AppPath($path) { if ([IO.Path]::IsPathRooted($path)) { $path } else { [IO.Path]::GetFullPath((Join-Path $root $path)) } }
$projects = AppPath $config.PROJECTS_PATH
$watch = AppPath $config.WATCH_PATH
$bots = @(Get-ChildItem $projects -Directory -ErrorAction SilentlyContinue |
    Where-Object { $config.EXCLUDED_PROJECTS -notcontains $_.Name -and (Test-Path (Join-Path $_.FullName 'src\main.py')) })
if ($bots.Count) { Ok "$($bots.Count) bots with src\main.py in $projects" } else { Warn "no bots found in $projects (PROJECTS_PATH in config.json)" }
if (Test-Path $watch) { Ok "logs in $watch" } else { Warn "$watch does not exist yet; it is created on the first bot run (WATCH_PATH in config.json)" }

# ---------- 4. Shortcuts ----------
Step 'Shortcuts'
if ($NoShortcut) {
    Ok 'skipped (-NoShortcut)'
} else {
# WScript.Shell can't set System.AppUserModel.ID; without it the running window would show as a second taskbar
# button next to the pinned one, because the app sets its own APP_ID at startup
Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace AppExecuterSetup {
    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder file, int max, IntPtr data, uint flags);
        void GetIDList(out IntPtr pidl);
        void SetIDList(IntPtr pidl);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder name, int max);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder dir, int max);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string dir);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder args, int max);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string args);
        void GetHotkey(out short hotkey);
        void SetHotkey(short hotkey);
        void GetShowCmd(out int cmd);
        void SetShowCmd(int cmd);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int max, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr hwnd, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string file);
    }

    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        void GetCount(out uint count);
        void GetAt(uint index, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    struct PropertyKey { public Guid FormatId; public uint PropertyId; }

    // PROPVARIANT: 16 bytes on x86, 24 on x64
    [StructLayout(LayoutKind.Explicit, Size = 24)]
    struct PropVariant {
        [FieldOffset(0)] public ushort VarType;
        [FieldOffset(8)] public IntPtr Pointer;
    }

    public static class Shortcut {
        public static void Create(string path, string target, string args, string workDir, string icon, string description, string appId) {
            var link = (IShellLinkW)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
            link.SetPath(target);
            link.SetArguments(args);
            link.SetWorkingDirectory(workDir);
            link.SetIconLocation(icon, 0);
            link.SetDescription(description);

            var store = (IPropertyStore)link;
            var key = new PropertyKey { FormatId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), PropertyId = 5 };
            var value = new PropVariant { VarType = 31, Pointer = Marshal.StringToCoTaskMemUni(appId) };  // VT_LPWSTR
            try {
                store.SetValue(ref key, ref value);
                store.Commit();
            } finally {
                Marshal.FreeCoTaskMem(value.Pointer);
            }
            ((IPersistFile)link).Save(path, true);
        }
    }
}
'@

$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) "$appName.lnk"
$targets = @($startMenu)
if ($Desktop) { $targets += Join-Path ([Environment]::GetFolderPath('Desktop')) "$appName.lnk" }
$icon = Join-Path $root (Join-Path $config.ASSETS_PATH $config.ICON_FILE)
foreach ($lnk in $targets) {
    [AppExecuterSetup.Shortcut]::Create($lnk, $pythonw, "`"$(Join-Path $root 'src\main.py')`"", $root, $icon,
        'Runs the KRETON RPA bots with live progress and logs', $config.APP_ID)
    $shell = New-Object -ComObject Shell.Application
    $item = $shell.NameSpace((Split-Path $lnk)).ParseName((Split-Path $lnk -Leaf))
    $appId = $item.ExtendedProperty('System.AppUserModel.ID')
    if ($appId -ne $config.APP_ID) { Fail "shortcut created but its AppUserModelID is '$appId' (expected '$($config.APP_ID)')" }
    Ok $lnk
}
}

# ---------- 5. Scheduler driver ----------
Step 'Scheduler driver (CRON_DRIVER)'
if ($NoScheduler) {
    Warn "skipped (-NoScheduler): the schedules in $($config.SCHEDULES_FILE) won't run on this PC"
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Warn "'$taskName' is still installed; remove it with -RemoveScheduler" }
} else {
    try {
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$(Join-Path $root 'src\main.py')`" --tick" -WorkingDirectory $root
        # every minute, with no end; the tick itself decides which bots are due and records the missed ones
        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 1)
        $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
            -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        # Interactive: only while the user is logged on, because the bots need the desktop session (Chrome, Excel COM, Outlook)
        $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force `
            -Description "Runs '$appName --tick' every minute: starts the bots whose CRON_DRIVER schedule is due ($($config.SCHEDULES_FILE))." `
            -ErrorAction Stop | Out-Null
    } catch {
        Fail "could not register '$taskName': $($_.Exception.Message)"
    }
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.Triggers[0].Repetition.Interval -ne 'PT1M') { Fail "'$taskName' was registered without the 1 minute repetition" }
    Ok "'$taskName': every minute while you are logged on (also with the screen locked or the PC unattended)"
}

Write-Host "`nDone." -ForegroundColor Green
if (-not $NoShortcut) { Write-Host "To pin it: Start menu > search '$appName' > right click > Pin to taskbar." -ForegroundColor Green }
Write-Host "Run this setup again if you move the project folder." -ForegroundColor Green
