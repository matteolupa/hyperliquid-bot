# Hyperliquid 24/7 Algorithmic Trading Bot & Quant Suite 🚀

Software quantitativo modulare ad alta affidabilità per il trading algoritmico e l'arbitraggio di **Funding Rate Delta-Neutral** su **Hyperliquid DEX** (Mainnet e Testnet).

Progettato per operare 24/7 in cloud (es. istanze Ubuntu / Oracle Cloud), con gestione avanzata del rischio, persistenza atomica dello stato, registro contabile CSV e **bot Telegram bidirezionale interattivo**.

---

## 🌟 Caratteristiche Principali & Innovazioni

### 1. ⚖️ True Delta-Neutral Spot-Perp Cash & Carry (`--hedge-mode spot-perp` - DEFAULT)
* **Rischio Prezzo ZERO ($\Delta = 0$):** Apertura simultanea e simmetrica di una posizione **🟢 LONG sul mercato Spot** (USDC) e di una posizione **🔴 SHORT sul Perpetual contract** del medesimo token (es. `HYPE`, `PURR`, `TRUMP`).
* **Immunità alle oscillazioni di mercato:** Se il prezzo sale del +50%, il guadagno dello Spot ripaga esattamente la perdita del Perp. Se il prezzo crolla del -50%, il guadagno dello short ripaga esattamente la perdita dello Spot. Il capitale resta intatto al 100% mentre si incassa la rendita da funding rate passivo.
* **Supporto Cross-Market Hyperliquid L1:** Riconoscimento automatico delle corrispondenze tra Universo Perp e Universo Spot (inclusi token numerici `@107` per HYPE o ticker diretti).
* **Doppia Chiusura Sincronizzata:** Vendita automatica dello Spot e riacquisto del Perp al verificarsi dei criteri di uscita o su comando `/closeall`.

### 2. 🧠 Moduli Quant Avanzati & Ottimizzazioni di Rendimento
* **📈 Funding Rate Prediction & Trend Detection (`funding_analytics.py`):** Analizza la cronologia dei tassi su finestre mobili di 1h/4h/8h/24h, calcola la derivata temporale ($dF/dt$) tramite regressione lineare, classifica il trend (`RISING`, `STABLE`, `FALLING`) e stima l'APY proiettato per le successive 4 ore con indice di confidenza.
* **🌐 Multi-Exchange Spread Monitoring (`multi_exchange.py`):** Interroga simultaneamente le API pubbliche di **Binance**, **Bybit** e **dYdX**, normalizza i tassi a base oraria (es. 8h $\rightarrow$ 1h) e calcola lo spread rispetto a Hyperliquid per identificare divergenze e convergenze di funding.
* **📊 Basis Trade Monitoring (`basis_monitor.py`):** Monitora il premio/sconto del prezzo Perpetual rispetto al prezzo Spot USDC su Hyperliquid. Quando il Perp prezza a premio (`PREMIUM`, spread positivo in bps), l'entrata Cash & Carry blocca un guadagno aggiuntivo alla convergenza dei prezzi al settlement.
* **🔄 Rotazione Intelligente Multi-Asset & Scoring Composito:** Quando tutti gli slot sono occupati ($N=3$), il bot calcola uno **Score Composito** (APY 40%, Trend 25%, Basis 20%, Spread Cross-Exchange 15%). Se emerge un'opportunità con spread $\ge 30\%$ APY rispetto alla peggiore posizione attiva e il costo delle commissioni di round-trip si ripaga in $\le 4$ ore, il bot chiude automaticamente la posizione inferiore e rialloca il capitale sul nuovo leader!
* **⚡ Dynamic Yield-Weighted Sizing (`--dynamic-sizing`):** Anziché suddividere il capitale in parti rigidamente uguali, alloca più fondi all'asset più redditizio (45% al 1° classificato, 33% al 2°, 22% al 3°), massimizzando la rendita oraria complessiva mantenendo la diversificazione e i limiti di rischio (20%-50% per slot).
* **⏱️ Accredito Orario Push & Countdown:** Invia una mini-notifica Telegram allo scoccare di ogni ora (:00 UTC) con gli incassi esatti dell'ora appena trascorsa e mostra il conto alla rovescia in minuti/secondi verso il prossimo accredito.
* **🛡️ Perp Liquidation Buffer:** Calcola e monitora in tempo reale la distanza percentuale dal prezzo di liquidazione della gamba Short Perpetual per garantire la massima sicurezza del capitale collaterale.

