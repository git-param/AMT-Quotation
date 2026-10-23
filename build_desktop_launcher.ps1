# Build once on a Windows developer PC. Employees receive only the resulting EXE.
$source = Join-Path $PSScriptRoot 'desktop_launcher\Program.cs'
$outputDir = Join-Path $PSScriptRoot 'dist'
$output = Join-Path $outputDir 'AMTQuotationLauncher.exe'
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
Add-Type -Path $source -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'System.Windows.Forms.dll') `
    -OutputAssembly $output -OutputType WindowsApplication -ErrorAction Stop
Write-Output "Built $output"
