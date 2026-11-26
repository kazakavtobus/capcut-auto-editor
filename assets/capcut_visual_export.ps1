# Windows PowerShell 5.1; local OCR fallback for inaccessible CapCut QML controls.
# No fixed screen coordinates; refuse to export unless exact project and settings are verified.
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$writer=[IO.StreamWriter]::new([Console]::OpenStandardError(),[Text.UTF8Encoding]::new($false))
$writer.AutoFlush=$true
[Console]::SetError($writer)
$stage='visual initialization'
$req=[Console]::In.ReadLine() | ConvertFrom-Json
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class VisualWin {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X,Y; }
    public delegate bool EnumProc(IntPtr h,IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f,IntPtr l);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
    [DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
    [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint x,uint y,uint d,UIntPtr extra);
    public static IntPtr[] Visible() {
        var list=new List<IntPtr>(); EnumWindows((h,l)=>{if(IsWindowVisible(h))list.Add(h);return true;},IntPtr.Zero); return list.ToArray();
    }
    public static uint Pid(IntPtr h){uint p; GetWindowThreadProcessId(h,out p);return p;}
    public static string Class(IntPtr h){var s=new StringBuilder(512);GetClassName(h,s,s.Capacity);return s.ToString();}
    public static uint PointPid(int x,int y){var p=new POINT{X=x,Y=y};return Pid(WindowFromPoint(p));}
}
'@
$null=[VisualWin]::SetThreadDpiAwarenessContext([IntPtr](-4))
$null=[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime]
$null=[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq ('IAsyncOperation' + [char]96 + '1')
} | Select-Object -First 1
if(!$asTask){throw 'Windows OCR async bridge unavailable.'}
function Await-Result($operation,[type]$type) {
    $task=$asTask.MakeGenericMethod($type).Invoke($null,@($operation))
    if(!$task.Wait(15000)){throw 'Windows OCR timed out.'}
    return $task.Result
}
$lang=[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Where-Object {$_.LanguageTag -like 'ru*'} | Select-Object -First 1
if(!$lang){throw 'Windows OCR: install Russian language OCR in Windows language settings.'}
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if(!$engine){throw 'Cannot initialize Russian Windows OCR.'}
function Norm([string]$s) {
    (($s.Normalize([Text.NormalizationForm]::FormKC) -replace '[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]','' -replace '[\u2010-\u2015\u2212]','-' -replace '\s+','').ToLowerInvariant())
}
function CapCut-Pid([IntPtr]$h) {
    if($h -eq [IntPtr]::Zero){return $false}
    $p=Get-Process -Id ([VisualWin]::Pid($h)) -ErrorAction SilentlyContinue
    return ($null -ne $p -and $p.ProcessName -eq 'CapCut')
}
function Active-CapCut {
    $h=[VisualWin]::GetForegroundWindow()
    if(!(CapCut-Pid $h)){throw 'CapCut must remain in the foreground during visual export.'}
    return $h
}
function Bring-CapCut {
    $h=[VisualWin]::GetForegroundWindow()
    if(CapCut-Pid $h){return}
    $wins=@([VisualWin]::Visible() | Where-Object {(CapCut-Pid $_) -and [VisualWin]::Class($_) -match '^(MainWindow|HomePageX)_QMLTYPE_'})
    $editors=@($wins | Where-Object {[VisualWin]::Class($_) -like 'MainWindow_QMLTYPE_*'})
    if($editors.Count -eq 1){$wins=$editors}
    if($wins.Count -ne 1){throw 'Open the intended CapCut project or home window and retry.'}
    if([VisualWin]::IsIconic($wins[0])){$null=[VisualWin]::ShowWindow($wins[0],9)}
    $null=[VisualWin]::SetForegroundWindow($wins[0])
    Start-Sleep -Milliseconds 500
    $null=Active-CapCut
}
function Read-Frame {
    $h=Active-CapCut
    $r=New-Object VisualWin+RECT
    if(![VisualWin]::GetWindowRect($h,[ref]$r)){throw 'Cannot locate CapCut window.'}
    $w=$r.Right-$r.Left;$height=$r.Bottom-$r.Top
    if($w -lt 250 -or $height -lt 250){throw 'CapCut window is too small.'}
    $bounds=[Windows.Forms.SystemInformation]::VirtualScreen
    if($r.Left -lt $bounds.Left -or $r.Top -lt $bounds.Top -or $r.Right -gt $bounds.Right -or $r.Bottom -gt $bounds.Bottom){throw 'Keep the full CapCut window on screen.'}
    $scale=[Math]::Min(2.0,[double][Windows.Media.Ocr.OcrEngine]::MaxImageDimension/[Math]::Max($w,$height))
    $bmp=[Drawing.Bitmap]::new($w,$height)
    $g=[Drawing.Graphics]::FromImage($bmp)
    $img=$null;$g2=$null;$stream=$null;$bitmap=$null
    $tmp=Join-Path ([IO.Path]::GetTempPath()) ('studio-ocr-'+[guid]::NewGuid().ToString('N')+'.png')
    try {
        $g.CopyFromScreen($r.Left,$r.Top,0,0,$bmp.Size)
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed while capturing.'}
        $img=[Drawing.Bitmap]::new([int]($w*$scale),[int]($height*$scale))
        $g2=[Drawing.Graphics]::FromImage($img)
        $g2.InterpolationMode=[Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g2.DrawImage($bmp,0,0,$img.Width,$img.Height)
        $img.Save($tmp,[Drawing.Imaging.ImageFormat]::Png)
        $file=Await-Result ([Windows.Storage.StorageFile]::GetFileFromPathAsync($tmp)) ([Windows.Storage.StorageFile])
        $stream=Await-Result ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder=Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap=Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocr=Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $lines=@(foreach($line in $ocr.Lines){
            $words=@(foreach($word in $line.Words){
                $b=$word.BoundingRect
                [pscustomobject]@{Text=$word.Text;X=$b.X/$scale;Y=$b.Y/$scale;Right=($b.X+$b.Width)/$scale;Bottom=($b.Y+$b.Height)/$scale}
            })
            if($words.Count){[pscustomobject]@{Text=$line.Text;Words=$words}}
        })
        return [pscustomobject]@{Handle=$h;Left=$r.Left;Top=$r.Top;Width=$w;Height=$height;Lines=$lines}
    } finally {
        if($bitmap){$bitmap.Dispose()};if($stream){$stream.Dispose()}
        if($g2){$g2.Dispose()};if($img){$img.Dispose()};$g.Dispose();$bmp.Dispose()
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}
function Box($words) {
    [pscustomobject]@{
        X=($words | Measure-Object X -Minimum).Minimum
        Y=($words | Measure-Object Y -Minimum).Minimum
        Right=($words | Measure-Object Right -Maximum).Maximum
        Bottom=($words | Measure-Object Bottom -Maximum).Maximum
        Text=($words.Text -join ' ')
    }
}
function Matches($frame,[string[]]$names,[double]$minX=0,[double]$minY=0,[double]$maxX=100000,[double]$maxY=100000) {
    $norms=@($names | ForEach-Object {Norm $_})
    foreach($line in $frame.Lines){
        $words=@($line.Words | Where-Object {$_.X -ge $minX -and $_.Y -ge $minY -and $_.Right -le $maxX -and $_.Bottom -le $maxY})
        for($i=0;$i -lt $words.Count;$i++){
            $text=''
            for($j=$i;$j -lt $words.Count;$j++){
                $text+=Norm $words[$j].Text
                if($norms -contains $text){Box @($words[$i..$j]);break}
                if(!@($norms | Where-Object {$_.StartsWith($text)}).Count){break}
            }
        }
    }
}
function One($items,[string]$description) {
    $a=@($items | Where-Object {$null -ne $_})
    if($a.Count -ne 1){throw ('Cannot uniquely recognize '+$description+' ('+$a.Count+').')}
    return $a[0]
}
function Click($frame,[double]$x,[double]$y) {
    $h=Active-CapCut
    if($h -ne $frame.Handle){throw 'CapCut window changed before click.'}
    $rect=New-Object VisualWin+RECT
    if(![VisualWin]::GetWindowRect($h,[ref]$rect) -or $rect.Left -ne $frame.Left -or $rect.Top -ne $frame.Top -or ($rect.Right-$rect.Left) -ne $frame.Width -or ($rect.Bottom-$rect.Top) -ne $frame.Height){throw 'CapCut moved before click.'}
    if($x -lt 0 -or $y -lt 0 -or $x -ge $frame.Width -or $y -ge $frame.Height){throw 'Click would leave CapCut window.'}
    $sx=[int]($frame.Left+$x);$sy=[int]($frame.Top+$y)
    if([VisualWin]::PointPid($sx,$sy) -ne [VisualWin]::Pid($h)){throw 'Another window covers the CapCut control.'}
    $null=[VisualWin]::SetCursorPos($sx,$sy)
    [VisualWin]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    [VisualWin]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 400
}
function Click-Box($frame,$box){Click $frame (($box.X+$box.Right)/2) (($box.Y+$box.Bottom)/2)}
function Dialog-Title($frame) {
    $name=[string]$req.project
    $titles=@(('Экспорт-'+$name),('Экспорт '+$name),('Экспорт: '+$name),('Export-'+$name),('Export '+$name),('Export: '+$name)) | ForEach-Object {Norm $_}
    @(foreach($line in $frame.Lines){
        if($titles -contains (Norm ($line.Words.Text -join ' '))){Box $line.Words}
    })
}
function Require-Dialog($frame) {
    $null=One (Dialog-Title $frame) 'exact export dialog project title'
    $null=One (Matches $frame @('Разрешение','Resolution')) 'resolution label'
    $null=One (Matches $frame @('Частота кадров','Frame rate')) 'frame rate label'
}
function Open-Dialog {
    Bring-CapCut
    $frame=Read-Frame
    if(@(Dialog-Title $frame).Count -eq 1){return $frame}
    $cls=[VisualWin]::Class($frame.Handle)
    if($cls -like 'HomePageX_QMLTYPE_*'){
        $stageLocal='home project list'
        $heading=One (Matches $frame @('Проекты','Projects')) $stageLocal
        $items=@(foreach($line in $frame.Lines){
            $words=@($line.Words | Where-Object {$_.Y -gt $heading.Bottom -and $_.Right -lt ($frame.Width*0.66)})
            if($words.Count -and (Norm ($words.Text -join ' ')) -eq (Norm ([string]$req.project))){Box $words}
        })
        $item=One $items 'exact visible project row'
        Click-Box $frame $item
        $deadline=[DateTime]::UtcNow.AddSeconds(25)
        do {
            Start-Sleep -Milliseconds 800
            $h=Active-CapCut
            if([VisualWin]::Class($h) -like 'MainWindow_QMLTYPE_*'){break}
        } while([DateTime]::UtcNow -lt $deadline)
        if([VisualWin]::Class($h) -notlike 'MainWindow_QMLTYPE_*'){throw 'Editor did not open; open exact project manually.'}
        $frame=Read-Frame
    }
    if([VisualWin]::Class($frame.Handle) -notlike 'MainWindow_QMLTYPE_*'){throw 'Expected CapCut editor or export dialog.'}
    $btn=One (Matches $frame @('Экспорт','Export') ($frame.Width*0.65) 0 $frame.Width ($frame.Height*0.12)) 'editor export button'
    Click-Box $frame $btn
    $deadline=[DateTime]::UtcNow.AddSeconds(15)
    do {
        Start-Sleep -Milliseconds 500
        $frame=Read-Frame
        if(@(Dialog-Title $frame).Count -eq 1){return $frame}
    } while([DateTime]::UtcNow -lt $deadline)
    throw 'Cannot verify exact project title in export dialog. No export confirmed.'
}
function Row-Value($frame,[string[]]$labels,[string[]]$values) {
    $label=One (Matches $frame $labels) ($labels[0]+' label')
    $pad=[Math]::Max(10,($label.Bottom-$label.Y)*1.3)
    @(Matches $frame $values ($label.Right+2) ([Math]::Max(0,$label.Y-$pad)) $frame.Width ($label.Bottom+$pad))
}
function Choose-Value($frame,[string[]]$labels,[string[]]$current,[string[]]$wanted) {
    if(@(Row-Value $frame $labels $wanted).Count -eq 1){return $frame}
    $value=One (Row-Value $frame $labels $current) ($labels[0]+' current value')
    Click-Box $frame $value
    $next=Read-Frame
    $option=One (Matches $next $wanted) ($labels[0]+' target option')
    Click-Box $next $option
    $next=Read-Frame
    Require-Dialog $next
    $null=One (Row-Value $next $labels $wanted) ($labels[0]+' verified value')
    return $next
}
function Set-TextField($frame,$label,[double]$fieldX,[string]$value,[bool]$path=$false) {
    # Verify actual clipboard readback, not a truncated OCR rendering.
    $original=[Windows.Forms.Clipboard]::GetDataObject()
    try {
        Click $frame $fieldX (($label.Y+$label.Bottom)/2)
        $h=Active-CapCut
        if($h -ne $frame.Handle){throw 'The field opened a different window; manual folder selection is required.'}
        # First confirm keyboard focus by reading the existing value. A read-only
        # folder picker or an unrelated focused control must not receive pasted text.
        [Windows.Forms.Clipboard]::SetText('studio-before-'+[guid]::NewGuid().ToString())
        [Windows.Forms.SendKeys]::SendWait('^a')
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed.'}
        [Windows.Forms.SendKeys]::SendWait('^c')
        Start-Sleep -Milliseconds 250
        $before=[Windows.Forms.Clipboard]::GetText()
        if($path){
            if($before -notmatch '^(?:[A-Za-z]:[\\/]|\\\\)'){throw 'Cannot read output folder field; choose the folder manually.'}
        } elseif((Norm $before) -ne (Norm ([string]$req.project)) -and $before -cne 'video'){
            throw 'Cannot confirm focus on the intended filename field.'
        }
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed.'}
        [Windows.Forms.Clipboard]::SetText($value)
        [Windows.Forms.SendKeys]::SendWait('^a')
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed.'}
        [Windows.Forms.SendKeys]::SendWait('^v')
        Start-Sleep -Milliseconds 300
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed.'}
        [Windows.Forms.Clipboard]::SetText('studio-readback-'+[guid]::NewGuid().ToString())
        [Windows.Forms.SendKeys]::SendWait('^a')
        if((Active-CapCut) -ne $h){throw 'CapCut focus changed.'}
        [Windows.Forms.SendKeys]::SendWait('^c')
        Start-Sleep -Milliseconds 300
        $actual=[Windows.Forms.Clipboard]::GetText()
        if($path){
            if($actual.Replace('/','\').TrimEnd('\') -ne $value.Replace('/','\').TrimEnd('\')){throw 'Cannot verify output folder. CapCut may use a read-only folder picker.'}
        } elseif($actual -cne $value){throw 'Cannot verify export filename.'}
    } finally {
        if($null -ne $original){[Windows.Forms.Clipboard]::SetDataObject($original,$true)}
        else{[Windows.Forms.Clipboard]::Clear()}
    }
}
try {
    $stage='visual open exact project'
    $frame=Open-Dialog
    Require-Dialog $frame
    $stage='visual resolution'
    $frame=Choose-Value $frame @('Разрешение','Resolution') @('480P','720P','1080P','2K','4K','1440P','2160P') @('1080P','1080 P')
    $stage='visual frame rate'
    $frame=Choose-Value $frame @('Частота кадров','Frame rate') @('24fps','25fps','30fps','50fps','60fps','23.976fps','29.97fps') @('30fps','30 fps')
    $stage='visual MP4 format'
    $frame=Choose-Value $frame @('Формат','Format') @('mp4','mov') @('mp4')
    $stage='visual output filename'
    $column=One (Row-Value $frame @('Разрешение','Resolution') @('1080P','1080 P')) 'settings value column'
    $name=One (Matches $frame @('Имя','Name','File name')) 'filename label'
    Set-TextField $frame $name ($column.X+12) 'video'
    $frame=Read-Frame;Require-Dialog $frame
    $stage='visual output folder'
    $column=One (Row-Value $frame @('Разрешение','Resolution') @('1080P','1080 P')) 'settings value column'
    $folder=One (Matches $frame @('Экспортировать в','Экспортировать...','Экспортирова...','Экспортирова…','Export to','Save to') 0 $name.Bottom $column.X $column.Y) 'output folder label'
    Set-TextField $frame $folder ($column.X+12) ([string]$req.folder) $true
    $frame=Read-Frame;Require-Dialog $frame
    $stage='visual final verification'
    $null=One (Row-Value $frame @('Разрешение','Resolution') @('1080P','1080 P')) '1080p'
    $null=One (Row-Value $frame @('Частота кадров','Frame rate') @('30fps','30 fps')) '30fps'
    $null=One (Row-Value $frame @('Формат','Format') @('mp4')) 'MP4'
    $null=One (Row-Value $frame @('Имя','Name','File name') @('video')) 'output filename'
    $fps=One (Matches $frame @('Частота кадров','Frame rate')) 'frame rate label'
    $confirm=One (Matches $frame @('Экспорт','Export') 0 ($fps.Bottom+12)) 'dialog export confirmation'
    $stage='visual confirm export'
    Click-Box $frame $confirm
    Write-Output 'EXPORT_STARTED'
} catch {
    [Console]::Error.WriteLine('STAGE: '+$stage+' | '+$_.Exception.Message)
    exit 1
}
