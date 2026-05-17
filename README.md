# YieldIQ --- Institutional-Grade Stock Valuation

![Canary streak](https://img.shields.io/badge/canary%20streak-0%2F7%20nights-red) <!-- canary-streak-badge -->

An AI-powered stock valuation platform for US and Indian equities.
Identifies undervalued stocks using DCF modelling, ML forecasting,
and 14 quantitative signals.

## Features
- DCF valuation with edge case handling (negative FCF, IPOs, high debt)
- Piotroski F-Score quality screening
- Economic Moat Engine (5-signal, 100-point scoring)
- Reverse DCF (what growth rate is the market pricing in?)
- Monte Carlo simulation (1,000 scenarios)
- Earnings quality analysis
- Momentum scoring
- Sector heatmap and peer comparison
- AI Analyst chat (Gemini / Groq)
- Portfolio tracker with backtesting
- Price alerts
- PDF and Excel report export
- Google Sheets sync

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up environment variables
```bash
cp .env.example .env
# Edit .env and add your API keys
```

### 3. Run the app
```bash
cd yieldiq_v7
streamlit run dashboard/app.py
```

## Project Structure
```
yieldiq_v7/
├── dashboard/
│   ├── app.py               Main Streamlit entry point
│   ├── auth.py              Authentication + session management
│   ├── tier_gate.py         Free/Starter/Pro tier gating
│   ├── tabs/                Individual page modules (11 tabs)
│   ├── ui/                  Styles, sidebar, helpers
│   └── utils/               Formatting, scoring, chart layouts
├── screener/                14 valuation engine modules
├── models/                  ML forecaster + industry WACC tables
├── data/                    Data collector (Finnhub + yfinance)
├── utils/                   Config + logger
└── tests/                   Test suite
```

## Environment Variables
See `.env.example` for all required and optional API keys.

## Deployment
Deploys to Streamlit Cloud from GitHub.
Add environment variables in App Settings > Secrets.

## Disclaimer
This tool is for educational and research purposes only and does not
constitute financial advice. DCF models are highly sensitive to input
assumptions. Always perform your own due diligence before making
investment decisions.
