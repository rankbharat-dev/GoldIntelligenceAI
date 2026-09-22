# Candle Intelligence — Poora Feature Guide (Hinglish)

*22 Sep 2026 · sirf samjhane ke liye — app mein kuch change nahi kiya gaya.*
Iske saath ki PPT: [Candle_Intelligence_Feature_Guide.pptx](Candle_Intelligence_Feature_Guide.pptx)

---

## Naya: Simple mode (22 Sep 2026)

App ab **Simple mode** mein khulta hai. Sidebar mein sirf 5 cheezein hain:

| Page | Kya karta hai |
|---|---|
| **Home** | "Aaj kya karna hai?" — 3 bade buttons + aapki strategies aur unka agla step |
| **Idea test karo** | 5 aasaan sawaal → engine test karta → seedha jawab |
| **AI Research** | Sawaal likho, AI team research kare (CEO Work Lab) |
| **Market samjho** | Kaunse patterns ke baad gold sach mein kuch karta hai |
| **Meri strategies** | Har strategy kahan tak pahunchi: Banaya → Pehla test → Sudhaaro → Final check → Paper trade |

Result page pe **pehle jawab** aata hai (kaam karti hai ya nahi, aur kyun), phir sirf 3 numbers
(har number pe **?** dabao to matlab), phir "Ab kya karein?". Saara technical jargon
**Expert details** ke andar hai.

Sidebar ke neeche **Simple / Expert** switch hai. Expert mein neeche wale saare purane pages
(section 6) waise hi milte hain — yeh guide aur PPT unhi ko samjhate hain.

---

## 0. Ek line mein

Yeh **gold (XAUUSD) trading ideas ko imaandari se test karne ki lab** hai. Aap ya AI koi idea
dete ho → engine use purane 5 saal ke data pe, **asli kharchon ke saath** chalata hai → batata
hai ki idea sach mein kaam karta hai ya sirf luck tha.

**Yeh kya NAHI hai:** trading bot nahi (koi order nahi lagata), signal service nahi, real account
ko touch nahi karta. "Backtest mein achha dikha" ko yeh profitable nahi maanta.

**Misaal:** nayi dawa pehle lab mein test hoti hai — chuhon pe (Tier A), phir volunteers pe
(Tier B), phir ek final trial (Tier C). Yeh app gold strategies ki wahi lab hai.

---

## 1. Poora safar (big picture)

```
Data → Costs → Samjho → Idea → Rules → Backtest → Optimize → Validate → Paper trade
(Data Center)  (Explorer)  (Strategy Lab)  (Backtest/Optimize)  (Validate)  (Phase 11, abhi nahi)
```

Do raaste, ek hi engine:
- **Khud karo:** Strategy Lab → Backtest → Validate
- **AI se karwao:** CEO Work Lab, Research Pipeline, AI Assistant

Har number Python engine nikalta hai. AI sirf idea deta aur engine chalata hai — khud number nahi banata.

---

## 2. App start / band karna

1. `Start_Candle_Intelligence.bat` double-click. Yeh khud: Docker + database → MT5 → Research API
   (port 8000) → Web app (port 3000) → browser khol deta hai.
2. Browser mein **http://localhost:3000** — yahi aapka app hai.
   (`127.0.0.1:8000/docs` engine ka technical page hai — ignore karo.)
3. Sidebar ke neeche **● Local engine connected** (green) = sab theek.
   **● Engine offline** (red) = API band → `.bat` dobara chalao.
4. Band karna: `Stop_Candle_Intelligence.bat`. Beech mein kaale cmd windows band mat karo.

MT5 mein hamesha: **demo account**, **Algo Trading OFF**.

---

## 3. Sidebar ke 13 pages — 5 groups

