# J.A.R.V.I.S. always-on wake listener.
#
# Uses the *offline* Windows desktop speech recognizer (System.Speech), so it
# needs no internet and no API key - unlike the browser Speech Recognition API,
# which cannot reach a speech service from inside the packaged window.
#
# Say "Hello JARVIS" -> it answers "Yes, Sir?" and brings JARVIS to the
# foreground (starting it if it is closed). Then say your command; the words are
# written to ~/.jarvis/wake_command.json for the app to pick up and run.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File wake_listener.ps1 `
#            [-DataDir <path>] [-LaunchTarget <exe/bat>] [-LaunchArgs <args>] [-SelfTest]

param(
    [string]$DataDir = '',
    [string]$LaunchTarget = '',
    [string]$LaunchArgs = '',
    [string]$InputWave = '',
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'
if (-not $DataDir) { $DataDir = Join-Path $env:USERPROFILE '.jarvis' }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

$Global:statusFile = Join-Path $DataDir 'wake_status.json'
$Global:cmdFile    = Join-Path $DataDir 'wake_command.json'
$Global:logFile    = Join-Path $DataDir 'wake_listener.log'

# The app records where it lives in this file, which keeps the sign-in entry free
# of nested quoting. An explicit -LaunchTarget still wins.
if (-not $LaunchTarget) {
    $cfgFile = Join-Path $DataDir 'wake_config.json'
    if (Test-Path $cfgFile) {
        try {
            $cfg = Get-Content -Path $cfgFile -Raw | ConvertFrom-Json
            $LaunchTarget = "$($cfg.launch_target)"
            if (-not $LaunchArgs) { $LaunchArgs = "$($cfg.launch_args)" }
        } catch { }
    }
}
$Global:LaunchTarget = $LaunchTarget
$Global:LaunchArgs   = $LaunchArgs
$Global:InputWave    = $InputWave
$Global:stop         = $false
$Global:wakePattern  = '(hello|hey|ok|okay|yes)?\s*(jar|char|jerv|gar)[aeiouy]*v[ie][sz]'
$Global:wakeFor      = 14      # seconds JARVIS stays "listening to you" after waking
$Global:mode         = 'wake-only'
$Global:engineName   = ''

# Event actions run in the global scope, so every helper they need is global.
function global:Write-Log($m) {
    try { Add-Content -Path $Global:logFile -Value ("[{0}] {1}" -f (Get-Date -Format 's'), $m) } catch {}
}

function global:Write-Status($state, $err) {
    $o = @{
        state   = $state
        pid     = $PID
        mode    = $Global:mode
        engine  = $Global:engineName
        error   = "$err"
        wakeFor = $Global:wakeFor
        updated = (Get-Date -Format 'o')
    }
    try { $o | ConvertTo-Json -Compress | Set-Content -Path $Global:statusFile -Encoding UTF8 } catch {}
}

function global:Save-Command($text) {
    $payload = @{ text = $text; at = (Get-Date -Format 'o'); id = [Guid]::NewGuid().ToString('N') }
    try {
        $tmp = "$($Global:cmdFile).tmp"
        $payload | ConvertTo-Json -Compress | Set-Content -Path $tmp -Encoding UTF8
        Move-Item -Path $tmp -Destination $Global:cmdFile -Force
        Write-Log "command: $text"
    } catch { Write-Log "command write failed: $_" }
}

function global:Remove-WakeToken([string]$text) {
    # "Jarvis open YouTube" -> "open YouTube"; "hello jarvis" -> ""
    return ("$text" -replace "(?i)^(hello\s+|hey\s+|ok\s+|okay\s+|yes\s+)?(jar|char|jerv|gar)[aeiouy]*v[ie][sz]\s*[,\.:]?\s*", '').Trim()
}

function global:Raise-Jarvis {
    $h = [JarvisWin]::Find('J.A.R.V.I.S.')
    if ($h -ne [IntPtr]::Zero) {
        if ([JarvisWin]::IsIconic($h)) { [void][JarvisWin]::ShowWindow($h, 9) }  # SW_RESTORE
        [void][JarvisWin]::SetForegroundWindow($h)
        return
    }
    if ($Global:LaunchTarget -and (Test-Path $Global:LaunchTarget)) {
        try {
            if ($Global:LaunchArgs) { Start-Process -FilePath $Global:LaunchTarget -ArgumentList $Global:LaunchArgs }
            else { Start-Process -FilePath $Global:LaunchTarget }
            Write-Log "launched $($Global:LaunchTarget)"
        } catch { Write-Log "launch failed: $_" }
    }
}

Add-Type -AssemblyName System.Speech

if (-not ('JarvisWin' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class JarvisWin {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
    [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);
    public static void StayAwake() {
        // ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no suspend while we listen.
        // The display may still switch off - that does not stop the microphone.
        SetThreadExecutionState(0x80000000u | 0x00000001u);
    }
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    public static IntPtr Find(string prefix) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            if (!IsWindowVisible(h)) return true;
            StringBuilder sb = new StringBuilder(256);
            GetWindowText(h, sb, sb.Capacity);
            if (sb.ToString().Trim().StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) {
                found = h; return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@ -Language CSharp
}

# --- pick the offline recognizer ------------------------------------------
$cults = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
$cult = $cults | Where-Object { $_.Culture.Name -like 'en*' } | Select-Object -First 1
if (-not $cult) { $cult = $cults | Select-Object -First 1 }
if (-not $cult) {
    Write-Status 'unavailable' 'no Windows speech recognizer is installed'
    Write-Log 'no recognizer installed'
    exit 2
}
$Global:engineName = $cult.Culture.Name

$engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine($cult.Id)

try {
    $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
    $Global:mode = 'dictation'
} catch {
    Write-Status 'unavailable' "dictation grammar failed: $_"
    Write-Log "dictation grammar failed: $_"
    exit 3
}

try {
    if ($InputWave) {
        $engine.SetInputToWaveFile($InputWave)
        $Global:mode = "$($Global:mode) via wav"
    } else {
        $engine.SetInputToDefaultAudioDevice()
    }
}
catch {
    Write-Status 'unavailable' "no microphone available: $_"
    Write-Log "no mic: $_"
    exit 4
}
$engine.InitialSilenceTimeout      = [TimeSpan]::FromSeconds(3600)
$engine.BabbleTimeout              = [TimeSpan]::FromSeconds(2)
$engine.EndSilenceTimeout          = [TimeSpan]::FromMilliseconds(700)
$engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds(1400)

$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $v = $voice.GetInstalledVoices() |
         Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en*' } |
         Select-Object -First 1
    if ($v) { $voice.SelectVoice($v.VoiceInfo.Name) }
    $voice.Rate = 1
} catch {}

# --- the wake / command state machine -------------------------------------
$Global:awake = $false
$Global:awakeUntil = Get-Date
$Global:engine = $engine
$Global:voice = $voice

Register-ObjectEvent -InputObject $engine -EventName SpeechRecognized -Action {
    $text = "$($EventArgs.Result.Text)".Trim()
    if (-not $text) { return }
    $low = $text.ToLower()
    $now = Get-Date

    if ($Global:awake) {
        if ($now -lt $Global:awakeUntil) {
            $Global:awake = $false
            $cmd = Remove-WakeToken $text
            if ($cmd) { Save-Command $cmd }
            Write-Status 'listening' ''
            return
        }
        $Global:awake = $false
    }

    if ($low -notmatch $Global:wakePattern) { return }

    # "Hello JARVIS, what time is it?" arrives as one phrase - keep the rest.
    $rest = Remove-WakeToken $text
    $Global:awake = $true
    $Global:awakeUntil = $now.AddSeconds($Global:wakeFor)
    Write-Log "wake: $text"
    Raise-Jarvis
    try { $Global:voice.SpeakAsync('Yes, Sir?') | Out-Null } catch {}
    Write-Status 'armed' ''
    if ($rest.Length -ge 3) {
        $Global:awake = $false
        Start-Sleep -Milliseconds 200
        Save-Command $rest
        Write-Status 'listening' ''
    }
} | Out-Null

Register-ObjectEvent -InputObject $engine -EventName RecognizeCompleted -Action {
    if ($EventArgs.Error) { Write-Log "recognize error: $($EventArgs.Error)" }
    if ($Global:InputWave) { $Global:stop = $true; return }   # end of the test clip
    try { $Global:engine.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple) }
    catch { Write-Log "restart failed: $_" }
} | Out-Null

$engine.RecognizeAsync([System.Speech.Recognition.RecognizeMode]::Multiple)
try { [JarvisWin]::StayAwake() } catch { Write-Log "keep-awake failed: $_" }
Write-Status 'listening' ''
Write-Log "started (mode=$($Global:mode), engine=$($Global:engineName), pid=$PID)"

if ($SelfTest) {
    Start-Sleep -Seconds 4
    try { $engine.RecognizeStopAsync() } catch {}
    Write-Status 'selftest-ok' ''
    Write-Log 'self test passed'
    exit 0
}

$lastBeat = Get-Date
while ($true) {
    Start-Sleep -Milliseconds 500
    if ($Global:stop) { Write-Log 'stopped'; break }
    if ($Global:awake -and (Get-Date) -gt $Global:awakeUntil) {
        $Global:awake = $false
        Write-Status 'listening' ''
    }
    if (((Get-Date) - $lastBeat).TotalSeconds -ge 10) {
        $lastBeat = Get-Date
        Write-Status $(if ($Global:awake) { 'armed' } else { 'listening' }) ''
    }
}
Start-Sleep -Seconds 1
