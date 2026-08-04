// Resolve API Base URL depending on how index.html is loaded
const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:8080" : "";

// Local memory to cache last scanned data for client-side search/filter/sort
let activeScanData = {
    bullish_candidates: [],
    bearish_candidates: []
};

// Tab Switcher Logic for iOS Segmented Controls
function setupTabNavigation() {
    const buttons = document.querySelectorAll(".segment-btn");
    const sections = document.querySelectorAll(".view-section");
    const filtersContainer = document.getElementById("filters-container");

    buttons.forEach(button => {
        button.addEventListener("click", () => {
            const targetId = button.getAttribute("data-target");

            // Toggle button active state
            buttons.forEach(btn => btn.classList.remove("active"));
            button.classList.add("active");

            // Toggle section visibility
            sections.forEach(sec => {
                if (sec.id === targetId) {
                    sec.classList.add("active");
                } else {
                    sec.classList.remove("active");
                }
            });

            // Hide filter tools on history page
            if (targetId === "history-section") {
                filtersContainer.style.display = "none";
            } else {
                filtersContainer.style.display = "flex";
            }
        });
    });
}

// Open TradingView widget in modal
function openTradingViewModal(symbol) {
    const modal = document.getElementById("chart-modal");
    const modalTitle = document.getElementById("modal-title");
    const externalLink = document.getElementById("modal-external-link");
    
    modalTitle.innerText = `${symbol} Interactive Chart`;
    externalLink.href = `https://www.tradingview.com/symbols/NSE-${symbol}/`;
    
    modal.classList.add("active");

    new TradingView.widget({
        "autosize": true,
        "symbol": `NSE:${symbol}`,
        "interval": "D",
        "timezone": "Asia/Kolkata",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "toolbar_bg": "#f1f3f6",
        "enable_publishing": false,
        "hide_side_toolbar": false,
        "allow_symbol_change": true,
        "container_id": "tradingview_widget"
    });
}

// Modal closing setup
document.getElementById("modal-close").addEventListener("click", () => {
    document.getElementById("chart-modal").classList.remove("active");
});
window.addEventListener("click", (e) => {
    const modal = document.getElementById("chart-modal");
    if (e.target === modal) {
        modal.classList.remove("active");
    }
});

// Click delegation to trigger modal on clicking any stock badge
document.addEventListener("click", (e) => {
    const badge = e.target.closest(".stock-badge");
    if (badge) {
        const symbol = badge.textContent.trim().replace(".NS", "");
        openTradingViewModal(symbol);
    }
});