| Group | Page | Ek line |
|---|---|---|
| **1 · Shuru yahan se** | CEO Work Lab | Sawaal likho, AI team research kare |
| | Overview | Chart + har candle ki details |
| **2 · Market samjho** | Data Center | Data aur trading ke kharche |
| | Behaviour Explorer | Pattern ke baad gold kya karta hai |
| **3 · Strategy banao** | Strategy Lab | Rules banao (3 tareeke) |
| | My Strategies | Saari saved strategies + results |
| **4 · Test karo** | Backtest | Purane data pe chalao |
| | Optimize | Best settings dhoondo |
| | Validate | Final imaandar test |
| **5 · AI / Automation** | Research Pipeline | Engine khud 100s ideas test kare |
| | ML Lab | Machine learning filter |
| | AI Assistant | Chat mein poocho |

Header mein **Research jobs** tray: lambe kaam (backtest, optimize, validate) ki progress. Page band
karke bhi kaam chalta rehta hai.

---

## 4. Keyword dictionary

### 4a. Market aur paisa

| Shabd | Matlab |
|---|---|
| **XAUUSD** | Gold ka price US Dollar mein. App sirf isi pe kaam karta hai. |
| **Candle / Bar** | Ek time-block ka Open, High, Low, Close. Dono shabd same. |
| **M1 · M5 · M15 · H1** | 1 min · 5 min · 15 min · 1 ghante ki candle. Faisla M5 candle band hone pe; fill M1 pe check. |
| **ATR** | "Average candle size" (pichhli 14 candles). Stop 1.5 × ATR = normal candle se 1.5 guna door. |
| **R** | 1 R = ek trade mein jitna risk kiya. $100 risk → +2 R = +$200, −1 R = −$100. |
| **Expectancy** | Har trade ka average R. **Sabse zaroori number.** +0.10 R × 100 trades ≈ +10 R. |
| **Spread** | Buy aur sell price ka farak — har trade ka "tax". |
| **Slippage** | Socha tha usse thoda kharab price mila (khaas kar stop pe). |
| **Commission** | Broker fee per lot. Exness Raw: $10 / lot round turn. |
| **Swap** | Raat bhar trade rakhne ka charge. |
| **Long / Short** | Long = upar jaane pe kamai (buy). Short = neeche jaane pe (sell). |

### 4b. Imaandari (honesty) ke shabd

| Shabd | Matlab |
|---|---|
| **Tier A / B / C** | Data ke 3 hisse (neeche detail). A = homework, B = mock test, C = sealed board exam. |
| **Optimistic · Base · Pessimistic** | 3 cost scenario: sasta (p25) · normal (p50) · mehenga (p90). Pass/fail **sirf Pessimistic** ("gate") se. |
| **Trial** | Har backtest ek "koshish" gina jaata hai. Zyada koshish = luck se jeetne ka chance zyada. |
| **Family** | Ek idea + uske saare variants. Family ke trials jitne zyada, pass hone ka bar utna ooncha. |
| **Deflated Sharpe** | "Kya yeh sirf luck hai?" test, trials ke hisaab se. > 0 chahiye. |
| **Hypothesis / Pre-registration** | Result dekhne se PEHLE likh dena ki idea kyun kaam karega. |
| **Profit Factor (PF)** | Total jeet ÷ total haar. 1.0 = barabar. Chahiye ≥ 1.15. |
| **Max Drawdown (DD)** | Peak se sabse bada gira hua nuksaan (R mein). Chahiye ≤ 15 R. |
| **Walk-forward (WF)** | 12 mahine pe seekho → agle 3 mahine pe trade → aage khisko → repeat. |
| **§15** | Pehle se likhe hue pass/fail rules (blueprint ka section 15). |
| **Candidate / Rejected** | Sab §15 pass (holdout ke alawa) = Candidate. Ek bhi fail = Rejected. Partial pass nahi hota. |
| **Holdout** | Tier C ka doosra naam — final exam. |
| **Bootstrap / Monte Carlo** | Trades ko shuffle karke dekhna ki result kitna upar-neeche ho sakta tha. |
| **FDR / q** | Bahut saare ideas ek saath test karne pe luck-correction (q = 10%). |