### 3. ⚡ Perpetual Carry Mode Alternativa (`--hedge-mode perp-carry`)
* Per chi desidera operare su altcoin senza mercato Spot nativo:
  * **Positive Funding Arbitrage (🔴 SHORT):** Quando i trader long pagano gli short ($F > 0$), incassa rendita oraria con perp short.
  * **Negative Funding Arbitrage (🟢 LONG):** Nei crolli di mercato ($F < 0$), i trader short pagano chi va long; incassa rendita con perp long.
* **Live Dynamic Accrual:** Calcolo matematico incrementale esatto basato su $\Delta t$ e tasso live per ogni tick.
* **Auto-Compounding Reale:** Reinveste automaticamente il 100% dei guadagni storici aumentando progressivamente la taglia d'ordine per ogni slot.

### 4. 🛡️ Tripla Barriera di Sicurezza & Anti-Manipolazione
* **Filtro Liquidità (`--min-oi-usd`):** Scarta i mercati con Open Interest insufficiente (default: **$50,000+**) per evitare slippage su coppie illiquide.
* **Filtro Anti-Manipolazione (`--max-apy`):** Ignora token con APY anomali o pump artificiali superiori alla soglia massima (default: **1000% APY**).
* **Filtro di Persistenza (`--persistence-checks`):** Richiede che un'opportunità mantenga tassi elevati per $N$ scansioni consecutive (default: **2 tick**) prima di entrare.

### 5. 📉 Trailing APY Exit Intelligente (`--trailing-exit`)
* Monitora il picco massimo di APY registrato per ciascuna posizione.
* Chiude automaticamente il trade se il tasso cala di oltre il $75\%$ dal picco (oppure scende sotto la soglia assoluta del $3\%$), monetizzando il funding e ruotando il capitale verso opportunità più redditizie.

### 6. 📱 Bot Telegram Bidirezionale Interattivo
Controlla il bot in qualsiasi momento dal tuo smartphone con comandi istantanei:

| Comando | Descrizione |
|---|---|
| **/status** | Report live su guadagni, rendita oraria, countdown prossimo accredito, buffer liquidazione e posizioni aperte (con badge [⚖️ DELTA-ZERO] o 🔴/🟢). |
| **/stats** | **Dashboard di Performance:** guadagno netto ultime 24 ore e ultimi 7 giorni, APY effettivo realizzato, numero accrediti riscossi e rendita media oraria/giornaliera. |
| **/balance** | Riepilogo di equity totale, capitale allocato, margine libero e quota di auto-compounding. |
| **/watchlist** | Classifica in tempo reale delle **Top 5 opportunità** con APY, Score Composito, Trend e Basis. |
| **/funding** | Analisi predittiva del trend del funding rate (📈 RISING, ➡️ STABLE, 📉 FALLING) e APY previsto. |
| **/spread** | Confronto multi-exchange del funding rate rispetto a Binance, Bybit e dYdX. |
| **/basis** | Analisi dello spread Spot-Perp (Basis in bps, Premium/Discount e rendimento stimato da convergenza). |
| **/history** | Storico dettagliato delle **ultime 5 posizioni chiuse** estratte direttamente dal Ledger CSV con motivo e modalità. |
| **/closeall** | **Chiusura di Emergenza:** chiude immediatamente entrambe le gambe (Spot + Perp), riscuote il funding e salva lo stato su disco. |
| **/help** | Guida rapida ai comandi. |

