# Application du correctif métier — notary_rag_app_prompt2
# Exécuter depuis la racine du projet existant, après sauvegarde.
$ErrorActionPreference = 'Stop'
$Root = (Get-Location).Path
$Bundle = Join-Path $Root 'notary_rag_app_prompt2_correctif_metier.zip'
$tmp = Join-Path $env:TEMP 'notary_rag_correctif_metier'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -LiteralPath $Bundle -DestinationPath $tmp -Force
Copy-Item (Join-Path $tmp 'app\services\fact_extraction.py') (Join-Path $Root 'app\services\fact_extraction.py') -Force
Copy-Item (Join-Path $tmp 'tests\test_rag_metier_roles_et_prudence.py') (Join-Path $Root 'tests\test_rag_metier_roles_et_prudence.py') -Force
Write-Host 'Correctif applique. Aucun fichier data/, DOCX, chunks, collection Qdrant ou embedding n est remplace par ce bundle.'
Write-Host 'Validation a executer depuis la racine avec votre interpreteur local :'
Write-Host '& $PY -m pytest .\tests -q'
Write-Host '& $PY .\scripts\run_representative_tests.py'
Write-Host '& $PY -m app.cli diagnose'
