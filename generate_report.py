from fpdf import FPDF

FONT_DIR = "/System/Library/Fonts/Supplemental/"
ARIAL = FONT_DIR + "Arial.ttf"
ARIAL_B = FONT_DIR + "Arial Bold.ttf"
ARIAL_I = FONT_DIR + "Arial Italic.ttf"
ARIAL_BI = FONT_DIR + "Arial Bold Italic.ttf"

class PDF(FPDF):
    def setup_fonts(self):
        self.add_font("Arial", "", ARIAL)
        self.add_font("Arial", "B", ARIAL_B)
        self.add_font("Arial", "I", ARIAL_I)
        self.add_font("Arial", "BI", ARIAL_BI)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Arial", "I", 9)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, "Polymarket Trading Bot Research Report", align="R")
        self.ln(4)
        self.set_draw_color(210, 210, 210)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no() - 1}  |  Generated March 2026", align="C")

    def cover(self):
        self.add_page()
        # Dark background
        self.set_fill_color(15, 23, 42)
        self.rect(0, 0, 210, 297, "F")
        # Indigo accent bar
        self.set_fill_color(99, 102, 241)
        self.rect(0, 118, 210, 4, "F")
        # Subtle top bar
        self.set_fill_color(30, 41, 100)
        self.rect(0, 0, 210, 18, "F")

        self.set_y(55)
        self.set_font("Arial", "B", 32)
        self.set_text_color(255, 255, 255)
        self.cell(0, 14, "POLYMARKET", align="C")
        self.ln(12)
        self.set_font("Arial", "B", 22)
        self.set_text_color(165, 180, 252)
        self.cell(0, 10, "Trading Bot Landscape", align="C")
        self.ln(9)
        self.set_font("Arial", "I", 13)
        self.set_text_color(148, 163, 184)
        self.cell(0, 8, "Strategy Research & Architecture Analysis", align="C")
        self.ln(26)
        self.set_font("Arial", "", 10)
        self.set_text_color(100, 116, 139)
        self.cell(0, 6, "March 2026", align="C")

    def chapter_title(self, title, subtitle=None):
        self.set_line_width(0.8)
        self.set_draw_color(99, 102, 241)
        self.line(10, self.get_y(), 10, self.get_y() + 10)
        self.set_x(16)
        self.set_font("Arial", "B", 14)
        self.set_text_color(30, 41, 100)
        self.cell(0, 10, title)
        self.ln(11)
        if subtitle:
            self.set_font("Arial", "I", 10)
            self.set_text_color(100, 116, 139)
            self.cell(0, 5, subtitle)
            self.ln(7)
        self.set_line_width(0.2)
        self.set_draw_color(200, 200, 200)
        self.ln(2)

    def section_title(self, title):
        self.ln(4)
        self.set_font("Arial", "B", 10)
        self.set_text_color(55, 65, 130)
        self.cell(0, 7, title)
        self.ln(7)

    def body(self, text):
        self.set_font("Arial", "", 10)
        self.set_text_color(51, 51, 51)
        self.multi_cell(0, 5.5, text)
        self.ln(2)

    def bullet(self, items):
        self.set_font("Arial", "", 10)
        self.set_text_color(51, 51, 51)
        for item in items:
            self.set_x(14)
            self.cell(5, 5.5, "-")
            self.multi_cell(0, 5.5, item)
        self.ln(2)

    def tag_row(self, label, value, color=(70, 70, 180)):
        self.set_font("Arial", "B", 9)
        self.set_text_color(*color)
        self.set_fill_color(238, 242, 255)
        self.cell(40, 6, f"  {label}", fill=True, border=0)
        self.set_font("Arial", "", 9)
        self.set_text_color(51, 51, 51)
        self.cell(0, 6, f"  {value}")
        self.ln(7)

    def strategy_card(self, number, name, repos, edge, complexity, risk, description, how_it_works, key_detail):
        if self.get_y() > 230:
            self.add_page()
        y_start = self.get_y()
        # Card header
        self.set_fill_color(30, 41, 100)
        self.rect(10, y_start, 190, 9, "F")
        self.set_y(y_start + 1)
        self.set_font("Arial", "B", 11)
        self.set_text_color(255, 255, 255)
        self.cell(10, 7, f"{number}.")
        self.cell(0, 7, name)
        self.ln(11)

        self.tag_row("Repos", repos)
        self.tag_row("Edge Source", edge)
        self.tag_row("Complexity", complexity, (50, 120, 60))
        self.tag_row("Risk Level", risk, (160, 60, 60))

        self.section_title("Description")
        self.body(description)
        self.section_title("How It Works")
        self.body(how_it_works)
        self.section_title("Key Technical Detail")
        self.set_fill_color(255, 251, 235)
        self.set_x(10)
        self.set_font("Arial", "I", 9)
        self.set_text_color(92, 60, 0)
        self.multi_cell(190, 5.5, key_detail, border=0, fill=True)
        self.ln(6)
        self.set_draw_color(220, 220, 220)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def comparison_table(self):
        cols = [55, 50, 32, 28, 25]
        headers = ["Strategy", "Edge Source", "Complexity", "Risk", "Reward"]
        self.set_font("Arial", "B", 9)
        self.set_fill_color(30, 41, 100)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(cols[i], 7, f"  {h}", fill=True, border=1)
        self.ln()
        rows = [
            ("Market Making", "Spread + LP rewards", "High", "Medium", "Medium"),
            ("YES+NO Arbitrage", "Mispricing", "Medium", "Low", "Low"),
            ("Cross-Market Arb", "Convergence", "High", "Medium", "Medium"),
            ("CEX-Lag Momentum", "Latency vs CEX", "Low-Med", "Med-High", "High"),
            ("Copy / Whale", "Whale alpha", "Low", "High", "Variable"),
            ("AI / LLM Agent", "Info edge", "High", "High", "High"),
        ]
        toggle = False
        for row in rows:
            self.set_font("Arial", "", 9)
            self.set_text_color(40, 40, 40)
            self.set_fill_color(245, 247, 255) if toggle else self.set_fill_color(255, 255, 255)
            for i, val in enumerate(row):
                self.cell(cols[i], 6, f"  {val}", border=1, fill=True)
            self.ln()
            toggle = not toggle
        self.ln(6)


