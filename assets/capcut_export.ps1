$ErrorActionPreference='Stop'
[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$errWriter=New-Object System.IO.StreamWriter([Console]::OpenStandardError(),[System.Text.UTF8Encoding]::new($false))
$errWriter.AutoFlush=$true
[Console]::SetError($errWriter)
$stage='initialization'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$req=[Console]::In.ReadLine() | ConvertFrom-Json
$project=[string]$req.project
$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=[System.Windows.Automation.Condition]::TrueCondition
$child=[System.Windows.Automation.TreeScope]::Children
$desc=[System.Windows.Automation.TreeScope]::Descendants
$script:scopePid=0
$script:scopeHandle=0
$script:dialogHandles=@()
function Windows {
    $ids=@(Get-Process -Name CapCut -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
    @($root.FindAll($child,$all) | Where-Object {
        try { $ids -contains $_.Current.ProcessId -and !$_.Current.IsOffscreen } catch {$false}
    })
}
function Elements {
    foreach($w in @(Windows)) {
        if($script:scopePid -and $w.Current.ProcessId -ne $script:scopePid){continue}
        if($script:scopeHandle -and $w.Current.NativeWindowHandle -ne $script:scopeHandle -and $script:dialogHandles -notcontains $w.Current.NativeWindowHandle){continue}
        $w
        foreach($e in $w.FindAll($desc,$all)) {
            try {if(!$e.Current.IsOffscreen -and $e.Current.IsEnabled){$e}} catch {}
        }
    }
}
function Normal-Name([string]$name) {
    return (($name.Normalize([System.Text.NormalizationForm]::FormKC) -replace '[\u200B-\u200F\u202A-\u202E\u2060\uFEFF]','' -replace '[\u2010-\u2015\u2212]','-' -replace '\s+',' ').Trim())
}
function Find([string[]]$names,[string[]]$types) {
    @(Elements | Where-Object {
        try {($names -contains $_.Current.Name.Trim()) -and ($types.Count -eq 0 -or $types -contains $_.Current.ControlType.ProgrammaticName)} catch {$false}
    })
}
function Unique([string[]]$names,[string[]]$types,[int]$seconds=12) {
    $until=[DateTime]::UtcNow.AddSeconds($seconds)
    do {
        $found=@(Find $names $types)
        if($found.Count -eq 1){return $found[0]}
        Start-Sleep -Milliseconds 400
    } while([DateTime]::UtcNow -lt $until)
    throw ('Cannot uniquely identify CapCut control: '+($names -join '/'))
}
function Invoke-Control($e) {
    $p=$null
    if(!$e.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$p)){throw ('No safe Invoke pattern: '+$e.Current.Name)}
    $p.Invoke()
}
function Value($e) {
    $p=$null
    if($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$p)){return [string]$p.Current.Value}
    if($e.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern,[ref]$p)){return (@($p.Current.GetSelection() | ForEach-Object {$_.Current.Name}) -join '')}
    return ''
}
function Set-Field([string[]]$names,[string]$value) {
    $e=Unique $names @('ControlType.Edit')
    $p=$null
    if(!$e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$p) -or $p.Current.IsReadOnly){throw ('Cannot set '+$names[0])}
    $p.SetValue($value)
    if((Value $e) -ne $value){throw ('Cannot verify '+$names[0])}
}
function Select-Option([string[]]$labels,[string[]]$options) {
    $e=Unique $labels @('ControlType.ComboBox')
    if($options -contains (Value $e)){return}
    $p=$null
    if(!$e.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$p)){throw ('Cannot expand '+$labels[0])}
    $p.Expand()
    $item=Unique $options @('ControlType.ListItem','ControlType.MenuItem','ControlType.Button','ControlType.RadioButton') 5
    $sel=$null
    if($item.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$sel)){$sel.Select()}else{Invoke-Control $item}
    Start-Sleep -Milliseconds 350
    if(!($options -contains (Value $e))){throw ('Cannot verify '+$labels[0])}
}
function Project-Windows {
    $titles=@($project,($project+' - CapCut'),('CapCut - '+$project),($project+' | CapCut'),('CapCut | '+$project))
    $normalized=@($titles | ForEach-Object {Normal-Name $_})
    @(Windows | Where-Object {$normalized -contains (Normal-Name $_.Current.Name)})
}
function Find-ProjectCards {
    # CapCut builds expose project titles as Text/Custom elements as well as ListItem.
    # Only accept exact normalized names, never choose another project by position.
    $expected=Normal-Name $project
    $walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
    $cards=@{}
    foreach($e in @(Elements)){
        try {
            if((Normal-Name $e.Current.Name) -ne $expected){continue}
            $node=$e
            for($depth=0;$depth -lt 5 -and $null -ne $node;$depth++){
                if($node.Current.ControlType.ProgrammaticName -in @('ControlType.Window','ControlType.Pane')){break}
                $pattern=$null
                if($node.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern,[ref]$pattern)){
                    $key=$node.GetRuntimeId() -join ','
                    $cards[$key]=$node;break
                }
                $node=$walker.GetParent($node)
            }
        } catch {}
    }
    @($cards.Values)
}
function Open-ExactProject {
    $until=[DateTime]::UtcNow.AddSeconds(35)
    do {
        if(@(Project-Windows).Count -eq 1){return}
        $cards=@(Find-ProjectCards)
        if($cards.Count -eq 1){Invoke-Control $cards[0];return}
        Start-Sleep -Milliseconds 700
    } while([DateTime]::UtcNow -lt $until)
    # If CapCut was left on its cached home page, request a restart instead of
    # closing an editor with possibly unsaved changes or guessing a project.
    throw 'Project card not found or ambiguous. Close CapCut normally, reopen it so the local list refreshes, open this exact project and retry export from Studio.'
}

