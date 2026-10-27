Option Explicit
Dim shell, fso, base, pythonExe, runner
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = base
pythonExe = base & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(pythonExe) Then
  MsgBox "Run install.bat first to install required components.", 48, "CapCut Auto Editor"
Else
  runner = Chr(34) & pythonExe & Chr(34) & " " & Chr(34) & base & "\app.py" & Chr(34)
  shell.Run runner, 0, False
End If