// Helper function to build rows
const populateTable = (candidates, tbody, type) => {
    if (candidates.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="no-results">
                    <i class="fa-solid fa-circle-info" style="font-size: 20px; color: var(--accent-orange); margin-bottom: 10px; display: block;"></i>
                    No stocks matching ${type} setups found.
                </td>
            </tr>
        `;
    } else {
        tbody.innerHTML = "";
        candidates.forEach(candidate => {
            const tr = document.createElement("tr");
            
            const isApproved = candidate.status === "APPROVED";
            const statusClass = isApproved ? "approved" : "blocked";
            const aiBadge = isApproved 
                ? `<span class="status-badge approved"><i class="fa-solid fa-shield-check"></i> Clean</span>`
                : `<span class="status-badge blocked"><i class="fa-solid fa-triangle-exclamation"></i> Flagged</span>`;
                
            tr.innerHTML = `
                <td><span class="stock-badge">${candidate.symbol}</span></td>
                <td><span class="price-text">₹ ${candidate.close_price}</span></td>
                <td><span class="${type === 'bullish' ? 'target-text' : 'sl-text'}">₹ ${candidate.target_price}</span></td>
                <td><span class="${type === 'bullish' ? 'sl-text' : 'target-text'}">₹ ${candidate.stop_loss}</span></td>
                <td><strong style="color: var(--accent-blue);">${candidate.accuracy_score}%</strong></td>
                <td><strong>${candidate.rsi}</strong></td>
                <td><span class="trigger-text">${candidate.setup_trigger}</span></td>
                <td title="${candidate.ai_reason}">${aiBadge}</td>
                <td><span class="status-badge ${statusClass}">${candidate.status}</span></td>
            `;
            
            tbody.appendChild(tr);
        });
    }
};

// Filter & Sort core logic
function applyFiltersAndSorting() {
    const searchQuery = document.getElementById("search-input").value.toLowerCase().trim();
    const selectedStrategy = document.getElementById("strategy-filter").value.toLowerCase();
    const sortVal = document.getElementById("sort-select").value;

    const filterCandidates = (candidates) => {
        let result = [...candidates];

        // 1. Search Query
        if (searchQuery) {
            result = result.filter(c => c.symbol.toLowerCase().includes(searchQuery));
        }

        // 2. Strategy Filter
        if (selectedStrategy) {
            result = result.filter(c => c.setup_trigger.toLowerCase().includes(selectedStrategy));
        }

        // 3. Sorting
        if (sortVal === "accuracy-desc") {
            result.sort((a, b) => b.accuracy_score - a.accuracy_score);
        } else if (sortVal === "rsi-asc") {
            result.sort((a, b) => a.rsi - b.rsi);
        } else if (sortVal === "rsi-desc") {
            result.sort((a, b) => b.rsi - a.rsi);
        } else if (sortVal === "price-asc") {
            result.sort((a, b) => a.close_price - b.close_price);
        } else if (sortVal === "price-desc") {
            result.sort((a, b) => b.close_price - a.close_price);
        }

        return result;
    };

    const filteredBullish = filterCandidates(activeScanData.bullish_candidates);
    const filteredBearish = filterCandidates(activeScanData.bearish_candidates);

    populateTable(filteredBullish, document.getElementById("bullish-tbody"), "bullish");
    populateTable(filteredBearish, document.getElementById("bearish-tbody"), "bearish");
}

// Bind Filter controls to the filter function
document.getElementById("search-input").addEventListener("input", applyFiltersAndSorting);
document.getElementById("strategy-filter").addEventListener("change", applyFiltersAndSorting);
document.getElementById("sort-select").addEventListener("change", applyFiltersAndSorting);

// Fetch past scans and populate the audit/performance tracker table
async function loadHistory() {
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    
    try {
        const response = await fetch(`${API_BASE}/history`);
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.history.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="9" class="no-results">No past scan records logged in history. Run a scan to build history.</td>
                </tr>
            `;
            return;
        }
        
        tbody.innerHTML = ""; // Clear loader/previous data
        
        data.history.forEach(item => {
            const tr = document.createElement("tr");
            
            // Format Outcome Status badge
            let outcomeBadge = "";
            if (item.outcome === "ACHIEVED") {
                outcomeBadge = `<span class="status-badge achieved"><i class="fa-solid fa-circle-check"></i> ACHIEVED</span>`;
            } else if (item.outcome === "FAILED") {
                outcomeBadge = `<span class="status-badge failed"><i class="fa-solid fa-circle-xmark"></i> FAILED</span>`;
            } else if (item.outcome === "EXPIRED") {
                outcomeBadge = `<span class="status-badge expired"><i class="fa-solid fa-circle-minus"></i> EXPIRED</span>`;
            } else {
                outcomeBadge = `<span class="status-badge active-trade"><i class="fa-solid fa-circle-play"></i> ACTIVE</span>`;
            }
            
            const isBuy = item.type === "BUY";
            const typeBadge = `<span style="font-weight: 600; color: ${isBuy ? 'var(--accent-green)' : 'var(--accent-red)'};">${item.type}</span>`;
            
            tr.innerHTML = `
                <td><span style="font-size: 12px; color: var(--text-secondary); font-family: monospace;">${item.scan_date}</span></td>
                <td><span class="stock-badge">${item.symbol}</span></td>
                <td>${typeBadge}</td>
                <td><span class="price-text">₹ ${item.entry_price}</span></td>
                <td><span class="target-text">₹ ${item.target_price}</span></td>
                <td><span class="sl-text">₹ ${item.stop_loss}</span></td>
                <td><span class="trigger-text" style="font-size: 12px; display: block; max-width: 320px; line-height: 1.4;">${item.setup_trigger}</span></td>
                <td><strong>${item.rsi}</strong></td>
                <td>${outcomeBadge}</td>
            `;
            
            tbody.appendChild(tr);
        });
        
    } catch (err) {
        console.error("Failed to load scan history:", err);
        tbody.innerHTML = `
            <tr>
                <td colspan="9" class="no-results" style="color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation"></i> Error loading past suggestions.
                </td>
            </tr>
        `;
    }
}

