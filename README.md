# US Labor Statistics Dashboard (BLS)

This repo contains:
- A Streamlit dashboard (`app.py`) that reads a local dataset in `data/bls_monthly.csv`
- A monthly GitHub Action that updates that dataset from the BLS Public Data API

## Quick start (local)
```bash
python -m venv .venv
source .venv/bin/activate  # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt

python -m src.update_data
streamlit run app.py
