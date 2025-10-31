# ejecutar_paralelo.ps1
$numEjecuciones = 10
$scriptPath = "risk_classifier_only_text.py"
$workingDir = "C:\Users\ASUS VIVOBOOK PRO\tff-bgchecker\GPT"

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Ejecutando $numEjecuciones instancias en paralelo" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

$startTime = Get-Date

# Crear jobs en paralelo con seguimiento de tiempo
$jobs = 1..$numEjecuciones | ForEach-Object {
    $id = $_
    Start-Job -ScriptBlock {
        param($scriptPath, $workingDir, $id)
        
        # Configurar UTF-8 para evitar problemas con emojis
        $env:PYTHONIOENCODING = "utf-8"
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        
        # Cambiar al directorio correcto
        Set-Location $workingDir
        
        $processStart = Get-Date
        $output = python $scriptPath 2>&1
        $processEnd = Get-Date
        $processDuration = $processEnd - $processStart
        
        return @{
            Id = $id
            Output = $output
            ExitCode = $LASTEXITCODE
            Duration = $processDuration.TotalSeconds
            StartTime = $processStart
            EndTime = $processEnd
        }
    } -ArgumentList $scriptPath, $workingDir, $id -Name "Proceso_$id"
}

Write-Host "OK $numEjecuciones procesos iniciados`n" -ForegroundColor Green

# Monitorear progreso
while ($jobs | Where-Object { $_.State -eq 'Running' }) {
    $running = ($jobs | Where-Object { $_.State -eq 'Running' }).Count
    $completed = $numEjecuciones - $running
    $elapsed = (Get-Date) - $startTime
    Write-Host "`r[Progreso] Completados: $completed/$numEjecuciones | Tiempo transcurrido: $($elapsed.ToString('mm\:ss'))" -NoNewline
    Start-Sleep -Seconds 2
}

Write-Host "`n`nOK Todas las ejecuciones completadas`n" -ForegroundColor Green

# Recopilar resultados
$results = $jobs | Receive-Job -Wait -AutoRemoveJob

$endTime = Get-Date
$duration = $endTime - $startTime

# Mostrar resumen
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "RESUMEN DE EJECUCION" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Tiempo total: $($duration.ToString('hh\:mm\:ss'))"

# Calcular estadísticas de tiempo
$successfulResults = $results | Where-Object { $_.ExitCode -eq 0 }
if ($successfulResults) {
    $avgTime = ($successfulResults | Measure-Object -Property Duration -Average).Average
    $minTime = ($successfulResults | Measure-Object -Property Duration -Minimum).Minimum
    $maxTime = ($successfulResults | Measure-Object -Property Duration -Maximum).Maximum
    
    Write-Host "Tiempo promedio por proceso: $([math]::Round($avgTime, 2))s"
    Write-Host "Tiempo mas rapido: $([math]::Round($minTime, 2))s"
    Write-Host "Tiempo mas lento: $([math]::Round($maxTime, 2))s"
}

Write-Host "`nResultados por proceso:" -ForegroundColor Yellow
Write-Host "---------------------------------------------------------------" -ForegroundColor Gray
Write-Host " ID | Estado | Tiempo   | Inicio    | Fin      " -ForegroundColor Gray
Write-Host "---------------------------------------------------------------" -ForegroundColor Gray

foreach ($result in $results | Sort-Object { $_.Id }) {
    $status = if ($result.ExitCode -eq 0) { "OK " } else { "ERR" }
    $timeStr = if ($result.Duration) { "$([math]::Round($result.Duration, 1))s" } else { "N/A" }
    $startStr = if ($result.StartTime) { $result.StartTime.ToString("HH:mm:ss") } else { "N/A" }
    $endStr = if ($result.EndTime) { $result.EndTime.ToString("HH:mm:ss") } else { "N/A" }
    
    $color = if ($result.ExitCode -eq 0) { "Green" } else { "Red" }
    Write-Host ("{0,3} | {1,6} | {2,8} | {3,9} | {4,9}" -f $result.Id, $status, $timeStr, $startStr, $endStr) -ForegroundColor $color
}

Write-Host "---------------------------------------------------------------" -ForegroundColor Gray

# Cambiar al directorio de trabajo para guardar logs ahí
Set-Location $workingDir

# Guardar logs
Write-Host "`nGuardando logs..." -ForegroundColor Yellow
$results | ForEach-Object {
    $_.Output | Out-File "log_proceso_$($_.Id).txt" -Encoding utf8
}

# Guardar resumen detallado en JSON
$summaryData = @{
    num_ejecuciones = $numEjecuciones
    tiempo_total_segundos = $duration.TotalSeconds
    tiempo_total_formato = $duration.ToString('hh\:mm\:ss')
    procesos = $results | ForEach-Object {
        @{
            id = $_.Id
            exitoso = ($_.ExitCode -eq 0)
            duracion_segundos = $_.Duration
            hora_inicio = if ($_.StartTime) { $_.StartTime.ToString("yyyy-MM-dd HH:mm:ss") } else { $null }
            hora_fin = if ($_.EndTime) { $_.EndTime.ToString("yyyy-MM-dd HH:mm:ss") } else { $null }
            exit_code = $_.ExitCode
        }
    }
}

$summaryData | ConvertTo-Json -Depth 3 | Out-File "resumen_ejecucion_paralela.json" -Encoding utf8

Write-Host "OK Logs guardados en: $workingDir\log_proceso_*.txt" -ForegroundColor Green
Write-Host "OK Resumen guardado en: $workingDir\resumen_ejecucion_paralela.json`n" -ForegroundColor Green