document.getElementById("scan-btn").addEventListener("click", async () => {
    const btn = document.getElementById("scan-btn");
    const loader = document.getElementById("loader");
    const board = document.getElementById("results-board");
    const bullishTbody = document.getElementById("bullish-tbody");
    const bearishTbody = document.getElementById("bearish-tbody");
    
    // UI state transitions
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-sync fa-spin"></i> Scanning...`;
    loader.style.display = "flex";
    board.style.opacity = "0.5";
    
    bullishTbody.innerHTML = "";
    bearishTbody.innerHTML = "";
    
    document.getElementById("stat-bullish").innerText = "Scanning...";
    document.getElementById("stat-bearish").innerText = "Scanning...";
    document.getElementById("stat-sentinel").innerText = "RUNNING";
    
    try {
        const response = await fetch(`${API_BASE}/scan`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            }
        });
        
        if (!response.ok) {
            throw new Error(`API Error: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        // Save scan results in memory
        activeScanData.bullish_candidates = data.bullish_candidates || [];
        activeScanData.bearish_candidates = data.bearish_candidates || [];
        
        // Update Stats Cards
        document.getElementById("stat-total").innerText = `${data.total_scanned} Stocks`;
        document.getElementById("stat-bullish").innerText = `${activeScanData.bullish_candidates.length} Found`;
        document.getElementById("stat-bearish").innerText = `${activeScanData.bearish_candidates.length} Found`;
        document.getElementById("stat-sentinel").innerText = "COMPLETED";
        
        // Populate Tables
        populateTable(activeScanData.bullish_candidates, bullishTbody, 'bullish');
        populateTable(activeScanData.bearish_candidates, bearishTbody, 'bearish');
        
        // Clear filter inputs on new scan
        document.getElementById("search-input").value = "";
        document.getElementById("strategy-filter").value = "";
        document.getElementById("sort-select").value = "accuracy-desc";

        // Refresh past suggestion tracker
        await loadHistory();
        
    } catch (err) {
        alert("Scanner failed. Please verify uvicorn backend is running!");
        console.error(err);
        
        const errRow = `
            <tr>
                <td colspan="9" class="no-results" style="color: var(--accent-red);">
                    <i class="fa-solid fa-triangle-exclamation" style="font-size: 24px; margin-bottom: 10px; display: block;"></i>
                    Scanning error encountered. Check your connection or server status.
                </td>
            </tr>
        `;
        bullishTbody.innerHTML = errRow;
        bearishTbody.innerHTML = errRow;
        
        document.getElementById("stat-bullish").innerText = "ERROR";
        document.getElementById("stat-bearish").innerText = "ERROR";
        document.getElementById("stat-sentinel").innerText = "OFFLINE";
    } finally {
        loader.style.display = "none";
        board.style.opacity = "1";
        btn.disabled = false;
        btn.innerHTML = `<i class="fa-solid fa-satellite-dish"></i> Scan Watchlist`;
    }
});

// Load history and setup navigation automatically on page bootup
window.addEventListener("load", () => {
    loadHistory();
    setupTabNavigation();
});