# Build PDF
pdf = PDF()
pdf.setup_fonts()
pdf.set_auto_page_break(auto=True, margin=20)

# --- Cover ---
pdf.cover()

# --- Page 2: Infrastructure ---
pdf.add_page()
pdf.chapter_title("1. Infrastructure Foundation", "What every Polymarket bot is built on")
pdf.body(
    "All trading bots interact with Polymarket through the same core infrastructure: a Central Limit Order "
    "Book (CLOB) running on Polygon blockchain. Understanding this layer is essential before evaluating any strategy."
)
pdf.section_title("Core Technical Specs")
pdf.bullet([
    "Rate limit: 60 orders per minute per API key",
    "Settlement: Hybrid -- off-chain order matching, on-chain settlement (Polygon)",
    "Official Python SDK: py-clob-client",
    "Official TypeScript SDK: @polymarket/clob-client",
    "WebSocket streams: real-time orderbook data (6 parallel connections supported)",
    "Gamma API: separate endpoint for market metadata and event data",
    "Two market types: binary YES/NO, multi-outcome",
])
pdf.section_title("Market Mechanics")
pdf.body(
    "Each market resolves to either $1.00 (YES wins) or $0.00 (NO wins). Shares are priced between 0 and 1, "
    "representing the implied probability. For example, YES at 0.62 means the market prices a 62% chance of YES. "
    "A YES share + NO share always = $1.00 at resolution, creating the foundation for arbitrage strategies."
)
pdf.body(
    "Polymarket offers maker rewards -- bots that provide liquidity by posting limit orders earn a fee rebate "
    "on top of the spread they capture. This makes market making doubly attractive for well-positioned bots."
)

# --- Strategy Cards ---
pdf.add_page()
pdf.chapter_title("2. Strategy Breakdown", "Six distinct approaches found across open-source repositories")

