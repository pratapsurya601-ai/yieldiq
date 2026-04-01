# 📊 AI DCF Stock Screener

An AI-powered stock valuation platform that automatically identifies undervalued stocks using **Discounted Cash Flow (DCF)** modelling and **Machine Learning** forecasting.

---

## 🏗️ Project Structure

```
ai_dcf_screener/
│
├── data/
│   ├── collector.py        ← Yahoo Finance data fetching
│   ├── processor.py        ← Metric derivation (growth rates, margins)
│   └── tickers.csv         ← Default ticker list (40 US stocks)
│
├── models/
│   └── forecaster.py       ← AI FCF forecaster (LR + Random Forest + Rules)
│
├── screener/
│   ├── dcf_engine.py       ← Full DCF calculation engine
│   └── stock_screener.py   ← Batch screening orchestrator + alert system
│
├── dashboard/
│   └── app.py              ← Streamlit web dashboard
│
├── utils/
│   ├── config.py           ← All tunable parameters
│   └── logger.py           ← Logging setup
│
├── main.py                 ← CLI entry point
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Analyse a single stock (CLI)

```bash
python main.py --ticker AAPL
python main.py --ticker MSFT
python main.py --ticker RELIANCE.NS   # NSE India
```

### 3. Run the batch screener

```bash
# Screen default 40 tickers
python main.py --screen

# Use your own ticker list
python main.py --screen --tickers my_tickers.csv

# Customise DCF parameters
python main.py --screen --discount-rate 0.12 --terminal-growth 0.03
```

### 4. Launch the web dashboard

```bash
streamlit run dashboard/app.py
```

Open your browser at: **http://localhost:8501**

---

## ⚙️ DCF Model

### Valuation Steps

| Step | Formula |
|------|---------|
| Project FCF (10 years) | AI Forecaster (LR + RF + Heuristic blend) |
| Terminal Value | `FCF_n × (1 + g) / (r - g)` |
| Enterprise Value | `PV(FCFs) + PV(Terminal Value)` |
| Equity Value | `Enterprise Value − Total Debt + Cash` |
| Intrinsic Value | `Equity Value / Shares Outstanding` |
| Margin of Safety | `(IV − Price) / IV` |

### Default Parameters

| Parameter | Default | Flag |
|-----------|---------|------|
| Discount Rate (WACC) | 10% | `--discount-rate` |
| Terminal Growth Rate | 2.5% | `--terminal-growth` |
| Forecast Horizon | 10 years | Config |

---

## 🚦 Signals

| Signal | Condition |
|--------|-----------|
| 🟢 BUY | Margin of Safety > 30% |
| 🟡 WATCH | MoS 10–30% |
| 🔵 HOLD | MoS 0–10% |
| 🔴 SELL | MoS < 0% |
| 🚨 STRONG BUY | MoS > 40% (printed alert) |

---

## 🤖 AI Forecasting

The `FCFForecaster` blends three models:

1. **Ridge Regression** (35%) — captures linear growth trend
2. **Random Forest** (35%) — captures non-linear patterns
3. **Rule-Based Heuristic** (30%) — mean-reverting CAGR model

Growth fades from the predicted base rate → 3% terminal growth by Year 10 (analyst-style fade model).

---

## 📄 Ticker CSV Format

```csv
ticker
AAPL
MSFT
INFY.NS
RELIANCE.NS
```

---

## ⚠️ Disclaimer

This tool is for **educational and research purposes only** and does **not** constitute financial advice. DCF models are highly sensitive to input assumptions. Always perform your own due diligence before making investment decisions.

---

## 🛠️ Tech Stack

- **Python 3.10+**
- **yfinance** — financial data
- **pandas / numpy** — data processing
- **scikit-learn** — ML models
- **Streamlit** — web dashboard
- **Plotly** — interactive charts