### 4c. Chart aur pattern ke shabd

| Shabd | Matlab |
|---|---|
| **Session** | Asian, London, New York, overlap (London + NY saath). |
| **Swing (●)** | Chhota pahad (high) ya ghaati (low). 5 candle baad pakka hota hai. |
| **S/R** | Support / Resistance: level jahan price 2+ baar ruka. Motii line = 3+ baar. |
| **Trendline / Channel** | Rising lows ko jodne wali line (blue) / falling highs (orange). Dashed = channel. |
| **SW — Sweep** | Level ke thoda paar gaya aur wapas aa gaya (stop-hunt / liquidity sweep). |
| **BO · RT · FB** | Breakout (level toda) · Retest (wapas aake chhua) · Failed break (toda, phir fail). |
| **PDH / PDL** | Previous Day High / Low — kal ka sabse ooncha / neecha price. |
| **Volatility regime** | Market kitna hil raha hai: low / mid / high. |
| **Rollover window** | Roz raat ka time jab spread bahut badh jaata — us time entry band. |
| **Sequence (DDU, UUD…)** | Pichhli candles ka pattern: D = down, U = up. DDU = down-down-up. |
| **available_at** | Yeh info kis time pata chali. Future ka data kabhi use nahi hota (no look-ahead). |
| **Spec** | Strategy ke rules ki file. Har tareeka (form, chart, AI) yahi banata hai. |
| **Intrabar ambiguity (amb)** | Ek hi M1 candle mein stop aur target dono — kaun pehle laga, pakka nahi. |

---

## 5. Sabse zaroori concept: Tier A · B · C

| Tier | Dates | Kaam | Misaal |
|---|---|---|---|
| **A** | Jul 2021 → Aug 2024 | Development — idea banao, tune karo, Optimize yahin | Homework — jitni baar chaho |
| **B** | Aug 2024 → Sep 2025 | Validation — strategy ne yeh data kabhi "dekha" nahi | Mock test — pehla asli saboot |
| **C** | Sep 2025 → aaj | **Sealed.** Sirf Validate page pe, sab pass hone ke baad, har family ke liye **ek baar**, reason likh ke | Board exam |

AI kabhi Tier C nahi dekh sakta. Split `storage/research/split.json` mein freeze hai.

---

## 6. Har page — kya hai, kaise use karein

### 6.1 CEO Work Lab — `/ceo-lab`
**Kya hai:** sabse aasaan darwaza. Aap sawaal Hinglish mein likhte ho; 5 AI agents plan bana ke
engine se test karte hain aur simple report dete hain.
**Misaal:** aap CEO, Director kaam baantta, 4 specialist research karte.

Kaise:
1. "Naya research mission" box mein sawaal likho (ya 3 examples mein se chuno).
2. Claude Code is folder mein kholo aur `/ceo-run` chalao (ya `Start_CEO_Bridge.bat` + page ka button).
3. Director plan banata hai → **Plan approve karo**, ya Director ko likho kya badalna hai.
4. "Kaam ki list" aur "Live activity" mein dekho kaun kya kar raha hai.
5. Report padho: verdict + limitations + aage kya. Har number ke saath uska run id.

Agents: **Research Director** (plan), **Data Scientist** (data quality, sessions, volatility),
**Pattern Analyst** (chart idea → exact rule → study), **Strategy Architect** (rule → spec),
**Validator** (costs ke saath backtest + walk-forward). **Director Room** = Director se chat.
Verdicts: *Aage research karne layak · Abhi pakka nahi keh sakte · Edge nahi mila · Data/tool ki kami se ruka.*

> Dhyan: Claude Code CLI abhi is PC pe install nahi hai, isliye bridge button abhi test nahi hua.

