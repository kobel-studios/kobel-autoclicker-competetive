$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [System.Environment]::GetFolderPath("Desktop")
$Shortcut = $WshShell.CreateShortcut("$Desktop\Kobel Autoclicker.lnk")
$Shortcut.TargetPath = "pythonw.exe"
$Shortcut.Arguments = "`"C:\Users\jacks\CascadeProjects\autoclicker-hub\autoclicker_hub.py`""
$Shortcut.WorkingDirectory = "C:\Users\jacks\CascadeProjects\autoclicker-hub"
$Shortcut.IconLocation = "C:\Users\jacks\CascadeProjects\autoclicker-hub\kobel_icon.ico"
$Shortcut.Description = "Kobel Autoclicker - Competitive Clicking"
$Shortcut.Save()
Write-Host "Shortcut created on Desktop"