> 🔒 **Sicurezza:** Il bot risponde **esclusivamente** al tuo `CHAT_ID` Telegram autorizzato. Qualsiasi messaggio da utenti esterni viene rifiutato.

### 7. 📒 Ledger Contabile & Equity Curve CSV
* **`data/equity_curve_dry.csv` (o `_live.csv`):** Log orario continuo con timestamp, equity totale, capitale allocato, rendita oraria e APY realizzato.
* **`data/funding_ledger_dry.csv` (o `_live.csv`):** Append-only log con modalità di copertura (`hedge_mode`), coppia spot (`spot_pair`), durata trade, APY in/out, funding incassato e motivo di uscita.
* **`data/funding_state_dry.json`:** Salvataggio atomico su disco con ripristino istantaneo di posizioni, watchlist e contatori in caso di riavvio del server.
* **Circuit Breaker:** Arresto d'emergenza in caso di drawdown di portafoglio superiore alla soglia impostata (`--max-drawdown-pct`).

---

## 📁 Struttura del Progetto

```
hyperliquid-bot/
├── .env.example              # Template variabili d'ambiente (Zero secret esposti)
├── pyproject.toml            # Configurazione packaging Python
├── requirements.txt          # Dipendenze
├── README.md                 # Documentazione del progetto
├── run_bot.py                # Entrypoint CLI principale
├── scripts/
│   ├── start_nohup.sh        # Avvio background 24/7 con tracciamento PID
│   └── stop_nohup.sh         # Graceful shutdown con salvataggio atomico
├── src/
│   └── hyperliquid_bot/
│       ├── __init__.py               # Export dei moduli
│       ├── config.py                 # Caricamento configurazioni da .env
│       ├── client.py                 # Wrapper SDK Hyperliquid
│       ├── fees.py                   # Fee Calculator e stima break-even
│       ├── ledger.py                 # Modulo contabile Funding Ledger CSV
│       ├── performance.py            # Performance Tracker & Equity Curve CSV
│       ├── funding_analytics.py      # Trend Detection & APY Predictor
│       ├── multi_exchange.py         # Spread Multi-Exchange (Binance/Bybit/dYdX)
│       ├── basis_monitor.py          # Monitoraggio Basis Spot vs Perp
│       ├── risk.py                   # Risk Manager & Circuit Breaker
│       ├── telegram.py               # Notifier & Command Listener bidirezionale
│       ├── engine.py                 # Bot Engine 24/7 e gestione comandi
│       └── strategies/
│           ├── base.py               # Interfaccia base astratta
│           ├── funding_harvester.py  # Funding Harvester Spot-Perp Delta-Zero
│           ├── scalper.py            # Scalper & Take-Profit
│           └── market_maker.py       # Adaptive Grid / Market Maker
├── data/                             # Stato JSON, Ledger CSV ed Equity Curve
├── logs/                             # Log di esecuzione con rotazione automatica
└── tests/
    ├── test_fees.py                  # Test calcolo commissioni
    ├── test_risk_and_strategies.py   # Test suite strategie, hedging e comandi
    └── test_funding_optimizations.py # Test sizing dinamico, rollover e buffer
```

---

## 🚀 Guida Rapida all'Installazione