### 6.2 Overview — `/`
**Kya hai:** gold ka chart + har candle ki "report card".
1. Timeframe chuno (M1/M5/M15/H1); time zone India (IST) default.
2. **Structure** buttons: Swings, S/R, Trendlines, Events (SW, BO, RT, FB).
3. Kisi candle pe click → right side **M5 bar features** panel.
4. Green **Entry allowed** ya red **No entry · Rollover / Abnormal spread / First-Last 3 bars of week**.
5. Neeche 4 cards: AI Discovery, Visual Builder, Chart-Based Creator, Strategy Library. Right: Data Health.

Feature groups: *anatomy* (body, wicks), *sequence*, *volatility*, *session*, *M15/H1 context*,
*market structure*, *indicators* (EMA, RSI, MACD, Bollinger…), *hygiene flags*, *cost model spread*.

### 6.3 Data Center · Costs — `/costs`
**Kya hai:** har trade ka asli kharcha — spread, slippage, commission, swap.
**Misaal:** dukaan ka profit tabhi asli jab kiraya-bijli minus karke bhi bache.
1. **Account cost profiles:** `demo_trial7` (✓ validated) aur `raw` (◐ provisional). "Active" wala naye tests mein lagta.
2. **Use for new runs** se profile badlo. Final faisla `raw` profile se (aap Raw account pe trade karoge).
3. Heatmap (ghanta × din), spread level since 2021, saal-wise table.
4. Right cards: Cost scenarios (pessimistic = gate), Validation, Swap & commission.
5. Raw demo ke ticks aane pe **Calibrate Raw** (open item A7). Tab tak `raw` provisional hai aur isse koi strategy pass nahi ho sakti.

Roz kuch karna nahi — kabhi-kabhi check.

### 6.4 Behaviour Explorer — `/explorer`
**Kya hai:** "Pattern X ke baad gold ne asal mein kya kiya?" — strategy se pehle.
**Misaal:** mausam vibhag — pehle pakka karo ki baadal ke baad baarish hoti hai, phir chhata becho.

Teen tabs:
- **Pre-registered library:** pehle se likhe behaviours. **Screen every behaviour** = sab ek saath,
  luck-correction (FDR) ke saath, costs se pehle aur baad. Kisi pe **Study** → poori report.
- **Event study:** apna pattern likho (conditions + stop/target × ATR + horizon) → sirf Tier A pe
  *exploratory*. Pasand aaye to pre-register → tab Tier B pe test.
- **Distributions:** koi feature saal / session / volatility / tier ke hisaab se kaisa behave karta.

Report ke shabd: *Occurrences* (kitni baar), *Target hit first*, *Avg R before/after costs*,
*Chance it is luck*, *95% range*, *MFE/MAE* (trade ke dauran max faayda / nuksaan),
*Years / sessions positive*, *Next steps* (engine ka suggestion).

### 6.5 Strategy Lab — `/strategy-lab`
Teen tareeke, ek hi spec, ek hi backtester:

| Tareeka | Kya | Kaise |
|---|---|---|
| **Visual Builder** | Forms bharke rules — koi code nahi | "Start from:" example chuno → 5 steps bharo → ✓ valid spec → Save → Backtest |
| **Chart-Based Creator** | Chart pe candle pe click → rules | Chart Tier B ke end pe khulta → entry candle pe click → 2–4 facts tick → Review in Visual Builder |
| **AI Discovery** | Engine saare combinations khud test kare | New search: behaviours × sessions × volatility × exits; method grid/random/evolutionary; mode "I approve" ya unattended |

**Visual Builder ke 5 hisse:**
1. **Idea** — Name, Family (variants ka group), Hypothesis (test se pehle likho).
2. **Entry rules** — Feature, Operator (>, <, =, in), Value. Ek rule ke andar sab conditions sach; koi bhi ek rule trade khol de.
3. **Filters** — Sessions, Hours (UTC), Weekdays, Volatility regime, Max spread ÷ 5-day median.
4. **Exit** — Stop × ATR, Target × ATR, Trailing × ATR, Time exit (M5 bars; 24 = 2 ghante).
5. **Sizing** — Starting equity (USD), Risk % per trade. Result R mein bhi aata hai, isliye size se edge nahi badalti.

