# References opened before citing (16 Nov 2026)

"Opened" means the page was fetched in the build session and read at the level stated. Only abstracts or landing pages were read, so each citing sentence in the paper is limited to what that page says. No reference was cited from memory.

| Key | URL opened | Level | Fact used |
|---|---|---|---|
| mcp2025 | https://modelcontextprotocol.io/specification/2025-06-18 | spec overview | MCP is an open protocol on JSON-RPC that lets servers expose tools to LLM applications. |
| fm2026brokers | https://www.financemagnates.com/forex/tradingview-adds-mcp-as-retail-brokers-adopt-ai-trading-tools/ (16 Sep 2026) | article | Several retail brokers and platforms (ThinkMarkets, IG Australia, Spotware, Webull named) launched MCP tools connecting AI assistants to trading platforms, some able to execute trades. Webull's own launch (financemagnates.com, 11 Jun 2026) was also opened: agents can submit and manage orders. |
| amodei2016 | https://arxiv.org/abs/1606.06565 | abstract | Lists "avoiding reward hacking" as one of five research problems, arising from a wrong objective function. The abstract does not define the term. |
| bailey2014 | https://api.crossref.org/works/10.3905/jpm.2014.40.5.094 | Crossref record | Title, authors, J. Portfolio Management 40(5), 94-107, 2014. The SSRN page returned 403, so the abstract was not read. The paper is cited for the expected-maximum-Sharpe correction named in its title and implemented in `court/forensics.py trial_haircut`. |
| bailey2016 | https://api.crossref.org/works/10.21314/JCF.2016.322 | Crossref record | Title, authors, J. Computational Finance, 2016. Abstract not read (SSRN 403). Cited only as a standard test for backtest overfitting. |
| harvey2016 | https://www.nber.org/papers/w20592 and https://api.crossref.org/works/10.1093/rfs/hhv059 | NBER abstract page and Crossref | Multiple-testing framework for factor research; a new factor should clear a t-ratio of about 3.0; many published findings are likely false. RFS 29(1), 5-68, 2016. |
| irving2018 | https://arxiv.org/abs/1805.00899 | abstract | Two agents argue opposing sides and a judge picks the truer answer. |
| khan2024 | https://arxiv.org/abs/2402.06782 | abstract | Debate between LLM experts helps a non-expert judge reach truthful answers. |
| kenton2024 | https://arxiv.org/abs/2407.04622 | abstract | Weak LLM judges of strong LLMs; debate beats consultancy on the tested tasks. |
| greenblatt2023 | https://arxiv.org/abs/2312.06942 | abstract | Safety protocols such as trusted editing and untrusted monitoring against intentional subversion. |
| chennabasappa2025 | https://arxiv.org/abs/2505.03574 | abstract | LlamaFirewall: guardrails for jailbreaks, prompt injection, goal misalignment and insecure code. |
| she2026 | https://arxiv.org/abs/2607.01236 | abstract | ProvenanceGuard checks that an agent's proposed tool call is backed by traceable evidence and blocks misaligned actions before they run. |
| xiao2024 | https://arxiv.org/abs/2412.20138 | abstract | TradingAgents: analysts, bull and bear researchers, risk managers and a trader that debate inside the agent. |
| scheurer2023 | https://arxiv.org/abs/2311.07590 | abstract | A GPT-4 trading agent acted on an insider tip and concealed its reasons from its manager. |
| gencay2026 | https://arxiv.org/abs/2608.27734 | abstract | Leakage-safe, search-aware assessment of LLM-discovered strategies; a leaky oracle with Sharpe 35 passes standard overfitting tests. |
| backtestauditor2026 | https://github.com/taku629/backtest-auditor | README | LLM agents write strategies, deterministic tests (look-ahead, survivorship, overfitting) decide whether they are honest; unrefereed repository. |

## Recheck by Pranav, 16 Nov 2026 (evening)
- All 16 entries were compared with their official records: Crossref for the three journal articles (titles, authors, journals, volume, issue, pages and years match; Crossref lists no volume or pages for bailey2016), the arXiv API for the ten arXiv papers (titles, every author and years match), and the live pages for mcp2025, fm2026brokers (published 16 Sep 2026) and backtestauditor2026.
- khan2024: the full text (arXiv v4, pp. 2-3) was read for the intro sentence. Debaters use a quote tool, quotes that match the text are marked verified, and the judge is told to trust only verified quotes. The sentence "Khan et al. let debaters quote verified text" is supported.
- gencay2026: the abstract supports the sentence about deterministic look-ahead and overfitting checks attached to strategy-writing agents.
- backtestauditor2026: the title copies the README heading. A comma was changed to a full stop to match it exactly.
- Still open: the abstracts of bailey2014 and bailey2016 were not fetched (SSRN). Pranav confirmed that bailey2014 fits the sentences that cite it, and that bailey2016 and harvey2016 fit the intro sentence ("The statistical traps are well documented"). For "The tests are standard [bailey2014, bailey2016, harvey2016]", the three papers cover the selection and trial-count corrections, not the lag, cost or survivorship tests; kept as is (see QUESTIONS_FOR_ARUSH.md).

Not cited, not opened in full: AEGIS (2603.12621), PolicyGuard, MELON, TradeTrap and the rest of the prior-art file. Each needs opening before any use.
Open items: full text of every entry was not read; the two Bailey papers need their abstracts checked (SSRN blocked the fetch); the claim "none is new" about the standard tests rests on their being published methods and should be rechecked at freeze.

## Recheck, 17 Nov 2026 (second pass before submission)
- All 16 entries re-checked independently against arXiv (abstract page and official BibTeX), Crossref and the live pages. Every author name, in order, matches its source; no entry is invented.
- greenblatt2023 and khan2024 now cite their ICML 2024 versions: PMLR vol. 235, pp. 16295-16336 and pp. 23662-23733 (proceedings.mlr.press/v235/greenblatt24a and khan24a; author lists identical to arXiv).
- she2026 now cites its ASE 2026 version: Proceedings of the 41st IEEE/ACM International Conference on Automated Software Engineering, pp. 3036-3048, DOI 10.1145/3832783.3837535 (Crossref).
- fm2026brokers now names its author, Tareq Sikder (article metadata; published 16 Sep 2026).
- scheurer2023 stays an arXiv citation: its only other venue is the ICLR 2024 LLM Agents workshop (OpenReview), not the main conference.
- kenton2024 and xiao2024 stay as arXiv citations (first-version years).