pdf.strategy_card(
    "1", "Market Making",
    repos="warproxxx/poly-maker, lorine93s/polymarket-market-maker-bot, terrytrl100/polymarket-automated-mm",
    edge="Spread capture + Polymarket LP maker rewards",
    complexity="High",
    risk="Medium (inventory imbalance risk)",
    description=(
        "Market makers post simultaneous limit orders on both YES and NO sides of a contract. "
        "They stay inventory-neutral and profit by capturing the bid-ask spread repeatedly. "
        "Polymarket's maker reward program adds an additional fee rebate for liquidity providers."
    ),
    how_it_works=(
        "1. Fetch current orderbook state via WebSocket.\n"
        "2. Calculate optimal bid/ask prices based on mid-price and desired spread.\n"
        "3. Place limit orders on both sides simultaneously.\n"
        "4. On fill: cancel opposite side, replace both quotes at new prices.\n"
        "5. Monitor inventory; hedge or pause if one side dominates.\n"
        "6. Periodically merge YES+NO positions into $1.00 for redemption (reduces gas).\n"
        "7. warproxxx/poly-maker fetches all parameters from Google Sheets -- no redeploy needed."
    ),
    key_detail=(
        "terrytrl100/polymarket-automated-mm calculates order placement using Polymarket's exact maker reward "
        "formula, ensuring the spread captured always exceeds gas + reward threshold. It also auto-selects "
        "which markets to make based on volume and reward rate."
    )
)

pdf.strategy_card(
    "2", "YES+NO Combinatorial Arbitrage",
    repos="ent0n29/polybot, Now-Or-Neverr/polymarket-trading-bot",
    edge="Mispricing: YES + NO combined price < $1.00",
    complexity="Medium",
    risk="Low (near risk-free if both legs fill)",
    description=(
        "When the sum of YES price + NO price falls below $1.00, buying both is guaranteed profit "
        "since they resolve to exactly $1.00 together. In multi-outcome markets, buying all outcomes "
        "when their sum < $1.00 achieves the same guaranteed return."
    ),
    how_it_works=(
        "1. Continuously scan all active markets for price_YES + price_NO < 1.00.\n"
        "2. Calculate profit: profit = 1.00 - (price_YES + price_NO) - gas_fees.\n"
        "3. If profit > threshold: submit simultaneous FOK (Fill or Kill) orders on both sides.\n"
        "4. FOK ensures both legs fill or neither does -- no directional exposure.\n"
        "5. Wait for market resolution to collect $1.00 per pair.\n"
        "6. Multi-outcome: same logic across all outcome tokens."
    ),
    key_detail=(
        "The main risk is execution: if only one leg fills (e.g. FOK fails), the position becomes "
        "directional. Sophisticated bots submit both orders atomically or cancel both on partial failure. "
        "Between April 2024-2025, this strategy class earned an estimated $40M on Polymarket."
    )
)

pdf.add_page()
pdf.strategy_card(
    "3", "Cross-Market Convergence Arbitrage",
    repos="dylanpersonguy/Polymarket-Trading-Bot, ent0n29/polybot",
    edge="Logically correlated markets with diverging prices",
    complexity="High",
    risk="Medium (requires valid logical relationship identification)",
    description=(
        "Finds pairs or groups of markets where outcomes are logically linked, then exploits price "
        "divergences between them. Example: 'Trump wins election' and 'Trump is Republican nominee' "
        "are correlated -- winning requires being nominated. If nominee trades at 48c but winner at 52c, "
        "there is a 4% arbitrage opportunity."
    ),
    how_it_works=(
        "1. Maintain a graph of related markets (political, sports, economic events).\n"
        "2. Monitor prices across all markets in real-time via WebSocket.\n"
        "3. Detect divergences exceeding a threshold relative to logical constraints.\n"
        "4. Enter opposing positions: long the underpriced, short the overpriced.\n"
        "5. Exit when prices converge or markets resolve.\n"
        "6. dylanpersonguy's bot scans 1,500+ markets simultaneously with async architecture."
    ),
    key_detail=(
        "This is the most alpha-rich but hardest-to-automate strategy. Identifying valid logical "
        "relationships requires domain knowledge (politics, sports rules, etc.). The most profitable "
        "implementations combine automated scanning with human-curated market relationship graphs."
    )
)