try {
    if($req.mode -eq 'close'){
        $w=@(Project-Windows)
        if($w.Count -ne 1){$stage='close exact project';throw 'Exact project window unavailable.'}
        if($w.Count -eq 1){
            # Close only the successfully exported project through its normal window pattern.
            # No forced process termination and no dismissal of save prompts.
            $p=$null
            if($w[0].TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern,[ref]$p)){$p.Close()}else{$stage='close exact project';throw 'Exact project has no close pattern.'}
        }
        Write-Output 'CLOSE_ATTEMPTED';exit 0
    }
    $stage='launch CapCut'
    if(@(Windows).Count -eq 0){
        $apps=Join-Path $env:LOCALAPPDATA 'CapCut\Apps'
        $exe=Join-Path $apps 'CapCut.exe'
        if(!(Test-Path $exe)){
            $exe=Get-ChildItem $apps -Directory -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | ForEach-Object {Join-Path $_.FullName 'CapCut.exe'} | Where-Object {Test-Path $_} | Select-Object -First 1
            if(!$exe){throw 'Open CapCut Desktop manually first.'}
        }
        Start-Process -FilePath $exe
        $until=[DateTime]::UtcNow.AddSeconds(45)
        while(@(Windows).Count -eq 0 -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 500}
    }
    $stage='open exact project'
    if(@(Project-Windows).Count -ne 1){
        Open-ExactProject
        $until=[DateTime]::UtcNow.AddSeconds(35)
        while(@(Project-Windows).Count -ne 1 -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 500}
    }
    if(@(Project-Windows).Count -ne 1){throw 'Cannot verify exact project window title. Open the intended project manually and retry; no export was started.'}
    $stage='find editor export button'
    $target=@(Project-Windows)[0]
    $script:scopePid=$target.Current.ProcessId
    $script:scopeHandle=$target.Current.NativeWindowHandle
    if(!$script:scopeHandle){throw 'Cannot identify the project window handle.'}
    $before=@(Windows | ForEach-Object {$_.Current.NativeWindowHandle})
    $export=Unique @('Export','Экспорт','Экспортировать') @('ControlType.Button') 10
    Invoke-Control $export
    Start-Sleep -Milliseconds 800
    # Allow only the exact project window or a newly appeared dialog of its own process.
    $script:dialogHandles=@(Windows | Where-Object {$_.Current.ProcessId -eq $script:scopePid -and $before -notcontains $_.Current.NativeWindowHandle} | ForEach-Object {$_.Current.NativeWindowHandle})
    $stage='resolution 1080p'
    Select-Option @('Resolution','Разрешение') @('1080P','1080p','1080 P')
    $stage='frame rate 30 fps'
    Select-Option @('Frame rate','Frame Rate','Частота кадров') @('30fps','30 fps','30 FPS','30')
    $stage='MP4 format'
    Select-Option @('Format','Формат') @('MP4','mp4')
    $stage='output filename'
    Set-Field @('Name','File name','Название','Имя','Имя файла') 'video'
    $stage='output folder'
    Set-Field @('Export to','Export To','Save to','Экспорт в','Сохранить в','Путь экспорта') ([string]$req.folder)
    $stage='confirm native export'
    $button=Unique @('Export','Экспорт','Экспортировать') @('ControlType.Button') 10
    Invoke-Control $button
    Write-Output 'EXPORT_STARTED'
} catch {
    [Console]::Error.WriteLine('STAGE: '+$stage+' | '+$_.Exception.Message)
    try {
        $ids=@(Get-Process -Name CapCut -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
        [Console]::Error.WriteLine('CapCut process count: '+$ids.Count)
        foreach($w in @(Windows)){
            [Console]::Error.WriteLine('WINDOW: '+$w.Current.Name+' | '+$w.Current.ClassName)
        }
        # Read only the visible accessibility control labels and types, never input values.
        $controls=@(Elements | Select-Object -First 180)
        foreach($e in $controls){
            try {
                if($e.Current.ControlType.ProgrammaticName -in @('ControlType.Button','ControlType.ComboBox','ControlType.Edit','ControlType.ListItem','ControlType.DataItem','ControlType.MenuItem','ControlType.Window')){
                    [Console]::Error.WriteLine('CONTROL: '+$e.Current.ControlType.ProgrammaticName+' | '+$e.Current.Name+' | '+$e.Current.AutomationId)
                }
            } catch {}
        }
    } catch {}
    exit 1
}
