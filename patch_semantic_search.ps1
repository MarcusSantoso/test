Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# 경로 설정
$apiPath = ".\src\user_service\api.py"
$backupPath = ".\src\user_service\api.py.bak_semantic"

if (-not (Test-Path $apiPath)) {
    Write-Error "api.py not found at $apiPath"
    exit 1
}

# 백업 생성
Copy-Item $apiPath $backupPath -Force
Write-Host "Backed up api.py to $backupPath"

# 파일 읽기
$apiText = Get-Content $apiPath -Raw
$lines = $apiText -split "`r?`n"

# -----------------------------
# 1) import logging / logger 추가
# -----------------------------
$hasLoggingImport = $apiText -match "import logging"
$hasLogger = $apiText -match "logger\s*=\s*logging\.getLogger\(__name__\)"

# 마지막 import 위치 찾기
$lastImportIndex = -1
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match "^\s*(from|import)\s+") {
        $lastImportIndex = $i
    }
}

if (-not $hasLoggingImport) {
    if ($lastImportIndex -ge 0) {
        $lines = @(
            $lines[0..$lastImportIndex]
            "import logging"
            $lines[($lastImportIndex + 1)..($lines.Length - 1)]
        )
        Write-Host "Inserted 'import logging'"
    } else {
        $lines = @("import logging") + $lines
        Write-Host "Prepended 'import logging'"
    }
}

# logger 정의 추가
$apiText = ($lines -join "`n")
if (-not ($apiText -match "logger\s*=\s*logging\.getLogger\(__name__\)")) {
    # import logging 바로 아래에 넣기
    $lines = $apiText -split "`r?`n"
    $inserted = $false
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match "import logging") {
            $before = $lines[0..$i]
            $after = $lines[($i + 1)..($lines.Length - 1)]
            $lines = @(
                $before
                "logger = logging.getLogger(__name__)"
                $after
            )
            $inserted = $true
            Write-Host "Inserted logger = logging.getLogger(__name__)"
            break
        }
    }
    if (-not $inserted) {
        $lines += "logger = logging.getLogger(__name__)"
        Write-Host "Appended logger definition at end of file"
    }
}

# -----------------------------
# 2) semantic_search import 수정
# -----------------------------
for ($i = 0; $i -lt $lines.Length; $i++) {
    if ($lines[$i] -match "from\s+src\.services\.semantic_search\s+import") {
        if ($lines[$i] -notmatch "recompute_professor_embedding") {
            $lines[$i] = "from src.services.semantic_search import search_professors, recompute_professor_embedding"
            Write-Host "Updated semantic_search import line"
        } else {
            Write-Host "semantic_search import already includes recompute_professor_embedding"
        }
        break
    }
}

$apiText = $lines -join "`n"

# -----------------------------
# 3) create_review 안에 recompute 추가
# -----------------------------
if ($apiText -match "recompute_professor_embedding\s*\(") {
    Write-Host "recompute_professor_embedding already used in api.py; skipping insertion."
} else {
    $lines = $apiText -split "`r?`n"
    $newLines = New-Object System.Collections.Generic.List[string]
    $insertedBlock = $false

    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        $newLines.Add($line)

        if (-not $insertedBlock -and $line -match "db\.refresh\(review\)") {
            # 들여쓰기 가져오기
            $indent = ($line -replace "db\.refresh\(review\).*","")

            $snippet = @"
$indent# 새 리뷰가 들어올 때마다 해당 교수 임베딩 최신화
${indent}try:
${indent}    recompute_professor_embedding(db, professor_id)
${indent}except Exception as e:
${indent}    logger.exception(
${indent}        "Failed to recompute embedding for professor %s: %s",
${indent}        professor_id,
${indent}        e,
${indent}    )
"@

            $snippetLines = $snippet -split "`r?`n" | Where-Object { $_ -ne "" }
            foreach ($sl in $snippetLines) {
                $newLines.Add($sl)
            }

            $insertedBlock = $true
            Write-Host "Inserted recompute_professor_embedding block after db.refresh(review)"
        }
    }

    if (-not $insertedBlock) {
        Write-Warning "Could not find 'db.refresh(review)' to insert recompute block. Please check create_review manually."
    } else {
        $lines = $newLines
    }
}

# -----------------------------
# 4) 파일 저장
# -----------------------------
$finalText = $lines -join "`n"
$finalText | Out-File -FilePath $apiPath -Encoding utf8 -Force

Write-Host ""
Write-Host "Done patching src/user_service/api.py"
Write-Host "Backup: $backupPath"