pdf.strategy_card(
    "4", "CEX-Lag Momentum (Crypto Markets)",
    repos="discountry/polymarket-trading-bot, ThinkEnigmatic/polymarket-bot-arena",
    edge="Polymarket crypto prices lag Binance/Coinbase by seconds",
    complexity="Low to Medium",
    risk="Medium-High (latency arms race)",
    description=(
        "Targets Polymarket's BTC/ETH/SOL 5-min and 15-min Up/Down binary markets. These markets "
        "price whether BTC (or ETH/SOL) will be higher or lower than the current price by expiry. "
        "When the underlying asset moves decisively on a CEX, Polymarket prices lag -- this gap is the edge."
    ),
    how_it_works=(
        "1. Subscribe to real-time price feeds from Binance, Coinbase, and/or Chainlink.\n"
        "2. Monitor BTC delta (price change) over the current round window.\n"
        "3. When momentum exceeds a conviction threshold (e.g. +0.5% in 3 min), enter the UP market.\n"
        "4. Place limit orders slightly better than current Polymarket price to ensure fill.\n"
        "5. discountry's bot: detects probability drops >5% in 15min as primary signal.\n"
        "6. polymarket-bot-arena: 4 bots (momentum, mean-reversion, sentiment, hybrid) compete "
        "with Bayesian learning and evolutionary replacement every 12 hours."
    ),
    key_detail=(
        "Bot Arena Architecture (ThinkEnigmatic): arena.py handles market discovery, trading, "
        "resolution, and evolution. learning.py runs a Bayesian engine that tracks win rates by "
        "(price bucket, BTC momentum, time of day). Every 12h: bottom 2 bots are killed and replaced "
        "with mutated versions of top performers -- continuously self-improving without human intervention."
    )
)

pdf.add_page()
pdf.strategy_card(
    "5", "Copy Trading / Whale Tracking",
    repos="iengineer/polymarket--whale-trading-bot, dev-protocol/polymarket-copytrading-bot-sport",
    edge="Mirror profitable whale wallets in real-time",
    complexity="Low",
    risk="High (latency, front-running, whale strategy drift)",
    description=(
        "Monitors target wallet addresses on Polygon blockchain and automatically replicates their "
        "trades with proportional sizing. The thesis: identified whale wallets have a persistent edge "
        "that can be copied before their trades fully move the market price."
    ),
    how_it_works=(
        "1. Define a list of target whale wallets (identified by historical profitability analysis).\n"
        "2. Poll wallet positions every ~4 seconds OR listen to on-chain blockchain events.\n"
        "3. Detect new trades: compare current positions to previous snapshot.\n"
        "4. Evaluate risk filters: max exposure per market, cooldown, min trade size.\n"
        "5. Calculate proportional size: (your_balance / whale_balance) x whale_trade_size.\n"
        "6. Execute via CLOB API immediately.\n"
        "7. Apply trailing stop-loss tracking peak prices for exit management."
    ),
    key_detail=(
        "The core challenge is latency: by the time the copy bot detects and executes, the whale's "
        "trade may have already moved the market. The best bots use on-chain event listeners "
        "rather than polling, reducing detection lag from ~4 seconds to sub-second."
    )
)

pdf.strategy_card(
    "6", "AI / LLM-Driven Agent",
    repos="Polymarket/agents (official), llSourcell/Poly-Trader, BlackSky-Jose/PolyMarket-trading-AI-model",
    edge="Information edge via news analysis and LLM probability estimation",
    complexity="High",
    risk="High (model hallucination, prompt sensitivity)",
    description=(
        "Uses a large language model (GPT-4, Claude, etc.) to estimate the true probability of market "
        "outcomes based on current news and context. Compares LLM estimate against market price to "
        "find mispricings. The official Polymarket/agents repo is the reference implementation."
    ),
    how_it_works=(
        "1. GammaMarketClient fetches active, tradable markets and their metadata.\n"
        "2. News connector retrieves recent articles relevant to each market question.\n"
        "3. ChromaDB vectorizes news for semantic retrieval -- LLM gets only most relevant context.\n"
        "4. LLM is prompted: 'Given this news, what probability resolves YES?'\n"
        "5. LLM outputs probability + confidence level.\n"
        "6. If LLM probability > market price by threshold (e.g. LLM=70%, market=55%): place BUY.\n"
        "7. MongoDB logs all LLM queries, trades, and outcomes for analysis.\n"
        "8. All actions accessible via cli.py interface."
    ),
    key_detail=(
        "Architecture is fully modular: connectors (data sources, order types) can be swapped "
        "independently. ChromaDB prevents hallucination by grounding the LLM in retrieved facts "
        "rather than parametric memory. The agent compares its probability estimate to the market's "
        "implied probability and only bets when the gap exceeds a configured threshold."
    )
)

# --- Comparison Table ---
pdf.add_page()
pdf.chapter_title("3. Strategy Comparison", "Side-by-side evaluation of all six approaches")
pdf.comparison_table()

