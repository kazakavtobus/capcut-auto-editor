$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$req=[Console]::In.ReadLine() | ConvertFrom-Json
$project=[string]$req.project
$root=[System.Windows.Automation.AutomationElement]::RootElement
$all=[System.Windows.Automation.Condition]::TrueCondition
$child=[System.Windows.Automation.TreeScope]::Children
$desc=[System.Windows.Automation.TreeScope]::Descendants
function Windows {
    $ids=@(Get-Process -Name CapCut -ErrorAction SilentlyContinue | ForEach-Object {$_.Id})
    @($root.FindAll($child,$all) | Where-Object {
        try { $ids -contains $_.Current.ProcessId -and !$_.Current.IsOffscreen } catch {$false}
    })
}
function Elements {
    foreach($w in @(Windows)) {
        $w
        foreach($e in $w.FindAll($desc,$all)) {
            try {if(!$e.Current.IsOffscreen -and $e.Current.IsEnabled){$e}} catch {}
        }
    }
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
    $titles=@($project,($project+' - CapCut'),('CapCut - '+$project),($project+' – CapCut'),('CapCut – '+$project))
    @(Windows | Where-Object {$titles -contains $_.Current.Name.Trim()})
}
try {
    if($req.mode -eq 'close'){
        $w=@(Project-Windows)
        if($w.Count -eq 1){
            # Close only the successfully exported project through its normal window pattern.
            # No forced process termination and no dismissal of save prompts.
            $done=@(Find @('Done','Готово') @('ControlType.Button'))
            if($done.Count -eq 1){Invoke-Control $done[0];Start-Sleep -Milliseconds 500}
            $p=$null
            if($w[0].TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern,[ref]$p)){$p.Close()}
        }
        Write-Output 'CLOSE_ATTEMPTED';exit 0
    }
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
    if(@(Project-Windows).Count -ne 1){
        $open=Unique @($project) @('ControlType.ListItem','ControlType.DataItem','ControlType.Button','ControlType.Hyperlink') 10
        Invoke-Control $open
        $until=[DateTime]::UtcNow.AddSeconds(35)
        while(@(Project-Windows).Count -ne 1 -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 500}
    }
    if(@(Project-Windows).Count -ne 1){throw 'Cannot verify exact project window title. Open the intended project manually.'}
    $export=Unique @('Export','Экспорт','Экспортировать') @('ControlType.Button') 10
    Invoke-Control $export
    Select-Option @('Resolution','Разрешение') @('1080P','1080p','1080 P')
    Select-Option @('Frame rate','Frame Rate','Частота кадров') @('30fps','30 fps','30 FPS','30')
    Select-Option @('Format','Формат') @('MP4','mp4')
    Set-Field @('Name','File name','Название','Имя','Имя файла') 'video'
    Set-Field @('Export to','Export To','Save to','Экспорт в','Сохранить в','Путь экспорта') ([string]$req.folder)
    $button=Unique @('Export','Экспорт','Экспортировать') @('ControlType.Button') 10
    Invoke-Control $button
    Write-Output 'EXPORT_STARTED'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
