# Reproduce the selected submission from a fresh PowerShell session.
$ErrorActionPreference = "Stop"

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .

python -m pytest -q
python -m procurement_desk evaluate-sample
python -m procurement_desk run --run-id reproduce-final --workers 8 --no-cache
python -m procurement_desk validate-submission

Get-FileHash output/submission.csv -Algorithm SHA256
