#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "UPI fraud console - startup"

if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

if [ ! -f "data/transactions.db" ]; then
  echo "No dataset found - generating one..."
  python3 -c "
from fastapi.testclient import TestClient
from mock_api.app import app
c = TestClient(app)
print(c.post('/simulate', params={'num_days':14,'normal_txns_per_day':800,'num_schemes':3}).json())
"
fi

echo ""
echo "Opening dashboard at http://localhost:8501"
echo "Press Ctrl+C to stop."
echo ""
PYTHONPATH=. streamlit run dashboard/app.py
