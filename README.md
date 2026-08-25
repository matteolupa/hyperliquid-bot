# Hyperliquid 24/7 Algorithmic Trading Bot & Fee Calculator

Progetto Python completo e modulare per il trading quantitativo ed automatico su **Hyperliquid DEX** (Perpetuals & Spot, Testnet e Mainnet).

Include strategie pronte all'uso per generare rendimento 24/7, esecuzione in background (`nohup`), gestione del rischio con circuit breaker, graceful shutdown e calcolo esatto delle commissioni (**fees** & break-even).

---

## 🌟 Strategie Incluse

### 1. 🎯 Scalper & Take-Profit (`--strategy scalper`) - *Consigliata per trade singoli tipo Bybit*
- **Obiettivo**: Acquista un importo fisso (es. **50€ / $50**) su una singola crypto (es. ETH, BTC, SOL) e piazza automaticamente l'ordine di vendita Take-Profit per incassare il profitto netto.
- **Logica**: Appena avviato, calcola al centesimo il prezzo di **Break-Even** con le commissioni di ingresso ed uscita tramite `FeeCalculator`, imposta l'ordine di vendita Take-Profit (es. **+0.8%** o **+1.5%** netto) ed eventuale Stop-Loss.
- **Ciclo continuo**: Appena l'ordine vende in profitto, incassa il guadagno e si rimette subito a caccia del ciclo successivo.

### 2. 🥇 Delta-Neutral Funding Rate Harvester (`--strategy funding`)
- **Obiettivo**: Rendita passiva da tassi orari con esposizione direzionale azzerata.
- **Logica**: Scansiona tutti i mercati perp di Hyperliquid in tempo reale, individua i contratti con funding rate positivo elevato (es. >15% APY), entra nella posizione hedged e incassa le commissioni orarie di funding.

### 3. 🥈 Adaptive Market Maker & Grid (`--strategy market_maker`)
- **Obiettivo**: Rendimento continuo da spread bid-ask e maker fee rebates in mercati laterali.

---

## 🛡️ Gestione del Rischio e Sicurezza

- **Circuit Breaker di Emergenza**: Arresto automatico del bot e rifiuto di nuovi ordini se il drawdown supera la soglia impostata (default 5%).
- **Position & Leverage Limits**: Controlli su dimensione massima della posizione per asset e notizionale totale del portafoglio.
- **Graceful Shutdown**: Intercettazione pulita dei segnali `SIGINT` e `SIGTERM` (es. arresto da `nohup` o `kill`), con cancellazione automatica degli ordini pendenti prima dello spegnimento.
- **Modalità Dry-Run di Default**: Il bot si avvia per impostazione predefinita in modalità simulazione (`dry-run`) per consentire test sicuri a costo zero.

---

## 📁 Struttura del Progetto

```
hyperliquid-bot/
├── .env.example              # Template per configurazioni e API keys
├── .gitignore                # File ignorati da Git
├── pyproject.toml            # Configurazione del pacchetto Python
├── requirements.txt          # Dipendenze Python
├── README.md                 # Guida all'uso
├── run_bot.py                # CLI Entrypoint principale del Bot
├── scripts/
│   ├── start_nohup.sh        # Script per avviare il bot in background con nohup
│   └── stop_nohup.sh         # Script per arresto pulito (salvataggio stato e kill)
├── src/
│   └── hyperliquid_bot/
│       ├── __init__.py       # Export dei moduli principali
│       ├── config.py         # Caricamento variabili d'ambiente
│       ├── client.py         # Wrapper SDK Hyperliquid (Info & Exchange)
│       ├── fees.py           # Calcolo matematico fees, tiers e break-even
│       ├── risk.py           # Risk Manager e Circuit Breaker
│       ├── engine.py         # Motore 24/7, gestione segnali e loop
│       └── strategies/       # Moduli delle strategie di trading
│           ├── base.py       # Interfaccia base astratta
│           ├── funding_harvester.py  # Delta-Neutral Funding Harvester
│           └── market_maker.py       # Adaptive Market Maker / Grid
├── examples/
│   └── demo_fees.py          # Demo interattiva per calcoli fees
└── tests/
    ├── test_fees.py          # Test suite per calcolo fees
    └── test_risk_and_strategies.py # Test suite per Risk Manager e strategie
```

---

## 🚀 Guida Rapida all'Avvio

### 1. Installazione
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurazione `.env`
Copia `.env.example` in `.env` e configura le chiavi:
```bash
cp .env.example .env
```
- `NETWORK`: `testnet` (consigliato per iniziare) o `mainnet`.
- `ACCOUNT_ADDRESS`: Indirizzo del tuo wallet.
- `SECRET_KEY`: Chiave privata Ethereum per il trading (lasciare vuoto per test sola lettura).

---

## 💻 Esecuzione in Background con `nohup`

Sono forniti script shell dedicati che gestiscono il PID e i log rotativi in `logs/bot.log`:

### Avviare la strategia Funding Harvester (Dry-Run):
```bash
bash scripts/start_nohup.sh --strategy funding --min-apy 12.0
```

### Avviare la strategia Market Maker su ETH (Dry-Run):
```bash
bash scripts/start_nohup.sh --strategy market_maker --symbol ETH --order-size-usd 300
```

### Monitorare i Log in Tempo Reale:
```bash
tail -f logs/bot.log
```

### Fermare il Bot in Sicurezza:
```bash
bash scripts/stop_nohup.sh
```

---

## ⚙️ Opzioni CLI di `run_bot.py`

```text
Opzioni:
  --strategy {funding,market_maker}  Strategia da eseguire (default: funding)
  --symbol SYMBOL                    Asset target per Market Maker (es. ETH, BTC, SOL)
  --dry-run                          Modalità simulazione senza ordini reali (default: True)
  --live                             Abilita piazzamento ordini REALI
  --interval SECONDS                 Secondi tra ogni ciclo di tick
  --order-size-usd USD               Dimensione ordine/posizione in USD (default: $200)
  --min-apy APY                      Soglia minima APY % per Funding Harvester (default: 12%)
  --spread-bps BPS                   Spread bid/ask in bps per Market Maker (default: 8 bps)
  --max-drawdown-pct PCT             Soglia Circuit Breaker max drawdown % (default: 5%)
```

---

## 🧪 Esecuzione dei Test Unitari

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