pdf.section_title("Key Takeaways")
pdf.bullet([
    "The CLOB API (py-clob-client) is the execution layer for all strategies -- mastering it is step one.",
    "CEX-lag momentum is the mechanically simplest strategy with a documented, consistent edge in crypto markets.",
    "YES+NO arbitrage is the lowest-risk strategy but opportunities are thin and quickly competed away.",
    "Market making earns fees + maker rewards but requires careful inventory management and risk controls.",
    "Copy trading is easy to implement but latency-sensitive; on-chain event listeners outperform polling.",
    "LLM agents are architecturally the most sophisticated and hardest to validate -- require rigorous backtesting.",
    "Cross-market arbitrage has the highest potential alpha but requires domain-specific market relationship knowledge.",
    "Paper trading mode (polymarket-paper-trader on GitHub) allows risk-free strategy testing before live deployment.",
])

pdf.section_title("Market Volume Context (2025-2026)")
pdf.body(
    "Polymarket processed $3.74 billion in monthly volume in November 2025, with Kalshi adding $5.8 billion -- "
    "nearly $10 billion combined monthly prediction market activity. Arbitrage bots alone earned an estimated "
    "$40 million between April 2024 and April 2025. The market is large and growing, but also increasingly competitive."
)

pdf.section_title("Recommended Starting Point")
pdf.set_fill_color(240, 253, 244)
pdf.set_x(10)
pdf.set_font("Arial", "B", 10)
pdf.set_text_color(22, 101, 52)
pdf.multi_cell(190, 6,
    "For a new trading system: start with CEX-lag momentum on BTC/ETH 15-min Up/Down markets. "
    "The edge is documented, the implementation is straightforward (Binance WebSocket + py-clob-client), "
    "and the market is liquid. Layer in YES+NO arbitrage scanning as a secondary strategy to "
    "capture risk-free opportunities when they appear. Build toward market making once the "
    "execution infrastructure is mature.",
    border=0, fill=True)

# --- Sources ---
pdf.add_page()
pdf.chapter_title("4. Sources & References")

sources = [
    ("Polymarket/agents (Official)", "github.com/Polymarket/agents"),
    ("warproxxx/poly-maker", "github.com/warproxxx/poly-maker"),
    ("ent0n29/polybot", "github.com/ent0n29/polybot"),
    ("ThinkEnigmatic/polymarket-bot-arena", "github.com/ThinkEnigmatic/polymarket-bot-arena"),
    ("discountry/polymarket-trading-bot", "github.com/discountry/polymarket-trading-bot"),
    ("dylanpersonguy/Polymarket-Trading-Bot", "github.com/dylanpersonguy/Polymarket-Trading-Bot"),
    ("lorine93s/polymarket-market-maker-bot", "github.com/lorine93s/polymarket-market-maker-bot"),
    ("iengineer/polymarket--whale-trading-bot", "github.com/iengineer/polymarket--whale-trading-bot"),
    ("terrytrl100/polymarket-automated-mm", "github.com/terrytrl100/polymarket-automated-mm"),
    ("Automated Trading on Polymarket -- QuantVPS", "quantvps.com/blog/automated-trading-polymarket"),
    ("Building a Prediction Market Arbitrage Bot", "navnoorbawa.substack.com/p/building-a-prediction-market-arbitrage"),
    ("Polymarket HFT & AI Arbitrage -- QuantVPS", "quantvps.com/blog/polymarket-hft-traders-use-ai-arbitrage-mispricing"),
    ("Polymarket Trading Bot -- DEV Community", "dev.to/benjamin_martin_749c1d57f/polymarket-trading-bot-real-time-arbitrage"),
    ("Definitive Guide to Polymarket Ecosystem -- DeFi Prime", "defiprime.com/definitive-guide-to-the-polymarket-ecosystem"),
    ("Polymarket Copy Trading Tutorial -- PolyTrack", "polytrackhq.app/blog/polymarket-copy-trading-bot-tutorial"),
]

pdf.set_font("Arial", "", 9)
for i, (name, url) in enumerate(sources):
    pdf.set_fill_color(248, 250, 252) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
    pdf.cell(80, 6, name, fill=True, border=0)
    pdf.set_text_color(99, 102, 241)
    pdf.cell(0, 6, url, fill=True, border=0)
    pdf.set_text_color(51, 51, 51)
    pdf.ln(6)

output_path = "/Users/poctave/Desktop/Claude Code/Polymarket/Polymarket_Trading_Bot_Research.pdf"
pdf.output(output_path)
print(f"PDF saved to: {output_path}")