Right side: **Check** (✓ valid spec), **Signals · tier A / B**, **Where it fires** (chart pe ▲ long / ▼ short).
Har M5 candle band hone pe rules check; entry agle M1 open pe.

### 6.6 Backtest — `/backtest`
**Kya hai:** saved strategy purane data pe, har trade asli kharchon ke saath, teeno scenario ek saath.
**Misaal:** gaadi ka test drive — shehar (A), highway (B), dono (A+B), petrol ka kharcha bhi.
1. **Run a backtest:** strategy chuno → Tier A / Tier B / Tier A+B.
2. Upar: Trades, Win rate, **Expectancy · pessimistic**, Profit factor, Max drawdown, Family trials, Deflated Sharpe.
3. **Equity in R:** teen lines; gold (pessimistic) hi count hoti.
4. **What the costs take** (kharcha kitna R kha gaya) · **How much cost can it take?** (aur kitna spread seh sakti).
5. **Where it works:** year / session / weekday / regime. **Trades** list pe click → M1 chart pe replay.
6. **Is it luck?** Deflated Sharpe + bootstrap.

### 6.7 Optimize — `/optimize`
**Kya hai:** 1–3 settings ki range do (From / To / Step); engine har combination Tier A pe test karta (max 400).
1. Strategy chuno → **+ add a parameter** → Run.
2. **All variants** table (pessimistic expectancy se sorted).
3. Do parameter ho to **Sensitivity map**: **plateau** (aas-paas ki settings bhi achhi = asli pattern) ✓ vs **spike** (sirf ek setting achhi = shayad luck) ✗.
4. Best wale ko → Validate.

Har variant ek trial — 400 try kiye to bar bahut ooncha. "Best vs luck (Deflated Sharpe)" yahi batata.

### 6.8 Validate — `/validate`
**Kya hai:** final judge. §15 checklist, pessimistic costs.

| Criterion | Chahiye |
|---|---|
| Net expectancy (pessimistic) | ≥ +0.10 R |
| Trades — Tier A / Tier B | ≥ 1,000 / ≥ 250 |
| Profit factor (pessimistic) | ≥ 1.15 |
| Max drawdown | ≤ 15 R aur ≤ 20% equity |
| Stability — saal aur session | ≥ 70% positive |
| Intrabar ambiguity | ≤ 5% |
| Deflated Sharpe (trials ke saath) | > 0 |
| Holdout (Tier C) expectancy | > 0 aur ≥ 50% of Tier A |
| Holdout accesses | exactly 1 |
| Cost profile | calibrated Raw profile (research note 3) |

Kaise: strategy chuno → Walk-forward (khaali = fixed rules; ya parameters do = har 12 mahine re-tune,
agle 3 pe trade) → Run → *Tiers side by side, Stability, Promotion checklist* → verdict
(**Candidate / Rejected / Not yet decided**). Sab pass ho tabhi **Unseal tier C** — reason likho, ek baar.

### 6.9 Research Pipeline — `/pipeline`
**Kya hai:** AI Discovery searches ka control room. Engine ideas banata → register → Tier A screen →
top ones ka Validate → har ek ka accept/reject reason ke saath.
Hypothesis status: *registered · passed screen · not selected · ✓ candidate · ✗ rejected*.
**Luck bar (SR0)** = itne trials mein sirf luck se kitna achha dikh sakta — isse upar chahiye.
**Screen floor** = Tier A mein kam se kam itne trades.

