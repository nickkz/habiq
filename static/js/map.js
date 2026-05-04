/**
 * HaBIQ / IQ – Map & UI
 */
const HaBIQ = (() => {
  let map, clusterGroup, tileLayer;
  let allFeatures = [];
  let activeMarkerId = null;
  let priceChart = null;
  const markerMap = {};
  let lbPhotos = [], lbIdx = 0;

  let activeMarket = "";
  let mapTheme = "dark";  // "dark" | "light"

  const TILES = {
    dark:  { url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",  attr: "&copy; OpenStreetMap &copy; CARTO" },
    light: { url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", attr: "&copy; OpenStreetMap &copy; CARTO" },
  };

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    initMap();
    initMarketToggle();
    loadStats();
    loadCounties();
    applyFilters();   // use default filter values (Multi-Family selected) from first load
  }

  function initMap() {
    const cfg = window.HABIQ_CONFIG || { mapLat: 41.15, mapLng: -75.2, mapZoom: 10 };
    map = L.map("map", { zoomControl: true }).setView([cfg.mapLat, cfg.mapLng], cfg.mapZoom);
    tileLayer = L.tileLayer(TILES.dark.url, {
      attribution: TILES.dark.attr, subdomains: "abcd", maxZoom: 19,
    }).addTo(map);
    clusterGroup = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: 55, spiderfyOnMaxZoom: true });
    map.addLayer(clusterGroup);
    map.on("click", () => closeDetail());
  }

  function toggleMapTheme() {
    mapTheme = mapTheme === "dark" ? "light" : "dark";
    tileLayer.setUrl(TILES[mapTheme].url);
    const btn = document.getElementById("map-theme-btn");
    btn.innerHTML = mapTheme === "dark"
      ? '<i class="fa fa-sun"></i> Light Map'
      : '<i class="fa fa-moon"></i> Dark Map';
    btn.classList.toggle("btn-outline-secondary", mapTheme === "dark");
    btn.classList.toggle("btn-secondary",         mapTheme === "light");
  }

  function initMarketToggle() {
    document.querySelectorAll(".mtbtn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".mtbtn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeMarket = btn.dataset.val;
      });
    });
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadStats() {
    fetch("/api/stats").then(r => r.json()).then(d => {
      setText("stat-total",    d.total_properties ?? 0);
      setText("stat-onmarket",  d.on_market ?? 0);
      setText("stat-offmarket", d.off_market ?? 0);
      setText("stat-owners",    d.with_owner_info ?? 0);
    }).catch(() => {});
  }

  function loadCounties() {
    fetch("/api/counties").then(r => r.json()).then(counties => {
      const sel = document.getElementById("f-county");
      counties.forEach(c => {
        const o = document.createElement("option");
        o.value = c; o.textContent = c;
        sel.appendChild(o);
      });
    }).catch(() => {});
  }

  function loadProperties(params = {}) {
    showLoader(true);
    const qs = new URLSearchParams(params).toString();
    fetch(`/api/properties${qs ? "?" + qs : ""}`)
      .then(r => r.json())
      .then(geo => {
        allFeatures = geo.features || [];
        renderMarkers(allFeatures);
        renderList(allFeatures);
        setText("result-count", allFeatures.length);
        showLoader(false);
      })
      .catch(err => {
        showLoader(false);
        showToast("Failed to load properties.", "danger");
      });
  }

  // ── Markers ───────────────────────────────────────────────────────────────
  function renderMarkers(features) {
    clusterGroup.clearLayers();
    Object.keys(markerMap).forEach(k => delete markerMap[k]);
    features.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;
      const tier = priceTier(p);
      const icon = makeIcon(tier, false);
      const marker = L.marker([lat, lng], { icon })
        .bindPopup(buildPopup(p), { maxWidth: 240 })
        .on("click", () => {
          setActiveMarker(p.id, marker, tier);
          openDetail(p.id);
        });
      markerMap[p.id] = { marker, tier };
      clusterGroup.addLayer(marker);
    });
  }

  function makeIcon(tier, selected) {
    return L.divIcon({
      className: "",
      html: `<div class="habiq-marker ${tier}${selected ? " selected" : ""}"></div>`,
      iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -34],
    });
  }

  function setActiveMarker(id, marker, tier) {
    if (activeMarkerId && markerMap[activeMarkerId]) {
      markerMap[activeMarkerId].marker.setIcon(makeIcon(markerMap[activeMarkerId].tier, false));
    }
    activeMarkerId = id;
    marker.setIcon(makeIcon(tier, true));
    document.querySelectorAll(".prop-card").forEach(el => el.classList.remove("active"));
    const card = document.querySelector(`.prop-card[data-id="${id}"]`);
    if (card) { card.classList.add("active"); card.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
  }

  function buildPopup(p) {
    const photo = p.first_photo
      ? `<img src="${escHtml(p.first_photo)}" class="popup-photo" onerror="this.outerHTML='<div class=popup-photo-ph><i class=fa-regular fa-image></i></div>'" />`
      : `<div class="popup-photo-ph"><i class="fa fa-image"></i></div>`;
    const mBadge = p.market_status === "off_market"
      ? `<span class="market-badge badge-off">Off-Market</span>`
      : `<span class="market-badge badge-on">On-Market</span>`;
    return `<div>
      ${photo}
      <div class="popup-body">
        <div class="popup-addr">${escHtml(p.address)}</div>
        <div class="popup-city">${escHtml(p.city || "")} &nbsp;${mBadge}</div>
        <div class="popup-price">${fmtPrice(p.price || p.zestimate)}</div>
        <div class="popup-row">
          <span><i class="fa fa-bed"></i> ${p.beds ?? "–"}</span>
          <span><i class="fa fa-bath"></i> ${p.baths ?? "–"}</span>
          <span><i class="fa fa-ruler-combined"></i> ${fmtSqft(p.sqft)}</span>
        </div>
        <button class="popup-btn" onclick="HaBIQ.openDetail(${p.id})">View Details</button>
      </div>
    </div>`;
  }

  // ── Property list ─────────────────────────────────────────────────────────
  function renderList(features) {
    const el = document.getElementById("property-list");
    if (!features.length) {
      el.innerHTML = `<div class="empty-state"><i class="fa fa-map-location-dot"></i><h6>No properties found</h6><small>Adjust filters or run <code>python main.py seed</code></small></div>`;
      return;
    }
    const sorted = [...features].sort((a, b) => (a.properties.price || 0) - (b.properties.price || 0));
    el.innerHTML = sorted.map(f => {
      const p = f.properties;
      const tier = priceTier(p);
      const photo = p.first_photo
        ? `<img src="${escHtml(p.first_photo)}" class="prop-card-thumb" loading="lazy" onerror="this.outerHTML='<div class=prop-card-thumb-ph><i class=fa fa-image></i></div>'">`
        : `<div class="prop-card-thumb-ph"><i class="fa fa-image"></i></div>`;
      const badge = p.market_status === "off_market"
        ? `<span class="market-badge badge-off">Off</span>`
        : `<span class="market-badge badge-on">On</span>`;
      const displayPrice = p.price || p.zestimate;
      const noiLabel = p.noi != null
        ? `<span class="prop-card-noi ${p.noi >= 0 ? "noi-pos" : "noi-neg"}">NOI ${fmtPrice(p.noi)}/yr</span>`
        : "";
      return `<div class="prop-card" data-id="${p.id}" onclick="HaBIQ.flyToProperty(${p.id})">
        ${photo}
        <div class="prop-card-body">
          <div class="prop-card-addr">${escHtml(p.address)}</div>
          <div class="prop-card-city">${escHtml(p.city || "")}, ${escHtml(p.county || "")}</div>
          <div class="prop-card-row">
            <span class="prop-card-price price-${tier}">${fmtPrice(displayPrice)}</span>
            <span class="prop-card-meta">${p.beds ?? "–"}bd / ${p.baths ?? "–"}ba ${badge}</span>
          </div>
          ${noiLabel}
        </div>
      </div>`;
    }).join("");
  }

  // ── Detail panel ──────────────────────────────────────────────────────────
  function openDetail(propertyId) {
    document.getElementById("detail-panel").classList.add("open");
    document.getElementById("detail-content").innerHTML =
      `<div class="empty-state" style="padding-top:3rem"><div class="spinner"></div><p>Loading…</p></div>`;
    fetch(`/api/property/${propertyId}`)
      .then(r => r.json())
      .then(renderDetail)
      .catch(() => {
        document.getElementById("detail-content").innerHTML =
          `<div class="empty-state"><i class="fa fa-circle-exclamation"></i><h6>Failed to load</h6></div>`;
      });
  }

  function renderDetail(p) {
    const owner   = (p.owners || [])[0] || {};
    const history = p.sale_history || [];
    const photos  = Array.isArray(p.photos) ? p.photos : [];

    // ── Hero photo + thumbnail strip ──────────────────────────────────────
    const photosJson = JSON.stringify(photos);
    const heroHtml = photos.length
      ? `<img src="${escHtml(photos[0])}" class="detail-hero" id="detail-hero-img"
              loading="lazy" onclick="HaBIQ.openLightbox(${photosJson}, 0)"
              onerror="this.outerHTML='<div class=detail-hero-ph><i class=\\'fa fa-image\\'></i></div>'" />`
      : `<div class="detail-hero-ph"><i class="fa fa-image"></i><span>No photo available</span></div>`;

    const thumbsHtml = photos.length > 1
      ? `<div class="photo-thumbs">${photos.map((url, i) =>
          `<img src="${escHtml(url)}" class="thumb-img" loading="lazy"
               onerror="this.style.display='none'"
               onclick="HaBIQ.switchHero(${photosJson}, ${i})" />`
        ).join("")}</div>`
      : "";

    // ── Market badge ──────────────────────────────────────────────────────
    const mBadge = p.market_status === "off_market"
      ? `<span class="market-badge badge-off ms-1">Off-Market</span>`
      : `<span class="market-badge badge-on ms-1">On-Market</span>`;

    // ── Valuation grid ────────────────────────────────────────────────────
    const valHtml = `<div class="value-grid">
      ${p.price      ? `<div class="value-box"><div class="value-label">${p.market_status === "off_market" ? "Last Sale" : "List Price"}</div><div class="value-num">${fmtPrice(p.price)}</div></div>` : ""}
      ${p.zestimate  ? `<div class="value-box"><div class="value-label">Estimated Value</div><div class="value-num">${fmtPrice(p.zestimate)}</div></div>` : ""}
      ${p.rent_zestimate ? `<div class="value-box"><div class="value-label">Est. Monthly Rent</div><div class="value-num">${fmtPrice(p.rent_zestimate)}</div></div>` : ""}
    </div>`;

    // ── NOI analysis ──────────────────────────────────────────────────────
    const nd = p.noi_details;
    const noiHtml = nd ? `
    <div class="noi-table">
      <div class="noi-section-label">Income</div>
      <div class="noi-row"><span>Gross Annual Rent</span><span class="noi-val pos">${fmtPrice(nd.gross_rent)}</span></div>
      <div class="noi-row"><span>Vacancy (5%)</span><span class="noi-val neg">−${fmtPrice(nd.vacancy)}</span></div>
      <div class="noi-row noi-subtotal"><span>Effective Gross Income</span><span class="noi-val">${fmtPrice(nd.egi)}</span></div>
      <div class="noi-section-label">Expenses</div>
      <div class="noi-row"><span>Property Tax (1.5%)</span><span class="noi-val neg">−${fmtPrice(nd.taxes)}</span></div>
      <div class="noi-row"><span>Maintenance (1%)</span><span class="noi-val neg">−${fmtPrice(nd.maintenance)}</span></div>
      <div class="noi-row"><span>Insurance (0.5%)</span><span class="noi-val neg">−${fmtPrice(nd.insurance)}</span></div>
      <div class="noi-row noi-subtotal"><span>Total Expenses</span><span class="noi-val neg">−${fmtPrice(nd.expenses)}</span></div>
      <div class="noi-row noi-total">
        <span><strong>Net Operating Income</strong></span>
        <span class="noi-val ${nd.noi >= 0 ? "pos" : "neg"}">${fmtPrice(nd.noi)}</span>
      </div>
      ${nd.cap_rate != null ? `<div class="noi-row"><span>Cap Rate</span><span class="noi-val">${nd.cap_rate}%</span></div>` : ""}
    </div>`
    : `<div class="empty-state" style="padding:.75rem"><i class="fa fa-calculator"></i><h6>Insufficient data</h6><small>Requires rent estimate + property value</small></div>`;

    // ── Owner ─────────────────────────────────────────────────────────────
    const ownerHtml = owner.name ? `<div class="owner-card">
      <div class="owner-name">${escHtml(owner.name)}
        ${owner.owner_type ? `<span class="badge-type">${escHtml(owner.owner_type)}</span>` : ""}
      </div>
      ${owner.mailing_address ? `<div class="owner-row"><i class="fa fa-envelope-open-text"></i>${escHtml([owner.mailing_address, owner.mailing_city, owner.mailing_state, owner.mailing_zip].filter(Boolean).join(", "))}</div>` : ""}
      ${owner.phone ? `<div class="owner-row"><i class="fa fa-phone"></i><a href="tel:${escHtml(owner.phone)}">${escHtml(owner.phone)}</a></div>` : `<div class="owner-row"><i class="fa fa-phone"></i><span style="color:var(--muted)">Phone not on file</span></div>`}
      ${owner.email ? `<div class="owner-row"><i class="fa fa-at"></i><a href="mailto:${escHtml(owner.email)}">${escHtml(owner.email)}</a></div>` : ""}
      <div class="owner-row" style="margin-top:.35rem"><i class="fa fa-database"></i><small style="font-size:.65rem;color:var(--muted)">Source: ${escHtml(owner.source || "unknown")}</small></div>
    </div>`
    : `<div class="empty-state" style="padding:.8rem"><i class="fa fa-user-slash"></i><h6>Owner not found</h6><small>Run <code>python main.py owners</code></small></div>`;

    // ── Sale history ──────────────────────────────────────────────────────
    const histHtml = history.length ? `<table class="sale-table">
      <thead><tr><th>Date</th><th>Event</th><th>Price</th></tr></thead>
      <tbody>${history.map(e => {
        const cls = e.event?.toLowerCase().includes("sold") ? "ev-sold"
                  : e.event?.toLowerCase().includes("list") ? "ev-listed" : "ev-change";
        return `<tr><td>${fmtDate(e.date)}</td><td class="${cls}">${escHtml(e.event || "–")}</td><td>${fmtPrice(e.price)}</td></tr>`;
      }).join("")}</tbody>
    </table>` : `<div class="empty-state" style="padding:.75rem"><i class="fa fa-clock-rotate-left"></i><h6>No history available</h6></div>`;

    const showChart = history.filter(e => e.price).length > 1;

    document.getElementById("detail-content").innerHTML = `
      ${heroHtml}
      ${thumbsHtml}
      <div class="detail-address">${escHtml(p.address)} ${mBadge}</div>
      <div class="detail-city">${escHtml(p.city || "")}, ${escHtml(p.state || "PA")} ${escHtml(p.zip_code || "")} · ${escHtml(p.county || "")}</div>
      <div class="detail-price">${fmtPrice(p.zestimate || p.price)}</div>
      <div class="detail-price-label">${p.zestimate ? "Est. Value" : "List Price"}</div>
      <div class="detail-chips">
        ${p.property_type ? `<span class="chip chip-type"><i class="fa fa-house-chimney"></i><strong>${escHtml(p.property_type)}</strong></span>` : ""}
        <span class="chip"><i class="fa fa-bed"></i><strong>${p.beds ?? "?"}</strong> beds</span>
        <span class="chip"><i class="fa fa-bath"></i><strong>${p.baths ?? "?"}</strong> ba</span>
        ${p.sqft          ? `<span class="chip"><i class="fa fa-ruler-combined"></i><strong>${fmtSqft(p.sqft)}</strong></span>` : ""}
        ${p.unit_count    ? `<span class="chip"><i class="fa fa-building"></i><strong>${p.unit_count}</strong> units</span>` : ""}
        ${p.year_built    ? `<span class="chip"><i class="fa fa-calendar"></i>Built <strong>${p.year_built}</strong></span>` : ""}
        ${p.days_on_market != null && p.market_status === "on_market" ? `<span class="chip"><i class="fa fa-clock"></i><strong>${p.days_on_market}</strong> DOM</span>` : ""}
        <span class="chip"><i class="fa fa-ban" style="color:var(--accent2)"></i>No HOA</span>
      </div>
      ${p.description ? `<div style="font-size:.77rem;color:var(--muted);line-height:1.55;margin-bottom:.75rem">${escHtml(p.description).substring(0, 300)}${p.description.length > 300 ? "…" : ""}</div>` : ""}

      <div class="section-title"><i class="fa fa-user-tie"></i>Owner</div>
      ${ownerHtml}

      <div class="section-title"><i class="fa fa-chart-line"></i>Valuation</div>
      ${valHtml}
      <div class="listing-links">
        ${buildZillowLink(p)}
        ${buildRedfinLink(p)}
      </div>

      <div class="section-title"><i class="fa fa-calculator"></i>Financial Analysis</div>
      ${noiHtml}

      <div class="section-title"><i class="fa fa-clock-rotate-left"></i>Sale History</div>
      ${histHtml}
      ${showChart ? `<canvas id="price-chart"></canvas>` : ""}
    `;

    if (showChart) renderPriceChart(history.filter(e => e.price));
  }

  function buildZillowLink(p) {
    const url = p.zillow_url ||
      `https://www.zillow.com/homes/${encodeURIComponent(`${p.address}, ${p.city}, ${p.state}`)}_rb/`;
    return `<a href="${escHtml(url)}" target="_blank" rel="noopener" class="listing-btn btn-zillow-sm">
      <svg width="14" height="14" viewBox="0 0 48 48" fill="currentColor"><path d="M24 3 L45 22 H36 V45 H12 V22 H3 Z"/></svg>
      Zillow
    </a>`;
  }

  function buildRedfinLink(p) {
    const query = encodeURIComponent(`${p.address}, ${p.city}, ${p.state} ${p.zip_code || ""}`);
    const url = p.redfin_url || `https://www.redfin.com/search#location=${query}`;
    return `<a href="${escHtml(url)}" target="_blank" rel="noopener" class="listing-btn btn-redfin-sm">
      <svg width="14" height="14" viewBox="0 0 32 32" fill="currentColor"><circle cx="16" cy="16" r="14"/><circle cx="16" cy="16" r="7" fill="#fff"/></svg>
      Redfin
    </a>`;
  }

  function renderPriceChart(events) {
    const sorted = [...events].sort((a, b) => new Date(a.date) - new Date(b.date));
    const labels = sorted.map(e => fmtDate(e.date));
    const data   = sorted.map(e => e.price);
    if (priceChart) priceChart.destroy();
    const ctx = document.getElementById("price-chart");
    if (!ctx) return;
    priceChart = new Chart(ctx, {
      type: "line",
      data: { labels, datasets: [{ label: "Price", data, borderColor: "#38d9a9", backgroundColor: "rgba(56,217,169,.1)", pointBackgroundColor: "#38d9a9", tension: .35, fill: true }] },
      options: {
        responsive: true,
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => fmtPrice(c.raw) } } },
        scales: {
          x: { ticks: { color: "#7a85a0", font: { size: 10 } }, grid: { color: "#2a3050" } },
          y: { ticks: { color: "#7a85a0", font: { size: 10 }, callback: v => "$" + (v >= 1000 ? (v/1000).toFixed(0)+"K" : v) }, grid: { color: "#2a3050" } },
        },
      },
    });
  }

  // ── Hero photo switcher ───────────────────────────────────────────────────
  function switchHero(photos, idx) {
    const img = document.getElementById("detail-hero-img");
    if (img) {
      img.src = photos[idx];
      img.onclick = () => openLightbox(photos, idx);
      // Highlight active thumb
      document.querySelectorAll(".thumb-img").forEach((t, i) => {
        t.classList.toggle("thumb-active", i === idx);
      });
    }
  }

  // ── Lightbox ──────────────────────────────────────────────────────────────
  function openLightbox(photos, idx) {
    lbPhotos = photos; lbIdx = idx;
    document.getElementById("lb-img").src = photos[idx];
    document.getElementById("lb-counter").textContent = `${idx + 1} / ${photos.length}`;
    document.getElementById("lightbox").classList.add("open");
  }

  function closeLightbox() { document.getElementById("lightbox").classList.remove("open"); }

  function lbNav(dir, evt) {
    evt.stopPropagation();
    lbIdx = (lbIdx + dir + lbPhotos.length) % lbPhotos.length;
    document.getElementById("lb-img").src = lbPhotos[lbIdx];
    document.getElementById("lb-counter").textContent = `${lbIdx + 1} / ${lbPhotos.length}`;
  }

  // ── Flyto + close ─────────────────────────────────────────────────────────
  function flyToProperty(id) {
    const feat = allFeatures.find(f => f.properties.id === id);
    if (!feat) return;
    const [lng, lat] = feat.geometry.coordinates;
    map.flyTo([lat, lng], 15, { duration: 1 });
    const entry = markerMap[id];
    if (entry) {
      setTimeout(() => {
        clusterGroup.zoomToShowLayer(entry.marker, () => {
          entry.marker.openPopup();
          setActiveMarker(id, entry.marker, entry.tier);
        });
      }, 500);
    }
    openDetail(id);
  }

  function closeDetail() {
    document.getElementById("detail-panel").classList.remove("open");
    activeMarkerId = null;
    document.querySelectorAll(".prop-card").forEach(el => el.classList.remove("active"));
  }

  // ── Filters ───────────────────────────────────────────────────────────────
  function applyFilters() {
    const params = {};
    const minP   = document.getElementById("f-min-price").value;
    const maxP   = document.getElementById("f-max-price").value;
    const beds   = document.getElementById("f-beds").value;
    const minNoi = document.getElementById("f-min-noi").value;
    const county = document.getElementById("f-county").value;
    const ptype  = document.getElementById("f-type").value;
    if (minP)         params.min_price     = minP;
    if (maxP)         params.max_price     = maxP;
    if (beds)         params.min_beds      = beds;
    if (minNoi)       params.min_noi       = minNoi;
    if (county)       params.county        = county;
    if (activeMarket) params.market_status = activeMarket;
    if (ptype && ptype !== "all") params.property_type = ptype;
    loadProperties(params);
  }

  function triggerRefresh() {
    showToast("Data refresh started…");
    fetch("/api/refresh", { method: "POST" }).then(() => {
      setTimeout(() => { loadStats(); loadProperties(); showToast("Map refreshed!", "success"); }, 3000);
    }).catch(() => showToast("Refresh failed.", "danger"));
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function priceTier(p) {
    if (p.market_status === "off_market") return "off";
    const price = p.price || p.zestimate || 0;
    if (price < 200000) return "low";
    if (price < 300000) return "mid";
    return "high";
  }

  function fmtPrice(v) { return v || v === 0 ? "$" + Number(v).toLocaleString("en-US") : "–"; }
  function fmtSqft(v)  { return v ? Number(v).toLocaleString("en-US") + " sqft" : "–"; }
  function fmtDate(iso) {
    if (!iso) return "–";
    try { return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short" }); }
    catch { return iso; }
  }
  function escHtml(s) {
    if (s == null) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function setText(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }

  function showLoader(v) {
    let el = document.querySelector(".map-loader");
    if (!el) {
      el = document.createElement("div");
      el.className = "map-loader";
      el.innerHTML = `<div class="spinner"></div> Loading properties…`;
      document.getElementById("map").appendChild(el);
    }
    el.classList.toggle("hidden", !v);
  }

  function showToast(msg, type = "primary") {
    const t = document.getElementById("toast");
    document.getElementById("toast-msg").textContent = msg;
    t.className = `toast align-items-center text-bg-${type} border-0`;
    bootstrap.Toast.getOrCreateInstance(t, { delay: 3500 }).show();
  }

  return { init, openDetail, flyToProperty, closeDetail, openLightbox, switchHero, toggleMapTheme,
           applyFilters, triggerRefresh, closeLightbox, lbNav };
})();
