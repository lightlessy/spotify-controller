Option Explicit
Dim shell, fso, folder, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /c cd /d """ & folder & """ && "".venv\Scripts\pythonw.exe"" calibrated_detector.py"
shell.Run command, 0, False