### 6.10 My Strategies — `/strategies`
Har saved strategy, version, run ek jagah. Upar: Strategies saved, Families, Variants tried, Holdouts used.
- **Library:** search, ⭐ favourite, Edit / clone, Backtest / Optimize / Validate.
- **Families:** har idea ke kitne variants try hue.
- **Candidates leaderboard:** Verdict, A∪B net R, Walk-forward R, Holdout.

### 6.11 ML Lab — `/ml`
**Kya hai:** LightGBM model seekhta hai ki strategy ke kaunse signals lene, kaunse skip karne. Tier A pe
seekhta, Tier B pe judge.
**Misaal:** cricket selector — sirf form mein chal rahe khilaadi, par selection naye match mein prove ho.
Strategy chuno → cut-off (**Probability ≥** ya **Keep top**) → **Rule alone vs Rule + ML filter** →
**What the model looked at**. Har filter = 1 trial. Tier C kabhi use nahi.

### 6.12 AI Assistant — `/assistant`
- **Mode 1 · Claude Code / Desktop (no API):** folder kholo, woh `candle-intelligence-research` tools se engine chalata. Kaam karta hai.
- **Mode 2 · Chat (API mode):** page pe chat; AgentRouter key `.env` mein. **Abhi band — budget khatam (A9).**

Kar sakta: features/behaviours/results padhna, strategy propose ("assistant" naam se), Tier A/B backtest
(trial gina jaata), Tier A exploratory study, search propose (aapki approval ke baad chalti).
Nahi kar sakta: Tier C, apni search khud approve, delete / rules badalna, account dekhna ya order.

---

## 7. Ek poora example — "Three-candle reversal"

Idea: do opposite candles ke baad strong close = turn (DDU + high ke paas close → long; ulta → short).

1. Strategy Lab → "Start from: Three-candle reversal".
2. Check → ✓ valid spec, signals gine.
3. Backtest Tier A → before costs thoda theek, pessimistic mein neeche.
4. What the costs take → kharcha hi edge kha gaya.
5. ML Lab → behtar, phir bhi loss.
6. Verdict → **Rejected** (≈ −0.28 R / trade after pessimistic costs).

**Sabak:** chhote M5 ideas mein spread + commission sabse bada dushman. Upaay: bada target/stop, strongest
cases ka filter, ya Raw account ka sasta cost profile.

---

## 8. Imaandar status (ab tak)

| Result | Matlab |
|---|---|
| 0 / 18 | pre-registered behaviours luck-correction ke baad pass (Tier A) |
| 0 / 120 | pehli AI search — sab variants rejected |
| +0.025 R | pehla CEO mission (PDL sweep long, 59 trades) → "abhi pakka nahi" |
| −0.28 R | example strategies, pessimistic costs ke baad |

Aapki taraf se pending: **A7** Raw Spread demo ke ticks → Calibrate Raw (iske bina kuch pass nahi ho
sakta) · **A9** AgentRouter budget · Claude Code CLI install (CEO bridge ke liye).
Aage: Phase 11 Paper Trading → Phase 12 20 saal ka data → Phase 13 Research Gate.

---

## 9. Beginner ke 3 raaste

| Raasta | Steps |
|---|---|
| **A · Sirf sawaal poochna** (sabse aasaan) | CEO Work Lab mein mission → `/ceo-run` → plan approve → report |
| **B · Apna idea test** | Overview → Strategy Lab (Visual Builder, example se) → Backtest Tier A → achha lage to Validate |
| **C · Market samajhna** | Behaviour Explorer → Library → Screen every behaviour → Study → Next steps |

---

## 10. Aapke feedback ke liye sawaal (changes isi se plan honge)

1. Kaunse pages sabse confusing lage? Kuch pages "Advanced" mein chhupa dein?
2. Screen pe keywords English rahein, ya Hinglish label + hover pe matlab?
3. "Simple mode" chahiye — sirf CEO Work Lab + Overview + My Strategies?
4. Har page pe "Yeh page kya karta hai" help box?
5. Kaunsa raasta (A / B / C) sabse zyada use karoge?
