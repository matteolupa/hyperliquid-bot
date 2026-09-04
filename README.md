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

### 2. ⚡ Perpetual Carry Mode Alternativa (`--hedge-mode perp-carry`)
* Per chi desidera operare su altcoin senza mercato Spot nativo:
  * **Positive Funding Arbitrage (🔴 SHORT):** Quando i trader long pagano gli short ($F > 0$), incassa rendita oraria con perp short.
  * **Negative Funding Arbitrage (🟢 LONG):** Nei crolli di mercato ($F < 0$), i trader short pagano chi va long; incassa rendita con perp long.
* **Live Dynamic Accrual:** Calcolo matematico incrementale esatto basato su $\Delta t$ e tasso live per ogni tick.
* **Auto-Compounding Reale:** Reinveste automaticamente il 100% dei guadagni storici aumentando progressivamente la taglia d'ordine per ogni slot.

### 3. 🛡️ Tripla Barriera di Sicurezza & Anti-Manipolazione
* **Filtro Liquidità (`--min-oi-usd`):** Scarta i mercati con Open Interest insufficiente (default: **$50,000+**) per evitare slippage su coppie illiquide.
* **Filtro Anti-Manipolazione (`--max-apy`):** Ignora token con APY anomali o pump artificiali superiori alla soglia massima (default: **1000% APY**).
* **Filtro di Persistenza (`--persistence-checks`):** Richiede che un'opportunità mantenga tassi elevati per $N$ scansioni consecutive (default: **2 tick**) prima di entrare.

### 4. 📉 Trailing APY Exit Intelligente (`--trailing-exit`)
* Monitora il picco massimo di APY registrato per ciascuna posizione.
* Chiude automaticamente il trade se il tasso cala di oltre il $75\%$ dal picco (oppure scende sotto la soglia assoluta del $3\%$), monetizzando il funding e ruotando il capitale verso opportunità più redditizie.

### 5. 📱 Bot Telegram Bidirezionale Interattivo
Controlla il bot in qualsiasi momento dal tuo smartphone con comandi istantanei:

| Comando | Descrizione |
|---|---|
| **/status** | Report live su guadagni, rendita oraria stimata e posizioni aperte (con badge [⚖️ DELTA-ZERO] o 🔴/🟢). |
| **/balance** | Riepilogo di equity totale, capitale allocato, margine libero e quota di auto-compounding. |
| **/watchlist** | Classifica in tempo reale delle **Top 5 opportunità di mercato** compatibili con la modalità attiva. |
| **/history** | Storico dettagliato delle **ultime 5 posizioni chiuse** estratte direttamente dal Ledger CSV con modalità di hedge. |
| **/closeall** | **Chiusura di Emergenza:** chiude immediatamente entrambe le gambe (Spot + Perp), riscuote il funding e salva lo stato su disco. |
| **/help** | Guida rapida ai comandi. |

> 🔒 **Sicurezza:** Il bot risponde **esclusivamente** al tuo `CHAT_ID` Telegram autorizzato. Qualsiasi messaggio da utenti esterni viene rifiutato.

### 6. 📒 Ledger Contabile CSV & Persistenza Atomica
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
│       ├── __init__.py       # Export dei moduli
│       ├── config.py         # Caricamento configurazioni da .env
│       ├── client.py         # Wrapper SDK Hyperliquid
│       ├── fees.py           # Fee Calculator e stima break-even
│       ├── ledger.py         # Modulo contabile Funding Ledger CSV
│       ├── risk.py           # Risk Manager & Circuit Breaker
│       ├── telegram.py       # Notifier & Command Listener bidirezionale
│       ├── engine.py         # Bot Engine 24/7 e gestione segnali
│       └── strategies/
│           ├── base.py       # Interfaccia base astratta
│           ├── funding_harvester.py  # Funding Harvester Bidirezionale
│           ├── scalper.py            # Scalper & Take-Profit
│           └── market_maker.py       # Adaptive Grid / Market Maker
├── data/                     # Stato JSON e Ledger CSV (persistenza)
├── logs/                     # Log di esecuzione con rotazione automatica
└── tests/
    ├── test_fees.py          # Test calcolo commissioni
    └── test_risk_and_strategies.py # Test suite completa (28 test)
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
*(29 test unitari superati con successo in < 0.01s).*

---

## 📜 Licenza
Rilasciato sotto licenza MIT. Sviluppato per trading ad alte prestazioni e quantitativo su Hyperliquid DEX.
