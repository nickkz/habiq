/**
 * HaBIQ – Map & UI logic
 */
const HaBIQ = (() => {
  // ── State ────────────────────────────────────────────────────────────────
  let map, clusterGroup;
  let allFeatures = [];          // GeoJSON features
  let activeMarkerId = null;
  let priceChart = null;
  const markerMap = {};          // id → Leaflet marker

  // ── Init ─────────────────────────────────────────────────────────────────
  function init() {
    initMap();
    loadStats();
    loadCounties();
    loadProperties();
  }

  function initMap() {
    const cfg = window.HABIQ_CONFIG || { mapLat: 41.15, mapLng: -75.2, mapZoom: 10 };
    map = L.map("map", { zoomControl: true }).setView([cfg.mapLat, cfg.mapLng], cfg.mapZoom);

    // Tile layer – CartoDB Positron Dark
    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains: "abcd",
        maxZoom: 19,
      }
    ).addTo(map);

    clusterGroup = L.markerClusterGroup({
      chunkedLoading: true,
      maxClusterRadius: 60,
      spiderfyOnMaxZoom: true,
    });
    map.addLayer(clusterGroup);

    // Close detail panel on map click
    map.on("click", () => closeDetail());
  }

  // ── Data loading ──────────────────────────────────────────────────────────
  function loadStats() {
    fetch("/api/stats")
      .then(r => r.json())
      .then(data => {
        setText("stat-total", data.total_properties ?? 0);
        setText("stat-owners", data.with_owner_info ?? 0);
        setText("stat-phones", data.with_phone ?? 0);
      })
      .catch(() => {});
  }

  function loadCounties() {
    fetch("/api/counties")
      .then(r => r.json())
      .then(counties => {
        const sel = document.getElementById("f-county");
        counties.forEach(c => {
          const opt = document.createElement("option");
          opt.value = c;
          opt.textContent = c;
          sel.appendChild(opt);
        });
      })
      .catch(() => {});
  }

  function loadProperties(params = {}) {
    showLoader(true);
    const qs = new URLSearchParams(params).toString();
    fetch(`/api/properties${qs ? "?" + qs : ""}`)
      .then(r => r.json())
      .then(geojson => {
        allFeatures = geojson.features || [];
        renderMarkers(allFeatures);
        renderList(allFeatures);
        setText("result-count", allFeatures.length);
        showLoader(false);
      })
      .catch(err => {
        showLoader(false);
        console.error("Failed to load properties:", err);
        showToast("Failed to load properties. Is the server running?", "danger");
      });
  }

  // ── Marker rendering ──────────────────────────────────────────────────────
  function renderMarkers(features) {
    clusterGroup.clearLayers();
    Object.keys(markerMap).forEach(k => delete markerMap[k]);

    features.forEach(f => {
      const p = f.properties;
      const [lng, lat] = f.geometry.coordinates;

      const tier = priceTier(p.price);
      const icon = L.divIcon({
        className: "",
        html: `<div class="habiq-marker ${tier}"></div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 30],
        popupAnchor: [0, -32],
      });

      const marker = L.marker([lat, lng], { icon })
        .bindPopup(buildPopupHTML(p), { maxWidth: 260 })
        .on("click", () => {
          setActiveMarker(p.id, marker, tier);
          openDetail(p.id);
        });

      markerMap[p.id] = { marker, tier };
      clusterGroup.addLayer(marker);
    });
  }

  function setActiveMarker(id, marker, tier) {
    // Reset previous
    if (activeMarkerId && markerMap[activeMarkerId]) {
      const prev = markerMap[activeMarkerId];
      prev.marker.setIcon(L.divIcon({
        className: "",
        html: `<div class="habiq-marker ${prev.tier}"></div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 30],
        popupAnchor: [0, -32],
      }));
    }
    activeMarkerId = id;
    marker.setIcon(L.divIcon({
      className: "",
      html: `<div class="habiq-marker ${tier} selected"></div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 30],
      popupAnchor: [0, -32],
    }));

    // Highlight list card
    document.querySelectorAll(".prop-card").forEach(el => el.classList.remove("active"));
    const card = document.querySelector(`.prop-card[data-id="${id}"]`);
    if (card) {
      card.classList.add("active");
      card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function buildPopupHTML(p) {
    return `
      <div>
        <div class="popup-addr">${escHtml(p.address)}</div>
        <div class="popup-city">${escHtml(p.city || "")}, ${escHtml(p.county || "")}</div>
        <div class="popup-price">${fmtPrice(p.price)}</div>
        <div class="popup-row">
          <span><i class="fa fa-bed"></i> ${p.beds ?? "–"} bd</span>
          <span><i class="fa fa-bath"></i> ${p.baths ?? "–"} ba</span>
          <span><i class="fa fa-ruler-combined"></i> ${fmtSqft(p.sqft)}</span>
        </div>
        ${p.owner_name ? `<div class="mt-1 text-muted" style="font-size:.72rem"><i class="fa fa-user" style="color:#4f8ef7"></i> ${escHtml(p.owner_name)}</div>` : ""}
        <button class="btn btn-sm w-100 mt-2" style="background:#4f8ef7;color:#fff;font-size:.72rem;"
          onclick="HaBIQ.openDetail(${p.id})">
          View Details
        </button>
      </div>`;
  }

  // ── Property list ─────────────────────────────────────────────────────────
  function renderList(features) {
    const el = document.getElementById("property-list");
    if (!features.length) {
      el.innerHTML = `<div class="empty-state">
        <i class="fa fa-map-location-dot"></i>
        <h6>No properties found</h6>
        <small>Adjust filters or run <code>python main.py seed</code> to load demo data.</small>
      </div>`;
      return;
    }

    // Sort by price ascending
    const sorted = [...features].sort((a, b) => (a.properties.price || 0) - (b.properties.price || 0));

    el.innerHTML = sorted.map(f => {
      const p = f.properties;
      const tier = priceTier(p.price);
      return `
        <div class="prop-card" data-id="${p.id}" onclick="HaBIQ.flyToProperty(${p.id})">
          <div class="prop-card-addr">${escHtml(p.address)}</div>
          <div class="prop-card-city">${escHtml(p.city || "")}, ${escHtml(p.county || "")}</div>
          <div class="prop-card-row">
            <span class="prop-card-price price-${tier}">${fmtPrice(p.price)}</span>
            <span class="prop-card-meta">${p.beds ?? "–"}bd / ${p.baths ?? "–"}ba · ${fmtSqft(p.sqft)}</span>
          </div>
        </div>`;
    }).join("");
  }

  // ── Detail panel ──────────────────────────────────────────────────────────
  function openDetail(propertyId) {
    const panel = document.getElementById("detail-panel");
    panel.classList.add("open");

    const content = document.getElementById("detail-content");
    content.innerHTML = `<div class="empty-state"><div class="spinner"></div><p>Loading…</p></div>`;

    fetch(`/api/property/${propertyId}`)
      .then(r => r.json())
      .then(prop => renderDetail(prop))
      .catch(err => {
        content.innerHTML = `<div class="empty-state"><i class="fa fa-circle-exclamation"></i><h6>Failed to load</h6></div>`;
      });
  }

  function renderDetail(p) {
    const owner = (p.owners || [])[0] || {};
    const history = p.sale_history || [];
    const photos = tryParseJSON(p.photos) || [];

    // Estimate display
    const zest = p.zestimate ? `<div class="value-row">
      <div><div class="value-label">Zillow Zestimate</div></div>
      <div class="value-num">${fmtPrice(p.zestimate)}</div>
    </div>` : "";

    const rentZest = p.rent_zestimate ? `<div class="value-row">
      <div><div class="value-label">Rent Zestimate (mo.)</div></div>
      <div class="value-num">${fmtPrice(p.rent_zestimate)}</div>
    </div>` : "";

    // GRM (Gross Rent Multiplier)
    const grm = (p.price && p.rent_zestimate)
      ? ((p.price / (p.rent_zestimate * 12)).toFixed(1))
      : null;

    // Cap rate estimate (rough)
    const capRate = (p.rent_zestimate && p.price)
      ? (((p.rent_zestimate * 12 * 0.5) / p.price) * 100).toFixed(1)
      : null;

    // Sale history chart data
    const soldEvents = history.filter(e => e.event === "Sold" || e.event === "Listed").slice(0, 10);

    const photoHtml = photos.length
      ? `<img src="${escHtml(photos[0])}" class="detail-photo" alt="Property photo" onerror="this.outerHTML='<div class=detail-photo><i class=\\'fa fa-image\\'></i></div>'" />`
      : `<div class="detail-photo"><i class="fa fa-image"></i></div>`;

    const ownerHtml = owner.name ? `
      <div class="owner-card">
        <div class="owner-name">
          ${escHtml(owner.name)}
          ${owner.owner_type ? `<span class="badge-type">${escHtml(owner.owner_type)}</span>` : ""}
        </div>
        ${owner.mailing_address ? `<div class="owner-row"><i class="fa fa-envelope-open-text"></i>${escHtml([owner.mailing_address, owner.mailing_city, owner.mailing_state, owner.mailing_zip].filter(Boolean).join(", "))}</div>` : ""}
        ${owner.phone ? `<div class="owner-row"><i class="fa fa-phone"></i><a href="tel:${escHtml(owner.phone)}">${escHtml(owner.phone)}</a></div>` : '<div class="owner-row"><i class="fa fa-phone"></i><span>Phone not available</span></div>'}
        ${owner.email ? `<div class="owner-row"><i class="fa fa-at"></i><a href="mailto:${escHtml(owner.email)}">${escHtml(owner.email)}</a></div>` : ""}
        ${owner.source ? `<div class="owner-row" style="margin-top:.4rem"><i class="fa fa-database"></i><small style="font-size:.65rem">Source: ${escHtml(owner.source)}</small></div>` : ""}
      </div>` : `<div class="empty-state" style="padding:1rem"><i class="fa fa-user-slash"></i><h6>Owner info not yet looked up</h6><small>Run <code>python main.py owners</code></small></div>`;

    const historyHtml = history.length ? `
      <table class="sale-table">
        <thead><tr><th>Date</th><th>Event</th><th>Price</th></tr></thead>
        <tbody>
          ${history.map(e => `
            <tr>
              <td>${fmtDate(e.date)}</td>
              <td class="sale-event-${(e.event || "").toLowerCase().replace(/\s/g,"-")}">${escHtml(e.event || "–")}</td>
              <td>${fmtPrice(e.price)}</td>
            </tr>`).join("")}
        </tbody>
      </table>` : `<div class="empty-state" style="padding:.75rem"><i class="fa fa-clock-rotate-left"></i><h6>No sale history available</h6></div>`;

    const investHtml = (grm || capRate) ? `
      <div class="d-flex gap-2">
        ${grm ? `<div class="value-row flex-fill"><div><div class="value-label">GRM</div></div><div class="value-num">${grm}×</div></div>` : ""}
        ${capRate ? `<div class="value-row flex-fill"><div><div class="value-label">Est. Cap Rate</div></div><div class="value-num">${capRate}%</div></div>` : ""}
      </div>` : "";

    document.getElementById("detail-content").innerHTML = `
      ${photoHtml}
      <div class="detail-address">${escHtml(p.address)}</div>
      <div class="detail-city">${escHtml(p.city || "")}, ${escHtml(p.state || "PA")} ${escHtml(p.zip_code || "")} · ${escHtml(p.county || "")}</div>
      <div class="detail-price">${fmtPrice(p.price)}</div>

      <div class="detail-chips">
        ${p.beds ? `<span class="chip"><i class="fa fa-bed"></i><strong>${p.beds}</strong> beds</span>` : ""}
        ${p.baths ? `<span class="chip"><i class="fa fa-bath"></i><strong>${p.baths}</strong> baths</span>` : ""}
        ${p.sqft ? `<span class="chip"><i class="fa fa-ruler-combined"></i><strong>${fmtSqft(p.sqft)}</strong></span>` : ""}
        ${p.unit_count ? `<span class="chip"><i class="fa fa-building"></i><strong>${p.unit_count}</strong> units</span>` : ""}
        ${p.year_built ? `<span class="chip"><i class="fa fa-calendar"></i>Built <strong>${p.year_built}</strong></span>` : ""}
        ${p.days_on_market != null ? `<span class="chip"><i class="fa fa-clock"></i><strong>${p.days_on_market}</strong> DOM</span>` : ""}
        <span class="chip"><i class="fa fa-ban" style="color:#38d9a9"></i>No HOA</span>
      </div>

      ${p.description ? `<div style="font-size:.78rem;color:var(--muted);line-height:1.5;margin-bottom:.75rem">${escHtml(p.description).substring(0, 280)}${p.description.length > 280 ? "…" : ""}</div>` : ""}

      <!-- Owner Info -->
      <div class="section-title"><i class="fa fa-user-tie"></i>Owner</div>
      ${ownerHtml}

      <!-- Valuation -->
      <div class="section-title"><i class="fa fa-chart-line"></i>Valuation</div>
      ${zest}
      ${rentZest}
      ${investHtml}
      ${p.zillow_url ? `<a href="${escHtml(p.zillow_url)}" target="_blank" class="btn-zillow"><i class="fa-solid fa-arrow-up-right-from-square"></i>View on Zillow</a>` : ""}

      <!-- Sale History -->
      <div class="section-title"><i class="fa fa-clock-rotate-left"></i>Sale History</div>
      ${historyHtml}
      ${soldEvents.length > 1 ? `<canvas id="price-chart" style="margin-top:.75rem"></canvas>` : ""}
    `;

    // Render price chart if data available
    if (soldEvents.length > 1) {
      renderPriceChart(soldEvents);
    }
  }

  function renderPriceChart(events) {
    const labels = events.map(e => fmtDate(e.date)).reverse();
    const data = events.map(e => e.price).reverse();

    if (priceChart) priceChart.destroy();
    const ctx = document.getElementById("price-chart");
    if (!ctx) return;

    priceChart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: "Price",
          data,
          borderColor: "#38d9a9",
          backgroundColor: "rgba(56,217,169,.1)",
          pointBackgroundColor: "#38d9a9",
          tension: .3,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => fmtPrice(ctx.raw),
            },
          },
        },
        scales: {
          x: { ticks: { color: "#8892a4", font: { size: 10 } }, grid: { color: "#2e3349" } },
          y: {
            ticks: {
              color: "#8892a4",
              font: { size: 10 },
              callback: v => "$" + (v >= 1000 ? (v / 1000).toFixed(0) + "K" : v),
            },
            grid: { color: "#2e3349" },
          },
        },
      },
    });
  }

  function flyToProperty(id) {
    const feature = allFeatures.find(f => f.properties.id === id);
    if (!feature) return;
    const [lng, lat] = feature.geometry.coordinates;
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
    const minP = document.getElementById("f-min-price").value;
    const maxP = document.getElementById("f-max-price").value;
    const beds = document.getElementById("f-beds").value;
    const county = document.getElementById("f-county").value;
    const status = document.getElementById("f-status").value;
    if (minP) params.min_price = minP;
    if (maxP) params.max_price = maxP;
    if (beds) params.min_beds = beds;
    if (county) params.county = county;
    if (status) params.status = status;
    loadProperties(params);
  }

  function triggerRefresh() {
    showToast("Data refresh started…");
    fetch("/api/refresh", { method: "POST" })
      .then(r => r.json())
      .then(() => {
        setTimeout(() => {
          loadStats();
          loadProperties();
          showToast("Map refreshed!", "success");
        }, 3000);
      })
      .catch(() => showToast("Refresh failed.", "danger"));
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function priceTier(price) {
    if (!price) return "mid";
    if (price < 200000) return "low";
    if (price < 300000) return "mid";
    return "high";
  }

  function fmtPrice(v) {
    if (!v && v !== 0) return "–";
    return "$" + Number(v).toLocaleString("en-US");
  }

  function fmtSqft(v) {
    if (!v) return "–";
    return Number(v).toLocaleString("en-US") + " sqft";
  }

  function fmtDate(iso) {
    if (!iso) return "–";
    try {
      return new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short" });
    } catch { return iso; }
  }

  function escHtml(s) {
    if (!s && s !== 0) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function tryParseJSON(s) {
    try { return JSON.parse(s); } catch { return null; }
  }

  function showLoader(visible) {
    let el = document.querySelector(".map-loader");
    if (!el) {
      el = document.createElement("div");
      el.className = "map-loader";
      el.innerHTML = `<div class="spinner"></div> Loading properties…`;
      document.getElementById("map").appendChild(el);
    }
    el.classList.toggle("hidden", !visible);
  }

  function showToast(msg, type = "primary") {
    const toast = document.getElementById("toast");
    document.getElementById("toast-msg").textContent = msg;
    toast.className = `toast align-items-center text-bg-${type} border-0`;
    bootstrap.Toast.getOrCreateInstance(toast, { delay: 3500 }).show();
  }

  // ── Public API ────────────────────────────────────────────────────────────
  return { init, openDetail, flyToProperty, closeDetail };
})();