### 1. Clona e configura l'ambiente virtuale:
```bash
git clone https://github.com/matteolupa/hyperliquid-bot.git
cd hyperliquid-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configura le variabili d'ambiente:
Copia `.env.example` in `.env`:
```bash
cp .env.example .env
```
Compila i campi:
* `NETWORK`: `mainnet` (per dati e tassi reali) o `testnet`.
* `ACCOUNT_ADDRESS`: Indirizzo del tuo wallet Ethereum/Arbitrum.
* `SECRET_KEY`: Chiave privata API Agent (necessaria solo in `--live`).
* `TELEGRAM_BOT_TOKEN`: Token API del tuo bot Telegram ottenuto da `@BotFather`.
* `TELEGRAM_CHAT_ID`: Il tuo ID utente Telegram.

---

## 💻 Esecuzione 24/7 su Cloud (Ubuntu / Oracle Cloud)

Il bot include script pronti per girare in background con `nohup` e rotazione automatica dei log:

### Avviare il Bot in Background:
```bash
bash scripts/start_nohup.sh --strategy funding --order-size-usd 166 --trailing-exit 75 --max-apy 1000
```

### Controllare i Log in Tempo Reale:
```bash
tail -f logs/bot.log
```

### Fermare il Bot in Sicurezza (Graceful Shutdown):
```bash
bash scripts/stop_nohup.sh
```

---

## ⚙️ Parametri CLI di `run_bot.py`

| Parametro | Default | Descrizione |
|---|:---:|---|
| `--strategy` | `funding` | Strategia da eseguire (`funding`, `scalper`, `market_maker`). |
| `--hedge-mode` | `spot-perp` | **Modalità di copertura:** `spot-perp` (True Delta-Neutral Cash & Carry, zero rischio prezzo) oppure `perp-carry` (Single-leg su perps). |
| `--dry-run` | `True` | Modalità simulazione senza piazzamento ordini reali. |
| `--live` | `False` | Abilita l'esecuzione reale di ordini su Hyperliquid. |
| `--order-size-usd` | `50.0` | Capitale base allocato per singolo slot (es. `166.0` per ~$500 su 3 slot). |
| `--min-apy` | `12.0` | APY minimo (%) richiesto per entrare in una posizione. |
| `--max-apy` | `1000.0` | Filtro anti-manipolazione: ignora APY oltre questa soglia. |
| `--trailing-exit` | `50.0` | Percentuale di calo dell'APY dal picco storico per uscire (consigliato `75.0`). |
| `--min-oi-usd` | `50000.0`| Open Interest minimo in USD per filtrare mercati illiquidi. |
| `--persistence-checks` | `2` | Numero di tick consecutivi di conferma prima dell'ingresso. |
| `--rotation-min-spread` | `30.0` | APY gap minimo (%) per innescare la rotazione intelligente da una posizione attiva a un candidato superiore. |
| `--rotation-breakeven-hours`| `4.0` | Massimo numero di ore per ripagare le fee di round-trip prima di consentire la rotazione. |
| `--enable-trend-detection` | `True` | Abilita il modulo Funding Analytics e trend detection (1h/4h/8h/24h). |
| `--enable-cross-exchange` | `True` | Abilita il monitoraggio spread multi-exchange (Binance, Bybit, dYdX). |
| `--enable-basis-monitor` | `True` | Abilita il monitoraggio del Basis Spot vs Perp. |
| `--dynamic-sizing` | `True` | Alloca il capitale in base alla resa (45% top performer, 33% 2°, 22% 3°). |
| `--hourly-alerts` | `True` | Invia una notifica Telegram oraria allo scoccare di ogni ora (:00 UTC) con gli incassi riscossi. |
| `--allow-negative-funding` | `True` | Abilita il Negative Funding Arbitrage in modalità `perp-carry`. |
| `--auto-compound` | `True` | Reinveste i guadagni aumentando dinamicamente la taglia degli slot. |
| `--report-interval` | `300.0` | Secondi tra i report periodici di stato su Telegram e nei log. |
| `--max-drawdown-pct` | `5.0` | Soglia massima di drawdown per il Circuit Breaker d'emergenza. |

---

## 🧪 Esecuzione della Test Suite

Il progetto include una suite completa di test unitari con isolamento del filesystem:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
*(41 test unitari superati con successo in < 0.06s).*

---

## 📜 Licenza
Rilasciato sotto licenza MIT. Sviluppato per trading ad alte prestazioni e quantitativo su Hyperliquid DEX.
