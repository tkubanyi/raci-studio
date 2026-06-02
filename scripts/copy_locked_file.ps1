param(
    [string]$Source,
    [string]$Destination
)

$stream = [System.IO.File]::Open(
    $Source,
    [System.IO.FileMode]::Open,
    [System.IO.FileAccess]::Read,
    [System.IO.FileShare]::ReadWrite
)
try {
    $ms = New-Object System.IO.MemoryStream
    $stream.CopyTo($ms)
    [System.IO.File]::WriteAllBytes($Destination, $ms.ToArray())
    Write-Output "Copied $($ms.Length) bytes"
}
finally {
    $stream.Close()
}
